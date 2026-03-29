# chat_director.py — İnteraktif Direktör: Telegram Sohbet Modu
#
# Bu modül, strategy_director.py'deki tam analizden farklıdır.
# Oradaki direktör 5 analist raporunu sentezleyen ağır bir analiz makinesi.
# Buradaki direktör seninle konuşan, sorularını anlık yanıtlayan bir stratejist.
#
# Temel farklar:
#   - Tam analiz yerine sohbet formatında yanıt
#   - Konuşma geçmişini hafızada tutar (bağlamı kaybetmez)
#   - Portföy verisini her mesajda arka plana enjekte eder
#   - Master Prompt'un kısa versiyonunu kullanır (token tasarrufu)

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Konuşma geçmişinin tutulduğu dosya
CHAT_HISTORY_FILE = Path(__file__).parent / "chat_history.json"

# Son kaç mesajı bağlam olarak tutacağız
# Daha fazlası = daha iyi bağlam ama daha yüksek token maliyeti
MAX_HISTORY_TURNS = 20  # 10 soru + 10 cevap


# ─── Konuşma Geçmişi Yönetimi ────────────────────────────────────────────────

def _load_history() -> list[dict]:
    """Konuşma geçmişini diskten yükle."""
    if CHAT_HISTORY_FILE.exists():
        try:
            return json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_history(history: list[dict]) -> None:
    """Konuşma geçmişini diske kaydet."""
    # Sadece son MAX_HISTORY_TURNS kaydı tut
    trimmed = history[-MAX_HISTORY_TURNS * 2:]  # Her tur: 1 user + 1 assistant
    try:
        CHAT_HISTORY_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Sohbet geçmişi kaydedilemedi: %s", e)


def get_history_summary() -> str:
    """
    Konuşma geçmişinin kısa özetini döndürür.
    /durum komutu veya dashboard için kullanılabilir.
    """
    history = _load_history()
    if not history:
        return "Henüz sohbet geçmişi yok."
    turns = len([h for h in history if h["role"] == "user"])
    return f"{turns} soru soruldu. Son mesaj: {history[-1]['content'][:80]}..."


def clear_history() -> None:
    """Sohbet geçmişini temizle — /sifirla komutu için."""
    if CHAT_HISTORY_FILE.exists():
        CHAT_HISTORY_FILE.unlink()
    logger.info("Sohbet geçmişi temizlendi.")


# ─── Portföy Bağlamı ─────────────────────────────────────────────────────────

def _build_portfolio_context(usd_try: float) -> str:
    """
    Mevcut portföy durumunu kısa ve okunabilir formatta hazırla.
    Bu bağlam her mesajda sistem promptuna eklenir — direktör
    "hangi varlıklar var?" diye düşünmek zorunda kalmaz.
    """
    try:
        from portfolio_manager import load_portfolio
        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        if not portfolio:
            return "Portföy boş veya yüklenemedi."

        lines = ["MEVCUT PORTFÖY:"]
        class_groups: dict[str, list] = {}
        for p in portfolio:
            ac = p.get("asset_class", "us_equity")
            class_groups.setdefault(ac, []).append(p)

        for ac, positions in class_groups.items():
            ac_label = {
                "us_equity": "ABD Hisse",
                "crypto":    "Kripto",
                "commodity": "Emtia",
                "tefas":     "TEFAS",
                "cash":      "Nakit",
            }.get(ac, ac)
            tickers = [p.get("ticker", "?") for p in positions]
            total_cost = sum(
                float(p.get("shares", 0)) * float(p.get("avg_cost", 0)) /
                (usd_try if p.get("currency") == "TRY" else 1)
                for p in positions
            )
            lines.append(f"  {ac_label}: {', '.join(tickers)} — ${total_cost:,.0f}")

        return "\n".join(lines)
    except Exception as e:
        return f"Portföy alınamadı: {e}"


def _build_memory_context() -> str:
    """Hafıza sisteminden güncel direktör bağlamını getir."""
    try:
        from director_memory import memory
        regime, days = memory.get_current_regime()
        locks = memory.get_active_locks()

        lines = [f"MEVCUT REJİM: {regime} ({days} gündür)"]
        if locks:
            lines.append(f"KİLİTLİ VARLIKLAR: {', '.join(locks.keys())}")
        return "\n".join(lines)
    except Exception:
        return ""


# ─── Ana Direktör Fonksiyonu ──────────────────────────────────────────────────

def ask_director(user_message: str) -> str:
    """
    Kullanıcının mesajına direktörden yanıt al.

    Bu fonksiyon şunları yapar:
      1. Konuşma geçmişini yükler (bağlam sürekliliği)
      2. Portföy ve hafıza bağlamını hazırlar
      3. Claude API'ye gönderir
      4. Yanıtı kaydeder ve döndürür
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "❌ API anahtarı eksik."

    # USD/TRY kurunu çek
    try:
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()
    except Exception:
        usd_try = 44.0  # Fallback

    # Bağlamları hazırla
    portfolio_ctx = _build_portfolio_context(usd_try)
    memory_ctx    = _build_memory_context()
    tr_time       = (datetime.now(timezone.utc) +
                     timedelta(hours=3)).strftime("%d %B %Y, %H:%M")

    # ── Sistem Promptu ──────────────────────────────────────────────────────
    system_prompt = f"""Sen deneyimli bir portföy strateji direktörüsün. \
Kullanıcının (Cankat) kişisel yatırım direktörüsün.

GÖREV: Sorularını portföy bağlamında, dürüst ve somut biçimde yanıtla. \
Gereksiz laf kalabalığı yapma. "Araştırın" veya "uzmana danışın" gibi \
sorumluluktan kaçan yanıtlar verme — sen zaten o uzmanısın.

{portfolio_ctx}

{memory_ctx}

TARİH/SAAT: {tr_time} (Türkiye)
USD/TRY: {usd_try:.2f}

KURALLAR:
- Türkçe yanıt ver.
- Somut ol: "IREN'i %20 azalt" gibi, "riski değerlendirin" gibi değil.
- Geçmiş konuşmaya atıfta bulunabilirsin — sohbet geçmişi sende var.
- Kullanıcı makale veya haber paylaşırsa, portföye etkisini analiz et.
- Emin olmadığın konularda bunu açıkça söyle.
- Yanıtını Telegram'da okunabilir şekilde formatla (HTML değil, düz metin tercih et, \
  ama <b>bold</b> ve <i>italic</i> için HTML kullanabilirsin).
"""

    # Konuşma geçmişini yükle
    history = _load_history()

    # Mevcut mesajı geçmişe ekle
    history.append({"role": "user", "content": user_message})

    # Claude'a gönder
    client  = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,           # Sohbet için yeterli, tam analizden kısa
            system=system_prompt,
            messages=history[-MAX_HISTORY_TURNS * 2:],  # Son N tur
        )
        answer = response.content[0].text.strip()

        # Direktörün yanıtını geçmişe ekle ve kaydet
        history.append({"role": "assistant", "content": answer})
        _save_history(history)

        logger.info("Direktör yanıtladı (%d karakter).", len(answer))
        return answer

    except anthropic.APIError as e:
        logger.error("Claude API hatası: %s", e)
        return f"⚠️ Direktör şu an erişilemez: {e}"
    except Exception as e:
        logger.error("Beklenmeyen hata: %s", e)
        return "⚠️ Beklenmeyen bir hata oluştu. Lütfen tekrar dene."
