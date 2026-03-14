# radar_engine.py — Fırsat Radarı v2
#
# YENİ 5 Katmanlı Puanlama:
#   Katman 1 — Zengin Temel Skor (0-100): gelir büyümesi, FCF, ROE, marj, beta
#   Katman 2 — Haber Etkisi     (0-100): sinyal kalitesi + kaynak güvenilirliği
#   Katman 3 — Gerçek Sürpriz   (0-100): EPS beat + analist konsensüs sapması
#   Katman 4 — Momentum Skoru   (0-100): RSI, 52H pozisyon, hacim patlaması
#   Katman 5 — Makro Çarpanı    (0.6-1.3): VIX, yield curve, piyasa rejimi
#
# Formül:
#   Radar = (Temel×0.25 + Haber×0.30 + Sürpriz×0.20 + Momentum×0.15) × Makro_Çarpanı
#   + Insider_Bonus (0-10)

import os, re, json, time, logging
from datetime import datetime, timezone, timedelta
import requests, feedparser

logger = logging.getLogger(__name__)

# ─── Haber kaynakları ────────────────────────────────────────────────────────
# Seeking Alpha kaldırıldı (gürültü), SEC EDGAR + Bloomberg eklendi

RADAR_RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.marketwatch.com/rss/realtimeheadlines",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]

BLOCKED_DOMAINS = {
    "seekingalpha.com", "zerohedge.com", "motleyfool.com",
    "investorplace.com", "benzinga.com", "fool.com",
    "stocktwits.com", "reddit.com", "penny-stocks.com",
}

SIGNAL_KEYWORDS = [
    "contract", "deal", "partnership", "acquisition", "merger",
    "fda approval", "fda approved", "patent", "earnings beat",
    "revenue beat", "guidance raised", "insider buy", "form 4",
    "buyback", "dividend increase", "upgrade", "breakthrough",
    "record revenue", "milestone", "awarded", "selected",
    "wins contract", "secures deal", "closes acquisition",
    "eps beat", "above estimates", "exceeded expectations",
]

NOISE_KEYWORDS = [
    "analyst says could", "might", "speculation", "rumor",
    "sources say", "allegedly", "expected to", "prediction",
]

FALSE_POSITIVES = {
    "US","UK","EU","CEO","CFO","IPO","GDP","ETF","SEC","FED",
    "AI","IT","OR","AT","BY","IN","TO","OF","ON","BE","DO",
    "THE","AND","FOR","NEW","TOP","BIG","OIL","GAS","EPS",
    "INC","LLC","LTD","PLC","NYSE","WSJ","CNN","BBC","NBC",
    "EST","PST","GMT","USD","EUR","GBP","YTD","QOQ","YOY",
}

KNOWN_TICKERS = {
    "NVDA","AMD","INTC","QCOM","TSM","AVGO","MU","AMAT","LRCX","KLAC","ASML",
    "AAPL","MSFT","GOOGL","GOOG","META","AMZN","TSLA","NFLX","CRM","ORCL",
    "PLTR","CRWD","PANW","ZS","NET","DDOG","SNOW","MDB","ABNB","SHOP",
    "LMT","RTX","NOC","GD","BA","HII","LDOS","SAIC","CACI","AXON","KTOS",
    "LLY","ISRG","MRNA","BNTX","REGN","BIIB","GILD","VRTX","INCY",
    "CAT","GE","PWR","HON","ETN","DE","EMR","XYL","ROK",
    "V","MA","SPGI","JPM","GS","BAC","WFC","BLK","AXP","ALL",
    "NEE","CEG","VST","DUK","SO","AEP","EQIX","AMT","PLD",
    "DVN","XOM","CVX","COP","EOG","OXY","KMI","WMB",
    "RKLB","ASTS","COST","LULU","BKNG","CIEN",
}


# ─── Haber çekme ─────────────────────────────────────────────────────────────

