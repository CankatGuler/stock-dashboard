# data/news_client.py — Finansal Haber Akışı İstemcisi (v2)
#
# TAVİZ VERİLEMEZ KURALLAR:
#   1. Kesin Yönlendirme  — asset_type belirtilmeden haber çekilmez
#   2. 30 Gün Sınırı      — 30 günden eski haberler atlanır
#   3. Karantina Filtresi — anahtar kelime yoksa haber reddedilir
#   4. Hata Yönetimi      — hata durumunda çökme yok, bilgi mesajı

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FMP_BASE  = "https://financialmodelingprep.com/api/v3"
_TIMEOUT  = 12
_MAX_NEWS = 5
_30_DAYS  = timedelta(days=30)

COMMODITY_MAP = {
    "XAU": "gold", "GC=F": "gold", "ALTIN": "gold", "ALTIN_GRAM_TRY": "gold",
    "GLD": "gold ETF", "IAU": "gold ETF",
    "XAG": "silver", "SI=F": "silver",
    "XPT": "platinum", "XPD": "palladium",
    "CL=F": "crude oil WTI", "BZ=F": "brent crude oil",
    "NG=F": "natural gas", "USO": "crude oil",
    "XCU": "copper", "HG=F": "copper",
}

TRUE_MACRO_KEYWORDS = [
    "VIX", "DXY", "Treasury Yield", "Fed", "Jerome Powell",
    "OVX", "crude oil volatility", "global macro",
    "dollar index", "bond yield", "10-year yield",
]

US_ECONOMY_KEYWORDS = [
    "ISM", "PMI", "NFP", "nonfarm payroll",
    "unemployment", "CPI", "interest rates",
    "recession", "US economy", "FOMC", "inflation",
    "Federal Reserve", "rate hike", "rate cut",
]

TURKEY_KEYWORDS = [
    "TCMB", "Borsa Istanbul", "yabanci yatirimci",
    "TUFE", "enflasyon", "faiz", "Mehmet Simsek", "PPK",
    "Turkiye ekonomi", "Turk lirasi", "TL kuru",
    "BIST", "Merkez Bankasi",
]


def _fmp_key():
    return os.getenv("FMP_API_KEY") or None


def _clean_html(text):
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()[:300]


