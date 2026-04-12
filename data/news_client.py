# data/news_client.py — Finansal Haber Akışı İstemcisi
#
# Üç katmanlı haber sistemi:
#   1. Küresel Makro  — FMP API + anahtar kelime filtresi
#   2. Türkiye Makro  — RSS (Bloomberg HT / TRT)
#   3. Portföy Özel   — Hisse (FMP), Kripto (FMP), Emtia (Google News), TEFAS fonu
#
# Direktör bu haberleri sabah brifinginde okuyarak portföy yorumu yapar.

import logging
import os
import time
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"
_TIMEOUT = 10
_MAX_NEWS = 5   # Her kategori için maksimum haber sayısı

# ── Emtia sembol → İngilizce isim eşlemesi ───────────────────────────────────
COMMODITY_MAP = {
    # Değerli metaller
    "XAU":             "gold",
    "GC=F":            "gold",
    "ALTIN":           "gold",
    "ALTIN_GRAM_TRY":  "gold",
    "GLD":             "gold ETF",
    "IAU":             "gold ETF",
    "XAG":             "silver",
    "SI=F":            "silver",
    "XPT":             "platinum",
    "XPD":             "palladium",
    # Enerji
    "CL=F":            "crude oil WTI",
    "BZ=F":            "brent crude oil",
    "NG=F":            "natural gas",
    "USO":             "crude oil",
    # Sanayi metalleri
    "XCU":             "copper",
    "HG=F":            "copper",
    "COPPER":          "copper",
    # Tarım
    "ZC=F":            "corn",
    "ZW=F":            "wheat",
    "ZS=F":            "soybeans",
}

# ── Küresel Makro Filtre Kelimeleri ──────────────────────────────────────────
MACRO_KEYWORDS = [
    "Fed", "Federal Reserve", "FOMC", "Powell",
    "CPI", "inflation", "interest rates", "rate hike", "rate cut",
    "NFP", "nonfarm payroll", "unemployment", "jobs report",
    "ISM", "PMI", "Purchasing Managers", "Manufacturing Index",
    "recession", "GDP", "economic growth",
    "OPEC", "oil production", "Treasury",
    "tariff", "trade war", "sanctions",
    "VIX", "S&P", "market crash", "bear market", "bull market",
]

# ── Türkiye Makro Filtre Kelimeleri ──────────────────────────────────────────
TR_MACRO_KEYWORDS = [
    "TCMB", "Merkez Bankası", "PPK",
    "faiz", "enflasyon", "TÜFE", "ÜFE",
    "Mehmet Şimşek", "Erkan", "Karahan",
    "TL", "dolar", "kur", "BIST", "Borsa İstanbul",
    "Türkiye ekonomi", "büyüme", "cari açık",
]


# ─── Yardımcılar ──────────────────────────────────────────────────────────────

def _fmp_key() -> Optional[str]:
    key = os.getenv("FMP_API_KEY", "")
    return key if key else None


def _clean_html(text: str) -> str:
    """HTML tag'lerini temizle."""
    import re
    text = re.sub(r"<[^>]+>", "", text or "")
    return text.strip()[:300]


def _contains_keywords(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _parse_rss(url: str, max_items: int = _MAX_NEWS) -> list[dict]:
    """RSS feed'inden haber çek."""
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:max_items]:
            results.append({
                "title":   entry.get("title", ""),
                "summary": _clean_html(entry.get("summary", entry.get("description", ""))),
                "url":     entry.get("link", ""),
                "date":    entry.get("published", ""),
                "source":  feed.feed.get("title", "RSS"),
            })
        return results
    except Exception as e:
        logger.debug("RSS parse hatası [%s]: %s", url, e)
        return []