def fetch_radar_news(max_age_hours: int = 24) -> list[dict]:
    articles = []
    cutoff   = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for feed_url in RADAR_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:30]:
                url = entry.get("link", "")
                if any(d in url for d in BLOCKED_DOMAINS):
                    continue
                title   = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
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
        except Exception as e:
            logger.warning("RSS failed %s: %s", feed_url, e)

    # NewsAPI
    api_key = os.getenv("NEWS_API_KEY", "")
    if api_key:
        try:
            from_date = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime("%Y-%m-%d")
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": "stock earnings contract acquisition FDA",
                        "language": "en", "from": from_date,
                        "sortBy": "publishedAt", "pageSize": 50, "apiKey": api_key},
                timeout=15,
            )
            resp.raise_for_status()
            for a in resp.json().get("articles", []):
                src_url = a.get("url", "")
                if any(d in src_url for d in BLOCKED_DOMAINS):
                    continue
                articles.append({
                    "title":     a.get("title", ""),
                    "summary":   (a.get("description", "") or "")[:300],
                    "url":       src_url,
                    "published": a.get("publishedAt", ""),
                    "source":    a.get("source", {}).get("name", ""),
                })
        except Exception as e:
            logger.warning("NewsAPI failed: %s", e)

    logger.info("Radar: %d articles fetched", len(articles))
    return articles


def filter_signal_articles(articles: list[dict]) -> list[dict]:
    result = []
    for a in articles:
        text       = f"{a['title']} {a['summary']}".lower()
        has_signal = any(kw in text for kw in SIGNAL_KEYWORDS)
        has_noise  = sum(1 for kw in NOISE_KEYWORDS if kw in text) >= 2
        if has_signal and not has_noise:
            result.append({**a, "is_signal": True})
    return result


def extract_tickers_from_articles(articles: list[dict]) -> dict[str, list[dict]]:
    ticker_map: dict[str, list[dict]] = {}
    for article in articles:
        text  = f"{article['title']} {article['summary']}"
        found = set()
        for m in re.finditer(r'\(([A-Z]{1,5})\)', text):
            t = m.group(1)
            if t not in FALSE_POSITIVES:
                found.add(t)
        for w in re.findall(r'\b[A-Z]{2,5}\b', text):
            if w in KNOWN_TICKERS and w not in FALSE_POSITIVES:
                found.add(w)
        for ticker in found:
            ticker_map.setdefault(ticker, []).append(article)
    return ticker_map


# ─── Katman 1: Zengin Temel Skor ─────────────────────────────────────────────

def get_fundamental_score(ticker: str) -> tuple[float, dict]:
    """
    yfinance tk.info ile zengin temel skor (0-100).
    Gelir büyümesi, FCF, ROE, brüt marj, beta hepsi dahil.
    """
    try:
        import yfinance as yf
        info  = yf.Ticker(ticker).info
        fi    = yf.Ticker(ticker).fast_info

        score = 40.0
        meta  = {"ticker": ticker}

        price     = float(info.get("currentPrice") or info.get("regularMarketPrice") or
                          getattr(fi, "last_price", 0) or 0)
        mkt_cap   = float(info.get("marketCap") or getattr(fi, "market_cap", 0) or 0)
        pe        = float(info.get("trailingPE") or 0)
        fpe       = float(info.get("forwardPE") or 0)
        rev_gr    = float(info.get("revenueGrowth") or 0)      # yüzde (0.15 = %15)
        gross_m   = float(info.get("grossMargins") or 0)
        roe       = float(info.get("returnOnEquity") or 0)
        fcf       = float(info.get("freeCashflow") or 0)
        beta      = float(info.get("beta") or 1.0)
        div       = float(info.get("dividendYield") or 0)
        rec       = (info.get("recommendationKey") or "").lower()
        tgt       = float(info.get("targetMeanPrice") or 0)
        n_analyst = int(info.get("numberOfAnalystOpinions") or 0)
        sector    = info.get("sector", "")

        meta.update({"price": price, "market_cap": mkt_cap, "pe": pe,
                     "fpe": fpe, "rev_gr": rev_gr, "gross_m": gross_m,
                     "roe": roe, "fcf": fcf, "beta": beta, "sector": sector,
                     "rec": rec, "tgt": tgt, "n_analyst": n_analyst})

        # Piyasa değeri
        if mkt_cap > 200e9: score += 12
        elif mkt_cap > 50e9: score += 8
        elif mkt_cap > 10e9: score += 5
        elif mkt_cap > 1e9:  score += 2

        # Gelir büyümesi — en önemli faktör
        if rev_gr > 0.30:   score += 18
        elif rev_gr > 0.15: score += 12
        elif rev_gr > 0.05: score += 6
        elif rev_gr < 0:    score -= 8

        # Brüt marj — rekabet gücü
        if gross_m > 0.60:   score += 10
        elif gross_m > 0.35: score += 6
        elif gross_m > 0.20: score += 3
        elif gross_m < 0.10: score -= 5

        # ROE — sermaye verimliliği
        if roe > 0.25:   score += 8
        elif roe > 0.15: score += 5
        elif roe > 0.08: score += 2
        elif roe < 0:    score -= 6

        # FCF — gerçek para kazanıyor mu?
        if fcf > 5e9:   score += 8
        elif fcf > 1e9: score += 5
        elif fcf > 0:   score += 2
        elif fcf < 0:   score -= 4

        # P/E — büyümeyle birlikte değerlendir
        if pe > 0:
            if fpe > 0 and fpe < pe * 0.7:  score += 6   # Forward PE çok düşük = büyüme beklentisi
            elif pe < 15:                    score += 5   # Ucuz
            elif pe > 80 and rev_gr < 0.20: score -= 8   # Pahalı + düşük büyüme

        # Beta — risk profili (düşük beta bonus değil, sadece ceza yok)
        if beta > 2.5: score -= 5

        # Analist konsensüs
        if rec in ("strong_buy", "buy") and n_analyst >= 10: score += 6
        elif rec in ("strong_buy", "buy"):                    score += 3
        elif rec == "sell":                                   score -= 8

        # Analist hedef upside
        if tgt > 0 and price > 0:
            upside = (tgt - price) / price
            if upside > 0.30:   score += 8
            elif upside > 0.15: score += 4
            elif upside < -0.10: score -= 5

        return round(min(100, max(0, score)), 1), meta

    except Exception as e:
        logger.warning("Fundamental score failed %s: %s", ticker, e)
        return 40.0, {"ticker": ticker, "price": 0, "market_cap": 0}


