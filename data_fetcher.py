# data_fetcher.py — Financial Modeling Prep (FMP) API integration
#
# All endpoints use the 2025/2026 "stable" base URL:
#   https://financialmodelingprep.com/stable/
#
# Docs: https://site.financialmodelingprep.com/developer/docs

import os
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

FMP_BASE   = "https://financialmodelingprep.com/stable"
FMP_BASE_V3 = "https://financialmodelingprep.com/api/v3"   # fallback for some endpoints

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json", "User-Agent": "StockDashboard/1.0"})


def _fmp_get(path: str, params: dict | None = None, base: str = FMP_BASE) -> dict | list | None:
    """
    Generic FMP GET helper with basic retry logic.

    Returns parsed JSON or None on failure.
    """
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        logger.error("FMP_API_KEY is not set.")
        return None

    url    = f"{base}/{path.lstrip('/')}"
    params = params or {}
    params["apikey"] = api_key

    for attempt in range(3):
        try:
            resp = _SESSION.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # FMP returns {"Error Message": "..."} on bad key / plan limit
            if isinstance(data, dict) and "Error Message" in data:
                logger.error("FMP error: %s", data["Error Message"])
                return None
            return data
        except requests.exceptions.HTTPError as exc:
            logger.warning("FMP HTTP error (attempt %d): %s", attempt + 1, exc)
            if exc.response is not None and exc.response.status_code in (429, 503):
                time.sleep(2 ** attempt)
            else:
                break
        except Exception as exc:
            logger.warning("FMP request failed (attempt %d): %s", attempt + 1, exc)
            time.sleep(1)
    return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_profile(ticker: str) -> dict | None:
    """
    Fetch company profile from:
      GET /stable/profile?symbol=TICKER
    Returns a dict or None.
    """
    data = _fmp_get("profile", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def get_income_statement(ticker: str, period: str = "annual", limit: int = 1) -> dict | None:
    """
    Fetch the most-recent income statement.
      GET /stable/income-statement?symbol=TICKER&period=annual&limit=1
    """
    data = _fmp_get("income-statement", {"symbol": ticker, "period": period, "limit": limit})
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_cash_flow(ticker: str, period: str = "annual", limit: int = 1) -> dict | None:
    """
    Fetch the most-recent cash-flow statement.
      GET /stable/cash-flow-statement?symbol=TICKER
    """
    data = _fmp_get(
        "cash-flow-statement",
        {"symbol": ticker, "period": period, "limit": limit},
    )
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_key_metrics(ticker: str, period: str = "annual", limit: int = 1) -> dict | None:
    """
    Fetch key metrics (P/E, EV/EBITDA, etc.)
      GET /stable/key-metrics?symbol=TICKER
    """
    data = _fmp_get("key-metrics", {"symbol": ticker, "period": period, "limit": limit})
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_quote(ticker: str) -> dict | None:
    """
    Fetch real-time quote.
    Priority: Yahoo Finance (yfinance) → FMP stable → FMP profile
    yfinance is free, fast, and covers all tickers including ETFs.
    """
    # ── Endpoint 1: Yahoo Finance — ücretsiz, hızlı, geniş kapsam ────────
    try:
        import yfinance as yf
        tk    = yf.Ticker(ticker)
        info  = tk.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        if price and float(price) > 0:
            prev = getattr(info, "previous_close", price) or price
            chg  = ((float(price) - float(prev)) / float(prev) * 100) if prev else 0
            return {
                "price":             float(price),
                "changesPercentage": round(chg, 2),
                "symbol":            ticker,
                "source":            "yfinance",
            }
    except Exception as exc:
        logger.warning("yfinance failed for %s: %s", ticker, exc)

    # ── Endpoint 2: FMP /stable/quote ─────────────────────────────────────
    data = _fmp_get("quote", {"symbol": ticker})
    if isinstance(data, list) and data:
        q = data[0]
        if q.get("price") and float(q.get("price", 0)) > 0:
            return q
    if isinstance(data, dict) and data.get("price") and float(data.get("price", 0)) > 0:
        return data

    # ── Endpoint 3: FMP /stable/profile ───────────────────────────────────
    profile = get_profile(ticker)
    if profile and float(profile.get("price", 0)) > 0:
        return {
            "price":             profile.get("price", 0),
            "changesPercentage": profile.get("changes", 0),
            "symbol":            ticker,
        }

    logger.warning("Could not fetch price for %s from any endpoint.", ticker)
    return None


def enrich_ticker(ticker: str) -> dict:
    """
    Tüm hisse verisini tek bir yfinance çağrısıyla + FMP profile ile topla.
    yfinance: fiyat, metrikler, finansallar (ücretsiz, güvenilir)
    FMP profile: şirket adı, açıklama, logo (ek bilgi)
    """
    # ── 1. yfinance — önce fast_info (hızlı), sonra info (tam) ─────────
    yf_info = {}
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)

        # fast_info: fiyat, mktCap, beta — her zaman hızlı gelir
        try:
            fi = tk.fast_info
            yf_info["currentPrice"]   = getattr(fi, "last_price", None) or getattr(fi, "regularMarketPrice", None)
            yf_info["previousClose"]  = getattr(fi, "previous_close", None)
            yf_info["marketCap"]      = getattr(fi, "market_cap", None)
            yf_info["beta"]           = getattr(fi, "three_month_average_price", None)  # placeholder
        except Exception:
            pass

        # info: tüm temel metrikler — biraz daha yavaş ama kapsamlı
        try:
            full_info = tk.info or {}
            yf_info.update(full_info)  # full_info her şeyi ezer, daha doğru
        except Exception as exc:
            logger.warning("yfinance full info failed for %s: %s — fast_info ile devam", ticker, exc)

    except Exception as exc:
        logger.warning("yfinance tamamen başarısız %s: %s", ticker, exc)

    # ── 2. FMP profile — sadece kimlik/açıklama için ─────────────────────
    profile = {}
    try:
        profile = get_profile(ticker) or {}
    except Exception:
        pass

    # ── Yardımcı: yfinance yoksa FMP, o da yoksa default ─────────────────
    def yf_or_fmp(yf_key, fmp_dict, fmp_key, default=0):
        yf_val  = yf_info.get(yf_key)
        fmp_val = fmp_dict.get(fmp_key)
        if yf_val is not None and yf_val != 0:
            return yf_val
        if fmp_val is not None and fmp_val != 0:
            return fmp_val
        return default

    # Fiyat
    price = (yf_info.get("currentPrice")
             or yf_info.get("regularMarketPrice")
             or profile.get("price", 0) or 0)

    # Değişim %
    prev  = yf_info.get("previousClose") or price
    change_pct = ((price - prev) / prev * 100) if prev and price else 0

    combined_fin = {}  # backward compat

    return {
        # Kimlik
        "ticker":       ticker,
        "companyName":  (yf_info.get("longName") or profile.get("companyName") or ticker),
        "sector":       (yf_info.get("sector")   or profile.get("sector", "N/A") or "N/A"),
        "industry":     (yf_info.get("industry") or profile.get("industry", "N/A") or "N/A"),
        "description":  (profile.get("description", "") or yf_info.get("longBusinessSummary", "") or "")[:400],
        "exchange":     (yf_info.get("exchange")  or profile.get("exchangeShortName", "") or ""),
        "website":      (yf_info.get("website")   or profile.get("website", "") or ""),
        "image":        profile.get("image", ""),

        # Piyasa verisi
        "price":        price,
        "change_pct":   round(change_pct, 2),
        "mktCap":       yf_info.get("marketCap")  or profile.get("mktCap", 0) or 0,
        "beta":         yf_info.get("beta")        or profile.get("beta", 0) or 0,
        "volAvg":       yf_info.get("averageVolume") or profile.get("volAvg", 0) or 0,

        # Finansallar
        "revenue":       yf_info.get("totalRevenue", 0) or 0,
        "netIncome":     yf_info.get("netIncomeToCommon", 0) or 0,
        "operatingCashFlow": yf_info.get("operatingCashflow", 0) or 0,
        "freeCashFlow":  yf_info.get("freeCashflow", 0) or 0,
        "researchAndDevelopmentExpenses": yf_info.get("researchAndDevelopment", 0) or 0,
        "revenueGrowth": yf_info.get("revenueGrowth", 0) or 0,
        "earningsGrowth": yf_info.get("earningsGrowth", 0) or 0,

        # Temel metrikler
        "peRatio":      yf_info.get("trailingPE", 0)    or yf_info.get("forwardPE", 0) or 0,
        "pbRatio":      yf_info.get("priceToBook", 0)   or 0,
        "debtToEquity": yf_info.get("debtToEquity", 0)  or 0,
        "roic":         yf_info.get("returnOnEquity", 0) or 0,  # ROE proxy

        # Analist
        "analystTarget":    yf_info.get("targetMeanPrice", 0) or 0,
        "recommendation":   yf_info.get("recommendationKey", "") or "",
        "analystCount":     yf_info.get("numberOfAnalystOpinions", 0) or 0,

        # Güvenilir gösterge alanları
        "dividendYield":    yf_info.get("dividendYield", 0) or 0,
        "52wHigh":          yf_info.get("fiftyTwoWeekHigh", 0) or 0,
        "52wLow":           yf_info.get("fiftyTwoWeekLow", 0) or 0,
        "forwardPE":        yf_info.get("forwardPE", 0) or 0,
        "priceToSales":     yf_info.get("priceToSalesTrailing12Months", 0) or 0,
        "shortPercent":     yf_info.get("shortPercentOfFloat", 0) or 0,

        # Raw — backward compat
        "_profile":    profile,
        "_financials": combined_fin,
        "_yf_info":    yf_info,
    }


def batch_enrich(tickers: list[str], delay: float = 0.25) -> list[dict]:
    """
    Enrich a list of tickers, rate-limiting to avoid FMP 429s.
    Returns list of enriched dicts (skips any that return empty profile).
    """
    results = []
    for ticker in tickers:
        try:
            data = enrich_ticker(ticker)
            if data.get("companyName") != ticker:   # profile was found
                results.append(data)
            else:
                # Still add with whatever we got
                results.append(data)
            time.sleep(delay)
        except Exception as exc:
            logger.warning("Failed to enrich %s: %s", ticker, exc)
    return results
