# memory/decision_logger.py — Direktör Karar Günlüğü
#
# Görev: Direktörün ürettiği her yanıtı analiz edip içinde yatırım tavsiyesi
# varsa Supabase'e kaydetmek. Hata durumunda sessizce ölmek yerine açıkça
# bildir ve retry kuyruğuna ekle.
#
# Mimari ilke: Bu modül direktörün YANIT ÜRETMESİNİ engellemez.
# Ancak başarısız olduğunda da sessiz kalmaz — hem loglar hem bildirir.

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Başarısız kayıtlar için geçici kuyruk dosyası.
# Supabase geçici olarak erişilemezse, kayıt burada bekler
# ve bir sonraki çalışmada tekrar denenir.
RETRY_QUEUE_FILE = Path(__file__).parent / "decision_retry_queue.json"


# ─── Tavsiye Extractor ────────────────────────────────────────────────────────

def extract_recommendation(director_response: str, user_message: str) -> Optional[dict]:
    """
    Direktörün yanıtını Haiku ile analiz et.
    İçinde yatırım tavsiyesi varsa yapılandırılmış dict döndür, yoksa None.

    Haiku burada kasıtlı seçildi: bu basit bir sınıflandırma görevi,
    Sonnet'in kapasitesine gerek yok ve maliyeti 10-20x daha düşük.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("[DecisionLogger] ANTHROPIC_API_KEY eksik")
        return None

    # Çok kısa yanıtlarda tavsiye olma ihtimali düşük, API çağrısı yapma
    if len(director_response) < 100:
        return None

    system_prompt = """Sen bir finansal metin analiz uzmanısın. 
Sana bir yatırım direktörünün yanıtı verilecek.
Yanıtta belirli bir varlık (hisse, kripto, fon, emtia) için net bir yatırım 
tavsiyesi var mı analiz et.

YANIT KURALLARI:
- SADECE JSON formatında yanıt ver, başka hiçbir şey yazma.
- Eğer net bir tavsiye yoksa: {"has_recommendation": false}
- Eğer net tavsiye varsa, aşağıdaki formatı kullan.

Tavsiye sayılacaklar: al, sat, artır, azalt, tut, bekle, çık, gir
Tavsiye SAYILMAYACAKLAR: genel piyasa yorumu, makro analiz, bilgi verme

Format:
{
  "has_recommendation": true,
  "asset_symbol": "SEMBOL",
  "asset_class": "us_equity|crypto|tefas|commodity",
  "recommendation": "al|sat|artir|azalt|tut|bekle|çık|gir",
  "confidence": "yuksek|orta|dusuk",
  "reasoning_summary": "Max 200 karakter, ana gerekçe"
}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "system":     system_prompt,
                "messages":   [{
                    "role":    "user",
                    "content": (
                        f"KULLANICI SORUSU: {user_message[:200]}\n\n"
                        f"DİREKTÖR YANITI:\n{director_response[:1500]}"
                    )
                }],
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error("[DecisionLogger] Haiku API hatası: HTTP %s", resp.status_code)
            return None

        content = resp.json().get("content", [])
        texts   = [b["text"] for b in content if b.get("type") == "text"]
        if not texts:
            return None

        text = texts[0].strip()
        text = re.sub(r"```json\s*|\s*```", "", text).strip()

        parsed = json.loads(text)

        if not parsed.get("has_recommendation"):
            return None

        # Zorunlu alanları kontrol et
        required = ["asset_symbol", "recommendation"]
        if not all(parsed.get(f) for f in required):
            return None

        return parsed

    except json.JSONDecodeError as e:
        logger.warning("[DecisionLogger] JSON parse hatası: %s | metin: %s", e, text[:100])
        return None
    except Exception as e:
        logger.error("[DecisionLogger] extract_recommendation hatası: %s", e)
        return None


# ─── Fiyat ve Portföy Bağlamı ─────────────────────────────────────────────────

