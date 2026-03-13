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


def _yfinance_enrich(ticker: str) -> dict:
    """yfinance'den tüm finansal metrikleri çek — FMP fallback için."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return {
            "yf_mktCap":       info.get("marketCap", 0) or 0,
            "yf_beta":         info.get("beta", 0) or 0,
            "yf_peRatio":      info.get("trailingPE", 0) or 0,
            "yf_pbRatio":      info.get("priceToBook", 0) or 0,
            "yf_debtToEquity": info.get("debtToEquity", 0) or 0,
            "yf_roic":         info.get("returnOnEquity", 0) or 0,  # ROE as proxy
            "yf_freeCashFlow": info.get("freeCashflow", 0) or 0,
            "yf_revenue":      info.get("totalRevenue", 0) or 0,
            "yf_netIncome":    info.get("netIncomeToCommon", 0) or 0,
            "yf_revenueGrowth": info.get("revenueGrowth", 0) or 0,
            "yf_name":         info.get("longName", ""),
            "yf_sector":       info.get("sector", ""),
            "yf_industry":     info.get("industry", ""),
        }
    except Exception:
        return {}


def enrich_ticker(ticker: str) -> dict:
    """
    Aggregate all relevant data for a single ticker.
    Önce FMP profile (şirket adı, sektör, açıklama), ardından yfinance
    finansal metrikler için kullanılır — FMP ücretsiz plan eksik veri döndürdüğünde
    yfinance devreye girer.
    """
    profile  = get_profile(ticker)          or {}
    income   = get_income_statement(ticker)  or {}
    cashflow = get_cash_flow(ticker)         or {}
    metrics  = get_key_metrics(ticker)       or {}
    quote    = get_quote(ticker)             or {}
    yf       = _yfinance_enrich(ticker)

    combined_fin = {**income, **cashflow}

    # Yardımcı: FMP değeri varsa onu, yoksa yfinance değerini al
    def fmp_or_yf(fmp_val, yf_val):
        return fmp_val if (fmp_val and fmp_val != 0) else yf_val

    return {
        # Identity — FMP profil en güvenilir kaynak
        "ticker":        ticker,
        "companyName":   profile.get("companyName", "") or yf.get("yf_name", ticker),
        "sector":        profile.get("sector", "") or yf.get("yf_sector", "N/A"),
        "industry":      profile.get("industry", "") or yf.get("yf_industry", "N/A"),
        "description":   (profile.get("description", "") or "")[:400],
        "exchange":      profile.get("exchangeShortName", ""),
        "website":       profile.get("website", ""),
        "image":         profile.get("image", ""),

        # Market data
        "price":      quote.get("price") or profile.get("price", 0),
        "change_pct": quote.get("changesPercentage") or 0,
        "mktCap":     fmp_or_yf(profile.get("mktCap", 0), yf.get("yf_mktCap", 0)),
        "beta":       fmp_or_yf(profile.get("beta", 0),   yf.get("yf_beta", 0)),
        "volAvg":     profile.get("volAvg", 0) or 0,

        # Fundamentals — FMP yoksa yfinance
        "revenue":        fmp_or_yf(combined_fin.get("revenue", 0),         yf.get("yf_revenue", 0)),
        "netIncome":      fmp_or_yf(combined_fin.get("netIncome", 0),        yf.get("yf_netIncome", 0)),
        "operatingCashFlow": combined_fin.get("operatingCashFlow", 0) or 0,
        "freeCashFlow":   fmp_or_yf(combined_fin.get("freeCashFlow", 0),     yf.get("yf_freeCashFlow", 0)),
        "researchAndDevelopmentExpenses": combined_fin.get("researchAndDevelopmentExpenses", 0) or 0,
        "revenueGrowth":  yf.get("yf_revenueGrowth", 0),

        # Key metrics — FMP yoksa yfinance
        "peRatio":      fmp_or_yf(metrics.get("peRatio", 0),      yf.get("yf_peRatio", 0)),
        "pbRatio":      fmp_or_yf(metrics.get("pbRatio", 0),      yf.get("yf_pbRatio", 0)),
        "debtToEquity": fmp_or_yf(metrics.get("debtToEquity", 0), yf.get("yf_debtToEquity", 0)),
        "roic":         fmp_or_yf(metrics.get("roic", 0),         yf.get("yf_roic", 0)),

        # Raw objects
        "_profile":    profile,
        "_financials": combined_fin,
        "_yfinance":   yf,
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
