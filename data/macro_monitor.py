# data/macro_monitor.py — Makro Gösterge İzleme & Alarm Sistemi
#
# Haftalık rapor + eşik aşımında anlık Telegram uyarısı
#
# Veri kaynakları:
#   FRED API   — UST 10Y, 2Y-10Y Spread, TGA, RRP, ISM PMI, Jobless Claims
#   yfinance   — VIX, S&P 500
#   Web Search — GDPNow, HY Spread, tarife/Fed haberleri
#
# Scheduler entegrasyonu:
#   Haftalık rapor  : Her Pazartesi 08:00 TR
#   Alarm kontrolü  : Her 6 saatte bir

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_TIMEOUT  = 15

# ── Alarm Eşikleri ────────────────────────────────────────────────────────────
THRESHOLDS = {
    # Tahvil & Likidite
    "ust10y":        {"alarm": 4.8,   "direction": "above", "label": "UST 10Y",       "unit": "%"},
    "yield_curve":   {"alarm": 0.0,   "direction": "below", "label": "2Y-10Y Spread", "unit": "bps"},
    "tga":           {"alarm": 300,   "direction": "below", "label": "TGA Bakiyesi",   "unit": "$B"},
    "rrp":           {"alarm": 50,    "direction": "below", "label": "Fed RRP",        "unit": "$B"},
    # Büyüme
    "ism_mfg":       {"alarm": 48.0,  "direction": "below", "label": "ISM Manuf.",    "unit": ""},
    "ism_svc":       {"alarm": 50.0,  "direction": "below", "label": "ISM Services",  "unit": ""},
    "jobless_claims":{"alarm": 260,   "direction": "above", "label": "Jobless Claims","unit": "K"},
    "gdpnow":        {"alarm": 1.0,   "direction": "below", "label": "GDPNow",        "unit": "%"},
    # Piyasa Stresi
    "vix":           {"alarm": 25.0,  "direction": "above", "label": "VIX",           "unit": "",
                      "critical": 35.0, "critical_note": "Panik Bölgesi — Alım Fırsatı Yaklaşıyor"},
    "hy_spread":     {"alarm": 400,   "direction": "above", "label": "HY Spread",     "unit": "bps"},
}


# ─── FRED Veri Çekici ─────────────────────────────────────────────────────────

