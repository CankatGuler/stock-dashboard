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
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CHAT_HISTORY_FILE = Path(__file__).parent / "chat_history.json"
MAX_HISTORY_TURNS = 20

# GitHub'daki geçmiş dosyası yolu
GITHUB_HISTORY_PATH = "chat_history.json"


# ─── GitHub Geçmiş Yönetimi ──────────────────────────────────────────────────

def _github_read_history() -> tuple[list, str]:
    """GitHub'dan chat geçmişini oku. (data, sha) döndürür."""
    try:
        import requests, base64
        token = os.getenv("GH_PAT", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return [], ""
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_HISTORY_PATH}"
        resp = requests.get(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }, timeout=10)
        if resp.status_code == 404:
            return [], ""
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data.get("sha", "")
    except Exception as e:
        logger.debug("GitHub geçmiş okuma: %s", e)
    return [], ""


def _github_write_history(history: list, sha: str = "") -> bool:
    """Chat geçmişini GitHub'a yaz."""
    try:
        import requests, base64
        token = os.getenv("GH_PAT", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return False
        content = base64.b64encode(
            json.dumps(history, ensure_ascii=False, indent=2).encode()
        ).decode()
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_HISTORY_PATH}"
        body = {
            "message": "chore: direktör sohbet geçmişi güncellendi",
            "content": content,
        }
        if sha:
            body["sha"] = sha
        # Mevcut sha'yı al
        if not sha:
            r = requests.get(url, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }, timeout=8)
            if r.status_code == 200:
                body["sha"] = r.json().get("sha", "")
        resp = requests.put(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }, json=body, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.debug("GitHub geçmiş yazma: %s", e)
    return False


# ─── Konuşma Geçmişi Yönetimi ────────────────────────────────────────────────

def _load_history() -> list[dict]:
    """
    Konuşma geçmişini yükle.
    Önce lokal dosya, yoksa GitHub'dan çek.
    """
    # Lokal dosya varsa kullan (hız için)
    if CHAT_HISTORY_FILE.exists():
        try:
            return json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # GitHub'dan yükle
    history, _ = _github_read_history()
    if history:
        # Lokal'e cache'le
        try:
            CHAT_HISTORY_FILE.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
    return history


def _save_history(history: list[dict]) -> None:
    """
    Konuşma geçmişini kaydet.
    Hem lokal dosyaya hem GitHub'a yaz.
    """
    trimmed = history[-MAX_HISTORY_TURNS * 2:]
    # Lokal kaydet
    try:
        CHAT_HISTORY_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Lokal geçmiş kaydedilemedi: %s", e)
    # GitHub'a kaydet (arka planda, deploy'dan sonra da korunsun)
    try:
        _github_write_history(trimmed)
    except Exception as e:
        logger.warning("GitHub geçmiş kaydedilemedi: %s", e)


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


def inject_system_message(text: str, label: str = "SİSTEM ALARMI") -> None:
    """
    Otomatik sistem mesajlarını (Katman 1/2/3, haftalık tarama vs.)
    sohbet geçmişine 'assistant' rolüyle ekle.
    Böylece direktör bu mesajları bağlam olarak görür.
    """
    try:
        history = _load_history()
        # Mesajı kısa tut — çok uzun alarmlar token'ı şişirir
        max_len = 1500
        truncated = text[:max_len] + ("..." if len(text) > max_len else "")
        history.append({
            "role":    "assistant",
            "content": f"[{label}]\n{truncated}"
        })
        _save_history(history)
        logger.debug("Sistem mesajı geçmişe eklendi: %s karakter", len(truncated))
    except Exception as e:
        logger.warning("inject_system_message hatası: %s", e)


# ─── Portföy Bağlamı ─────────────────────────────────────────────────────────

