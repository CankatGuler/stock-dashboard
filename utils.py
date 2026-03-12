# utils.py — Shared helpers, constants, and sector ticker mappings
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# SECTOR → TICKER UNIVERSE
# Each sector maps to a curated list of representative tickers.
# These are starting candidates; FMP profile data will be used to
# enrich and confirm categorisation at runtime.
# ---------------------------------------------------------------------------
# S&P 500 Resmi 11 Sektörü (GICS — Global Industry Classification Standard)
SECTOR_TICKERS: dict[str, list[str]] = {

    # 1. Bilgi Teknolojisi
    "Bilgi Teknolojisi": [
        "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC",
        "AMAT", "LRCX", "KLAC", "MU", "ADI", "MCHP", "MPWR", "ON",
        "CRM", "ACN", "IBM", "ORCL", "NOW", "ADBE", "INTU", "SNPS",
        "CDNS", "ANSS", "FTNT", "PANW", "CRWD", "PLTR", "ANET", "DELL",
        "HPE", "STX", "WDC", "NTAP", "PSTG", "SMCI", "GLW", "KEYS",
    ],

    # 2. Sağlık Hizmetleri
    "Sağlık Hizmetleri": [
        "LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "DHR",
        "AMGN", "ISRG", "REGN", "VRTX", "GILD", "BIIB", "MRNA", "BNTX",
        "BSX", "MDT", "SYK", "ZTS", "ELV", "CI", "HUM", "CVS",
        "MCK", "CAH", "ABC", "IDXX", "IQV", "CRL", "PKI", "HOLX",
        "BAX", "BDX", "EW", "ALGN", "RMD", "DXCM", "PODD", "INCY",
    ],

    # 3. Finans
    "Finans": [
        "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS",
        "BLK", "SPGI", "C", "AXP", "USB", "TFC", "PNC", "COF",
        "MCO", "ICE", "CME", "CBOE", "SCHW", "BK", "STT", "NTRS",
        "PRU", "MET", "AFL", "ALL", "TRV", "CB", "MMC", "AON",
        "AJG", "WTW", "RE", "RNR", "HIG", "L", "GL", "FNF",
    ],

    # 4. Tüketici Takdiri (Consumer Discretionary)
    "Tüketici Takdiri": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX",
        "BKNG", "MAR", "HLT", "MGM", "WYNN", "LVS", "CZR", "DKNG",
        "ABNB", "UBER", "LYFT", "F", "GM", "RIVN", "LCID", "CVNA",
        "ROST", "ORLY", "AZO", "BBY", "KMX", "AN", "GPC", "APTV",
        "DHI", "LEN", "PHM", "TOL", "NVR", "MTH", "KBH", "MHO",
    ],

    # 5. İletişim Hizmetleri
    "İletişim Hizmetleri": [
        "GOOGL", "GOOG", "META", "NFLX", "DIS", "CMCSA", "T", "VZ",
        "TMUS", "CHTR", "WBD", "FOX", "FOXA", "PARA", "NWSA", "NWS",
        "TTWO", "EA", "ATVI", "RBLX", "U", "SNAP", "PINS", "MTCH",
        "IAC", "ZG", "TRIP", "YELP", "LUMN", "FYBR", "LBRDA",
    ],

    # 6. Sanayi (Industrials)
    "Sanayi": [
        "GE", "CAT", "HON", "UPS", "RTX", "LMT", "NOC", "GD",
        "BA", "HII", "TDG", "LDOS", "SAIC", "CACI", "L3H", "AXON",
        "AVAV", "KTOS", "DE", "EMR", "ETN", "ROK", "IR", "PH",
        "DOV", "AME", "XYL", "VRSK", "HUBB", "FTV", "GNRC", "ALLE",
        "OTIS", "CARR", "TT", "JCI", "FLR", "PWR", "MTZ", "PRIM",
    ],

    # 7. Temel Tüketim (Consumer Staples)
    "Temel Tüketim": [
        "WMT", "PG", "KO", "PEP", "COST", "PM", "MO", "MDLZ",
        "CL", "KMB", "GIS", "K", "CPB", "CAG", "SJM", "HRL",
        "TSN", "MKC", "CHD", "CLX", "EL", "COTY", "REV", "SFM",
        "KR", "SYY", "PFGC", "USFD", "BJ", "GO", "CASY", "WINN",
    ],

    # 8. Enerji
    "Enerji": [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "BKR", "NOV",
        "PSX", "VLO", "MPC", "OXY", "DVN", "FANG", "PXD", "APA",
        "MRO", "HES", "OVV", "SM", "MGY", "CIVI", "CPE", "PDCE",
        "KMI", "WMB", "OKE", "ET", "EPD", "MPLX", "PAA", "TRGP",
    ],

    # 9. Kamu Hizmetleri (Utilities)
    "Kamu Hizmetleri": [
        "NEE", "SO", "DUK", "AEP", "SRE", "D", "EXC", "XEL",
        "ED", "ETR", "FE", "EIX", "PCG", "PEG", "AES", "NI",
        "CMS", "WEC", "DTE", "LNT", "EVRG", "OGE", "NWE", "AVA",
        "VST", "CEG", "NRG", "CWEN", "AY", "BEP", "NOVA",
    ],

    # 10. Gayrimenkul (Real Estate)
    "Gayrimenkul": [
        "AMT", "PLD", "CCI", "EQIX", "PSA", "O", "WELL", "DLR",
        "SPG", "VTR", "AVB", "EQR", "ESS", "UDR", "MAA", "CPT",
        "NNN", "WPC", "STAG", "COLD", "EXR", "CUBE", "LSI", "NSA",
        "ARE", "BXP", "SLG", "KIM", "REG", "FRT", "BRX", "RPAI",
    ],

    # 11. Malzeme (Materials)
    "Malzeme": [
        "LIN", "APD", "ECL", "SHW", "FCX", "NEM", "NUE", "STLD",
        "RS", "CMC", "WOR", "ATI", "X", "CLF", "AA", "CENX",
        "ALB", "SQM", "LAC", "LTHM", "MP", "CINT", "IFF", "PPG",
        "RPM", "HUN", "CC", "OLN", "EMN", "CE", "WLK", "LYB",
        "PKG", "IP", "WRK", "SEE", "BMS", "SLGN", "BERY",
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
