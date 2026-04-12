# data/news_client.py — Finansal Haber Akışı İstemcisi (v3)
#
# Düzeltmeler:
#   - Evrensel tarih çözücü (dateutil + time.struct_time desteği)
#   - Genişletilmiş keyword listesi (daha fazla eşleşme)
#   - Türkiye için Google News TR (RSS erişim sorunu çözüldü)
#   - Case-insensitive filtreleme
#   - Şeffaf hata günlükleri

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests
from dateutil import parser as dateutil_parser
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FMP_BASE  = "https://financialmodelingprep.com/api/v3"
_TIMEOUT  = 12
_MAX_NEWS = 5

COMMODITY_MAP = {
    "XAU": "gold", "GC=F": "gold", "ALTIN": "gold", "ALTIN_GRAM_TRY": "gold",
    "GLD": "gold ETF", "IAU": "gold ETF",
    "XAG": "silver", "SI=F": "silver",
    "XPT": "platinum", "XPD": "palladium",
    "CL=F": "crude oil WTI", "BZ=F": "brent crude oil",
    "NG=F": "natural gas", "USO": "crude oil",
    "XCU": "copper", "HG=F": "copper",
}

# Geniş keyword listeleri — tekil/çoğul, kısaltma varyasyonları dahil
TRUE_MACRO_KEYWORDS = [
    "vix", "dxy", "treasury yield", "treasury yields", "fed", "powell",
    "ovx", "global macro", "dollar index", "bond yield", "bond yields",
    "10-year yield", "10-year", "yield curve", "safe haven",
    "risk-off", "risk off", "market volatility",
]

US_ECONOMY_KEYWORDS = [
    "ism", "pmi", "nfp", "nonfarm", "payroll", "unemployment", "jobless",
    "cpi", "interest rate", "interest rates", "rate hike", "rate cut",
    "recession", "us economy", "fomc", "inflation", "federal reserve", "fed",
    "jobs report", "jobs data", "gdp", "economic growth", "consumer price",
    "producer price", "retail sales", "housing", "ism manufacturing",
    "purchasing managers",
]

TURKEY_KEYWORDS = [
    "tcmb", "merkez bankası", "ppk", "borsa istanbul", "bist",
    "tüfe", "tufe", "enflasyon", "faiz", "mehmet şimşek", "simsek",
    "türk lirası", "turk lirasi", "türkiye ekonomi", "turkiye ekonomi",
    "yabancı yatırımcı", "cari açık", "döviz kuru", "tl",
]


# ─── Evrensel Tarih Çözücü ────────────────────────────────────────────────────

def is_within_30_days(date_val) -> bool:
    """
    RSS (time.struct_time), FMP (ISO string) veya herhangi bir tarih formatını
    tolere eden evrensel tarih filtresi.
    Tarih yoksa veya parse edilemezse True döner (haberi kaybetme).
    """
    if not date_val:
        return True
    try:
        if isinstance(date_val, time.struct_time):
            dt = datetime.fromtimestamp(time.mktime(date_val))
        else:
            dt = dateutil_parser.parse(str(date_val))
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
        days_ago = (datetime.now() - dt).days
        return days_ago <= 30
    except Exception as e:
        print(f"[TARIH-PARSE] Tarih çözülemedi: {date_val!r} — {e}")
        return True  # Hata durumunda haberi kaybetme


# ─── Yardımcılar ──────────────────────────────────────────────────────────────

def _fmp_key():
    return os.getenv("FMP_API_KEY") or None


def _clean_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()[:300]