def _get_current_context(asset_symbol: str) -> dict:
    """
    Karar anındaki fiyat, portföy ağırlığı ve VIX'i çek.
    Her biri ayrı try/except içinde — birinin başarısız olması diğerlerini etkilemez.
    """
    context = {
        "price_at_decision":      None,
        "portfolio_weight_pct":   None,
        "vix_at_decision":        None,
    }

    # Anlık fiyat
    try:
        import yfinance as yf
        h = yf.Ticker(asset_symbol).history(period="2d")
        if not h.empty:
            context["price_at_decision"] = round(float(h["Close"].iloc[-1]), 4)
    except Exception as e:
        logger.debug("[DecisionLogger] Fiyat çekilemedi [%s]: %s", asset_symbol, e)

    # VIX
    try:
        import yfinance as yf
        h = yf.Ticker("^VIX").history(period="2d")
        if not h.empty:
            context["vix_at_decision"] = round(float(h["Close"].iloc[-1]), 2)
    except Exception as e:
        logger.debug("[DecisionLogger] VIX çekilemedi: %s", e)

    # Portföy ağırlığı
    try:
        from core.database import SessionLocal
        from core import crud
        from strategy_data import fetch_usd_try_rate
        import yfinance as yf

        usd_try = fetch_usd_try_rate()
        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)

        positions = [p for p in summary["positions"] if p["is_open"]]
        total_usd = 0.0
        asset_usd = 0.0

        for p in positions:
            qty = float(p["quantity"])
            avg = float(p["avg_cost_usd"])
            val = qty * avg  # fallback: maliyet bazlı
            total_usd += val
            if p["symbol"].upper() == asset_symbol.upper():
                asset_usd = val

        if total_usd > 0 and asset_usd > 0:
            context["portfolio_weight_pct"] = round(asset_usd / total_usd * 100, 2)

    except Exception as e:
        logger.debug("[DecisionLogger] Portföy ağırlığı alınamadı: %s", e)

    return context


# ─── Supabase'e Kayıt ─────────────────────────────────────────────────────────

def _save_to_supabase(record: dict) -> bool:
    """
    Karar kaydını Supabase'e yaz.
    Başarılıysa True, başarısızsa False döndür.
    """
    try:
        from core.database import SessionLocal
        from sqlalchemy import text

        with SessionLocal() as db:
            db.execute(
                text("""
                    INSERT INTO director_decisions (
                        asset_symbol, asset_class, trigger_type,
                        question_summary, recommendation, confidence,
                        reasoning_summary, price_at_decision,
                        portfolio_weight_pct, vix_at_decision,
                        is_evaluated
                    ) VALUES (
                        :asset_symbol, :asset_class, :trigger_type,
                        :question_summary, :recommendation, :confidence,
                        :reasoning_summary, :price_at_decision,
                        :portfolio_weight_pct, :vix_at_decision,
                        FALSE
                    )
                """),
                record
            )
            db.commit()

        logger.info(
            "[DecisionLogger] ✅ Kaydedildi: %s → %s (%s)",
            record["asset_symbol"], record["recommendation"], record["confidence"]
        )
        return True

    except Exception as e:
        logger.error("[DecisionLogger] Supabase kayıt hatası: %s", e)
        return False


# ─── Retry Kuyruğu ───────────────────────────────────────────────────────────

def _add_to_retry_queue(record: dict) -> None:
    """Başarısız kayıtları geçici dosyaya ekle."""
    try:
        queue = []
        if RETRY_QUEUE_FILE.exists():
            queue = json.loads(RETRY_QUEUE_FILE.read_text(encoding="utf-8"))
        queue.append(record)
        RETRY_QUEUE_FILE.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.warning("[DecisionLogger] Retry kuyruğuna eklendi: %s", record.get("asset_symbol"))
    except Exception as e:
        logger.error("[DecisionLogger] Retry kuyruğu yazılamadı: %s", e)


