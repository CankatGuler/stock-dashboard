# data/macro_monitor.py — Makro Gösterge İzleme & Alarm Sistemi (v2)
#
# Veri kaynakları:
#   yfinance   — VIX, S&P 500, UST 10Y (^TNX), UST 2Y (^IRX)
#   web_search — ISM PMI, Jobless Claims, GDPNow, TGA, RRP, HY Spread, haberler
#
# FRED 403 hatası nedeniyle yfinance + web_search kombinasyonu kullanılıyor.

import logging
import os
import re
import time
from datetime import datetime, timezone

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_TIMEOUT = 20

# ── Alarm Eşikleri ────────────────────────────────────────────────────────────
THRESHOLDS = {
    "ust10y":         {"alarm": 4.8,   "direction": "above", "label": "UST 10Y",        "unit": "%"},
    "yield_curve":    {"alarm": 0.0,   "direction": "below", "label": "2Y-10Y Spread",  "unit": "bps"},
    "tga":            {"alarm": 300,   "direction": "below", "label": "TGA Bakiyesi",    "unit": "$B"},
    "rrp":            {"alarm": 50,    "direction": "below", "label": "Fed RRP",         "unit": "$B"},
    "ism_mfg":        {"alarm": 48.0,  "direction": "below", "label": "ISM Manufacturing","unit": ""},
    "ism_svc":        {"alarm": 50.0,  "direction": "below", "label": "ISM Services",    "unit": ""},
    "jobless_claims": {"alarm": 260,   "direction": "above", "label": "Jobless Claims",  "unit": "K"},
    "gdpnow":         {"alarm": 1.0,   "direction": "below", "label": "GDPNow",          "unit": "%"},
    "vix":            {"alarm": 25.0,  "direction": "above", "label": "VIX",             "unit": "",
                       "critical": 35.0, "critical_note": "Panik Bölgesi — Alım Fırsatı Yaklaşıyor"},
    "hy_spread":      {"alarm": 400,   "direction": "above", "label": "HY Spread",       "unit": "bps"},
}


# ─── Web Search Yardımcısı ────────────────────────────────────────────────────

def _ws(prompt: str, max_tokens: int = 200) -> str | None:
    """Claude web_search ile veri çek. Ham metin döndürür."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model":    "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "tools":    [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        content = resp.json().get("content", [])
        texts = [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
        return texts[-1].strip() if texts else None
    except Exception as e:
        logger.debug("web_search hatası: %s", e)
        return None


def _parse_json_value(text: str, key: str):
    """JSON veya düz metinden sayısal değer çıkar."""
    if not text:
        return None
    # Önce JSON dene
    clean = re.sub(r"```json\s*|\s*```", "", text).strip()
    match = re.search(rf'"{key}"\s*:\s*([\d.\-]+)', clean)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    # Düz metinden sayı çıkar
    patterns = [
        r'\$?([\d,]+\.?\d*)\s*(?:billion|B\b)',
        r'([\d,]+\.?\d*)\s*(?:basis points|bps)',
        r'([\d,]+\.?\d*)\s*(?:%|percent)',
        r'([\d,]+\.?\d+)',
    ]
    for pat in patterns:
        for m in re.findall(pat, text, re.IGNORECASE):
            try:
                val = float(str(m).replace(',', ''))
                if 0 < val < 100000:
                    return val
            except ValueError:
                continue
    return None


# ─── yfinance Çekiciler ───────────────────────────────────────────────────────

def _yf_latest(ticker: str) -> tuple[float, float, str] | None:
    """yfinance'den son fiyat, önceki fiyat ve tarih."""
    try:
        h = yf.Ticker(ticker).history(period="5d")
        if not h.empty:
            val  = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2]) if len(h) > 1 else val
            date = str(h.index[-1])[:10]
            return val, prev, date
    except Exception as e:
        logger.debug("yfinance [%s] hatası: %s", ticker, e)
    return None


def fetch_vix() -> dict:
    r = _yf_latest("^VIX")
    if r:
        return {"key": "vix", "value": round(r[0], 2), "prev": round(r[1], 2),
                "date": r[2], "label": "VIX", "unit": ""}
    return {"key": "vix", "value": None, "prev": None, "date": None}