def _contains_any(text: str, keywords: list) -> bool:
    """Case-insensitive keyword arama."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _fmp_get(endpoint: str, params: dict = None) -> list:
    key = _fmp_key()
    if not key:
        print("[ERROR] FMP_API_KEY eksik — haber çekilemiyor")
        return []
    try:
        p = {"apikey": key, "limit": 30}
        if params:
            p.update(params)
        resp = requests.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=_TIMEOUT)
        if resp.status_code == 429:
            print(f"[ERROR] FMP rate limit aşıldı")
            return []
        if resp.status_code != 200:
            print(f"[ERROR] FMP HTTP {resp.status_code}: {resp.text[:200]}")
            return []
        data = resp.json()
        if not isinstance(data, list):
            print(f"[ERROR] FMP beklenmeyen format: {type(data)}")
            return []
        return data
    except Exception as e:
        print(f"[ERROR] _fmp_get [{endpoint}]: {e}")
        return []


def _fmp_to_news(raw_list: list) -> list:
    """FMP ham verisini standart formata çevir."""
    result = []
    for item in raw_list:
        result.append({
            "title":   item.get("title", ""),
            "summary": _clean_html(item.get("text", "") or item.get("summary", "")),
            "url":     item.get("url", ""),
            "date":    item.get("publishedDate", ""),
            "source":  item.get("site", "FMP"),
        })
    return result


def _parse_rss(url: str) -> list:
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries:
            # RSS'de published_parsed (time.struct_time) veya published (string)
            date_val = entry.get("published_parsed") or entry.get("published", "")
            results.append({
                "title":    entry.get("title", ""),
                "summary":  _clean_html(entry.get("summary", entry.get("description", ""))),
                "url":      entry.get("link", ""),
                "date":     date_val,
                "source":   feed.feed.get("title", "RSS"),
            })
        return results
    except Exception as e:
        print(f"[ERROR] _parse_rss [{url[:60]}]: {e}")
        return []


def _apply_filters(items: list, required_keywords: list = None) -> list:
    """30 gün filtresi + opsiyonel keyword karantinası."""
    result = []
    for item in items:
        # 30 gün filtresi
        if not is_within_30_days(item.get("date", "")):
            continue
        # Keyword karantinası (varsa)
        if required_keywords:
            text = (item.get("title", "") + " " + item.get("summary", ""))
            if not _contains_any(text, required_keywords):
                continue
        result.append(item)
        if len(result) >= _MAX_NEWS:
            break
    return result


# ─── 1. Gerçek Makro Haberler ─────────────────────────────────────────────────

def get_true_macro_news() -> list:
    """VIX, DXY, Treasury Yield, Fed, Powell haberleri."""
    try:
        raw      = _fmp_get("stock_market_news")
        news     = _fmp_to_news(raw)
        filtered = _apply_filters(news, required_keywords=TRUE_MACRO_KEYWORDS)
        print(f"[INFO] Gerçek makro: {len(filtered)} haber (ham: {len(news)})")
        return filtered
    except Exception as e:
        print(f"[ERROR] get_true_macro_news: {e}")
        return []


# ─── 2. ABD Ekonomi Haberleri ─────────────────────────────────────────────────

def get_us_economy_news() -> list:
    """ISM, PMI, NFP, CPI, Fed, faiz kararı haberleri."""
    try:
        raw      = _fmp_get("stock_market_news")
        news     = _fmp_to_news(raw)
        filtered = _apply_filters(news, required_keywords=US_ECONOMY_KEYWORDS)
        print(f"[INFO] ABD ekonomi: {len(filtered)} haber (ham: {len(news)})")
        return filtered
    except Exception as e:
        print(f"[ERROR] get_us_economy_news: {e}")
        return []


# ─── 3. Türkiye Ekonomi Haberleri ─────────────────────────────────────────────

def get_turkey_economy_news() -> list:
    """TCMB, faiz, TÜFE, BIST haberleri. Google News TR kullanır."""
    try:
        query   = "TCMB faiz enflasyon Türkiye ekonomi Borsa İstanbul"
        encoded = quote_plus(query)
        url     = f"https://news.google.com/rss/search?q={encoded}&hl=tr-TR&gl=TR&ceid=TR:tr"

        items    = _parse_rss(url)
        filtered = _apply_filters(items, required_keywords=TURKEY_KEYWORDS)
        print(f"[INFO] Türkiye: {len(filtered)} haber (ham: {len(items)})")

        # Fallback: keyword filtresi olmadan sadece 30 gün filtresi
        if not filtered and items:
            print("[INFO] Türkiye karantina filtresi hiç geçemedi, sadece 30g filtresi uygulanıyor")
            filtered = _apply_filters(items, required_keywords=None)

        return filtered
    except Exception as e:
        print(f"[ERROR] get_turkey_economy_news: {e}")
        return []


# ─── 4. Varlığa Özgü Haberler ────────────────────────────────────────────────

def get_asset_news(symbol: str, asset_type: str) -> list:
    """
    Tek varlık için haber. 30 gün zorunlu.
    asset_type: US_STOCK | CRYPTO | COMMODITY | TR_FUND
    """
    asset_type = asset_type.upper()
    news       = []

    try:
        if asset_type == "US_STOCK":
            raw  = _fmp_get("stock_news", {"tickers": symbol.upper(), "limit": 20})
            news = _fmp_to_news(raw)
            print(f"[INFO] {symbol} US_STOCK ham: {len(raw)}")

        elif asset_type == "CRYPTO":
            clean = symbol.upper().replace("-USD", "").replace("USD", "")
            raw   = _fmp_get("crypto_news", {"symbol": f"{clean}USD", "limit": 20})
            if not raw:
                # Fallback: genel haberlerden filtrele
                all_raw = _fmp_get("stock_market_news")
                raw = [r for r in all_raw if clean in r.get("title", "").upper()]
            news = _fmp_to_news(raw)
            print(f"[INFO] {symbol} CRYPTO ham: {len(raw)}")

        elif asset_type == "COMMODITY":
            asset_name = COMMODITY_MAP.get(symbol.upper(), symbol.lower())
            query  = f'"{asset_name}" (price OR demand OR supply OR "central bank") +when:30d'
            url    = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
            news   = _parse_rss(url)
            print(f"[INFO] {symbol} COMMODITY ham: {len(news)}")

        elif asset_type == "TR_FUND":
            query  = f'"{symbol.upper()} fonu" +when:30d'
            url    = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=tr-TR&gl=TR&ceid=TR:tr"
            news   = _parse_rss(url)
            print(f"[INFO] {symbol} TR_FUND ham: {len(news)}")

        else:
            print(f"[ERROR] Bilinmeyen asset_type: {asset_type}")
            return []

    except Exception as e:
        print(f"[ERROR] get_asset_news [{symbol}/{asset_type}]: {e}")
        return []

    filtered = _apply_filters(news, required_keywords=None)
    print(f"[INFO] {symbol} filtrelenmiş: {len(filtered)}")
    return filtered


# ─── 5. Sabah Brifing ────────────────────────────────────────────────────────

def get_daily_news_briefing() -> dict:
    """Tam portföy + makro haber brifingı."""
    result = {"MAKRO_GERCEK": [], "ABD_EKONOMI": [], "TURKIYE": [], "PORTFOY_OZEL": {}}

    for key, fn in [
        ("MAKRO_GERCEK", get_true_macro_news),
        ("ABD_EKONOMI",  get_us_economy_news),
        ("TURKIYE",      get_turkey_economy_news),
    ]:
        try:
            result[key] = fn()
        except Exception as e:
            print(f"[ERROR] {key} brifing: {e}")

    try:
        from core.database import SessionLocal
        from core import crud
        _TYPE_MAP = {
            "us_equity": "US_STOCK", "crypto": "CRYPTO",
            "commodity": "COMMODITY", "tefas": "TR_FUND",
        }
        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)
        for pos in summary["positions"]:
            if not pos["is_open"]:
                continue
            at = _TYPE_MAP.get(pos.get("asset_class", ""))
            if not at:
                continue
            try:
                news = get_asset_news(pos["symbol"], at)
                if news:
                    result["PORTFOY_OZEL"][pos["symbol"]] = news
                time.sleep(0.2)
            except Exception as e:
                print(f"[ERROR] portfoy haber {pos['symbol']}: {e}")
    except Exception as e:
        print(f"[ERROR] get_daily_news_briefing portfoy: {e}")

    return result