def flush_retry_queue() -> int:
    """
    Retry kuyruğundaki bekleyen kayıtları Supabase'e yazmayı dene.
    Başarıyla yazılan kayıt sayısını döndürür.
    Scheduler tarafından periyodik olarak çağrılır.
    """
    if not RETRY_QUEUE_FILE.exists():
        return 0

    try:
        queue = json.loads(RETRY_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if not queue:
        return 0

    failed   = []
    success  = 0

    for record in queue:
        if _save_to_supabase(record):
            success += 1
        else:
            failed.append(record)
        time.sleep(0.3)

    # Başarısız olanları geri yaz, başarılıları sil
    if failed:
        RETRY_QUEUE_FILE.write_text(
            json.dumps(failed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    else:
        RETRY_QUEUE_FILE.unlink()

    if success > 0:
        logger.info("[DecisionLogger] Retry kuyruğundan %d kayıt yazıldı.", success)

    return success


# ─── Alarm Bildirimi ──────────────────────────────────────────────────────────

def _notify_failure(asset_symbol: str, error_msg: str) -> None:
    """
    Logger başarısız olduğunda Telegram'a uyarı gönder.
    Bu sayede sessiz hata olmaz — arıza hemen görünür hale gelir.
    """
    try:
        from bot import send_alarm
        import asyncio

        mesaj = (
            f"⚠️ <b>Karar Günlüğü Hatası</b>\n\n"
            f"Varlık: <code>{asset_symbol}</code>\n"
            f"Hata: {error_msg[:200]}\n\n"
            f"<i>Kayıt retry kuyruğuna alındı, tekrar denenecek.</i>"
        )

        # send_alarm async, mevcut loop'tan çağrılıyorsa run_coroutine_threadsafe kullan
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_alarm(mesaj))
        except RuntimeError:
            asyncio.run(send_alarm(mesaj))

    except Exception as e:
        # Bildirim de başarısız olursa sadece logla, başka bir şey yapma
        logger.error("[DecisionLogger] Hata bildirimi gönderilemedi: %s", e)


# ─── Ana Giriş Noktası ───────────────────────────────────────────────────────

def log_decision(
    director_response: str,
    user_message:      str,
    trigger_type:      str = "sohbet",
) -> None:
    """
    Direktörün yanıtını analiz et ve tavsiye varsa kaydet.

    Bu fonksiyon chat_director.py'den çağrılır.
    Başarısız olsa bile direktörün yanıtını engellemez —
    ama başarısız olduğunu hem loglar hem bildirir.

    Args:
        director_response: Direktörün ürettiği tam yanıt metni
        user_message:      Kullanıcının sorusu
        trigger_type:      'sor', 'sohbet', 'hisse', 'tarama'
    """
    try:
        # 1. Tavsiye var mı? Yoksa işlem yapma
        recommendation = extract_recommendation(director_response, user_message)
        if not recommendation:
            return  # Tavsiye yok, kayıt gerekmez

        asset_symbol = recommendation["asset_symbol"].upper()

        # 2. Piyasa bağlamını çek
        context = _get_current_context(asset_symbol)

        # 3. Kaydı oluştur
        record = {
            "asset_symbol":        asset_symbol,
            "asset_class":         recommendation.get("asset_class", "us_equity"),
            "trigger_type":        trigger_type,
            "question_summary":    user_message[:300] if user_message else "",
            "recommendation":      recommendation["recommendation"],
            "confidence":          recommendation.get("confidence", "orta"),
            "reasoning_summary":   recommendation.get("reasoning_summary", "")[:500],
            "price_at_decision":   context["price_at_decision"],
            "portfolio_weight_pct":context["portfolio_weight_pct"],
            "vix_at_decision":     context["vix_at_decision"],
        }

        # 4. Supabase'e kaydet
        success = _save_to_supabase(record)

        if not success:
            # Supabase başarısız → retry kuyruğuna ekle ve bildir
            _add_to_retry_queue(record)
            _notify_failure(
                asset_symbol,
                "Supabase bağlantı hatası — kayıt retry kuyruğuna alındı"
            )

    except Exception as e:
        # En üst seviye hata yakalama — bu noktaya asla gelinmemeli
        # ama gelirse direktörü engellemeden logla
        logger.error("[DecisionLogger] Kritik hata: %s", e)
