# radar_engine.py — Fırsat Radarı
#
# 3 Katmanlı Puanlama:
#   Katman 1 — Temel Skor      : Şirketin fundamentals kalitesi (0-100)
#   Katman 2 — Haber Etkisi    : Bu haberin hisse için önemi (0-100)
#   Katman 3 — Sürpriz Faktörü : Beklenmemiş mi? (0-100)
#
# Radar Puanı = Temel_Skor × Çarpan + Haber_Etkisi × 0.4 + Sürpriz × 0.3
# Temel Çarpan: 0-40→0.6 | 41-60→0.8 | 61-75→1.0 | 75+→1.2

import os
import re
import json
import logging
from datetime import datetime, timezone, timedelta

import requests
import feedparser
import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RSS Kaynakları — Genel finansal haber akışları
# ---------------------------------------------------------------------------
RADAR_RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",       # CNBC Markets
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",        # CNBC Tech
    "https://feeds.reuters.com/reuters/businessNews",               # Reuters Business
    "https://www.marketwatch.com/rss/realtimeheadlines",            # MarketWatch
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",               # WSJ Markets
    "https://seekingalpha.com/feed.xml",                            # Seeking Alpha
]

# Ticker tespiti için regex — büyük harf 1-5 karakter, bilinen prefixlerden sonra
TICKER_PATTERN = re.compile(
    r'\b(?:NYSE|NASDAQ|ticker|symbol|shares of|stock\s+(?:of\s+)?)?\s*'
    r'\(([A-Z]{1,5})\)'  # (NVDA) formatı
    r'|\b([A-Z]{2,5})\b(?=\s+(?:stock|shares|surged|jumped|fell|dropped|rose|gained|soared))',
    re.IGNORECASE
)

# Haber sinyali kelimeleri — bunlar olmadan haber zayıf sinyal
SIGNAL_KEYWORDS = [
    "contract", "deal", "partnership", "acquisition", "merger", "fda approval",
    "patent", "earnings beat", "revenue", "guidance", "insider buy", "form 4",
    "buyback", "dividend", "upgrade", "breakthrough", "launch", "ipo",
    "sözleşme", "anlaşma", "onay", "kazanç", "içeriden alım", "büyüme",
    "record", "milestone", "raised", "expansion", "awarded", "selected",
    "wins", "secures", "closes", "completes", "announces"
]

# Gürültü kelimeleri — bunlar varsa haber zayıf
NOISE_KEYWORDS = [
    "analyst says", "could", "might", "opinion", "prediction", "forecast",
    "speculation", "rumor", "report says", "sources say", "allegedly"
]

# ---------------------------------------------------------------------------
# Haber Çekme
# ---------------------------------------------------------------------------

def fetch_radar_news(max_age_hours: int = 24) -> list[dict]:
    """
    Tüm RSS kaynaklarından son haberleri çek.
    Returns list of {title, summary, url, published, source}
    """
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for feed_url in RADAR_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:30]:  # Her kaynaktan max 30 haber
                title   = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                url     = entry.get("link", "")

                # Tarih kontrolü
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass

                if published and published < cutoff:
                    continue

                articles.append({
                    "title":     title,
                    "summary":   summary[:500],
                    "url":       url,
                    "published": published.isoformat() if published else "",
                    "source":    feed.feed.get("title", feed_url),
                })
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", feed_url, exc)

    logger.info("Radar: %d raw articles fetched", len(articles))
    return articles