# ─── Katman 2: Temel Çarpan ───────────────────────────────────────────────────

def get_base_multiplier(score: float) -> float:
    if score >= 75:  return 1.2
    elif score >= 60: return 1.0
    elif score >= 40: return 0.8
    else:             return 0.6


# ─── Katman 3: Momentum Skoru ─────────────────────────────────────────────────

def get_momentum_score(ticker: str, fundamental_meta: dict) -> float:
    """
    RSI, 52H pozisyon, hacim patlaması — 0-100 arası.
    Haberin zaten fiyatlanıp fiyatlanmadığını ölçer.
    """
    try:
        import yfinance as yf
        fi    = yf.Ticker(ticker).fast_info
        price = float(getattr(fi, "last_price", 0) or 0)
        w52h  = float(getattr(fi, "year_high", 0) or 0)
        w52l  = float(getattr(fi, "year_low", 0) or 0)
        vol   = float(getattr(fi, "last_volume", 0) or 0)
        avgvol= float(getattr(fi, "three_month_average_volume", 0) or 1)
        prev  = float(getattr(fi, "previous_close", price) or price)

        score = 50.0

        # 52H pozisyon: ideal = %40-80 arası (potansiyel var ama henüz zirve değil)
        if w52h > w52l and (w52h - w52l) > 0:
            pos = (price - w52l) / (w52h - w52l) * 100
            if 40 <= pos <= 80:   score += 15   # İdeal bölge
            elif 80 < pos <= 95:  score += 8    # Yakın ama abartılı değil
            elif pos > 95:        score -= 10   # Zirveye çok yakın, fiyatlandı
            elif pos < 20:        score -= 5    # Çok düşük, trend kötü

        # Hacim patlaması
        vol_ratio = vol / avgvol if avgvol > 0 else 1
        if vol_ratio >= 3.0:   score += 20   # Devasa hacim — kurumsal hareket
        elif vol_ratio >= 2.0: score += 12
        elif vol_ratio >= 1.5: score += 6
        elif vol_ratio < 0.5:  score -= 8    # Hacimsiz hareket — güvenilmez

        # Günlük değişim
        if prev > 0 and price > 0:
            chg = (price - prev) / prev * 100
            if 2 <= chg <= 8:    score += 10   # Güçlü ama aşırı değil
            elif chg > 10:       score -= 5    # Aşırı hareket, geç kalındı
            elif chg < -5:       score -= 10   # Düşüş trendi

        return round(min(100, max(0, score)), 1)

    except Exception as e:
        logger.debug("Momentum score failed %s: %s", ticker, e)
        return 50.0


# ─── Katman 4: Makro Çarpanı ──────────────────────────────────────────────────

