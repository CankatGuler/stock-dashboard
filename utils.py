# utils.py — Shared helpers, constants, and sector ticker mappings
import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# SECTOR → TICKER UNIVERSE
# Each sector maps to a curated list of representative tickers.
# These are starting candidates; FMP profile data will be used to
# enrich and confirm categorisation at runtime.
# ---------------------------------------------------------------------------
# S&P 500 + Nasdaq Önemli Hisseler — 11 GICS Sektörü
SECTOR_TICKERS: dict[str, list[str]] = {

    # 1. Bilgi Teknolojisi
    "Bilgi Teknolojisi": [
        # Donanım & Semiconductor
        "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC",
        "AMAT", "LRCX", "KLAC", "MU", "ADI", "MCHP", "MPWR", "ON",
        "MRVL", "WOLF", "SWKS", "QRVO", "MTSI", "ONTO", "ENTG", "FORM",
        # Yazılım & Cloud
        "CRM", "ACN", "IBM", "ORCL", "NOW", "ADBE", "INTU", "SNPS",
        "CDNS", "ANSS", "HUBS", "WDAY", "DDOG", "MDB", "SNOW", "ZS",
        "OKTA", "TEAM", "ESTC", "GTLB", "PATH", "AI", "BBAI", "SOUN",
        # Siber Güvenlik
        "FTNT", "PANW", "CRWD", "CYBR", "S", "TENB", "QLYS", "VRNT",
        # Network & Donanım
        "ANET", "JNPR", "CSCO", "DELL", "HPE", "STX", "WDC", "NTAP",
        "PSTG", "SMCI", "GLW", "KEYS", "VNET", "ARM", "PLTR", "IONQ", "QUBT", "RGTI", "ARQQ", "PAYO", "AMBA", "IDCC", "CEVA", "SLAB",
        # AI Altyapısı
        "VRT", "TSM", "ASML", "ACLS", "MKSI",
        # Kripto & Blockchain
        "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BTDR", "IREN", "CIFR", "BITF",
    ],

    # 2. Sağlık Hizmetleri
    "Sağlık Hizmetleri": [
        # Büyük İlaç
        "LLY", "JNJ", "ABBV", "MRK", "PFE", "BMY", "AMGN", "GILD",
        # Biyoteknoloji
        "REGN", "VRTX", "BIIB", "MRNA", "BNTX", "INCY", "ALNY",
        "SRPT", "RARE", "EXEL", "GMAB", "NBIX", "UTHR", "ACAD",
        "CRSP", "BEAM", "EDIT", "NTLA", "VERV", "ARCT", "RXRX",
        # Medikal Cihaz
        "TMO", "ABT", "DHR", "ISRG", "BSX", "MDT", "SYK", "ZTS",
        "EW", "ALGN", "RMD", "DXCM", "PODD", "IDXX", "IQV", "HOLX",
        # Sağlık Sigortası & Hizmetleri
        "UNH", "ELV", "CI", "HUM", "CVS", "MCK", "CAH", "ABC",
        # NYSE American Sağlık Mid-Cap
        "ACST", "ADMA", "AGIO", "AKRO", "ARDX", "ARQT", "ASRT", "ATRC",
        "AVNS", "AXNX", "BCYC", "BLFS", "BNGO", "BPMC", "CABA", "CDMO",
        "CLDX", "CMRX", "CNMD", "COHU", "CRNX", "CTLT", "DBTX", "DCPH",
    ],

    # 3. Finans
    "Finans": [
        # Büyük Bankalar
        "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "USB",
        "TFC", "PNC", "COF", "FITB", "RF", "HBAN", "KEY", "CFG",
        # Ödeme & Fintech
        "V", "MA", "AXP", "PYPL", "SQ", "AFRM", "SOFI", "UPST",
        "COIN", "HOOD", "MKTX", "LPLA", "RJF", "SF", "BILL", "FLYW", "NVEI",
        # Varlık Yönetimi & Borsa
        "BLK", "SPGI", "MCO", "ICE", "CME", "CBOE", "SCHW", "BK",
        "STT", "NTRS", "IVZ", "BEN", "AMG", "VCTR",
        # Sigorta
        "PRU", "MET", "AFL", "ALL", "TRV", "CB", "MMC", "AON",
        # NYSE American Finans Mid-Cap
        "CURO", "ECPG", "ENVA", "FCFS", "GHL", "GPMT", "HFRO", "HLI",
        "IIPR", "LADR", "MAIN", "NMFC", "PFLT", "PSEC", "SLRC", "TPVG",
    ],

    # 4. Tüketici Takdiri (Consumer Discretionary)
    "Tüketici Takdiri": [
        # E-ticaret & Teknoloji
        "AMZN", "TSLA", "BKNG", "ABNB", "UBER", "LYFT", "DASH", "CART",
        "CHWY", "ETSY", "W", "OSTK", "PRTS",
        # Perakende
        "HD", "LOW", "TJX", "ROST", "ORLY", "AZO", "BBY", "KMX",
        # Yeme-İçme & Eğlence
        "MCD", "SBUX", "CMG", "YUM", "QSR", "WING", "TXRH", "DINE",
        "MAR", "HLT", "MGM", "WYNN", "LVS", "CZR", "DKNG", "PENN",
        # Otomobil
        "F", "GM", "RIVN", "LCID", "CVNA", "AN", "GPC", "APTV",
        # Konut
        "DHI", "LEN", "PHM", "TOL", "NVR", "MTH",
        # Moda & Diğer
        "NKE", "LULU", "PVH", "RL", "TPR", "CPRI", "SKX",
    ],

    # 5. İletişim Hizmetleri
    "İletişim Hizmetleri": [
        # Sosyal Medya & İnternet
        "GOOGL", "GOOG", "META", "SNAP", "PINS", "RDDT", "MTCH",
        "IAC", "ZG", "TRIP", "YELP", "ANGI",
        # Streaming & Medya
        "NFLX", "DIS", "CMCSA", "WBD", "PARA", "FOXA", "FOX",
        "NWSA", "NWS", "SIRI", "IACI", "LYV",
        # Oyun
        "TTWO", "EA", "RBLX", "U", "ZNGA", "DVAS", "PLTK",
        # Telekom
        "T", "VZ", "TMUS", "CHTR", "LUMN", "FYBR",
    ],

    # 6. Sanayi (Industrials)
    "Sanayi": [
        # Savunma
        "LMT", "RTX", "NOC", "GD", "BA", "HII", "TDG", "LDOS",
        "SAIC", "CACI", "AXON", "AVAV", "KTOS", "DRS", "ACHR",
        # Makine & Ekipman
        "CAT", "DE", "EMR", "ETN", "ROK", "IR", "PH", "DOV",
        "AME", "HUBB", "FTV", "GNRC", "ALLE", "OTIS", "CARR",
        # Havacılık & Uzay
        "GE", "HON", "TT", "JCI", "RKLB", "ASTS", "LUNR", "JOBY", "ACHR", "RDW", "SPCE", "ASTR", "PL", "BKSY",
        # Ulaşım & Lojistik
        "UPS", "FDX", "JBHT", "CHRW", "XPO", "SAIA", "ODFL",
        # İnşaat & Mühendislik
        "FLR", "PWR", "MTZ", "PRIM", "ACM", "J", "KBR",
        # NYSE American Sanayi Mid-Cap
        "AMRC", "ARIS", "AZEK", "BWMN", "CENX", "CLB", "CTOS", "DLX",
        "DNOW", "DY", "ECVT", "ESAB", "FWRD", "GBX", "GTES", "HXL",
        "ITRI", "KFRC", "MYRG", "NX", "OSIS", "PRLB", "RXO", "SHYF",
    ],

    # 7. Temel Tüketim (Consumer Staples)
    "Temel Tüketim": [
        # Perakende
        "WMT", "COST", "KR", "BJ", "GO", "SFM", "WINN", "CASY",
        # İçecek
        "KO", "PEP", "MNST", "CELH", "FIZZ", "COKE",
        # Gıda
        "PG", "MDLZ", "GIS", "K", "CPB", "CAG", "SJM", "HRL",
        "TSN", "MKC", "CHD", "CLX", "SYY", "PFGC", "USFD",
        # Tütün & Kişisel Bakım
        "PM", "MO", "BTI", "EL", "COTY", "CL", "KMB",
    ],

    # 8. Enerji
    "Enerji": [
        # Büyük Petrol
        "XOM", "CVX", "COP", "OXY", "HES", "MRO", "APA", "OVV",
        # E&P
        "EOG", "FANG", "DVN", "SM", "MGY", "CIVI", "CPE", "PDCE",
        # Servis
        "SLB", "HAL", "BKR", "NOV", "WHD", "NR", "NINE",
        # Rafineri
        "PSX", "VLO", "MPC", "DK", "PBF",
        # Boru Hattı & Midstream
        "KMI", "WMB", "OKE", "ET", "EPD", "MPLX", "PAA", "TRGP",
        # Yenilenebilir
        "ENPH", "SEDG", "FSLR", "RUN", "ARRY", "NOVA", "SHLS",
        # NYSE American Enerji Mid-Cap
        "AMPY", "ARCH", "BATL", "CDEV", "ESTE", "FTCO", "GPOR", "HNRG",
        "KALU", "MNRL", "MTDR", "NOG", "PANL", "PARR", "PTEN", "REX",
        "RING", "ROCC", "SBR", "SBOW", "SFL", "SNMP", "SWN", "TALO",
    ],

    # 9. Kamu Hizmetleri (Utilities)
    "Kamu Hizmetleri": [
        # Elektrik
        "NEE", "SO", "DUK", "AEP", "SRE", "D", "EXC", "XEL",
        "ED", "ETR", "FE", "EIX", "PCG", "PEG", "AES", "NI",
        "CMS", "WEC", "DTE", "LNT", "EVRG", "OGE", "NWE", "AVA",
        # Nükleer & Temiz Enerji
        "VST", "CEG", "NRG", "CWEN", "AY", "BEP", "NOVA",
        "SMR", "OKLO", "NNE", "BWXT", "CCJ",
    ],

    # 10. Gayrimenkul (Real Estate)
    "Gayrimenkul": [
        # Veri Merkezi & Tower REIT
        "AMT", "CCI", "EQIX", "DLR", "IRM", "SBAC",
        # Sanayi & Lojistik REIT
        "PLD", "STAG", "COLD", "EGP", "FR",
        # Konut REIT
        "AVB", "EQR", "ESS", "UDR", "MAA", "CPT", "NMD",
        # Ofis REIT
        "BXP", "SLG", "ARE", "HIW", "CUZ",
        # Perakende REIT
        "SPG", "O", "NNN", "WPC", "KIM", "REG", "FRT", "BRX",
        # Self-Storage & Diğer
        "PSA", "EXR", "CUBE", "LSI", "NSA", "WELL", "VTR",
        # Mortgage REIT
        "AGNC", "NLY", "MFA", "RITM", "TWO",
    ],

    # 11. Malzeme (Materials)
    "Malzeme": [
        # Kimya
        "LIN", "APD", "ECL", "SHW", "IFF", "PPG", "RPM",
        "HUN", "CC", "OLN", "EMN", "CE", "WLK", "LYB", "OLIN",
        # Metal & Madencilik
        "FCX", "NEM", "NUE", "STLD", "RS", "CMC", "ATI",
        "X", "CLF", "AA", "CENX", "MP", "CINT",
        # Lityum & Pil Malzemeleri
        "ALB", "SQM", "LAC", "LTHM", "PLL", "LITP",
        # Ambalaj
        "PKG", "IP", "WRK", "SEE", "BMS", "SLGN", "BERY",
        # Orman & Kağıt
        "WY", "PCH", "RYN", "CTT",
        # NYSE American Malzeme Mid-Cap
        "AMR", "ARNC", "ATZAF", "CSTM", "FTAI", "GEF", "HWKN", "IPEX",
        "KRO", "MERC", "METC", "MTRN", "NGVT", "NTIC", "OMN", "PCRX",
        "PRM", "RYAM", "SLCA", "SXT", "TROX", "VNTR", "WLKP", "ZEUS",
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
