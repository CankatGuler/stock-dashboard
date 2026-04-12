# data/news_client.py — Finansal Haber Akışı (Claude web_search tabanlı)
#
# FMP ücretsiz planı haber endpoint'lerini desteklemiyor.
# Google News bu ortamda proxy kısıtlaması yaşıyor.
# Çözüm: Anthropic Claude API'nin web_search tool'u
# — zaten sahibiz, ek ücret yok, tüm web'i tarıyor.

import logging
import os
from typing import Optional
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

COMMODITY_MAP = {
    "XAU": "gold", "GC=F": "gold", "ALTIN": "gold", "ALTIN_GRAM_TRY": "gold",
    "GLD": "gold ETF", "IAU": "gold ETF",
    "XAG": "silver", "SI=F": "silver",
    "XPT": "platinum", "XPD": "palladium",
    "CL=F": "crude oil WTI", "BZ=F": "brent crude oil",
    "NG=F": "natural gas", "USO": "crude oil",
    "XCU": "copper", "HG=F": "copper",
}


# ─── Claude web_search ile haber çek ─────────────────────────────────────────

def _claude_search_news(query: str, max_results: int = 5) -> list[dict]:
    """
    Claude API'nin web_search tool'unu kullanarak haber çek.
    Döner: [{title, summary, url, date, source}]
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY eksik")
        return []

    system = (
        "Sen bir finansal haber asistanısın. "
        "Web araması yaparak son haberleri bul. "
        "SADECE JSON formatında yanıt ver, başka hiçbir şey yazma. "
        "Format: [{\"title\": \"...\", \"summary\": \"...\", \"url\": \"...\", \"date\": \"...\", \"source\": \"...\"}] "
        f"En fazla {max_results} haber döndür. Özeti 150 karakter ile sınırla."
    )

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
                "max_tokens": 1500,
                "system":     system,
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": query}],
            },
            timeout=30,
        )

        if resp.status_code != 200:
            logger.error("Claude API HTTP %s: %s", resp.status_code, resp.text[:200])
            return []

        data     = resp.json()
        content  = data.get("content", [])
        
        # text bloğunu bul
        text_blocks = [b["text"] for b in content if b.get("type") == "text" and b.get("text")]
        if not text_blocks:
            return []
        
        text = text_blocks[-1].strip()
        
        # JSON'u temizle ve parse et
        import re, json
        # Markdown code block varsa temizle
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()
        
        # JSON array bul
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            news_list = json.loads(match.group())
            logger.info("Claude web_search: %d haber bulundu", len(news_list))
            return news_list[:max_results]

    except Exception as e:
        logger.error("_claude_search_news hatası: %s", e)

    return []


# ─── 1. Gerçek Makro Haberler ─────────────────────────────────────────────────

def get_true_macro_news() -> list[dict]:
    """VIX, DXY, Fed, Treasury Yield haberleri."""
    query = (
        "Search for today's top financial macro news about: "
        "VIX volatility index, DXY dollar index, US Treasury yields, "
        "Federal Reserve Fed Jerome Powell, global macro market risk. "
        "Find the 5 most recent and important news articles from last 7 days."
    )
    results = _claude_search_news(query, max_results=5)
    logger.info("Gerçek makro: %d haber", len(results))
    return results


# ─── 2. ABD Ekonomi Haberleri ─────────────────────────────────────────────────

def get_us_economy_news() -> list[dict]:
    """ISM, PMI, NFP, CPI, faiz kararı haberleri."""
    query = (
        "Search for the latest US economy news about: "
        "ISM manufacturing PMI, NFP nonfarm payroll jobs report, "
        "CPI inflation data, Federal Reserve interest rate decision, "
        "FOMC meeting, US GDP growth, recession indicators. "
        "Find 5 most important articles from the last 7 days."
    )
    results = _claude_search_news(query, max_results=5)
    logger.info("ABD ekonomi: %d haber", len(results))
    return results


# ─── 3. Türkiye Ekonomi Haberleri ─────────────────────────────────────────────

def get_turkey_economy_news() -> list[dict]:
    """TCMB, faiz, TÜFE, Borsa İstanbul haberleri."""
    query = (
        "Türkiye ekonomisi ile ilgili son haberleri ara: "
        "TCMB Merkez Bankası faiz kararı, PPK toplantısı, "
        "enflasyon TÜFE verileri, Borsa İstanbul BIST, "
        "Mehmet Şimşek ekonomi, Türk lirası TL kuru. "
        "Son 7 günden en önemli 5 haberi bul."
    )
    results = _claude_search_news(query, max_results=5)
    logger.info("Türkiye: %d haber", len(results))
    return results


# ─── 4. Varlığa Özgü Haberler ────────────────────────────────────────────────

def get_asset_news(symbol: str, asset_type: str) -> list[dict]:
    """Tek varlık için haber. asset_type: US_STOCK | CRYPTO | COMMODITY | TR_FUND"""
    asset_type = asset_type.upper()

    if asset_type == "US_STOCK":
        query = (
            f"Search for the latest news about {symbol} stock. "
            f"Find recent articles about {symbol} earnings, analyst ratings, "
            f"product launches, company news from last 7 days. Top 5 results."
        )

    elif asset_type == "CRYPTO":
        clean = symbol.upper().replace("-USD", "").replace("USD", "")
        query = (
            f"Search for the latest {clean} cryptocurrency news. "
            f"Find recent articles about {clean} price, adoption, regulation, "
            f"market developments from last 7 days. Top 5 results."
        )

    elif asset_type == "COMMODITY":
        asset_name = COMMODITY_MAP.get(symbol.upper(), symbol.lower())
        query = (
            f"Search for the latest {asset_name} commodity news. "
            f"Find recent articles about {asset_name} price, demand, supply, "
            f"central bank demand, market outlook from last 7 days. Top 5 results."
        )

    elif asset_type == "TR_FUND":
        # TEFAS fon kodlarının tam adlarını bulmak için daha geniş arama
        query = (
            f"Türkiye TEFAS yatırım fonu {symbol} hakkında haberleri ara. "
            f"'{symbol}' fon kodu ile işlem gören Türk yatırım fonu. "
            f"BIST Borsa İstanbul fon piyasası, fon performansı, "
            f"portföy yönetimi, Türkiye sermaye piyasaları. "
            f"Son 30 günden ilgili 5 haber veya analiz bul. "
            f"Eğer {symbol} fon koduna özel haber yoksa, "
            f"genel Türkiye yatırım fonu ve TEFAS haberleri getir."
        )

    else:
        logger.warning("Bilinmeyen asset_type: %s", asset_type)
        return []

    results = _claude_search_news(query, max_results=5)
    logger.info("%s (%s): %d haber", symbol, asset_type, len(results))
    return results


# ─── 5. Sabah Brifing ────────────────────────────────────────────────────────

def get_daily_news_briefing() -> dict:
    """Tam portföy + makro haber brifingı."""
    import time as _time

    result = {
        "MAKRO_GERCEK": [],
        "ABD_EKONOMI":  [],
        "TURKIYE":      [],
        "PORTFOY_OZEL": {},
    }

    for key, fn in [
        ("MAKRO_GERCEK", get_true_macro_news),
        ("ABD_EKONOMI",  get_us_economy_news),
        ("TURKIYE",      get_turkey_economy_news),
    ]:
        try:
            result[key] = fn()
            _time.sleep(1)  # API rate limit
        except Exception as e:
            logger.error("%s brifing hatası: %s", key, e)

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
                _time.sleep(1)
            except Exception as e:
                logger.debug("%s haber: %s", pos["symbol"], e)
    except Exception as e:
        logger.error("Portföy brifing hatası: %s", e)

    return result
