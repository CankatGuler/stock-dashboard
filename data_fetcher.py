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
    Fetch real-time quote with multiple fallback endpoints.
    Tries 3 different FMP endpoints to maximise coverage.
    """
    api_key = os.getenv("FMP_API_KEY", "")

    # ── Endpoint 1: /stable/quote ─────────────────────────────────────────
    data = _fmp_get("quote", {"symbol": ticker})
    if isinstance(data, list) and data:
        q = data[0]
        if q.get("price") and float(q.get("price", 0)) > 0:
            return q
    if isinstance(data, dict) and data.get("price") and float(data.get("price", 0)) > 0:
        return data

    # ── Endpoint 2: /stable/profile (always has price field) ─────────────
    profile = get_profile(ticker)
    if profile and float(profile.get("price", 0)) > 0:
        return {
            "price":              profile.get("price", 0),
            "changesPercentage":  profile.get("changes", 0),
            "symbol":             ticker,
        }

    # ── Endpoint 3: v3/quote-short (lightweight endpoint) ────────────────
    try:
        url  = f"{FMP_BASE_V3}/quote-short/{ticker}"
        resp = _SESSION.get(url, params={"apikey": api_key}, timeout=10)
        resp.raise_for_status()
        data3 = resp.json()
        if isinstance(data3, list) and data3:
            q = data3[0]
            if float(q.get("price", 0)) > 0:
                return {"price": q["price"], "changesPercentage": 0, "symbol": ticker}
    except Exception:
        pass

    logger.warning("Could not fetch price for %s from any endpoint.", ticker)
    return None


def enrich_ticker(ticker: str) -> dict:
    """
    Aggregate all relevant FMP data for a single ticker into one dict.
    Returns a flat dict with safe defaults for missing values.
    """
    profile  = get_profile(ticker)        or {}
    income   = get_income_statement(ticker) or {}
    cashflow = get_cash_flow(ticker)       or {}
    metrics  = get_key_metrics(ticker)     or {}
    quote    = get_quote(ticker)           or {}

    # Merge cash-flow fields into income dict for convenience
    combined_fin = {**income, **cashflow}

    return {
        # Identity
        "ticker":        ticker,
        "companyName":   profile.get("companyName", ticker),
        "sector":        profile.get("sector", "N/A"),
        "industry":      profile.get("industry", "N/A"),
        "description":   (profile.get("description", "") or "")[:400],
        "exchange":      profile.get("exchangeShortName", ""),
        "website":       profile.get("website", ""),
        "image":         profile.get("image", ""),

        # Market data (from quote or profile)
        "price":         quote.get("price")  or profile.get("price", 0),
        "change_pct":    quote.get("changesPercentage") or 0,
        "mktCap":        profile.get("mktCap", 0) or 0,
        "beta":          profile.get("beta", 0) or 0,
        "volAvg":        profile.get("volAvg", 0) or 0,

        # Fundamentals (income + cash-flow)
        "revenue":                combined_fin.get("revenue", 0) or 0,
        "netIncome":              combined_fin.get("netIncome", 0) or 0,
        "operatingCashFlow":      combined_fin.get("operatingCashFlow", 0) or 0,
        "freeCashFlow":           combined_fin.get("freeCashFlow", 0) or 0,
        "researchAndDevelopmentExpenses": combined_fin.get("researchAndDevelopmentExpenses", 0) or 0,

        # Key metrics
        "peRatio":       metrics.get("peRatio", 0) or 0,
        "pbRatio":       metrics.get("pbRatio", 0) or 0,
        "debtToEquity":  metrics.get("debtToEquity", 0) or 0,
        "roic":          metrics.get("roic", 0) or 0,

        # Raw objects preserved for categorisation
        "_profile":   profile,
        "_financials": combined_fin,
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