def fetch_newsapi_radar(days: int = 1) -> list[dict]:
    """
    NewsAPI'den genel finansal haber çek (opsiyonel).
    """
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        return []

    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q":        "stock OR shares OR earnings OR contract OR acquisition",
                "language": "en",
                "from":     from_date,
                "sortBy":   "publishedAt",
                "pageSize": 50,
                "apiKey":   api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for a in data.get("articles", []):
            articles.append({
                "title":     a.get("title", ""),
                "summary":   (a.get("description", "") or "")[:300],
                "url":       a.get("url", ""),
                "published": a.get("publishedAt", ""),
                "source":    a.get("source", {}).get("name", ""),
            })
        return articles
    except Exception as exc:
        logger.warning("NewsAPI radar fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Ticker Tespiti
# ---------------------------------------------------------------------------

# Bilinen ticker → şirket adı mapping (genişletilebilir)
KNOWN_TICKERS = {
    "NVDA", "AMD", "INTC", "QCOM", "TSM", "AVGO", "MU", "AMAT", "LRCX", "KLAC",
    "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "TSLA", "NFLX", "CRM",
    "PLTR", "CRWD", "PANW", "ZS", "NET", "DDOG", "SNOW", "MDB", "ABNB",
    "LMT", "RTX", "NOC", "GD", "BA", "HII", "LDOS", "SAIC", "CACI",
    "CCJ", "NNE", "OKLO", "SMR", "BWXT", "VST", "CEG", "ETR",
    "RKLB", "LUNR", "ASTS", "RDW", "SPCE", "ASTR",
    "ISRG", "MRNA", "BNTX", "REGN", "BIIB", "GILD", "VRTX", "ILMN",
    "IREN", "MARA", "RIOT", "CLSK", "HUT", "BTDR",
    "PPA", "ITA", "XAR", "SOFI", "NBIS", "CRDF", "ONDS", "ZETA",
    "VRT", "DELL", "HPE", "IBM", "ORCL", "SAP", "ADBE", "NOW",
    "AMSC", "PLUG", "BE", "FCEL", "ENPH", "SEDG",
    "AAON", "ACHR", "JOBY", "LILM",
}

# Yanlış pozitif ticker'lar (sık geçen ama hisse olmayan kelimeler)
FALSE_POSITIVES = {
    "US", "UK", "EU", "CEO", "CFO", "IPO", "GDP", "ETF", "SEC", "FED",
    "AI", "IT", "OR", "AT", "BY", "IN", "TO", "OF", "ON", "BE", "DO",
    "THE", "AND", "FOR", "NEW", "TOP", "BIG", "OIL", "GAS", "EPS",
    "INC", "LLC", "LTD", "PLC", "NYSE", "WSJ", "CNN", "BBC", "NBC",
    "EST", "PST", "GMT", "USD", "EUR", "GBP", "YTD", "QOQ", "YOY",
}


def extract_tickers_from_articles(articles: list[dict]) -> dict[str, list[dict]]:
    """
    Haberlerden ticker sembolleri çıkar.
    Returns dict: ticker → [article, ...]
    """
    ticker_map: dict[str, list[dict]] = {}

    for article in articles:
        text   = f"{article['title']} {article['summary']}"
        found  = set()

        # Yöntem 1: (TICKER) formatı — en güvenilir
        for m in re.finditer(r'\(([A-Z]{1,5})\)', text):
            t = m.group(1)
            if t not in FALSE_POSITIVES:
                found.add(t)

        # Yöntem 2: Bilinen ticker listesiyle eşleştir
        words = re.findall(r'\b[A-Z]{2,5}\b', text)
        for w in words:
            if w in KNOWN_TICKERS and w not in FALSE_POSITIVES:
                found.add(w)

        for ticker in found:
            ticker_map.setdefault(ticker, []).append(article)

    logger.info("Radar: %d unique tickers extracted", len(ticker_map))
    return ticker_map


def filter_signal_articles(articles: list[dict]) -> list[dict]:
    """
    Sadece sinyal içeren haberleri döndür.
    """
    result = []
    for a in articles:
        text = f"{a['title']} {a['summary']}".lower()
        has_signal = any(kw in text for kw in SIGNAL_KEYWORDS)
        has_noise  = sum(1 for kw in NOISE_KEYWORDS if kw in text) >= 2
        if has_signal and not has_noise:
            result.append(a)
    return result


# ---------------------------------------------------------------------------
# Temel Skor (yfinance)
# ---------------------------------------------------------------------------

def get_fundamental_score(ticker: str) -> tuple[float, dict]:
    """
    yfinance ile hızlı temel skor hesapla (0-100).
    Returns (score, meta_dict)
    """
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        info = tk.fast_info

        score = 50.0  # başlangıç
        meta  = {"ticker": ticker, "price": 0, "market_cap": 0}

        price      = getattr(info, "last_price",    0) or 0
        mkt_cap    = getattr(info, "market_cap",    0) or 0
        pe         = getattr(info, "pe_ratio",      0) or 0

        meta["price"]      = float(price)
        meta["market_cap"] = float(mkt_cap)
        meta["pe"]         = float(pe)

        # Büyük cap bonus
        if mkt_cap > 100e9:   score += 15
        elif mkt_cap > 10e9:  score += 10
        elif mkt_cap > 1e9:   score += 5

        # PE ratio değerlendirme
        if 0 < pe < 20:   score += 10
        elif 20 <= pe < 40: score += 5
        elif pe > 100:    score -= 10
        elif pe < 0:      score -= 5

        # Fiyat varlığı
        if price > 0:     score += 5

        return min(100, max(0, score)), meta

    except Exception as exc:
        logger.warning("Fundamental score failed for %s: %s", ticker, exc)
        return 50.0, {"ticker": ticker, "price": 0, "market_cap": 0, "pe": 0}


# ---------------------------------------------------------------------------
# Temel Çarpan
# ---------------------------------------------------------------------------

def get_base_multiplier(fundamental_score: float) -> float:
    if fundamental_score >= 75:  return 1.2
    elif fundamental_score >= 61: return 1.0
    elif fundamental_score >= 41: return 0.8
    else:                         return 0.6


# ---------------------------------------------------------------------------
# Claude Radar Analizi
# ---------------------------------------------------------------------------

RADAR_SYSTEM_PROMPT = """Sen bir fırsat tarama uzmanısın. Sana bir hisse sembolü ve o hisse hakkındaki son haberler verilecek.

Görevin:
1. Bu haberin bu hisse için ne kadar önemli olduğunu değerlendirmek (Haber Etkisi: 0-100)
2. Bu haberin beklenen mi yoksa sürpriz mi olduğunu değerlendirmek (Sürpriz Faktörü: 0-100)
3. Kısa bir neden açıklamak

HABER ETKİSİ KURALLARI (0-100):
- FDA onayı, büyük sözleşme, satın alma, içeriden alım → 70-100
- Ortaklık, ürün lansmanı, güçlü kazanç → 50-70
- Analist güncellemesi, küçük haber → 20-50
- Belirsiz, spekülatif, genel piyasa haberi → 0-20

SÜRPRİZ FAKTÖRÜ KURALLARI (0-100):
- Tamamen beklenmedik, piyasa daha bilmiyor → 70-100
- Kısmen beklenen ama zamanlaması sürpriz → 40-70
- Zaten fiyatlanmış olabilir → 0-40

ÇIKTI KURALI: Sadece JSON döndür, başka hiçbir şey yazma:
{
  "haber_etkisi": <0-100 tam sayı>,
  "surpriz_faktoru": <0-100 tam sayı>,
  "neden": "<tek cümle açıklama>",
  "tavsiye": "<İncele | Takibe Al | Önemsiz>"
}"""


def analyse_radar_opportunity(
    ticker: str,
    articles: list[dict],
    model: str = "claude-opus-4-5",
) -> dict | None:
    """
    Claude'a radar haberi gönder, haber etkisi ve sürpriz faktörü al.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not articles:
        return None

    # Haberleri birleştir
    news_text = "\n".join([
        f"• {a['title']} [{a.get('source','')}]"
        for a in articles[:5]  # Max 5 haber
    ])

    user_msg = f"""
HİSSE: {ticker}

SON HABERLER:
{news_text}

Bu hisse için haber etkisi ve sürpriz faktörünü değerlendir.
""".strip()

    try:
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=300,
            system=RADAR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = message.content[0].text if message.content else ""

        # JSON parse
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            import re as _re
            cleaned = _re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = _re.sub(r"\n?```$", "", cleaned).strip()

        data = json.loads(cleaned)
        data.setdefault("haber_etkisi",    0)
        data.setdefault("surpriz_faktoru", 0)
        data.setdefault("neden",           "")
        data.setdefault("tavsiye",         "Önemsiz")

        # Clamp
        data["haber_etkisi"]    = max(0, min(100, int(data["haber_etkisi"])))
        data["surpriz_faktoru"] = max(0, min(100, int(data["surpriz_faktoru"])))

        return data

    except Exception as exc:
        logger.warning("Radar Claude analysis failed for %s: %s", ticker, exc)
        return None


# ---------------------------------------------------------------------------
# Ana Radar Fonksiyonu
# ---------------------------------------------------------------------------

def run_radar(
    max_age_hours: int = 24,
    min_radar_score: float = 60.0,
    max_tickers: int = 20,
    progress_callback=None,
) -> list[dict]:
    """
    Fırsat Radarını çalıştır.
    
    Returns list of radar results sorted by radar_score desc:
    {
        ticker, radar_score, fundamental_score, haber_etkisi,
        surpriz_faktoru, neden, tavsiye, articles, price, market_cap
    }
    """
    # 1. Haberleri çek
    rss_articles     = fetch_radar_news(max_age_hours=max_age_hours)
    newsapi_articles = fetch_newsapi_radar(days=1)
    all_articles     = rss_articles + newsapi_articles

    # 2. Sinyal filtresi uygula
    signal_articles = filter_signal_articles(all_articles)
    if not signal_articles:
        signal_articles = all_articles[:50]  # Filtre çok kısıtlıysa ham haberleri kullan

    # 3. Ticker tespiti
    ticker_map = extract_tickers_from_articles(signal_articles)
    if not ticker_map:
        logger.warning("Radar: No tickers found in articles")
        return []

    # En fazla haber çıkan ticker'ları önceliklendir
    sorted_tickers = sorted(
        ticker_map.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )[:max_tickers]

    results = []
    total   = len(sorted_tickers)

    for idx, (ticker, articles) in enumerate(sorted_tickers):
        if progress_callback:
            progress_callback(ticker, idx + 1, total)

        # 4. Temel skor
        fundamental_score, meta = get_fundamental_score(ticker)
        multiplier = get_base_multiplier(fundamental_score)

        # 5. Claude analizi
        claude_result = analyse_radar_opportunity(ticker, articles)
        if not claude_result:
            continue

        haber_etkisi    = claude_result["haber_etkisi"]
        surpriz_faktoru = claude_result["surpriz_faktoru"]
        neden           = claude_result["neden"]
        tavsiye         = claude_result["tavsiye"]

        # 6. Radar skoru hesapla
        # Radar = Temel × Çarpan × 0.3 + Haber × 0.4 + Sürpriz × 0.3
        radar_score = (
            fundamental_score * multiplier * 0.30 +
            haber_etkisi                   * 0.40 +
            surpriz_faktoru                * 0.30
        )
        radar_score = round(min(100, radar_score), 1)

        if radar_score < min_radar_score:
            continue

        results.append({
            "ticker":             ticker,
            "radar_score":        radar_score,
            "fundamental_score":  round(fundamental_score, 1),
            "haber_etkisi":       haber_etkisi,
            "surpriz_faktoru":    surpriz_faktoru,
            "neden":              neden,
            "tavsiye":            tavsiye,
            "articles":           articles[:5],
            "price":              meta.get("price", 0),
            "market_cap":         meta.get("market_cap", 0),
            "haber_sayisi":       len(articles),
            "timestamp":          datetime.now().strftime("%H:%M"),
        })

    results.sort(key=lambda x: x["radar_score"], reverse=True)
    logger.info("Radar: %d opportunities found above %.0f score", len(results), min_radar_score)
    return results