def _fred(series_id: str, periods: int = 3) -> list[tuple[str, float]]:
    """FRED'den seri verisi çek. [(tarih, değer), ...] döndürür."""
    try:
        resp = requests.get(
            FRED_BASE,
            params={"id": series_id},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        data = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    data.append((parts[0].strip(), float(parts[1])))
                except ValueError:
                    pass
        data.sort(key=lambda x: x[0], reverse=True)
        return data[:periods]
    except Exception as e:
        logger.warning("FRED [%s] hatası: %s", series_id, e)
        return []


def _fred_latest(series_id: str) -> Optional[tuple[float, float, str]]:
    """En son değer, bir önceki değer ve tarih döndür."""
    data = _fred(series_id, periods=2)
    if not data:
        return None
    val  = data[0][1]
    prev = data[1][1] if len(data) > 1 else val
    date = data[0][0]
    return val, prev, date


# ─── Tahvil & Likidite ────────────────────────────────────────────────────────

def fetch_ust10y() -> dict:
    """10 Yıllık ABD Tahvil Faizi."""
    result = _fred_latest("DGS10")
    if not result:
        return {"key": "ust10y", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "ust10y", "value": val, "prev": prev, "date": date,
            "label": "UST 10Y", "unit": "%"}


def fetch_yield_curve() -> dict:
    """2Y-10Y Getiri Eğrisi Spread'i."""
    result = _fred_latest("T10Y2Y")  # FRED'in spread serisi
    if not result:
        # Manuel hesapla
        t10 = _fred_latest("DGS10")
        t2  = _fred_latest("DGS2")
        if t10 and t2:
            val  = round((t10[0] - t2[0]) * 100, 1)  # bps
            prev = round((t10[1] - t2[1]) * 100, 1)
            return {"key": "yield_curve", "value": val, "prev": prev,
                    "date": t10[2], "label": "2Y-10Y Spread", "unit": "bps"}
        return {"key": "yield_curve", "value": None, "prev": None, "date": None}
    val, prev, date = result
    # T10Y2Y FRED'den % olarak gelir, bps'e çevir
    return {"key": "yield_curve", "value": round(val * 100, 1),
            "prev": round(prev * 100, 1), "date": date,
            "label": "2Y-10Y Spread", "unit": "bps"}


def fetch_tga() -> dict:
    """Treasury General Account Bakiyesi (Milyar $)."""
    result = _fred_latest("WTREGEN")
    if not result:
        return {"key": "tga", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "tga", "value": round(val / 1000, 1),  # M$ → B$
            "prev": round(prev / 1000, 1), "date": date,
            "label": "TGA Bakiyesi", "unit": "$B"}


def fetch_rrp() -> dict:
    """Fed Reverse Repo Bakiyesi (Milyar $)."""
    result = _fred_latest("RRPONTSYD")
    if not result:
        return {"key": "rrp", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "rrp", "value": round(val / 1000, 1),
            "prev": round(prev / 1000, 1), "date": date,
            "label": "Fed RRP", "unit": "$B"}


# ─── Büyüme & Resesyon ────────────────────────────────────────────────────────

def fetch_ism_manufacturing() -> dict:
    """ISM Üretim PMI."""
    result = _fred_latest("NAPM")
    if not result:
        return {"key": "ism_mfg", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "ism_mfg", "value": val, "prev": prev, "date": date,
            "label": "ISM Manufacturing", "unit": ""}


def fetch_ism_services() -> dict:
    """ISM Hizmetler PMI."""
    result = _fred_latest("NMFBAI")
    if not result:
        return {"key": "ism_svc", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "ism_svc", "value": val, "prev": prev, "date": date,
            "label": "ISM Services", "unit": ""}


def fetch_jobless_claims() -> dict:
    """Haftalık İşsizlik Başvuruları (Bin kişi)."""
    result = _fred_latest("ICSA")
    if not result:
        return {"key": "jobless_claims", "value": None, "prev": None, "date": None}
    val, prev, date = result
    return {"key": "jobless_claims", "value": round(val / 1000, 1),
            "prev": round(prev / 1000, 1), "date": date,
            "label": "Jobless Claims", "unit": "K"}


def fetch_gdpnow() -> dict:
    """Atlanta Fed GDPNow (web search ile çek)."""
    try:
        import os, re
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"key": "gdpnow", "value": None, "prev": None, "date": None}

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model":   "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "tools":   [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content":
                    "What is the latest Atlanta Fed GDPNow forecast for US GDP growth? "
                    "Reply ONLY with JSON: {\"value\": <number>, \"date\": \"YYYY-MM-DD\"}"}],
            },
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            texts = [b["text"] for b in data.get("content", [])
                     if b.get("type") == "text" and b.get("text")]
            if texts:
                text = texts[-1]
                text = re.sub(r"```json\s*|\s*```", "", text).strip()
                import json
                parsed = json.loads(text)
                return {"key": "gdpnow", "value": parsed.get("value"),
                        "prev": None, "date": parsed.get("date", ""),
                        "label": "GDPNow", "unit": "%"}
    except Exception as e:
        logger.debug("GDPNow web search hatası: %s", e)
    return {"key": "gdpnow", "value": None, "prev": None, "date": None,
            "label": "GDPNow", "unit": "%"}


# ─── Piyasa Stresi ────────────────────────────────────────────────────────────

def fetch_vix() -> dict:
    """VIX Volatilite Endeksi."""
    try:
        h = yf.Ticker("^VIX").history(period="5d")
        if not h.empty:
            val  = round(float(h["Close"].iloc[-1]), 2)
            prev = round(float(h["Close"].iloc[-2]), 2) if len(h) > 1 else val
            return {"key": "vix", "value": val, "prev": prev,
                    "date": str(h.index[-1])[:10], "label": "VIX", "unit": ""}
    except Exception as e:
        logger.warning("VIX hatası: %s", e)
    return {"key": "vix", "value": None, "prev": None, "date": None}


def fetch_hy_spread() -> dict:
    """HY (High Yield) Kredi Spread'i — FRED ICE BofA."""
    result = _fred_latest("BAMLH0A0HYM2")
    if not result:
        return {"key": "hy_spread", "value": None, "prev": None, "date": None}
    val, prev, date = result
    # FRED yüzde olarak verir, bps'e çevir
    return {"key": "hy_spread", "value": round(val * 100, 0),
            "prev": round(prev * 100, 0), "date": date,
            "label": "HY Spread", "unit": "bps"}


def fetch_sp500_vs_200ma() -> dict:
    """S&P 500'ün 200 günlük hareketli ortalamasına göre konumu."""
    try:
        h = yf.Ticker("^GSPC").history(period="1y")
        if not h.empty and len(h) >= 200:
            current = float(h["Close"].iloc[-1])
            ma200   = float(h["Close"].rolling(200).mean().iloc[-1])
            pct_diff = (current - ma200) / ma200 * 100
            above    = current > ma200
            return {
                "key":      "sp500_200ma",
                "value":    round(current, 0),
                "ma200":    round(ma200, 0),
                "pct_diff": round(pct_diff, 2),
                "above":    above,
                "date":     str(h.index[-1])[:10],
                "label":    "S&P 500 / 200 GHO",
                "unit":     "",
            }
    except Exception as e:
        logger.warning("S&P 500 200 GHO hatası: %s", e)
    return {"key": "sp500_200ma", "value": None, "ma200": None,
            "above": None, "date": None}


