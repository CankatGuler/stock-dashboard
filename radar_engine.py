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
    Tek bir info çağrısı — fast_info ayrı çağrı gerektirmez.
    """
    try:
        import yfinance as yf
        tk    = yf.Ticker(ticker)
        info  = tk.info
        fi    = tk.fast_info  # Aynı objeden al, ikinci HTTP isteği yok

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
        return 35.0, {"ticker": ticker, "price": 0, "market_cap": 0}


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

def get_macro_multiplier() -> tuple[float, str, dict]:
    """
    6 faktörlü gelişmiş makro çarpanı:
      VIX×0.30 + Faiz(10Y)×0.25 + YieldCurve×0.20 + DXY×0.15 + SPX_trend×0.10
    Her faktör 0-100 arasında puanlanır, ağırlıklı ortalamayla 0.60-1.35 arasında çarpan üretilir.
    Returns (multiplier, description, detail_dict)
    """
    try:
        import yfinance as yf

        def _safe_price(ticker):
            try:
                return float(yf.Ticker(ticker).fast_info.last_price or 0)
            except Exception:
                return 0.0

        def _safe_prev(ticker):
            try:
                fi = yf.Ticker(ticker).fast_info
                return float(getattr(fi, "previous_close", 0) or 0)
            except Exception:
                return 0.0

        # ── Veri çek ─────────────────────────────────────────────────────
        vix       = _safe_price("^VIX")       or 20.0
        tnx       = _safe_price("^TNX")       or 4.0    # 10Y tahvil faizi (%)
        irx       = _safe_price("^IRX")       or 4.0    # 3M tahvil faizi (%)
        dxy       = _safe_price("DX-Y.NYB")   or 102.0  # Dolar endeksi
        gold      = _safe_price("GC=F")       or 2000.0 # Altın
        copper    = _safe_price("HG=F")       or 4.0    # Bakır

        spx_price = _safe_price("^GSPC")
        spx_prev  = _safe_prev("^GSPC")
        spx_chg   = ((spx_price - spx_prev) / spx_prev * 100) if spx_prev > 0 else 0

        # S&P 500 200 günlük MA yaklaşımı: son 1 yıl değişimi
        try:
            spx_hist  = yf.Ticker("^GSPC").history(period="1y", interval="1d")["Close"]
            spx_ma200 = float(spx_hist.mean()) if len(spx_hist) > 0 else spx_price
        except Exception:
            spx_ma200 = spx_price

        # ── Faktör 1: VIX (ağırlık %30) ──────────────────────────────────
        if   vix < 12:  vix_score, vix_note = 95, f"VIX {vix:.0f} — Aşırı sakin"
        elif vix < 16:  vix_score, vix_note = 85, f"VIX {vix:.0f} — Sakin, risk iştahı yüksek"
        elif vix < 20:  vix_score, vix_note = 70, f"VIX {vix:.0f} — Normal"
        elif vix < 25:  vix_score, vix_note = 50, f"VIX {vix:.0f} — Orta gerginlik"
        elif vix < 30:  vix_score, vix_note = 30, f"VIX {vix:.0f} — Yüksek volatilite"
        elif vix < 40:  vix_score, vix_note = 15, f"VIX {vix:.0f} — Panik bölgesi"
        else:           vix_score, vix_note = 5,  f"VIX {vix:.0f} — Ekstrem panik"

        # ── Faktör 2: 10Y Faiz (ağırlık %25) ─────────────────────────────
        # Yüksek faiz büyüme hisselerini ezer, değerlemeyi baskılar
        if   tnx < 3.0: faiz_score, faiz_note = 90, f"10Y %{tnx:.1f} — Düşük, hisse dostu"
        elif tnx < 3.5: faiz_score, faiz_note = 75, f"10Y %{tnx:.1f} — Makul"
        elif tnx < 4.0: faiz_score, faiz_note = 60, f"10Y %{tnx:.1f} — Orta baskı"
        elif tnx < 4.5: faiz_score, faiz_note = 45, f"10Y %{tnx:.1f} — Yüksek, değerleme baskısı"
        elif tnx < 5.0: faiz_score, faiz_note = 25, f"10Y %{tnx:.1f} — Çok yüksek"
        else:           faiz_score, faiz_note = 10, f"10Y %{tnx:.1f} — Tehlike bölgesi"

        # ── Faktör 3: Yield Curve 10Y-3M (ağırlık %20) ───────────────────
        # Negatif = ters eğri = resesyon sinyali
        spread = tnx - irx
        if   spread > 1.5:  yc_score, yc_note = 90, f"Yield spread +{spread:.1f}% — Sağlıklı eğri"
        elif spread > 0.5:  yc_score, yc_note = 75, f"Yield spread +{spread:.1f}% — Normal"
        elif spread > 0.0:  yc_score, yc_note = 55, f"Yield spread +{spread:.1f}% — Düzleşiyor"
        elif spread > -0.5: yc_score, yc_note = 35, f"Yield spread {spread:.1f}% — Ters eğri başlangıcı"
        elif spread > -1.0: yc_score, yc_note = 20, f"Yield spread {spread:.1f}% — Ters eğri — resesyon riski"
        else:               yc_score, yc_note = 8,  f"Yield spread {spread:.1f}% — Derin ters eğri"

        # ── Faktör 4: DXY (ağırlık %15) ──────────────────────────────────
        # Güçlü dolar = uluslararası gelirler düşer, gelişen piyasalar sıkışır
        if   dxy < 95:   dxy_score, dxy_note = 85, f"DXY {dxy:.0f} — Zayıf dolar, olumlu"
        elif dxy < 100:  dxy_score, dxy_note = 70, f"DXY {dxy:.0f} — Normal bölge"
        elif dxy < 103:  dxy_score, dxy_note = 55, f"DXY {dxy:.0f} — Biraz güçlü"
        elif dxy < 106:  dxy_score, dxy_note = 35, f"DXY {dxy:.0f} — Güçlü dolar, baskı"
        else:            dxy_score, dxy_note = 15, f"DXY {dxy:.0f} — Çok güçlü dolar"

        # ── Faktör 5: S&P 500 Trendi (ağırlık %10) ───────────────────────
        # Piyasa 200 MA üzerinde mi + bugünkü yön
        spx_above_ma = spx_price > spx_ma200 if spx_ma200 > 0 else True
        if   spx_above_ma and spx_chg > 0.5:  spx_score, spx_note = 85, f"S&P +{spx_chg:.1f}% — Trend yukarı"
        elif spx_above_ma and spx_chg > -0.5: spx_score, spx_note = 65, f"S&P {spx_chg:+.1f}% — Stabil"
        elif spx_above_ma:                     spx_score, spx_note = 45, f"S&P {spx_chg:.1f}% — 200MA üzeri ama düşüyor"
        elif spx_chg < -1.5:                   spx_score, spx_note = 15, f"S&P {spx_chg:.1f}% — Piyasa kötü gün"
        else:                                  spx_score, spx_note = 30, f"S&P {spx_chg:+.1f}% — 200MA altı"

        # ── Altın/Bakır oranı — bonus/ceza ───────────────────────────────
        # Altın/Bakır yüksekse risk-off (güvenli limana kaçış)
        gc_ratio = (gold / copper / 500) if copper > 0 else 1.0  # normalize
        gc_penalty = 0
        if gc_ratio > 1.2:   gc_penalty = -5   # Belirgin risk-off
        elif gc_ratio > 1.4: gc_penalty = -10  # Güçlü risk-off

        # ── Ağırlıklı makro skoru ─────────────────────────────────────────
        macro_score = (
            vix_score   * 0.30 +
            faiz_score  * 0.25 +
            yc_score    * 0.20 +
            dxy_score   * 0.15 +
            spx_score   * 0.10
        ) + gc_penalty

        macro_score = max(0, min(100, macro_score))

        # ── Skor → Çarpan ─────────────────────────────────────────────────
        if   macro_score >= 80: multiplier = 1.35
        elif macro_score >= 65: multiplier = 1.15
        elif macro_score >= 50: multiplier = 1.00
        elif macro_score >= 35: multiplier = 0.85
        elif macro_score >= 20: multiplier = 0.70
        else:                   multiplier = 0.60

        # Özet açıklama
        desc = (f"Makro Skor: {macro_score:.0f}/100 → Çarpan: ×{multiplier} | "
                f"{vix_note} | {faiz_note} | {yc_note} | {dxy_note} | {spx_note}")

        detail = {
            "macro_score":  round(macro_score, 1),
            "multiplier":   multiplier,
            "vix":          vix,   "vix_score":  vix_score,
            "tnx":          tnx,   "faiz_score": faiz_score,
            "spread":       round(spread, 2), "yc_score": yc_score,
            "dxy":          dxy,   "dxy_score":  dxy_score,
            "spx_chg":      round(spx_chg, 2), "spx_score": spx_score,
            "gc_ratio":     round(gc_ratio, 2),
            "notes": {
                "vix": vix_note, "faiz": faiz_note, "yc": yc_note,
                "dxy": dxy_note, "spx": spx_note,
            }
        }

        logger.info("Makro çarpan: %.2f (skor: %.0f)", multiplier, macro_score)
        return round(multiplier, 2), desc, detail

    except Exception as e:
        logger.warning("Macro multiplier failed: %s", e)
        return 1.0, "Makro veri alınamadı", {}


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


# ─── Gerçek Sürpriz: EPS Beat ────────────────────────────────────────────────

def get_eps_surprise(ticker: str) -> tuple[float, str]:
    """
    yfinance'ten son çeyrek EPS sürprizi çek.
    Returns (surprise_score 0-100, description)
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info

        # yfinance EPS sürpriz alanları
        eps_actual   = float(info.get("trailingEps") or 0)
        eps_estimate = float(info.get("epsForward") or 0)

        # Earnings history varsa daha kesin veri
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is not None and not cal.empty:
                # Bazı versiyonlarda earnings_surprise geliyor
                pass
        except Exception:
            pass

        # Analist konsensüs sapmaya bak
        rec_mean   = float(info.get("recommendationMean") or 3.0)
        n_analysts = int(info.get("numberOfAnalystOpinions") or 0)
        tgt        = float(info.get("targetMeanPrice") or 0)
        price      = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)

        score = 50.0
        desc_parts = []

        # Analist hedef sapması — temel sürpriz göstergesi
        if tgt > 0 and price > 0:
            upside = (tgt - price) / price * 100
            if upside > 40:
                score += 25
                desc_parts.append(f"Analist hedefi %{upside:.0f} yukarıda — büyük sürpriz potansiyeli")
            elif upside > 20:
                score += 15
                desc_parts.append(f"Analist hedefi %{upside:.0f} yukarıda")
            elif upside > 10:
                score += 8
                desc_parts.append(f"Analist hedefi %{upside:.0f} yukarıda")
            elif upside < -5:
                score -= 15
                desc_parts.append(f"Analist hedefi %{abs(upside):.0f} aşağıda — negatif sapma")

        # Analist konsensüs kuvveti
        if rec_mean <= 1.5 and n_analysts >= 10:
            score += 15
            desc_parts.append(f"Güçlü konsensüs alım ({n_analysts} analist)")
        elif rec_mean <= 2.0 and n_analysts >= 5:
            score += 8
            desc_parts.append(f"Al konsensüsü ({n_analysts} analist)")
        elif rec_mean >= 4.0:
            score -= 15
            desc_parts.append(f"Satış konsensüsü")

        # EPS forward vs trailing karşılaştırması
        if eps_estimate > 0 and eps_actual > 0:
            eps_growth = (eps_estimate - eps_actual) / abs(eps_actual) * 100
            if eps_growth > 30:
                score += 15
                desc_parts.append(f"EPS %{eps_growth:.0f} büyüme beklentisi")
            elif eps_growth > 15:
                score += 8
            elif eps_growth < -10:
                score -= 10
                desc_parts.append(f"EPS düşüş beklentisi")

        score = max(0, min(100, score))
        desc  = " | ".join(desc_parts) if desc_parts else "Veri yetersiz"
        return round(score, 1), desc

    except Exception as e:
        logger.debug("EPS surprise failed %s: %s", ticker, e)
        return 50.0, "EPS verisi alınamadı"