def fetch_sp500_vs_200ma() -> dict:
    try:
        h = yf.Ticker("^GSPC").history(period="1y")
        if not h.empty and len(h) >= 200:
            current  = float(h["Close"].iloc[-1])
            ma200    = float(h["Close"].rolling(200).mean().iloc[-1])
            pct_diff = (current - ma200) / ma200 * 100
            return {"key": "sp500_200ma", "value": round(current, 0),
                    "ma200": round(ma200, 0), "pct_diff": round(pct_diff, 2),
                    "above": current > ma200, "date": str(h.index[-1])[:10]}
    except Exception as e:
        logger.debug("S&P 500 hatası: %s", e)
    return {"key": "sp500_200ma", "value": None, "ma200": None, "above": None, "date": None}


def fetch_ust10y() -> dict:
    """UST 10Y — önce yfinance, başarısız olursa web search."""
    r = _yf_latest("^TNX")
    if r:
        return {"key": "ust10y", "value": round(r[0], 3), "prev": round(r[1], 3),
                "date": r[2], "label": "UST 10Y", "unit": "%"}
    # Fallback: web search
    text = _ws(
        "What is the current US 10-year Treasury yield percentage? "
        'Reply ONLY with JSON: {"value": <number>, "date": "YYYY-MM-DD"}'
    )
    val = _parse_json_value(text, "value")
    if val:
        return {"key": "ust10y", "value": val, "prev": None, "date": "",
                "label": "UST 10Y", "unit": "%"}
    return {"key": "ust10y", "value": None, "prev": None, "date": None}


def fetch_yield_curve() -> dict:
    """2Y-10Y Spread — yfinance ile ^TNX ve ^IRX."""
    t10 = _yf_latest("^TNX")
    t2  = _yf_latest("^IRX")
    if t10 and t2:
        spread      = round((t10[0] - t2[0]) * 10, 1)  # ^IRX 13-week, yaklaşık
        spread_prev = round((t10[1] - t2[1]) * 10, 1)
        return {"key": "yield_curve", "value": spread, "prev": spread_prev,
                "date": t10[2], "label": "2Y-10Y Spread", "unit": "bps"}
    return {"key": "yield_curve", "value": None, "prev": None, "date": None}


# ─── Web Search Çekiciler ─────────────────────────────────────────────────────

def fetch_ism_manufacturing() -> dict:
    text = _ws(
        "What is the latest ISM Manufacturing PMI reading? "
        'Reply ONLY with JSON: {"value": <number>, "date": "YYYY-MM-DD"}'
    )
    val = _parse_json_value(text, "value")
    return {"key": "ism_mfg", "value": val, "prev": None, "date": "",
            "label": "ISM Manufacturing", "unit": ""}


def fetch_ism_services() -> dict:
    text = _ws(
        "What is the latest ISM Services PMI reading? "
        'Reply ONLY with JSON: {"value": <number>, "date": "YYYY-MM-DD"}'
    )
    val = _parse_json_value(text, "value")
    return {"key": "ism_svc", "value": val, "prev": None, "date": "",
            "label": "ISM Services", "unit": ""}


def fetch_jobless_claims() -> dict:
    text = _ws(
        "What is the latest US weekly initial jobless claims number (in thousands)? "
        'Reply ONLY with JSON: {"value": <number_in_thousands>, "date": "YYYY-MM-DD"}'
    )
    val = _parse_json_value(text, "value")
    return {"key": "jobless_claims", "value": val, "prev": None, "date": "",
            "label": "Jobless Claims", "unit": "K"}


def fetch_gdpnow() -> dict:
    text = _ws(
        "What is the latest Atlanta Fed GDPNow forecast for US GDP growth rate? "
        'Reply ONLY with JSON: {"value": <percentage_number>, "date": "YYYY-MM-DD"}'
    )
    val = _parse_json_value(text, "value")
    return {"key": "gdpnow", "value": val, "prev": None, "date": "",
            "label": "GDPNow", "unit": "%"}


def fetch_tga() -> dict:
    text = _ws(
        "Search for the current US Treasury General Account TGA balance. "
        "What is the TGA balance today in billions of dollars? "
        "Give me just the number in billions."
    )
    val = _parse_json_value(text, "value")
    return {"key": "tga", "value": val, "prev": None, "date": "",
            "label": "TGA Bakiyesi", "unit": "$B"}