def get_macro_multiplier() -> tuple[float, str]:
    """
    VIX ve piyasa rejiminden makro çarpanı hesapla.
    Streamlit session state yoksa yfinance'ten direkt çek.
    Returns (multiplier, description)
    """
    try:
        import yfinance as yf
        vix   = float(yf.Ticker("^VIX").fast_info.last_price or 20)
        spx_fi = yf.Ticker("^GSPC").fast_info
        spx_chg = 0.0
        spx_prev = float(getattr(spx_fi, "previous_close", 0) or 0)
        spx_price= float(getattr(spx_fi, "last_price", 0) or 0)
        if spx_prev > 0:
            spx_chg = (spx_price - spx_prev) / spx_prev * 100

        if vix < 15:
            multiplier = 1.3
            desc = f"VIX {vix:.0f} — Sakin piyasa, risk iştahı yüksek"
        elif vix < 20:
            multiplier = 1.1
            desc = f"VIX {vix:.0f} — Normal, olumlu ortam"
        elif vix < 25:
            multiplier = 1.0
            desc = f"VIX {vix:.0f} — Orta belirsizlik"
        elif vix < 30:
            multiplier = 0.85
            desc = f"VIX {vix:.0f} — Yüksek volatilite, dikkatli ol"
        else:
            multiplier = 0.70
            desc = f"VIX {vix:.0f} — Panik ortamı, spekülatif girişten kaçın"

        # S&P 500 sert düşüşünde ek ceza
        if spx_chg < -2.0:
            multiplier = max(0.6, multiplier - 0.15)
            desc += f" | S&P {spx_chg:.1f}% — Piyasa düşüşte"

        return round(multiplier, 2), desc

    except Exception as e:
        logger.debug("Macro multiplier failed: %s", e)
        return 1.0, "Makro veri alınamadı"


# ─── Katman 5: Insider Bonus ──────────────────────────────────────────────────

def get_insider_bonus(ticker: str) -> float:
    """
    Son 14 günde insider alımı varsa bonus puan (0-10).
    """
    try:
        from insider_tracker import fetch_insider_transactions, score_transactions
        txs    = fetch_insider_transactions(ticker, days=14)
        scored = score_transactions(txs)
        if scored["buy_count"] == 0:
            return 0.0
        bonus = 0.0
        if scored["ceo_involved"]:   bonus += 5.0
        if scored["cluster_buy"]:    bonus += 4.0
        elif scored["buy_count"] > 0: bonus += 2.0
        if scored["buy_value"] > 1e6: bonus += 1.0
        return min(10.0, bonus)
    except Exception:
        return 0.0


# ─── Claude Radar Analizi ─────────────────────────────────────────────────────

RADAR_SYSTEM_PROMPT = """Sen bir fırsat tarama uzmanısın.

HABER ETKİSİ (0-100):
- FDA onayı, büyük sözleşme, satın alma, CEO alımı → 70-100
- Güçlü kazanç, ürün lansmanı, anlaşma → 50-70
- Analist güncellemesi, küçük haber → 20-50
- Belirsiz, spekülatif → 0-20

SÜRPRIZ FAKTÖRÜ (0-100):
- Tamamen beklenmedik → 70-100
- Kısmen beklenen ama zamanlama sürpriz → 40-70
- Zaten fiyatlanmış olabilir → 0-40

ÇIKTI: Sadece JSON, başka hiçbir şey:
{"haber_etkisi": <0-100>, "surpriz_faktoru": <0-100>, "neden": "<tek cümle>", "tavsiye": "<İncele|Takibe Al|Önemsiz>", "katalizor": "<kısa>"}"""


def analyse_radar_opportunity(ticker: str, articles: list[dict], macro_desc: str = "") -> dict | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or not articles:
        return None

    import anthropic as _ant
    news_text = "\n".join([f"• {a['title']} [{a.get('source','')}]" for a in articles[:5]])
    macro_line = f"\nMakro Ortam: {macro_desc}" if macro_desc else ""

    user_msg = f"HİSSE: {ticker}\n\nSON HABERLER:\n{news_text}{macro_line}\n\nDeğerlendir."

    try:
        client  = _ant.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-opus-4-5", max_tokens=300,
            system=RADAR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = (message.content[0].text if message.content else "").strip()
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

        data = json.loads(raw)
        data.setdefault("haber_etkisi",    0)
        data.setdefault("surpriz_faktoru", 0)
        data.setdefault("neden",           "")
        data.setdefault("tavsiye",         "Önemsiz")
        data.setdefault("katalizor",       "")
        data["haber_etkisi"]    = max(0, min(100, int(data["haber_etkisi"])))
        data["surpriz_faktoru"] = max(0, min(100, int(data["surpriz_faktoru"])))
        return data
    except Exception as e:
        logger.warning("Radar Claude failed %s: %s", ticker, e)
        return None


