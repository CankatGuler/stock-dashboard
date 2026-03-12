# utils.py — Shared helpers, constants, and sector ticker mappings
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# SECTOR → TICKER UNIVERSE
# Each sector maps to a curated list of representative tickers.
# These are starting candidates; FMP profile data will be used to
# enrich and confirm categorisation at runtime.
# ---------------------------------------------------------------------------
SECTOR_TICKERS: dict[str, list[str]] = {
    "Yapay Zeka": [
        "NVDA", "AMD", "PLTR", "AI", "SOUN", "BBAI", "CRNC",
        "AAON", "MSFT", "GOOGL", "META", "SMCI", "ANET", "ARM",
        "IONQ", "QUBT", "RGTI", "ARQQ",
    ],
    "Nükleer Enerji": [
        "CCJ", "UEC", "DNN", "NXE", "UUUU", "LEU", "SMR",
        "OKLO", "NNE", "BW", "BWXT", "VST", "CEG", "ETR",
    ],
    "Su Teknolojileri": [
        "WTRG", "AWK", "XYL", "MSEX", "YORW", "CWCO", "PRMW",
        "FWRD", "PNR", "DHR", "A", "VEOEY",
    ],
    "İnsansı Robotlar": [
        "TSLA", "ABB", "ROK", "IRBT", "FANUY", "KION",
        "NVDA", "MVIS", "IROQ", "BDTX", "NNDM", "RBOT",
    ],
    "Batarya Sektörü": [
        "TSLA", "LTHM", "ALB", "SQM", "LAC", "ALTM",
        "FREYR", "NKLA", "QS", "MVST", "BLNK", "CHPT",
        "ENS", "FLUX",
    ],
    "Savunma Sanayii": [
        "LMT", "RTX", "NOC", "GD", "BA", "HII", "LDOS",
        "AVAV", "KTOS", "PLTR", "CACI", "SAIC", "DRS",
        "TDG", "HXL", "AXON",
    ],
    "Biyoteknoloji": [
        "MRNA", "BNTX", "REGN", "CRSP", "EDIT", "NTLA",
        "BEAM", "PACB", "RXRX", "TWST", "FATE", "BLUE",
        "AGEN", "SANA", "VERV", "ARCT",
    ],
    "Uzay Teknolojileri": [
        "RKLB", "ASTS", "SPCE", "BA", "LMT", "NOC",
        "MAXR", "BKSY", "SATL", "MNTS", "ASTR", "RDW",
        "IRDM", "VSAT", "GSAT", "PL",
    ],
    "İlaç Sektörü": [
        "JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY",
        "GILD", "AMGN", "BIIB", "VRTX", "ALNY", "INCY",
        "EXEL", "HALO", "PRGO", "JAZZ",
    ],
    "Semiconductor": [
        "NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN",
        "MCHP", "MPWR", "ON", "SWKS", "QRVO", "WOLF",
        "AMAT", "LRCX", "KLAC", "ASML",
    ],
    "Memory": [
        "MU", "WDC", "STX", "KIOXF", "SSNLF",
        "AMAT", "LRCX", "ENTG", "ONTO", "FORM", "PLAB",
        "CRUS", "RMBS", "MRAM", "NVDA",
    ],
}

# ---------------------------------------------------------------------------
# NOISE-FILTER: Keywords that elevate a news item from "noise" to "signal"
# ---------------------------------------------------------------------------
SIGNAL_KEYWORDS: list[str] = [
    r"\bcontract\b", r"\bpentagon\b", r"\bdod\b",
    r"\binsider.?buy", r"\bform.?4\b", r"\bpatent\b",
    r"\bfda\b", r"\bfaa\b", r"\binterest.?rate\b",
    r"\bsanction", r"\bmerger\b", r"\bacquisition\b",
    r"\bihale\b", r"\bsözleşme\b",                     # Turkish equivalents
]

# ---------------------------------------------------------------------------
# TIER-3 DOMAINS to exclude (clickbait / low-quality aggregators)
# ---------------------------------------------------------------------------
BLOCKED_DOMAINS: set[str] = {
    "zerohedge.com", "seekingalpha.com", "motleyfool.com",
    "investorplace.com", "benzinga.com", "fool.com",
    "stockanalysis.com", "stocktwits.com", "reddit.com",
    "tradingview.com", "wsb.com", "penny-stocks.com",
    "hotstocked.com", "smallcappower.com", "bullmarketnews.com",
}

# ---------------------------------------------------------------------------
# CATEGORY thresholds — Rocket / Balanced / Shield
# ---------------------------------------------------------------------------
ROCKET_MAX_MARKET_CAP   = 10_000_000_000    # < 10B  → Rocket
BALANCED_MAX_MARKET_CAP = 50_000_000_000    # 10-50B → Balanced
ROCKET_MIN_BETA         = 1.2               # Beta > 1.2 güçlendirir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_signal_news(title: str, description: str = "") -> bool:
    """Return True if the combined text contains at least one signal keyword."""
    combined = f"{title} {description}".lower()
    return any(re.search(pat, combined, re.IGNORECASE) for pat in SIGNAL_KEYWORDS)


def is_blocked_domain(url: str) -> bool:
    """Return True if the URL belongs to a blocked (Tier-3) domain."""
    return any(domain in url.lower() for domain in BLOCKED_DOMAINS)


def categorise_stock(stock: dict, *args) -> str:
    """
    Katalizör Potansiyeli Kategorisi — mktCap + Beta bazlı.

    Rocket   : mktCap < 10B  (büyük sıçrama potansiyeli)
    Balanced : mktCap 10-50B (orta risk/getiri)
    Shield   : mktCap > 50B  (stabil, korumalı)

    Beta > 1.2 ise Balanced → Rocket'a yükseltilir.
    """
    # stock dict'i veya eski imzayla (profile, financials) çağrılabilir
    if isinstance(stock, dict) and "mktCap" in stock:
        market_cap = stock.get("mktCap", 0) or 0
        beta       = stock.get("beta", 0) or 0
    elif isinstance(stock, dict):
        market_cap = stock.get("mktCap", 0) or 0
        beta       = stock.get("beta", 0) or 0
    else:
        market_cap = 0
        beta       = 0

    if market_cap == 0 or market_cap < ROCKET_MAX_MARKET_CAP:
        return "Rocket 🚀"
    if market_cap <= BALANCED_MAX_MARKET_CAP:
        # Beta yüksekse Rocket'a yükselt
        if beta >= ROCKET_MIN_BETA:
            return "Rocket 🚀"
        return "Balanced ⚖️"
    return "Shield 🛡️"


def score_color(score: int) -> str:
    """Map a 0-100 confidence score to a Streamlit-compatible hex colour."""
    if score >= 70:
        return "#00c48c"   # green
    if score >= 45:
        return "#f5a623"   # amber
    return "#e74c3c"       # red


def score_badge(score: int) -> str:
    """Return a small coloured HTML badge for use inside st.markdown."""
    color = score_color(score)
    return (
        f'<span style="background:{color};color:#0d1117;font-weight:700;'
        f'padding:3px 10px;border-radius:4px;font-size:1rem;">{score}</span>'
    )


def today_minus(days: int) -> str:
    """Return ISO-8601 date string for (today - days)."""
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