# ─── Makro Haberleri (Web Search) ─────────────────────────────────────────────

def fetch_macro_news_summary() -> str:
    """Tarife, Fed ve Çin GDP haberleri özeti."""
    try:
        import os, re
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return ""

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model":   "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "tools":   [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content":
                    "Search for the latest news this week on: "
                    "1) US tariff developments (new tariffs or trade deals), "
                    "2) Federal Reserve meeting statements or rate signals, "
                    "3) China GDP or economic data. "
                    "Reply with 2-3 sentences max, Turkish language, most important only."}],
            },
            timeout=25,
        )
        if resp.status_code == 200:
            data  = resp.json()
            texts = [b["text"] for b in data.get("content", [])
                     if b.get("type") == "text" and b.get("text")]
            return texts[-1].strip() if texts else ""
    except Exception as e:
        logger.debug("Makro haber hatası: %s", e)
    return ""


# ─── Tüm Verileri Topla ──────────────────────────────────────────────────────

def fetch_all_macro_indicators() -> dict:
    """Tüm makro göstergeleri çek ve tek dict olarak döndür."""
    logger.info("Makro göstergeler çekiliyor...")
    indicators = {}

    fetchers = [
        ("ust10y",         fetch_ust10y),
        ("yield_curve",    fetch_yield_curve),
        ("tga",            fetch_tga),
        ("rrp",            fetch_rrp),
        ("ism_mfg",        fetch_ism_manufacturing),
        ("ism_svc",        fetch_ism_services),
        ("jobless_claims", fetch_jobless_claims),
        ("gdpnow",         fetch_gdpnow),
        ("vix",            fetch_vix),
        ("hy_spread",      fetch_hy_spread),
        ("sp500_200ma",    fetch_sp500_vs_200ma),
    ]

    for key, fn in fetchers:
        try:
            indicators[key] = fn()
            time.sleep(0.3)  # FRED rate limit
        except Exception as e:
            logger.warning("Gösterge hatası [%s]: %s", key, e)
            indicators[key] = {"key": key, "value": None}

    # Makro haberler
    try:
        indicators["macro_news"] = fetch_macro_news_summary()
    except Exception:
        indicators["macro_news"] = ""

    logger.info("Makro göstergeler tamamlandı: %d gösterge", len(indicators))
    return indicators


# ─── Alarm Kontrolü ──────────────────────────────────────────────────────────

def check_alarms(indicators: dict) -> list[dict]:
    """
    Eşik değerlerini kontrol et.
    Returns: [{"key": ..., "label": ..., "value": ..., "threshold": ...,
               "message": ..., "severity": "warning"|"critical"}]
    """
    alarms = []

    for key, thresh in THRESHOLDS.items():
        ind = indicators.get(key, {})
        val = ind.get("value")
        if val is None:
            continue

        triggered = False
        if thresh["direction"] == "above" and val > thresh["alarm"]:
            triggered = True
        elif thresh["direction"] == "below" and val < thresh["alarm"]:
            triggered = True

        if triggered:
            severity = "warning"
            # Kritik eşik kontrolü (VIX için)
            if "critical" in thresh and val > thresh["critical"]:
                severity = "critical"
                note = thresh.get("critical_note", "")
            else:
                note = ""

            alarms.append({
                "key":       key,
                "label":     thresh["label"],
                "value":     val,
                "threshold": thresh["alarm"],
                "unit":      thresh.get("unit", ""),
                "severity":  severity,
                "note":      note,
                "direction": thresh["direction"],
            })

    # Yield curve inversiyon özel kontrolü
    yc = indicators.get("yield_curve", {})
    yc_val = yc.get("value")
    if yc_val is not None and yc_val < 0:
        # Sadece alarm listesinde yoksa ekle
        if not any(a["key"] == "yield_curve" for a in alarms):
            alarms.append({
                "key": "yield_curve", "label": "2Y-10Y Spread",
                "value": yc_val, "threshold": 0, "unit": "bps",
                "severity": "warning", "note": "İnversiyon — Resesyon sinyali",
                "direction": "below",
            })

    return alarms


# ─── Telegram Mesaj Formatı ──────────────────────────────────────────────────

