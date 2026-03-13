# data_fetcher.py — Financial Modeling Prep (FMP) + yfinance integration
#
# Strateji:
#   1. FMP /stable/profile       → kimlik, mktCap, beta, fiyat
#   2. FMP /stable/key-metrics   → P/E, D/E, ROIC (TTM)
#   3. FMP /stable/ratios        → alternatif metrikler
#   4. FMP /stable/price-target  → analist hedef fiyat
#   5. FMP /stable/rating        → analist tavsiyesi / skoru
#   6. FMP /stable/income-statement → gelir, büyüme hesabı
#   7. yfinance fast_info        → sadece fiyat ve 52H high/low (backup)

import os
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

FMP_BASE    = "https://financialmodelingprep.com/stable"
FMP_BASE_V3 = "https://financialmodelingprep.com/api/v3"

_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json", "User-Agent": "StockDashboard/1.0"})


def _fmp_get(path: str, params: dict | None = None, base: str = FMP_BASE) -> dict | list | None:
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return None
    url    = f"{base}/{path.lstrip('/')}"
    params = params or {}
    params["apikey"] = api_key
    for attempt in range(3):
        try:
            resp = _SESSION.get(url, params=params, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "Error Message" in data:
                return None
            return data
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (429, 503):
                time.sleep(2 ** attempt)
            else:
                break
        except Exception:
            time.sleep(1)
    return None


# ─── FMP endpoint wrappers ────────────────────────────────────────────────────

def get_profile(ticker: str) -> dict | None:
    data = _fmp_get("profile", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def get_key_metrics(ticker: str) -> dict | None:
    """TTM key metrics: P/E, D/E, ROIC, EV/EBITDA"""
    # TTM (trailing twelve months) — stable endpoint
    data = _fmp_get("key-metrics", {"symbol": ticker, "period": "annual", "limit": 1})
    if isinstance(data, list) and data:
        return data[0]
    # v3 TTM fallback
    data = _fmp_get("key-metrics-ttm", {"symbol": ticker}, base=FMP_BASE_V3)
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_ratios(ticker: str) -> dict | None:
    """Financial ratios: P/E, D/E, gross margin, etc."""
    data = _fmp_get("ratios", {"symbol": ticker, "period": "annual", "limit": 1})
    if isinstance(data, list) and data:
        return data[0]
    # TTM fallback
    data = _fmp_get("ratios-ttm", {"symbol": ticker}, base=FMP_BASE_V3)
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_price_target(ticker: str) -> dict | None:
    """Analist konsensüs hedef fiyat — FMP /stable/price-target"""
    # Consensus summary
    data = _fmp_get("price-target-consensus", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    # Summary fallback
    data = _fmp_get("price-target-summary", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_rating(ticker: str) -> dict | None:
    """Analist rating & recommendation"""
    data = _fmp_get("rating", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return None


def get_income_statement(ticker: str, period: str = "annual", limit: int = 2) -> list | None:
    """Son 2 yıl gelir tablosu — büyüme hesabı için"""
    data = _fmp_get("income-statement", {"symbol": ticker, "period": period, "limit": limit})
    if isinstance(data, list):
        return data
    return None


def get_cash_flow(ticker: str, period: str = "annual", limit: int = 1) -> dict | None:
    data = _fmp_get("cash-flow-statement", {"symbol": ticker, "period": period, "limit": limit})
    if isinstance(data, list) and data:
        return data[0]
    return None


def get_quote(ticker: str) -> dict | None:
    """Real-time fiyat: yfinance fast_info → FMP quote"""
    # 1. yfinance fast_info (ücretsiz, hızlı)
    try:
        import yfinance as yf
        fi    = yf.Ticker(ticker).fast_info
        price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        if price and float(price) > 0:
            prev = getattr(fi, "previous_close", price) or price
            chg  = ((float(price) - float(prev)) / float(prev) * 100) if prev else 0
            return {
                "price":             float(price),
                "changesPercentage": round(chg, 2),
                "symbol":            ticker,
                "year_high":         getattr(fi, "year_high", None),
                "year_low":          getattr(fi, "year_low", None),
                "market_cap":        getattr(fi, "market_cap", None),
                "source":            "yfinance",
            }
    except Exception:
        pass

    # 2. FMP quote fallback
    data = _fmp_get("quote", {"symbol": ticker})
    if isinstance(data, list) and data:
        return data[0]
    return None


# ─── Ana enrich fonksiyonu ────────────────────────────────────────────────────

def enrich_ticker(ticker: str) -> dict:
    """
    Tüm hisse verisini topla.
    FMP profile + key_metrics + ratios + price_target + rating + income öncelikli.
    yfinance sadece fiyat ve 52H için yedek.
    """
    profile  = get_profile(ticker)       or {}
    metrics  = get_key_metrics(ticker)   or {}
    ratios   = get_ratios(ticker)        or {}
    pt       = get_price_target(ticker)  or {}
    rating   = get_rating(ticker)        or {}
    incomes  = get_income_statement(ticker) or []
    cashflow = get_cash_flow(ticker)     or {}
    quote    = get_quote(ticker)         or {}

    # ── Fiyat ─────────────────────────────────────────────────────────────
    price    = (quote.get("price") or quote.get("price")
                or profile.get("price", 0) or 0)
    chg_pct  = quote.get("changesPercentage", 0) or 0

    # ── 52 Hafta High/Low ─────────────────────────────────────────────────
    # yfinance quote'dan, yoksa FMP profile'dan
    w52h = (quote.get("year_high")
            or profile.get("range", "").split("-")[-1].strip()
            if profile.get("range") else 0) or 0
    w52l = (quote.get("year_low")
            or profile.get("range", "").split("-")[0].strip()
            if profile.get("range") else 0) or 0
    try:
        w52h = float(w52h) if w52h else 0
        w52l = float(w52l) if w52l else 0
    except (ValueError, TypeError):
        w52h, w52l = 0, 0

    # ── Gelir büyümesi (son 2 yıl FMP income-statement) ──────────────────
    rev_growth = 0.0
    if len(incomes) >= 2:
        r_new = incomes[0].get("revenue", 0) or 0
        r_old = incomes[1].get("revenue", 0) or 0
        if r_old and r_old != 0:
            rev_growth = (r_new - r_old) / abs(r_old)

    # ── P/E oranı ─────────────────────────────────────────────────────────
    # Sıra: key_metrics peRatio → ratios priceEarningsRatio → profile
    pe = (metrics.get("peRatio")
          or metrics.get("priceEarningsRatio")
          or ratios.get("priceEarningsRatio")
          or ratios.get("peRatioTTM")
          or 0) or 0

    # ── D/E oranı ─────────────────────────────────────────────────────────
    de = (metrics.get("debtToEquity")
          or ratios.get("debtEquityRatio")
          or 0) or 0

    # ── ROIC ──────────────────────────────────────────────────────────────
    roic = (metrics.get("roic")
            or ratios.get("returnOnCapitalEmployed")
            or 0) or 0

    # ── Gross Margin ──────────────────────────────────────────────────────
    gross_margin = (ratios.get("grossProfitMargin")
                    or ratios.get("grossProfitMarginTTM")
                    or metrics.get("grossProfitMargin")
                    or 0) or 0

    # ── Analist hedef fiyat ───────────────────────────────────────────────
    analyst_target = (pt.get("targetConsensus")
                      or pt.get("priceTarget")
                      or pt.get("targetMean")
                      or 0) or 0
    analyst_high   = (pt.get("targetHigh") or 0) or 0
    analyst_low    = (pt.get("targetLow")  or 0) or 0

    # ── Analist tavsiye ───────────────────────────────────────────────────
    rec_score  = (rating.get("ratingScore")  or 0)   # 1-5 arası
    rec_detail = (rating.get("ratingDetailedRecommendation")
                  or rating.get("ratingRecommendation")
                  or "") or ""

    # ── FCF ───────────────────────────────────────────────────────────────
    fcf = (cashflow.get("freeCashFlow")
           or cashflow.get("operatingCashFlow", 0)
           or incomes[0].get("freeCashFlow", 0) if incomes else 0) or 0

    revenue    = (incomes[0].get("revenue", 0)   if incomes else 0) or 0
    net_income = (incomes[0].get("netIncome", 0) if incomes else 0) or 0

    return {
        # Kimlik
        "ticker":        ticker,
        "companyName":   profile.get("companyName", ticker),
        "sector":        profile.get("sector", "N/A"),
        "industry":      profile.get("industry", "N/A"),
        "description":   (profile.get("description", "") or "")[:400],
        "exchange":      profile.get("exchangeShortName", ""),
        "website":       profile.get("website", ""),
        "image":         profile.get("image", ""),

        # Piyasa verisi
        "price":         price,
        "change_pct":    chg_pct,
        "mktCap":        quote.get("market_cap") or profile.get("mktCap", 0) or 0,
        "beta":          profile.get("beta", 0) or 0,
        "volAvg":        profile.get("volAvg", 0) or 0,

        # 52 hafta
        "52wHigh":       w52h,
        "52wLow":        w52l,

        # Temel metrikler
        "peRatio":       pe,
        "debtToEquity":  de,
        "roic":          roic,
        "grossMargin":   gross_margin,

        # Finansallar
        "revenue":       revenue,
        "netIncome":     net_income,
        "freeCashFlow":  fcf,
        "revenueGrowth": rev_growth,

        # Analist
        "analystTarget": analyst_target,
        "analystHigh":   analyst_high,
        "analystLow":    analyst_low,
        "recommendation": rec_detail,
        "ratingScore":   rec_score,

        # Backward compat
        "pbRatio":       metrics.get("pbRatio") or ratios.get("priceToBookRatio") or 0,
        "operatingCashFlow": cashflow.get("operatingCashFlow", 0) or 0,
        "researchAndDevelopmentExpenses": (incomes[0].get("researchAndDevelopmentExpenses", 0) if incomes else 0) or 0,
        "earningsGrowth": 0,
        "revenueGrowth":  rev_growth,
        "dividendYield":  ratios.get("dividendYield") or ratios.get("dividendYieldTTM") or 0,
        "forwardPE":      0,
        "priceToSales":   ratios.get("priceToSalesRatio") or 0,
        "analystCount":   0,

        # Raw
        "_profile":    profile,
        "_metrics":    metrics,
        "_ratios":     ratios,
        "_pt":         pt,
        "_rating":     rating,
        "_financials": cashflow,
    }


def batch_enrich(tickers: list[str], delay: float = 0.25) -> list[dict]:
    results = []
    for ticker in tickers:
        try:
            data = enrich_ticker(ticker)
            if data.get("companyName") or data.get("price"):
                results.append(data)
        except Exception as exc:
            logger.warning("batch_enrich failed for %s: %s", ticker, exc)
        time.sleep(delay)
    return results