def fetch_rrp() -> dict:
    text = _ws(
        "Search for the Federal Reserve overnight reverse repo facility RRP balance. "
        "What is the latest daily RRP usage amount in billions of dollars?"
    )
    val = _parse_json_value(text, "value")
    return {"key": "rrp", "value": val, "prev": None, "date": "",
            "label": "Fed RRP", "unit": "$B"}


def fetch_hy_spread() -> dict:
    """HY Spread — ICE BofA OAS spread web search."""
    text = _ws(
        "Search for the current ICE BofA US High Yield OAS spread or "
        "high yield credit spread in basis points. "
        "What is the current high yield spread in bps?"
    )
    val = _parse_json_value(text, "value")
    # HY spread genellikle 200-800 bps aralığında olur
    if val and (val < 100 or val > 2000):
        val = None  # Mantıksız değer, temizle
    return {"key": "hy_spread", "value": val, "prev": None, "date": "",
            "label": "HY Spread", "unit": "bps"}


def fetch_macro_news_summary() -> str:
    text = _ws(
        "In Turkish, briefly summarize the 2-3 most important macro/market developments "
        "this week: US tariffs, Fed statements, China economy. Max 3 sentences.",
        max_tokens=300,
    )
    return text or ""


# ─── Tüm Verileri Topla ──────────────────────────────────────────────────────

def fetch_all_macro_indicators() -> dict:
    logger.info("Makro göstergeler çekiliyor...")
    indicators = {}

    # yfinance (hızlı)
    for key, fn in [("vix", fetch_vix), ("sp500_200ma", fetch_sp500_vs_200ma),
                    ("ust10y", fetch_ust10y), ("yield_curve", fetch_yield_curve)]:
        try:
            indicators[key] = fn()
        except Exception as e:
            logger.warning("[%s] hatası: %s", key, e)
            indicators[key] = {"key": key, "value": None}

    # web_search (biraz daha yavaş, rate limit için araya sleep)
    ws_fetchers = [
        ("ism_mfg",        fetch_ism_manufacturing),
        ("ism_svc",        fetch_ism_services),
        ("jobless_claims", fetch_jobless_claims),
        ("gdpnow",         fetch_gdpnow),
        ("tga",            fetch_tga),
        ("rrp",            fetch_rrp),
        ("hy_spread",      fetch_hy_spread),
    ]
    for key, fn in ws_fetchers:
        try:
            indicators[key] = fn()
            time.sleep(0.5)
        except Exception as e:
            logger.warning("[%s] hatası: %s", key, e)
            indicators[key] = {"key": key, "value": None}

    try:
        indicators["macro_news"] = fetch_macro_news_summary()
    except Exception:
        indicators["macro_news"] = ""

    logger.info("Makro göstergeler tamamlandı.")
    return indicators


# ─── Alarm Kontrolü ──────────────────────────────────────────────────────────

def check_alarms(indicators: dict) -> list[dict]:
    alarms = []
    for key, thresh in THRESHOLDS.items():
        ind = indicators.get(key, {})
        val = ind.get("value")
        if val is None:
            continue
        triggered = (thresh["direction"] == "above" and val > thresh["alarm"]) or \
                    (thresh["direction"] == "below" and val < thresh["alarm"])
        if triggered:
            severity = "warning"
            note = ""
            if "critical" in thresh and val > thresh["critical"]:
                severity = "critical"
                note = thresh.get("critical_note", "")
            alarms.append({"key": key, "label": thresh["label"], "value": val,
                           "threshold": thresh["alarm"], "unit": thresh.get("unit", ""),
                           "severity": severity, "note": note, "direction": thresh["direction"]})
    return alarms


# ─── Telegram Mesaj Formatı ──────────────────────────────────────────────────