# ─── Hafıza Bağlantısı ───────────────────────────────────────────────────────

def get_memory_context(ticker: str) -> tuple[float, str]:
    """
    Hafıza sisteminden geçmiş radar skorunu çek.
    Returns (trend_bonus -5 ile +8 arası, description)
    """
    try:
        from analysis_memory import get_ticker_history
        history = get_ticker_history(ticker, limit=5)
        if not history or len(history) < 2:
            return 0.0, ""

        # Son 5 analizin skorlarını al
        scores = []
        for record in history[:5]:
            s = record.get("nihai_guven_skoru") or record.get("score") or 0
            if s:
                scores.append(float(s))

        if len(scores) < 2:
            return 0.0, ""

        latest  = scores[0]
        prev    = scores[1]
        avg     = sum(scores) / len(scores)
        trend   = latest - prev

        bonus = 0.0
        desc_parts = []

        # Trend yönü
        if trend >= 15:
            bonus += 5
            desc_parts.append(f"Skor hızla yükseliyor (+{trend:.0f} son analizde)")
        elif trend >= 8:
            bonus += 3
            desc_parts.append(f"Skor artıyor (+{trend:.0f})")
        elif trend <= -15:
            bonus -= 5
            desc_parts.append(f"Skor hızla düşüyor ({trend:.0f})")
        elif trend <= -8:
            bonus -= 3
            desc_parts.append(f"Skor geriliyor ({trend:.0f})")

        # Tutarlı yüksek performans
        if avg >= 75 and latest >= 70:
            bonus += 3
            desc_parts.append(f"Sürekli güçlü ({len(scores)} analizde ort. {avg:.0f})")
        elif avg <= 40:
            bonus -= 2
            desc_parts.append(f"Tarihsel olarak zayıf (ort. {avg:.0f})")

        desc = " | ".join(desc_parts) if desc_parts else f"Geçmiş: {len(scores)} analiz, ort. {avg:.0f}"
        return round(max(-8, min(8, bonus)), 1), desc

    except Exception as e:
        logger.debug("Memory context failed %s: %s", ticker, e)
        return 0.0, ""