# ─── Ana Radar Fonksiyonu ─────────────────────────────────────────────────────

def run_radar(
    max_age_hours: int = 24,
    min_radar_score: float = 55.0,
    max_tickers: int = 20,
    progress_callback=None,
) -> list[dict]:
    """
    Fırsat Radarı v2 — 5 katmanlı puanlama.

    Formül:
      Radar = (Temel×0.25 + Haber×0.30 + Sürpriz×0.20 + Momentum×0.15)
              × Makro_Çarpanı + Insider_Bonus
    """
    # Makro çarpanı — bir kez hesapla
    macro_multiplier, macro_desc = get_macro_multiplier()
    logger.info("Makro çarpan: %.2f (%s)", macro_multiplier, macro_desc)

    # Haberleri çek ve filtrele
    all_articles    = fetch_radar_news(max_age_hours=max_age_hours)
    signal_articles = filter_signal_articles(all_articles)
    if not signal_articles:
        signal_articles = all_articles[:50]

    # Ticker tespiti
    ticker_map = extract_tickers_from_articles(signal_articles)
    if not ticker_map:
        logger.warning("Radar: No tickers found")
        return []

    sorted_tickers = sorted(ticker_map.items(), key=lambda x: len(x[1]), reverse=True)[:max_tickers]
    results = []
    total   = len(sorted_tickers)

    for idx, (ticker, articles) in enumerate(sorted_tickers):
        if progress_callback:
            progress_callback(ticker, idx + 1, total)

        # Katman 1: Zengin Temel Skor
        fundamental_score, meta = get_fundamental_score(ticker)
        multiplier = get_base_multiplier(fundamental_score)

        # Katman 2: Haber Etkisi (Claude)
        claude_result = analyse_radar_opportunity(ticker, articles, macro_desc)
        if not claude_result:
            continue

        haber_etkisi    = claude_result["haber_etkisi"]
        surpriz_faktoru = claude_result["surpriz_faktoru"]

        # Katman 3: Momentum
        momentum_score = get_momentum_score(ticker, meta)

        # Katman 4: Insider Bonus
        insider_bonus = get_insider_bonus(ticker)
        if insider_bonus > 0:
            logger.info("Insider bonus %s: +%.1f", ticker, insider_bonus)

        # Final Formül
        radar_score = (
            fundamental_score * 0.25 +
            haber_etkisi       * 0.30 +
            surpriz_faktoru    * 0.20 +
            momentum_score     * 0.15
        ) * macro_multiplier + insider_bonus

        radar_score = round(min(100, max(0, radar_score)), 1)

        if radar_score < min_radar_score:
            continue

        results.append({
            "ticker":            ticker,
            "radar_score":       radar_score,
            "fundamental_score": fundamental_score,
            "momentum_score":    momentum_score,
            "haber_etkisi":      haber_etkisi,
            "surpriz_faktoru":   surpriz_faktoru,
            "insider_bonus":     insider_bonus,
            "macro_multiplier":  macro_multiplier,
            "macro_desc":        macro_desc,
            "neden":             claude_result["neden"],
            "tavsiye":           claude_result["tavsiye"],
            "katalizor":         claude_result.get("katalizor", ""),
            "articles":          articles[:5],
            "price":             meta.get("price", 0),
            "market_cap":        meta.get("market_cap", 0),
            "rev_gr":            meta.get("rev_gr", 0),
            "gross_m":           meta.get("gross_m", 0),
            "roe":               meta.get("roe", 0),
            "beta":              meta.get("beta", 0),
            "sector":            meta.get("sector", ""),
            "rec":               meta.get("rec", ""),
            "haber_sayisi":      len(articles),
            "timestamp":         datetime.now().strftime("%H:%M"),
        })

        time.sleep(0.3)

    results.sort(key=lambda x: x["radar_score"], reverse=True)
    logger.info("Radar v2: %d opportunities above %.0f", len(results), min_radar_score)
    return results