def _parse_date(date_str):
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
    ):
        try:
            dt = datetime.strptime(date_str[:30], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _is_within_30_days(date_str):
    dt = _parse_date(date_str)
    if dt is None:
        return False
    return dt >= datetime.now(timezone.utc) - _30_DAYS


def _contains_any(text, keywords):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _fmp_get(endpoint, params=None):
    key = _fmp_key()
    if not key:
        logger.warning("FMP_API_KEY eksik")
        return []
    try:
        p = {"apikey": key, "limit": 20}
        if params:
            p.update(params)
        resp = requests.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("FMP rate limit")
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("FMP hatasi [%s]: %s", endpoint, e)
        return []


def _parse_rss(url):
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries:
            results.append({
                "title":   entry.get("title", ""),
                "summary": _clean_html(entry.get("summary", entry.get("description", ""))),
                "url":     entry.get("link", ""),
                "date":    entry.get("published", ""),
                "source":  feed.feed.get("title", "RSS"),
            })
        return results
    except Exception as e:
        logger.debug("RSS hatasi [%s]: %s", url, e)
        return []


def _apply_filters(items, required_keywords=None):
    result = []
    for item in items:
        if not _is_within_30_days(item.get("date", "")):
            continue
        if required_keywords:
            text = item.get("title", "") + " " + item.get("summary", "")
            if not _contains_any(text, required_keywords):
                continue
        result.append(item)
        if len(result) >= _MAX_NEWS:
            break
    return result


def get_true_macro_news():
    """VIX, DXY, Treasury Yield, Fed, Powell, OVX haberleri."""
    raw = _fmp_get("stock_market_news", {"limit": 30})
    news = [{"title": r.get("title",""), "summary": _clean_html(r.get("text","")),
             "url": r.get("url",""), "date": r.get("publishedDate",""),
             "source": r.get("site","FMP")} for r in raw]
    filtered = _apply_filters(news, required_keywords=TRUE_MACRO_KEYWORDS)
    logger.info("Gercek makro: %d haber", len(filtered))
    return filtered


def get_us_economy_news():
    """ISM, PMI, NFP, CPI, faiz kararı haberleri."""
    raw = _fmp_get("stock_market_news", {"limit": 30})
    news = [{"title": r.get("title",""), "summary": _clean_html(r.get("text","")),
             "url": r.get("url",""), "date": r.get("publishedDate",""),
             "source": r.get("site","FMP")} for r in raw]
    filtered = _apply_filters(news, required_keywords=US_ECONOMY_KEYWORDS)
    logger.info("ABD ekonomi: %d haber", len(filtered))
    return filtered


def get_turkey_economy_news():
    """TCMB, faiz, TUFE, BIST haberleri. Karantina kurali aktif."""
    rss_sources = [
        "https://www.bloomberght.com/rss",
        "https://www.trthaber.com/sondakika.rss",
        "https://www.hurriyet.com.tr/rss/ekonomi",
    ]
    all_items = []
    for url in rss_sources:
        all_items.extend(_parse_rss(url))
        if len(all_items) >= 40:
            break
        time.sleep(0.3)
    filtered = _apply_filters(all_items, required_keywords=TURKEY_KEYWORDS)
    logger.info("Turkiye: %d haber (ham: %d)", len(filtered), len(all_items))
    return filtered


def get_asset_news(symbol, asset_type):
    """
    Tek varlik haberi. 30 gun filtresi zorunlu.
    asset_type: US_STOCK | CRYPTO | COMMODITY | TR_FUND
    """
    asset_type = asset_type.upper()
    news = []

    if asset_type == "US_STOCK":
        raw = _fmp_get("stock_news", {"tickers": symbol.upper(), "limit": 20})
        news = [{"title": r.get("title",""), "summary": _clean_html(r.get("text","")),
                 "url": r.get("url",""), "date": r.get("publishedDate",""),
                 "source": r.get("site","FMP")} for r in raw]

    elif asset_type == "CRYPTO":
        clean = symbol.upper().replace("-USD","").replace("USD","")
        raw   = _fmp_get("crypto_news", {"symbol": f"{clean}USD", "limit": 20})
        if not raw:
            raw = [r for r in _fmp_get("stock_market_news", {"limit":30})
                   if clean in r.get("title","").upper()]
        news = [{"title": r.get("title",""), "summary": _clean_html(r.get("text","")),
                 "url": r.get("url",""), "date": r.get("publishedDate",""),
                 "source": r.get("site","FMP")} for r in raw]

    elif asset_type == "COMMODITY":
        asset_name = COMMODITY_MAP.get(symbol.upper(), symbol.lower())
        query  = f'"{asset_name}" (price OR demand OR supply OR "central bank") +when:30d'
        url    = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        news   = _parse_rss(url)

    elif asset_type == "TR_FUND":
        query  = f'"{symbol.upper()} fonu" +when:30d'
        url    = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=tr-TR&gl=TR&ceid=TR:tr"
        news   = _parse_rss(url)

    else:
        logger.warning("Bilinmeyen asset_type: %s", asset_type)
        return []

    filtered = _apply_filters(news, required_keywords=None)
    logger.info("%s (%s): %d haber", symbol, asset_type, len(filtered))
    return filtered


def get_daily_news_briefing():
    """Tam portfoy + makro haber brifingı."""
    result = {"MAKRO_GERCEK": [], "ABD_EKONOMI": [], "TURKIYE": [], "PORTFOY_OZEL": {}}

    for key, fn in [("MAKRO_GERCEK", get_true_macro_news),
                    ("ABD_EKONOMI",  get_us_economy_news),
                    ("TURKIYE",      get_turkey_economy_news)]:
        try:
            result[key] = fn()
        except Exception as e:
            logger.warning("%s haber hatasi: %s", key, e)

    try:
        from core.database import SessionLocal
        from core import crud
        _TYPE_MAP = {"us_equity":"US_STOCK","crypto":"CRYPTO",
                     "commodity":"COMMODITY","tefas":"TR_FUND"}
        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)
        for pos in summary["positions"]:
            if not pos["is_open"]:
                continue
            at = _TYPE_MAP.get(pos.get("asset_class",""))
            if not at:
                continue
            try:
                news = get_asset_news(pos["symbol"], at)
                if news:
                    result["PORTFOY_OZEL"][pos["symbol"]] = news
                time.sleep(0.2)
            except Exception as e:
                logger.debug("%s haber: %s", pos["symbol"], e)
    except Exception as e:
        logger.warning("Portfoy haber hatasi: %s", e)

    return result