def _build_portfolio_context(usd_try: float) -> str:
    """
    Mevcut portföy durumunu anlık fiyatlar ve K/Z ile hazırla.
    Direktör bu bağlamla "hangi varlık ne durumda?" sorusunu yanıtlayabilir.
    """
    try:
        import yfinance as yf
        from portfolio_manager import load_portfolio

        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        if not portfolio:
            return "Portföy boş veya yüklenemedi."

        # Altın fiyatını önceden çek
        gold_usd = 0.0
        try:
            h = yf.Ticker("GC=F").history(period="2d")
            if not h.empty:
                gold_usd = float(h["Close"].iloc[-1])
        except Exception:
            pass

        lines = [f"MEVCUT PORTFÖY (USD/TRY: {usd_try:.2f}):"]

        class_groups: dict[str, list] = {}
        for p in portfolio:
            ac = p.get("asset_class", "us_equity") or "us_equity"
            if ac in ("other", ""):
                ac = "us_equity"
            class_groups.setdefault(ac, []).append(p)

        ac_labels = {
            "us_equity": "ABD Hisse",
            "crypto":    "Kripto",
            "commodity": "Emtia",
            "tefas":     "TEFAS",
            "cash":      "Nakit",
        }

        total_cur  = 0.0
        total_cost = 0.0

        for ac, positions in class_groups.items():
            lines.append(f"\n{ac_labels.get(ac, ac)}:")
            for p in positions:
                tk  = p.get("ticker", "?")
                shr = float(p.get("shares", 0))
                avg = float(p.get("avg_cost", 0))
                cur = p.get("currency", "USD")

                cost_usd = shr * avg / usd_try if cur == "TRY" else shr * avg

                # Anlık fiyat
                # Anlık birim fiyat
                live_price_usd = avg  # fallback: maliyet birim fiyatı
                try:
                    if tk in ("ALTIN_GRAM_TRY", "XAUTRY=X") and gold_usd > 0:
                        live_tl        = gold_usd * usd_try / 31.1035
                        live_price_usd = live_tl / usd_try
                    elif ac == "tefas":
                        from data.turkey_fetcher import fetch_tefas_fund
                        fd = fetch_tefas_fund(tk)
                        if fd and fd.get("price", 0) > 0:
                            live_price_usd = float(fd["price"]) / usd_try
                    else:
                        h = yf.Ticker(tk).history(period="2d")
                        if not h.empty:
                            lp = float(h["Close"].iloc[-1])
                            live_price_usd = lp / usd_try if cur == "TRY" else lp
                except Exception:
                    pass

                live_usd = shr * live_price_usd
                pnl      = live_usd - cost_usd
                pnl_pct  = pnl / cost_usd * 100 if cost_usd > 0 else 0
                sign     = "+" if pnl >= 0 else ""

                total_cur  += live_usd
                total_cost += cost_usd

                # Açık ve kesin format — direktör birim/toplam karıştırmasın
                lines.append(
                    f"  {tk}: "
                    f"Miktar: {shr:,g} adet | "
                    f"Ort. Birim Maliyet: ${avg:,.2f} | "
                    f"Toplam Yatırılan: ${cost_usd:,.0f} | "
                    f"Anlık Birim Fiyat: ${live_price_usd:,.2f} | "
                    f"Toplam Güncel Değer: ${live_usd:,.0f} | "
                    f"K/Z: {sign}${pnl:,.0f} ({sign}{pnl_pct:.1f}%)"
                )

        # Genel toplam
        total_pnl     = total_cur - total_cost
        total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
        lines.append(
            f"\nTOPLAM: güncel ${total_cur:,.0f} | "
            f"maliyet ${total_cost:,.0f} | "
            f"K/Z ${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)"
        )

        return "\n".join(lines)

    except Exception as e:
        return f"Portföy alınamadı: {e}"


def _extract_tickers_from_message(message: str) -> list[str]:
    """
    Kullanıcı mesajından hisse/kripto sembollerini tespit et.
    Büyük harfli 1-5 karakter kelimeler potansiyel ticker.
    Bilinen kripto ve yaygın kısaltmaları filtrele.
    """
    import re
    # Büyük harfli 2-6 karakter kelimeler (ticker formatı)
    candidates = re.findall(r'\b([A-Z]{2,6}(?:-USD)?)\b', message.upper())

    # Filtrele — Türkçe büyük harf kısaltmalar ve stopword'ler
    stopwords = {
        "VIX", "DXY", "ETF", "ABD", "USD", "TRY",
        "TL", "FED", "GDP", "CPI", "PCE", "AI", "API", "EPS", "FCF",
        "ROE", "ROA", "PE", "PEG", "YOY", "QOQ", "TTM", "EBITDA",
        "OK", "TR", "EN", "DE", "KI", "BI", "NE", "BU", "DA",
    }

    tickers = []
    for c in candidates:
        if c not in stopwords and len(c) >= 2:
            tickers.append(c)

    return list(dict.fromkeys(tickers))[:5]  # max 5, tekrarsız