def format_weekly_report(indicators: dict) -> str:
    """Haftalık raporu Telegram formatında hazırla."""

    def _val(key: str, fmt: str = "{:.1f}", unit: str = "", na: str = "N/A") -> str:
        ind = indicators.get(key, {})
        v   = ind.get("value")
        if v is None:
            return na
        try:
            return fmt.format(v) + (f" {unit}" if unit else "")
        except Exception:
            return str(v)

    def _arrow(key: str) -> str:
        ind  = indicators.get(key, {})
        val  = ind.get("value")
        prev = ind.get("prev")
        if val is None or prev is None:
            return ""
        return " ↑" if val > prev else (" ↓" if val < prev else " →")

    def _alarm_emoji(key: str) -> str:
        thresh = THRESHOLDS.get(key)
        if not thresh:
            return ""
        ind = indicators.get(key, {})
        val = ind.get("value")
        if val is None:
            return ""
        if thresh["direction"] == "above":
            if "critical" in thresh and val > thresh["critical"]:
                return " 🔴"
            if val > thresh["alarm"]:
                return " 🟡"
        elif thresh["direction"] == "below":
            if val < thresh["alarm"]:
                return " 🟡"
        return " 🟢"

    # S&P 500 200 GHO
    sp = indicators.get("sp500_200ma", {})
    sp_text = "N/A"
    if sp.get("value") and sp.get("ma200"):
        above_str = "Üzerinde 🟢" if sp.get("above") else "Altında 🔴"
        sp_text   = f"${sp['value']:,.0f} / ${sp['ma200']:,.0f} — {above_str}"
        if sp.get("pct_diff") is not None:
            sign = "+" if sp["pct_diff"] >= 0 else ""
            sp_text += f" ({sign}{sp['pct_diff']:.1f}%)"

    # UST 10Y
    ust = indicators.get("ust10y", {})
    ust_text = "N/A"
    if ust.get("value"):
        ust_text = f"%{ust['value']:.2f}"
        if ust.get("prev"):
            ust_text += f" (önceki: %{ust['prev']:.2f})"
        ust_text += _arrow("ust10y") + _alarm_emoji("ust10y")

    # Makro haberler
    macro_news = indicators.get("macro_news", "")

    tarih = datetime.now(timezone.utc).strftime("%d %B %Y")

    lines = [
        f"📊 <b>HAFTALIK MAKRO RAPOR — {tarih}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🏦 <b>TAHVİL & LİKİDİTE</b>",
        f"• UST 10Y: {ust_text}",
        f"• 2Y-10Y Spread: {_val('yield_curve', '{:.0f}', 'bps')}{_arrow('yield_curve')}{_alarm_emoji('yield_curve')}",
        f"• TGA Bakiyesi: ${_val('tga', '{:.0f}')}B{_arrow('tga')}{_alarm_emoji('tga')}",
        f"• Fed RRP: ${_val('rrp', '{:.0f}')}B{_arrow('rrp')}{_alarm_emoji('rrp')}",
        "",
        "📈 <b>BÜYÜME</b>",
        f"• ISM Manufacturing: {_val('ism_mfg')}{_arrow('ism_mfg')}{_alarm_emoji('ism_mfg')}",
        f"• ISM Services: {_val('ism_svc')}{_arrow('ism_svc')}{_alarm_emoji('ism_svc')}",
        f"• Jobless Claims: {_val('jobless_claims', '{:.0f}')}K{_arrow('jobless_claims')}{_alarm_emoji('jobless_claims')}",
        f"• GDPNow: %{_val('gdpnow')}{_alarm_emoji('gdpnow')}",
        "",
        "⚡ <b>PİYASA STRESİ</b>",
        f"• VIX: {_val('vix')}{_arrow('vix')}{_alarm_emoji('vix')}",
        f"• HY Spread: {_val('hy_spread', '{:.0f}')}bps{_arrow('hy_spread')}{_alarm_emoji('hy_spread')}",
        f"• S&P 500 / 200 GHO: {sp_text}",
    ]

    if macro_news:
        lines += [
            "",
            "🌍 <b>MAKRO</b>",
            macro_news,
        ]

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>🟢 Normal  🟡 Dikkat  🔴 Kritik</i>",
    ]

    return "\n".join(lines)


def format_alarm_message(alarms: list[dict]) -> str:
    """Alarm mesajını formatla."""
    if not alarms:
        return ""

    lines = ["⚠️ <b>MAKRO ALARM</b>", ""]
    for a in alarms:
        emoji   = "🔴" if a["severity"] == "critical" else "🟡"
        val_str = f"{a['value']:.1f}{a['unit']}"
        thr_str = f"{a['threshold']:.0f}{a['unit']}"
        dir_str = "üzeri" if a["direction"] == "above" else "altı"
        lines.append(
            f"{emoji} <b>{a['label']}:</b> {val_str} "
            f"(eşik: {thr_str} {dir_str})"
        )
        if a.get("note"):
            lines.append(f"   → {a['note']}")

    return "\n".join(lines)