# ─── Pozisyon Büyüklüğü Önerisi ──────────────────────────────────────────────

def get_position_recommendation(
    ticker: str,
    radar_score: float,
    fundamental_score: float,
    macro_multiplier: float,
    meta: dict,
) -> dict:
    """
    Risk/ödül oranına göre pozisyon büyüklüğü önerisi.
    Kelly Criterion'un basitleştirilmiş versiyonu.

    Returns:
        {
          "action":        "Güçlü Al" | "Al" | "Küçük Pozisyon" | "İzle" | "Kaçın",
          "position_pct":  Portföy yüzdesi önerisi (0-15),
          "stop_loss_pct": Önerilen stop loss yüzdesi,
          "rationale":     Açıklama,
          "risk_level":    "Düşük" | "Orta" | "Yüksek" | "Çok Yüksek",
        }
    """
    price  = meta.get("price", 0)
    tgt    = meta.get("tgt", 0)
    beta   = meta.get("beta", 1.0) or 1.0
    sector = meta.get("sector", "")
    rec    = (meta.get("rec", "") or "").lower()

    # Risk/ödül oranı
    if tgt > 0 and price > 0:
        upside    = (tgt - price) / price * 100
        downside  = beta * 15  # Beta'ya göre tahmini düşüş riski
        rr_ratio  = upside / downside if downside > 0 else 0
    else:
        upside   = 0
        rr_ratio = 0

    # Risk seviyesi
    if   beta < 0.8:                 risk_level = "Düşük"
    elif beta < 1.3:                 risk_level = "Orta"
    elif beta < 1.8:                 risk_level = "Yüksek"
    else:                            risk_level = "Çok Yüksek"

    # Makro ortam etkisi
    macro_ok = macro_multiplier >= 1.0

    # Temel karar matrisi
    if radar_score >= 75 and fundamental_score >= 65 and macro_ok and rr_ratio >= 2:
        action       = "Güçlü Al"
        position_pct = min(12, 4 + (radar_score - 75) * 0.3)
        rationale    = f"Yüksek radar skoru + güçlü temel + elverişli makro + R/R {rr_ratio:.1f}x"

    elif radar_score >= 65 and fundamental_score >= 55 and macro_ok:
        action       = "Al"
        position_pct = min(8, 2 + (radar_score - 65) * 0.2)
        rationale    = f"Güçlü sinyal, makro destekli. R/R: {rr_ratio:.1f}x"

    elif radar_score >= 55 and macro_ok:
        action       = "Küçük Pozisyon"
        position_pct = min(4, 1 + (radar_score - 55) * 0.15)
        rationale    = f"Fırsat var ama temkinli gir. Stop loss kullan."

    elif radar_score >= 50 and not macro_ok:
        action       = "İzle"
        position_pct = 0
        rationale    = f"Sinyal var ama makro ortam olumsuz (çarpan {macro_multiplier}x). Beklemeye al."

    else:
        action       = "Kaçın"
        position_pct = 0
        rationale    = f"Yetersiz skor veya olumsuz makro."

    # Beta yüksekse pozisyonu küçült
    if beta > 1.8 and position_pct > 0:
        position_pct = position_pct * 0.6
        rationale   += f" | Beta={beta:.1f} → Pozisyon küçültüldü"

    # Stop loss hesapla — ATR proxy olarak beta kullan
    stop_loss_pct = round(beta * 8, 1)  # Yüksek beta = daha geniş stop

    return {
        "action":        action,
        "position_pct":  round(position_pct, 1),
        "stop_loss_pct": min(stop_loss_pct, 20),
        "upside_pct":    round(upside, 1),
        "rr_ratio":      round(rr_ratio, 2),
        "risk_level":    risk_level,
        "rationale":     rationale,
    }



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
    min_radar_score: float = 50.0,
    max_tickers: int = 20,
    progress_callback=None,
) -> list[dict]:
    """
    Fırsat Radarı v4 — Universe-First Mimari.

    Eski yaklaşım habere bağımlıydı: haber yoksa sonuç yok.
    Yeni yaklaşım evreni tarar: haber amplify eder ama zorunlu değil.

    Adımlar:
      1. Watchlist + KNOWN_TICKERS evrenini birleştir
      2. Her hisseyi Temel + Momentum ile skorla (habersiz çalışır)
      3. Haber varsa Claude ile Haber Etkisi + Sürpriz amplify et
      4. Haber yoksa Temel + Momentum + Makro yeterli
      5. En yüksek skorları döndür

    Formül (haberli):
      Radar = (Temel×0.40 + Haber×0.25 + Sürpriz×0.15 + Momentum×0.20)
              × Makro_Çarpanı + Insider_Bonus + Hafıza_Trend

    Formül (habersiz):
      Radar = (Temel×0.55 + Momentum×0.45) × Makro_Çarpanı + Insider_Bonus + Hafıza_Trend
    """
    # ── 1. Makro çarpanı ─────────────────────────────────────────────────
    macro_multiplier, macro_desc, macro_detail = get_macro_multiplier()
    logger.info("Makro çarpan: %.2f (skor: %.0f)", macro_multiplier,
                macro_detail.get("macro_score", 0))

    # Makro ortam kötüyse (çarpan < 1.0) min skoru otomatik düşür
    # Çünkü kötü ortamda tüm hisselerin skoru aşağı çekilir
    if macro_multiplier < 0.9:
        effective_min = min_radar_score * macro_multiplier
        logger.info("Makro düzeltme: min_radar_score %s → %.1f", min_radar_score, effective_min)
        min_radar_score = effective_min

    # ── 2. Ticker evreni oluştur ─────────────────────────────────────────
    # Watchlist'i yükle ve KNOWN_TICKERS ile birleştir
    universe = set(KNOWN_TICKERS)
    try:
        from breakout_scanner import load_watchlist
        universe.update(load_watchlist())
    except Exception:
        pass

    # ── 3. Haberleri çek — zorunlu değil, amplifier ───────────────────────
    news_ticker_map = {}
    try:
        all_articles    = fetch_radar_news(max_age_hours=max_age_hours)
        signal_articles = filter_signal_articles(all_articles)
        if not signal_articles:
            signal_articles = all_articles[:50]
        news_ticker_map = extract_tickers_from_articles(signal_articles)
        logger.info("Radar: %d haber, %d ticker haberde bulundu",
                    len(all_articles), len(news_ticker_map))
    except Exception as e:
        logger.warning("Radar: Haber çekme başarısız, sadece fundamental: %s", e)

    # ── 4. Her ticker'ı önce fundamental ile hızlıca filtrele ────────────
    # Önce temel skoru düşük olanları at, API çağrısı sayısını azalt
    pre_scores = []
    total_universe = list(universe)[:80]  # Max 80 ticker tara

    for idx, ticker in enumerate(total_universe):
        if progress_callback:
            progress_callback(ticker, idx + 1, len(total_universe))
        try:
            import yfinance as yf
            # Aşama 1: Çok hızlı fast_info ile market_cap kontrolü
            # Market cap < 500M olan hisseleri hemen ele - API çağrısı tasarrufu
            fi = yf.Ticker(ticker).fast_info
            mc = float(getattr(fi, "market_cap", 0) or 0)
            if mc > 0 and mc < 500e6:  # 500M altı hisseler çok spekülatif
                continue
            # Aşama 2: Tam fundamental skor
            fund_score, meta = get_fundamental_score(ticker)
            momentum_score   = get_momentum_score(ticker, meta)
            # Ön eleme: fallback skor (35.0) ile gerçek düşük skor arasındaki fark
            # Gerçek veri geldiyse price > 0 olur
            if meta.get("price", 0) == 0 and fund_score <= 35:
                continue  # Veri gelemeyen hisseler
            articles = news_ticker_map.get(ticker, [])
            pre_scores.append((ticker, fund_score, momentum_score, meta, articles))
        except Exception as e:
            logger.debug("Pre-score failed %s: %s", ticker, e)

    # Ön skora göre sırala, en iyi max_tickers×2 adayı al
    pre_scores.sort(key=lambda x: x[1] * 0.6 + x[2] * 0.4, reverse=True)
    candidates = pre_scores[:max_tickers * 3]
    logger.info("Radar: %d aday belirlendi (evren: %d)", len(candidates), len(total_universe))

    results = []

    for ticker, fundamental_score, momentum_score, meta, articles in candidates:
        # ── Haber Etkisi — haber varsa Claude, yoksa skor tahmini ────────
        haber_etkisi    = 0
        surpriz_faktoru = 0
        neden           = ""
        tavsiye         = "İzle"
        katalizor       = ""
        claude_used     = False

        if articles:
            # Haber var: Claude ile analiz
            eps_score, eps_desc = get_eps_surprise(ticker)
            claude_result = analyse_radar_opportunity(ticker, articles, macro_desc)
            if claude_result:
                haber_etkisi    = claude_result["haber_etkisi"]
                surpriz_faktoru = round(
                    claude_result["surpriz_faktoru"] * 0.6 + eps_score * 0.4, 1
                )
                neden    = claude_result.get("neden", "")
                tavsiye  = claude_result.get("tavsiye", "İzle")
                katalizor= claude_result.get("katalizor", "")
                claude_used = True
                eps_desc_out = eps_desc
            else:
                eps_score, eps_desc_out = get_eps_surprise(ticker)
                surpriz_faktoru = eps_score * 0.4
        else:
            # Haber yok: EPS sürprizi + fundamental'dan tahmini haber etkisi
            eps_score, eps_desc_out = get_eps_surprise(ticker)
            # Fundamental skoru yüksekse habersiz de "potansiyel" var
            haber_etkisi    = min(60, fundamental_score * 0.7)
            surpriz_faktoru = eps_score * 0.4
            # Neden metni fundamental'dan üret
            upside = 0
            price  = meta.get("price", 0)
            tgt    = meta.get("tgt", 0)
            if tgt > 0 and price > 0:
                upside = (tgt - price) / price * 100
            rec    = meta.get("rec", "")
            neden  = (
                f"Temel analiz güçlü (skor {fundamental_score:.0f}). "
                + (f"Analist hedefi %{upside:.0f} yukarıda. " if upside > 10 else "")
                + (f"Konsensüs: {rec}." if rec else "")
            )
            tavsiye = (
                "İncele" if fundamental_score >= 65
                else "Takibe Al" if fundamental_score >= 50
                else "Önemsiz"
            )
            # eps_desc_out already set by get_eps_surprise above

        # ── Final Formül — haberli vs habersiz ───────────────────────────
        if claude_used:
            # Haberli: haber bilgisi daha güvenilir
            base_score = (
                fundamental_score * 0.40 +
                haber_etkisi       * 0.25 +
                surpriz_faktoru    * 0.15 +
                momentum_score     * 0.20
            )
        else:
            # Habersiz: fundamental ve momentum ağırlığı artar
            base_score = (
                fundamental_score * 0.55 +
                momentum_score     * 0.45
            )
            # Habersiz maksimum skor kısıtı: 80
            base_score = min(base_score, 80)

        insider_bonus              = get_insider_bonus(ticker)
        memory_bonus, memory_desc  = get_memory_context(ticker)

        radar_score = base_score * macro_multiplier + insider_bonus + memory_bonus
        radar_score = round(min(100, max(0, radar_score)), 1)

        if radar_score < min_radar_score:
            continue

        # ── Pozisyon Büyüklüğü Önerisi ────────────────────────────────────
        position_rec = get_position_recommendation(
            ticker, radar_score, fundamental_score, macro_multiplier, meta
        )

        results.append({
            # Temel
            "ticker":            ticker,
            "radar_score":       radar_score,
            "fundamental_score": fundamental_score,
            "momentum_score":    momentum_score,
            # Haber & Sürpriz
            "haber_etkisi":      haber_etkisi,
            "surpriz_faktoru":   surpriz_faktoru,
            "eps_score":         eps_score if 'eps_score' in dir() else 50,
            "eps_desc":          eps_desc_out,
            # Makro
            "macro_multiplier":  macro_multiplier,
            "macro_desc":        macro_desc,
            "macro_detail":      macro_detail,
            # Insider & Hafıza
            "insider_bonus":     insider_bonus,
            "memory_bonus":      memory_bonus,
            "memory_desc":       memory_desc,
            # Pozisyon
            "position_rec":      position_rec,
            # Analiz
            "neden":             neden,
            "tavsiye":           tavsiye,
            "katalizor":         katalizor,
            "haber_var":         claude_used,
            # Meta
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

        time.sleep(0.1)

    results.sort(key=lambda x: x["radar_score"], reverse=True)
    logger.info("Radar v3: %d opportunities above %.0f", len(results), min_radar_score)
    return results