def _fetch_live_prices(tickers: list[str]) -> str:
    """
    Verilen ticker listesi için anlık fiyat ve temel metrikleri çek.
    Direktörün sistem promptuna enjekte edilecek.
    """
    if not tickers:
        return ""

    import yfinance as yf

    lines = ["\nANLIK FİYAT VERİSİ (otomatik çekildi):"]
    found_any = False

    for tk in tickers:
        try:
            ticker_obj = yf.Ticker(tk)
            hist = ticker_obj.history(period="5d")
            if hist.empty:
                continue

            price     = float(hist["Close"].iloc[-1])
            prev      = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
            chg_pct   = (price - prev) / prev * 100 if prev > 0 else 0
            price_5d  = float(hist["Close"].iloc[0])
            chg_5d    = (price - price_5d) / price_5d * 100 if price_5d > 0 else 0

            # Temel metrikler (hızlı — sadece fast_info)
            fi = ticker_obj.fast_info
            mkt_cap = getattr(fi, "market_cap", None)
            mc_str  = ""
            if mkt_cap:
                if mkt_cap >= 1e12:
                    mc_str = f" | Piyasa Değeri: ${mkt_cap/1e12:.2f}T"
                elif mkt_cap >= 1e9:
                    mc_str = f" | Piyasa Değeri: ${mkt_cap/1e9:.1f}B"

            chg_sign  = "+" if chg_pct >= 0 else ""
            chg5_sign = "+" if chg_5d  >= 0 else ""
            lines.append(
                f"  {tk}: ${price:,.2f} "
                f"(günlük {chg_sign}{chg_pct:.2f}%, "
                f"5g {chg5_sign}{chg_5d:.2f}%)"
                f"{mc_str}"
            )
            found_any = True
        except Exception:
            continue  # Geçersiz ticker, sessizce atla

    if not found_any:
        return ""

    lines.append("(Kaynak: yfinance — gerçek zamanlı veri)")
    return "\n".join(lines)


def _build_memory_context() -> str:
    """Hafıza sisteminden güncel direktör bağlamını getir."""
    try:
        from memory.director_memory import memory
        regime, days = memory.get_current_regime()
        locks        = memory.get_active_locks()
        recent       = memory.get_recent_decisions(n=3)

        lines = []
        if regime and regime != "Bilinmiyor":
            lines.append(f"MEVCUT REJİM: {regime} ({days} gündür)")
        if locks:
            lines.append(f"KİLİTLİ VARLIKLAR: {', '.join(locks.keys())}")
        if recent:
            son = recent[-1]
            lines.append(
                f"SON KARAR ({son.get('tarih','?')}): {son.get('ozet','')[:100]}"
            )
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _get_recent_news_context() -> str:
    """Son haberleri ve on-chain verileri direktöre bağlam olarak hazırla."""
    ctx_parts = []
    try:
        from core.database import SessionLocal
        from core import crud
        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)
        crypto_pos = [p for p in summary["positions"]
                      if p["is_open"] and p.get("asset_class") == "crypto"]
        if crypto_pos:
            from data.onchain_client import get_crypto_onchain_data
            btc_data = get_crypto_onchain_data("BTC")
            if btc_data.get("metrics"):
                m = btc_data["metrics"]
                lines = ["ON-CHAIN DURUMU (BTC):"]
                for key, label in [("mvrv_zscore","MVRV Z-Score"),("nupl","NUPL"),("sth_sopr","STH-SOPR")]:
                    if key in m:
                        lines.append(f"  {label}: {m[key]['value']} — {m[key]['note']}")
                lines.append(f"  Genel: {btc_data['summary']}")
                ctx_parts.append("\n".join(lines))
    except Exception as e:
        logger.debug("On-chain baglam: %s", e)
    try:
        from data.news_client import get_global_macro_news
        news = get_global_macro_news()
        if news:
            lines = ["GÜNCEL MAKRO HABERLER (son 3):"]
            for n in news[:3]:
                lines.append(f"  • {n.get('title','')[:100]} [{n.get('source','')}]")
            ctx_parts.append("\n".join(lines))
    except Exception as e:
        logger.debug("Haber baglam: %s", e)
    return "\n\n".join(ctx_parts) if ctx_parts else ""


def ask_director(user_message: str, deep_analysis: bool = False) -> str:
    """
    Kullanıcının mesajına direktörden yanıt al.
    deep_analysis=True: /sor komutuyla tetiklenir, XML düşünce odaları kullanır.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "❌ API anahtarı eksik."

    try:
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()
    except Exception:
        usd_try = 44.0

    portfolio_ctx    = _build_portfolio_context(usd_try)
    memory_ctx       = _build_memory_context()
    tr_time          = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d %B %Y, %H:%M")
    detected_tickers = _extract_tickers_from_message(user_message)
    live_price_ctx   = _fetch_live_prices(detected_tickers)

    news_onchain_ctx = ""
    if deep_analysis:
        try:
            news_onchain_ctx = _get_recent_news_context()
        except Exception as e:
            logger.debug("Derin analiz baglam: %s", e)

    if deep_analysis:
        system_prompt = f"""Sen bir Strateji Mentörüsün — yatırım botu değil.