def _fmp_news(endpoint: str, params: dict = None) -> list[dict]:
    """FMP news endpoint'inden haber çek."""
    key = _fmp_key()
    if not key:
        logger.warning("FMP_API_KEY eksik — haber çekilemiyor")
        return []
    try:
        p = {"apikey": key, "limit": _MAX_NEWS}
        if params:
            p.update(params)
        resp = requests.get(f"{FMP_BASE}/{endpoint}", params=p, timeout=_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("FMP rate limit — haber çekimi atlanıyor")
            return []
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        results = []
        for item in data[:_MAX_NEWS]:
            results.append({
                "title":   item.get("title", ""),
                "summary": _clean_html(item.get("text", item.get("summary", ""))),
                "url":     item.get("url", ""),
                "date":    item.get("publishedDate", ""),
                "source":  item.get("site", "FMP"),
                "symbol":  item.get("symbol", ""),
            })
        return results
    except Exception as e:
        logger.debug("FMP news hatası [%s]: %s", endpoint, e)
        return []


# ─── 1. Küresel Makro Haberler ────────────────────────────────────────────────

def get_global_macro_news() -> list[dict]:
    """
    FMP'den genel piyasa haberleri çek.
    Fed, enflasyon, ISM PMI, NFP, OPEC gibi kritik konuları filtrele.
    """
    all_news = _fmp_news("stock_market_news", {"limit": 20})

    # Makro anahtar kelime filtresi
    macro = [n for n in all_news if _contains_keywords(n["title"] + n["summary"], MACRO_KEYWORDS)]

    # Filtre sonucu boşsa tüm haberleri döndür
    return (macro if macro else all_news)[:_MAX_NEWS]


# ─── 2. Türkiye Makro Haberler ────────────────────────────────────────────────

def get_local_macro_news() -> list[dict]:
    """
    Türkiye ekonomi haberlerini RSS'ten çek.
    TCMB, faiz, enflasyon, TL kuru gibi konuları önceliklendir.
    """
    rss_sources = [
        # Bloomberg HT Ekonomi
        "https://www.bloomberght.com/rss",
        # TRT Haber Ekonomi
        "https://www.trthaber.com/sondakika.rss",
        # Hürriyet Ekonomi
        "https://www.hurriyet.com.tr/rss/ekonomi",
    ]

    all_news = []
    for url in rss_sources:
        news = _parse_rss(url, max_items=10)
        all_news.extend(news)
        if len(all_news) >= 15:
            break
        time.sleep(0.3)  # Rate limit koruması

    # Türkiye makro filtresi
    tr_macro = [n for n in all_news
                if _contains_keywords(n["title"] + n["summary"], TR_MACRO_KEYWORDS)]

    # Filtre sonucu boşsa genel Türkiye haberlerini döndür
    return (tr_macro if tr_macro else all_news)[:_MAX_NEWS]


# ─── 3. Varlığa Özgü Haberler ────────────────────────────────────────────────

def get_asset_news(symbol: str, asset_type: str) -> list[dict]:
    """
    Tek bir varlık için haber çek.

    Args:
        symbol:     Varlık sembolü (AAPL, BTC, XAU, IIH vb.)
        asset_type: US_STOCK | CRYPTO | COMMODITY | TR_FUND

    Returns:
        Haber listesi [{title, summary, url, date, source}]
    """
    asset_type = asset_type.upper()

    # ── ABD Hissesi ───────────────────────────────────────────────────────
    if asset_type == "US_STOCK":
        news = _fmp_news(f"stock_news", {"tickers": symbol.upper(), "limit": _MAX_NEWS})
        if not news:
            # Fallback: genel arama
            news = _fmp_news("stock_market_news", {"limit": 15})
            news = [n for n in news if symbol.upper() in n.get("title", "").upper()]
        return news[:_MAX_NEWS]

    # ── Kripto ────────────────────────────────────────────────────────────
    elif asset_type == "CRYPTO":
        # BTC-USD → BTC dönüşümü
        clean_sym = symbol.upper().replace("-USD", "").replace("USD", "")
        news = _fmp_news("crypto_news", {"symbol": f"{clean_sym}USD", "limit": _MAX_NEWS})
        if not news:
            news = _fmp_news("stock_market_news", {"limit": 20})
            news = [n for n in news
                    if clean_sym in n.get("title", "").upper()
                    or "crypto" in n.get("title", "").lower()
                    or "bitcoin" in n.get("title", "").lower()]
        return news[:_MAX_NEWS]

    # ── Emtia ─────────────────────────────────────────────────────────────
    elif asset_type == "COMMODITY":
        # Sembolü İngilizce emtia adına çevir
        asset_name = COMMODITY_MAP.get(symbol.upper(), symbol.lower())

        # Google News RSS — dinamik sorgu
        query = f'"{asset_name}" (demand OR supply OR price OR "central bank" OR reserves OR deficit)'
        encoded = quote_plus(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"

        news = _parse_rss(rss_url)
        if not news:
            # FMP fallback — genel haberlerden filtrele
            all_news = _fmp_news("stock_market_news", {"limit": 20})
            news = [n for n in all_news
                    if asset_name.lower() in n.get("title", "").lower()]
        return news[:_MAX_NEWS]

    # ── TEFAS Fonu ────────────────────────────────────────────────────────
    elif asset_type == "TR_FUND":
        # Google News Türkçe RSS
        query = f'"{symbol.upper()} fonu" OR "{symbol.upper()} yatırım fonu"'
        encoded = quote_plus(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded}&hl=tr-TR&gl=TR&ceid=TR:tr"

        news = _parse_rss(rss_url)
        return news[:_MAX_NEWS]

    else:
        logger.warning("Bilinmeyen asset_type: %s", asset_type)
        return []


# ─── 4. Portföy Haberler Brifing ─────────────────────────────────────────────

def get_daily_news_briefing() -> dict:
    """
    Portföydeki aktif varlıklar için kategorize haber brifingı.

    Supabase'den aktif pozisyonları çeker, her biri için ilgili haberleri bulur.

    Returns:
        {
            "MAKRO_KURESEL": [...],
            "MAKRO_TURKIYE": [...],
            "PORTFOY_OZEL":  {
                "AAPL": [...],
                "BTC":  [...],
                ...
            }
        }
    """
    result = {
        "MAKRO_KURESEL": [],
        "MAKRO_TURKIYE": [],
        "PORTFOY_OZEL":  {},
    }

    # ── Makro haberler ────────────────────────────────────────────────────
    try:
        result["MAKRO_KURESEL"] = get_global_macro_news()
        logger.info("Küresel makro: %d haber", len(result["MAKRO_KURESEL"]))
    except Exception as e:
        logger.warning("Küresel makro haber hatası: %s", e)

    try:
        result["MAKRO_TURKIYE"] = get_local_macro_news()
        logger.info("Türkiye makro: %d haber", len(result["MAKRO_TURKIYE"]))
    except Exception as e:
        logger.warning("Türkiye makro haber hatası: %s", e)

    # ── Portföy özel haberler ─────────────────────────────────────────────
    try:
        from core.database import SessionLocal
        from core import crud

        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)

        positions = [p for p in summary["positions"] if p["is_open"]]

        # Asset class → asset_type eşlemesi
        _TYPE_MAP = {
            "us_equity": "US_STOCK",
            "crypto":    "CRYPTO",
            "commodity": "COMMODITY",
            "tefas":     "TR_FUND",
        }

        for pos in positions:
            symbol     = pos["symbol"]
            ac         = pos.get("asset_class", "us_equity")
            asset_type = _TYPE_MAP.get(ac, "US_STOCK")

            # Nakit için haber çekme
            if ac == "cash":
                continue

            try:
                news = get_asset_news(symbol, asset_type)
                if news:
                    result["PORTFOY_OZEL"][symbol] = news
                    logger.info("%s (%s): %d haber", symbol, asset_type, len(news))
                time.sleep(0.2)  # API rate limit koruması
            except Exception as e:
                logger.warning("%s haber hatası: %s", symbol, e)

    except Exception as e:
        logger.warning("Portföy haber hatası: %s", e)

    return result