def format_weekly_report(indicators: dict) -> str:
    def _v(key, fmt="{:.1f}", unit="", na="N/A"):
        v = indicators.get(key, {}).get("value")
        if v is None:
            return na
        try:
            return fmt.format(v) + (f" {unit}" if unit else "")
        except Exception:
            return str(v)

    def _arr(key):
        ind = indicators.get(key, {})
        v, p = ind.get("value"), ind.get("prev")
        if v is None or p is None:
            return ""
        return " ↑" if v > p else (" ↓" if v < p else " →")

    def _em(key):
        thresh = THRESHOLDS.get(key)
        if not thresh:
            return ""
        v = indicators.get(key, {}).get("value")
        if v is None:
            return ""
        d = thresh["direction"]
        if d == "above":
            if "critical" in thresh and v > thresh["critical"]:
                return " 🔴"
            return " 🟡" if v > thresh["alarm"] else " 🟢"
        else:
            return " 🟡" if v < thresh["alarm"] else " 🟢"

    # S&P 500 200 GHO
    sp = indicators.get("sp500_200ma", {})
    if sp.get("value") and sp.get("ma200"):
        ab  = "Üzerinde 🟢" if sp.get("above") else "Altında 🔴"
        sgn = "+" if sp.get("pct_diff", 0) >= 0 else ""
        sp_text = f"${sp['value']:,.0f} / ${sp['ma200']:,.0f} — {ab} ({sgn}{sp.get('pct_diff', 0):.1f}%)"
    else:
        sp_text = "N/A"

    # UST 10Y
    ust = indicators.get("ust10y", {})
    if ust.get("value"):
        ust_text = f"%{ust['value']:.2f}"
        if ust.get("prev"):
            ust_text += f" (önceki: %{ust['prev']:.2f})"
        ust_text += _arr("ust10y") + _em("ust10y")
    else:
        ust_text = "N/A"

    tarih = datetime.now(timezone.utc).strftime("%d %B %Y")
    macro_news = indicators.get("macro_news", "")

    # Raporu iki parça olarak oluştur (Telegram 4096 limit)
    parca1 = "\n".join([
        f"📊 <b>HAFTALIK MAKRO RAPOR — {tarih}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🏦 <b>TAHVİL & LİKİDİTE</b>",
        f"• UST 10Y: {ust_text}",
        f"• 2Y-10Y Spread: {_v('yield_curve', '{:.0f}', 'bps')}{_arr('yield_curve')}{_em('yield_curve')}",
        f"• TGA Bakiyesi: ${_v('tga', '{:.0f}')}B{_em('tga')}",
        f"• Fed RRP: ${_v('rrp', '{:.0f}')}B{_em('rrp')}",
        "",
        "📈 <b>BÜYÜME</b>",
        f"• ISM Manufacturing: {_v('ism_mfg')}{_em('ism_mfg')}",
        f"• ISM Services: {_v('ism_svc')}{_em('ism_svc')}",
        f"• Jobless Claims: {_v('jobless_claims', '{:.0f}')}K{_em('jobless_claims')}",
        f"• GDPNow: %{_v('gdpnow')}{_em('gdpnow')}",
        "",
        "⚡ <b>PİYASA STRESİ</b>",
        f"• VIX: {_v('vix', '{:.1f}')}{_arr('vix')}{_em('vix')}",
        f"• HY Spread: {_v('hy_spread', '{:.0f}')}bps{_em('hy_spread')}",
        f"• S&P 500 / 200 GHO: {sp_text}",
    ])

    parca2 = ""
    if macro_news:
        parca2 = "\n".join([
            "🌍 <b>MAKRO</b>",
            macro_news,
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "<i>🟢 Normal  🟡 Dikkat  🔴 Kritik</i>",
        ])
    else:
        parca1 += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>🟢 Normal  🟡 Dikkat  🔴 Kritik</i>"

    return parca1, parca2


def format_alarm_message(alarms: list[dict]) -> str:
    if not alarms:
        return ""
    lines = ["⚠️ <b>MAKRO ALARM</b>", ""]
    for a in alarms:
        emoji   = "🔴" if a["severity"] == "critical" else "🟡"
        val_str = f"{a['value']:.1f}{a['unit']}"
        thr_str = f"{a['threshold']:.0f}{a['unit']}"
        dir_str = "üzeri" if a["direction"] == "above" else "altı"
        lines.append(f"{emoji} <b>{a['label']}:</b> {val_str} (eşik: {thr_str} {dir_str})")
        if a.get("note"):
            lines.append(f"   → {a['note']}")
    return "\n".join(lines)