Cankat'ın kişisel baş yatırım direktörü ve risk yönetimi danışmanısın.

{portfolio_ctx}

{memory_ctx}
{live_price_ctx}

{news_onchain_ctx}

TARİH/SAAT: {tr_time} | USD/TRY: {usd_try:.2f}

─── DÜŞÜNCE ODALARI SİSTEMİ ───────────────────────────────────────────────
Her soruyu şu XML etiketleriyle adım adım analiz et:

<makro_analiz>
Küresel atmosfere bak: DXY, VIX, tahvil faizleri, jeopolitik riskler.
Güncel haberler piyasayı destekliyor mu, sabote mi ediyor?
"Veriler X diyor ama haberler Y riski taşıyor" formatında yaz.
</makro_analiz>

<mikro_analiz>
İlgili varlığın temel verilerini değerlendir.
Hisse ise: F/K, büyüme, insider. Kripto ise: MVRV, SOPR, on-chain.
Emtia/fon ise: Sektör dinamikleri, talep/arz dengesi.
</mikro_analiz>

<uyumsuzluk_analizi>
KRİTİK ADIM: Veriler ile haberler/makro arasında ÇATIŞMA var mı?
ÖRNEK: "On-chain MVRV dip bölgesinde (alım sinyali) AMA DXY güçleniyor
ve jeopolitik gerilim tırmanıyor (risk-off) → Koruma moduna geç."
Çatışma varsa: korumacı öner. Uyum varsa: sinyali güçlü say.
</uyumsuzluk_analizi>

<risk_degerlendirmesi>
Portföydeki mevcut durumu kontrol et:
Nakit oranı yeterli mi? Konsantrasyon riski var mı?
</risk_degerlendirmesi>

<nihai_muhakeme>
"Evet ama..." veya "Hayır çünkü..." formatında konuş.
Asla sadece "Al" veya "Sat" deme. Mantık zincirini göster.
</nihai_muhakeme>

─── ÜSLUP ──────────────────────────────────────────────────────────────────
- Türkçe, temkinli, çok yönlü mentor üslubu.
- Balık vermek yerine balık tutmayı öğret.
- Telegram formatı: başlıklar için <b>bold</b>.
- 400-600 kelime arası yanıt.
"""
    else:
        system_prompt = f"""Sen deneyimli bir portföy strateji direktörüsün.
Cankat'ın kişisel yatırım direktörüsün.

{portfolio_ctx}
{memory_ctx}
{live_price_ctx}

TARİH/SAAT: {tr_time} | USD/TRY: {usd_try:.2f}

KURALLAR: Türkçe, somut, sorumluluktan kaçma. Geçmiş konuşmaya atıfta bulunabilirsin.
Telegram formatı için <b>bold</b> ve <i>italic</i> kullanabilirsin.
"""

    history = _load_history()
    history.append({"role": "user", "content": user_message})

    client     = anthropic.Anthropic(api_key=api_key)
    last_error = None
    max_tokens = 2500 if deep_analysis else 1500

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=history[-MAX_HISTORY_TURNS * 2:],
            )
            answer = response.content[0].text.strip()
            history.append({"role": "assistant", "content": answer})
            _save_history(history)
            logger.info("Direktör yanıtladı (%d karakter, derin=%s).", len(answer), deep_analysis)
            return answer

        except anthropic.APIError as e:
            last_error = e
            if "529" in str(e) or "overloaded" in str(e).lower():
                if attempt < 2:
                    wait = (attempt + 1) * 3
                    logger.warning("Claude API yüklü, %ds bekleniyor...", wait)
                    import time as _time
                    _time.sleep(wait)
                    continue
            logger.error("Claude API hatası: %s", e)
            break
        except Exception as e:
            last_error = e
            logger.error("Beklenmeyen hata: %s", e)
            break

    if last_error and ("529" in str(last_error) or "overloaded" in str(last_error).lower()):
        return "⚠️ Claude API şu an yoğun. 1-2 dakika sonra tekrar dene."
    return f"⚠️ Direktör yanıt veremedi: {last_error}"
