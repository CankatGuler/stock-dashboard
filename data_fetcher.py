# data_fetcher.py — yfinance only (ücretsiz, API key gerektirmez)
#
# yfinance tk.info içerdiği alanlar:
#   currentPrice, previousClose, marketCap, beta
#   trailingPE, forwardPE, trailingEps
#   fiftyTwoWeekHigh, fiftyTwoWeekLow
#   dividendYield, revenueGrowth, grossMargins
#   freeCashflow, debtToEquity, returnOnEquity
#   targetMeanPrice, targetHighPrice, targetLowPrice
#   recommendationKey, numberOfAnalystOpinions
#   totalRevenue, netIncomeToCommon, longName, sector, industry

import time
import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def _safe_float(val, default=0.0):
    """None veya geçersiz değeri güvenle float'a çevir."""
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def get_quote(ticker):
    """Sadece fiyat güncellemesi için — portföy sekmesi kullanır."""
    try:
        fi    = yf.Ticker(ticker).fast_info
        price = getattr(fi, "last_price", None)
        if price and float(price) > 0:
            prev = getattr(fi, "previous_close", price) or price
            chg  = ((float(price) - float(prev)) / float(prev) * 100) if prev else 0
            return {
                "price":             float(price),
                "changesPercentage": round(chg, 2),
                "symbol":            ticker,
            }
    except Exception as exc:
        logger.warning("get_quote failed for %s: %s", ticker, exc)
    return None


def enrich_ticker(ticker):
    """
    yfinance tk.info ile tek çağrıda tüm verileri çek.
    fast_info: hızlı fiyat/52H (her zaman çalışır)
    info:      tüm metrikler (throttle olabilir ama genelde çalışır)
    """
    info = {}
    fi   = {}

    # 1. fast_info — fiyat ve 52H için (çok hızlı, her zaman güvenilir)
    try:
        fast = yf.Ticker(ticker).fast_info
        fi = {
            "price":    _safe_float(getattr(fast, "last_price", None)),
            "prev":     _safe_float(getattr(fast, "previous_close", None)),
            "mktCap":   _safe_float(getattr(fast, "market_cap", None)),
            "52wHigh":  _safe_float(getattr(fast, "year_high", None)),
            "52wLow":   _safe_float(getattr(fast, "year_low", None)),
        }
    except Exception as exc:
        logger.warning("fast_info failed for %s: %s", ticker, exc)

    # 2. tk.info — tüm metrikler
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("tk.info failed for %s: %s", ticker, exc)

    # ── Fiyat ─────────────────────────────────────────────────────────────
    price = (_safe_float(info.get("currentPrice"))
             or _safe_float(info.get("regularMarketPrice"))
             or fi.get("price", 0))

    prev = _safe_float(info.get("previousClose")) or fi.get("prev", price)
    change_pct = ((price - prev) / prev * 100) if prev and price else 0

    # ── Piyasa değeri ─────────────────────────────────────────────────────
    mkt_cap = (_safe_float(info.get("marketCap"))
               or fi.get("mktCap", 0))

    # ── 52 Hafta ──────────────────────────────────────────────────────────
    w52h = (_safe_float(info.get("fiftyTwoWeekHigh"))
            or fi.get("52wHigh", 0))
    w52l = (_safe_float(info.get("fiftyTwoWeekLow"))
            or fi.get("52wLow", 0))

    # ── Temel metrikler ───────────────────────────────────────────────────
    beta    = _safe_float(info.get("beta"))
    pe      = _safe_float(info.get("trailingPE")) or _safe_float(info.get("forwardPE"))
    fwd_pe  = _safe_float(info.get("forwardPE"))
    eps     = _safe_float(info.get("trailingEps"))
    de      = _safe_float(info.get("debtToEquity"))
    roe     = _safe_float(info.get("returnOnEquity"))   # ROIC proxy
    gm      = _safe_float(info.get("grossMargins"))
    rev_gr  = _safe_float(info.get("revenueGrowth"))
    div     = _safe_float(info.get("dividendYield"))
    fcf     = _safe_float(info.get("freeCashflow"))
    revenue = _safe_float(info.get("totalRevenue"))
    net_inc = _safe_float(info.get("netIncomeToCommon"))
    op_cf   = _safe_float(info.get("operatingCashflow"))

    # ── Analist ───────────────────────────────────────────────────────────
    tgt_mean  = _safe_float(info.get("targetMeanPrice"))
    tgt_high  = _safe_float(info.get("targetHighPrice"))
    tgt_low   = _safe_float(info.get("targetLowPrice"))
    rec       = info.get("recommendationKey", "") or ""
    n_analyst = int(info.get("numberOfAnalystOpinions") or 0)

    # ── Kimlik ────────────────────────────────────────────────────────────
    company = info.get("longName") or info.get("shortName") or ticker
    sector  = info.get("sector", "N/A") or "N/A"
    industry = info.get("industry", "N/A") or "N/A"
    desc    = (info.get("longBusinessSummary", "") or "")[:400]
    website = info.get("website", "") or ""
    exchange = info.get("exchange", "") or ""

    return {
        # Kimlik
        "ticker":       ticker,
        "companyName":  company,
        "sector":       sector,
        "industry":     industry,
        "description":  desc,
        "exchange":     exchange,
        "website":      website,
        "image":        "",

        # Piyasa verisi
        "price":        price,
        "change_pct":   round(change_pct, 2),
        "mktCap":       mkt_cap,
        "beta":         beta,
        "volAvg":       _safe_float(info.get("averageVolume")),

        # 52 hafta
        "52wHigh":      w52h,
        "52wLow":       w52l,

        # Temel metrikler
        "peRatio":      pe,
        "forwardPE":    fwd_pe,
        "eps":          eps,
        "debtToEquity": de,
        "roic":         roe,
        "grossMargin":  gm,
        "dividendYield": div,

        # Finansallar
        "revenue":      revenue,
        "netIncome":    net_inc,
        "freeCashFlow": fcf,
        "operatingCashFlow": op_cf,
        "revenueGrowth": rev_gr,
        "researchAndDevelopmentExpenses": _safe_float(info.get("researchAndDevelopment")),
        "earningsGrowth": _safe_float(info.get("earningsGrowth")),

        # Analist
        "analystTarget":  tgt_mean,
        "analystHigh":    tgt_high,
        "analystLow":     tgt_low,
        "recommendation": rec,
        "ratingScore":    0,
        "analystCount":   n_analyst,
        "pbRatio":        _safe_float(info.get("priceToBook")),
        "priceToSales":   _safe_float(info.get("priceToSalesTrailing12Months")),

        # Raw
        "_info": info,
        "_profile": {},
        "_metrics": {},
        "_financials": {},
        "_quote": {},
    }


def batch_enrich(tickers, delay=0.3):
    results = []
    for ticker in tickers:
        try:
            data = enrich_ticker(ticker)
            if data.get("price") or data.get("companyName") != ticker:
                results.append(data)
        except Exception as exc:
            logger.warning("batch_enrich failed for %s: %s", ticker, exc)
        time.sleep(delay)
    return results
