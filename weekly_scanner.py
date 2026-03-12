# weekly_scanner.py — Haftalık S&P 500 Tarayıcı
#
# 2 Aşamalı Filtre:
#   Aşama 1 — yfinance ile S&P 500'ü tara, temel metriklerle top 50'yi seç (ücretsiz)
#   Aşama 2 — Top 50'yi Claude ile analiz et, puanlayarak top 25'i döndür

import os
import time
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S&P 500 Ticker Listesi
# ---------------------------------------------------------------------------

def get_sp500_tickers() -> list[str]:
    """
    Wikipedia'dan güncel S&P 500 listesini çek.
    Fallback: sabit liste.
    """
    try:
        import pandas as pd
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        logger.info("S&P 500: %d ticker Wikipedia'dan çekildi", len(tickers))
        return tickers
    except Exception as exc:
        logger.warning("Wikipedia S&P 500 çekme başarısız: %s — fallback kullanılıyor", exc)
        return SP500_FALLBACK


# Fallback — yaklaşık S&P 100 (Wikipedia erişilemezse)
SP500_FALLBACK = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","AVGO",
    "TSLA","JPM","UNH","V","XOM","MA","PG","COST","HD","JNJ",
    "ABBV","BAC","MRK","CVX","KO","PEP","ADBE","CRM","AMD","NFLX",
    "TMO","ACN","MCD","ABT","LIN","TXN","DHR","NEE","ORCL","PM",
    "WMT","CSCO","GE","IBM","INTC","QCOM","HON","UPS","RTX","CAT",
    "SPGI","GS","MS","BLK","C","WFC","AXP","USB","TFC","PNC",
    "NOW","INTU","ISRG","REGN","VRTX","AMGN","GILD","BIIB","MRNA","BMY",
    "PFE","MDT","SYK","BSX","ZTS","ELV","CI","HUM","CVS","MCK",
    "LMT","RTX","NOC","GD","BA","HII","L3H","LDOS","SAIC","CACI",
    "AMAT","LRCX","KLAC","MU","MRVL","SNPS","CDNS","FTNT","PANW","CRWD",
    "PLTR","DDOG","SNOW","MDB","NET","ZS","ABNB","UBER","LYFT","COIN",
    "VRT","DELL","HPE","STX","WDC","NTAP","PSTG","SMCI","ANET","JNPR",
    "DIS","CMCSA","NFLX","T","VZ","TMUS","CHTR","FOX","FOXA","WBD",
    "NKE","SBUX","TGT","LOW","TJX","ROST","BKNG","MAR","HLT","MGM",
    "XOM","CVX","COP","EOG","SLB","HAL","PSX","VLO","MPC","OXY",
]


# ---------------------------------------------------------------------------
# Aşama 1 — Temel Metrik Filtresi (yfinance, ücretsiz)
# ---------------------------------------------------------------------------

def score_ticker_fundamentals(ticker: str) -> tuple[float, dict]:
    """
    yfinance ile hızlı temel skor hesapla (0-100).
    Daha detaylı versiyon — haftalık tarama için optimize edilmiş.
    """
    try:
        import yfinance as yf
        tk   = yf.Ticker(ticker)
        info = tk.info  # fast_info yerine info — daha fazla veri

        score = 50.0
        meta  = {
            "ticker":      ticker,
            "name":        info.get("longName", ticker),
            "sector":      info.get("sector", "N/A"),
            "industry":    info.get("industry", "N/A"),
            "price":       info.get("currentPrice", 0) or info.get("regularMarketPrice", 0) or 0,
            "market_cap":  info.get("marketCap", 0) or 0,
            "pe":          info.get("trailingPE", 0) or 0,
            "forward_pe":  info.get("forwardPE", 0) or 0,
            "pb":          info.get("priceToBook", 0) or 0,
            "roe":         info.get("returnOnEquity", 0) or 0,
            "fcf":         info.get("freeCashflow", 0) or 0,
            "revenue_growth": info.get("revenueGrowth", 0) or 0,
            "earnings_growth": info.get("earningsGrowth", 0) or 0,
            "debt_equity": info.get("debtToEquity", 0) or 0,
            "52w_high":    info.get("fiftyTwoWeekHigh", 0) or 0,
            "52w_low":     info.get("fiftyTwoWeekLow", 0) or 0,
            "analyst_target": info.get("targetMeanPrice", 0) or 0,
            "recommendation": info.get("recommendationKey", ""),
        }

        price     = meta["price"]
        mkt_cap   = meta["market_cap"]
        pe        = meta["pe"]
        fcf       = meta["fcf"]
        rev_gr    = meta["revenue_growth"]
        earn_gr   = meta["earnings_growth"]
        roe       = meta["roe"]
        de        = meta["debt_equity"]
        w52h      = meta["52w_high"]
        target    = meta["analyst_target"]
        rec       = meta["recommendation"]

        # Büyüklük bonusu
        if mkt_cap > 500e9:   score += 15
        elif mkt_cap > 100e9: score += 10
        elif mkt_cap > 10e9:  score += 5

        # FCF pozitif mi?
        if fcf > 0:           score += 10
        elif fcf < 0:         score -= 10

        # PE değerlendirme
        if 0 < pe < 15:       score += 10
        elif 0 < pe < 25:     score += 7
        elif 0 < pe < 40:     score += 3
        elif pe > 80:         score -= 8
        elif pe < 0:          score -= 5

        # Büyüme
        if rev_gr > 0.20:     score += 12
        elif rev_gr > 0.10:   score += 8
        elif rev_gr > 0.05:   score += 4
        elif rev_gr < 0:      score -= 8

        if earn_gr > 0.20:    score += 8
        elif earn_gr > 0.10:  score += 5
        elif earn_gr < 0:     score -= 5

        # ROE
        if roe > 0.30:        score += 8
        elif roe > 0.15:      score += 5
        elif roe < 0:         score -= 5

        # Borç/Özsermaye
        if 0 <= de < 0.5:     score += 5
        elif de > 2.0:        score -= 5

        # 52 hafta yüksek yakınlığı (momentum)
        if price > 0 and w52h > 0:
            proximity = price / w52h
            if proximity > 0.95:  score += 8   # Zirveye yakın
            elif proximity > 0.85: score += 4

        # Analist hedefi
        if price > 0 and target > 0:
            upside = (target - price) / price
            if upside > 0.20:   score += 8
            elif upside > 0.10: score += 4
            elif upside < -0.10: score -= 5

        # Analist tavsiyesi
        rec_scores = {
            "strong_buy": 10, "buy": 7, "hold": 0,
            "underperform": -5, "sell": -8,
        }
        score += rec_scores.get(rec, 0)

        return min(100, max(0, round(score, 1))), meta

    except Exception as exc:
        logger.warning("Fundamental score başarısız %s: %s", ticker, exc)
        return 40.0, {"ticker": ticker, "name": ticker, "sector": "N/A",
                      "industry": "N/A", "price": 0, "market_cap": 0}


def stage1_filter(
    tickers: list[str],
    top_n: int = 50,
    progress_callback=None,
) -> list[tuple[float, dict]]:
    """
    Aşama 1: Tüm S&P 500'ü tara, temel metriklerle top_n seç.
    Returns list of (score, meta) tuples sorted desc.
    """
    scored = []
    total  = len(tickers)

    for idx, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(ticker, idx + 1, total, stage=1)

        score, meta = score_ticker_fundamentals(ticker)
        scored.append((score, meta))
        time.sleep(0.1)  # Rate limit

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]
    logger.info("Aşama 1 tamamlandı: %d/%d hisse seçildi", len(top), total)
    return top


# ---------------------------------------------------------------------------
# Aşama 2 — Claude Analizi
# ---------------------------------------------------------------------------

WEEKLY_SYSTEM_PROMPT = """Sen S&P 500 uzmanı bir kantitatif analistsin.
Sana bir hisse ve temel verileri verilecek. Haftalık perspektiften değerlendir.

PUANLAMA (0-100):
- Güçlü büyüme + pozitif FCF + makul PE → 70-100
- Orta büyüme, stabil iş modeli → 50-70
- Durgun veya riskli → 0-50

ÇIKTI: Sadece JSON, başka hiçbir şey yazma:
{
  "nihai_guven_skoru": <0-100 tam sayı>,
  "kategori": "A Tipi veya B Tipi",
  "analiz_ozeti": "<tek cümle>",
  "tavsiye": "<Ağırlık Artır | Tut | Azalt>"
}"""


def stage2_claude_analysis(
    stage1_results: list[tuple[float, dict]],
    progress_callback=None,
    model: str = "claude-opus-4-5",
) -> list[dict]:
    """
    Aşama 2: Top 50'yi Claude ile analiz et.
    Returns list of result dicts sorted by score.
    """
    import json
    import re
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY eksik")
        return []

    client  = anthropic.Anthropic(api_key=api_key)
    results = []
    total   = len(stage1_results)

    for idx, (fund_score, meta) in enumerate(stage1_results):
        ticker = meta["ticker"]

        if progress_callback:
            progress_callback(ticker, idx + 1, total, stage=2)

        user_msg = f"""
HİSSE: {ticker} — {meta.get('name', '')}
Sektör: {meta.get('sector', 'N/A')} / {meta.get('industry', 'N/A')}
Fiyat: ${meta.get('price', 0):.2f}
Piyasa Değeri: ${meta.get('market_cap', 0)/1e9:.1f}B
PE: {meta.get('pe', 0):.1f} | Forward PE: {meta.get('forward_pe', 0):.1f}
ROE: {meta.get('roe', 0):.1%}
Gelir Büyümesi: {meta.get('revenue_growth', 0):.1%}
Kazanç Büyümesi: {meta.get('earnings_growth', 0):.1%}
FCF: ${meta.get('fcf', 0)/1e9:.2f}B
Borç/Özsermaye: {meta.get('debt_equity', 0):.2f}
Analist Tavsiye: {meta.get('recommendation', 'N/A')}
Temel Skor (otomatik): {fund_score}

Haftalık perspektiften değerlendir ve JSON döndür.
""".strip()

        try:
            message = client.messages.create(
                model=model,
                max_tokens=300,
                system=WEEKLY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw     = message.content[0].text if message.content else ""
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned).strip()

            data = json.loads(cleaned)
            data.setdefault("nihai_guven_skoru", 0)
            data.setdefault("kategori", "Bilinmiyor")
            data.setdefault("analiz_ozeti", "")
            data.setdefault("tavsiye", "Tut")
            data["nihai_guven_skoru"] = max(0, min(100, int(data["nihai_guven_skoru"])))

            # Meta bilgileri ekle
            data["ticker"]       = ticker
            data["name"]         = meta.get("name", ticker)
            data["sector"]       = meta.get("sector", "N/A")
            data["industry"]     = meta.get("industry", "N/A")
            data["price"]        = meta.get("price", 0)
            data["market_cap"]   = meta.get("market_cap", 0)
            data["fund_score"]   = fund_score
            data["pe"]           = meta.get("pe", 0)
            data["revenue_growth"] = meta.get("revenue_growth", 0)
            data["fcf"]          = meta.get("fcf", 0)
            data["recommendation"] = meta.get("recommendation", "")

            results.append(data)

        except Exception as exc:
            logger.warning("Claude analizi başarısız %s: %s", ticker, exc)

        time.sleep(0.3)  # Rate limit

    results.sort(key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True)
    logger.info("Aşama 2 tamamlandı: %d hisse analiz edildi", len(results))
    return results


# ---------------------------------------------------------------------------
# Ana Tarama Fonksiyonu
# ---------------------------------------------------------------------------

def run_weekly_scan(
    top_n_stage1: int = 50,
    top_n_final: int = 25,
    progress_callback=None,
) -> list[dict]:
    """
    Haftalık S&P 500 taramasını çalıştır.

    Returns top_n_final hisse, sorted by nihai_guven_skoru desc.
    """
    logger.info("Haftalık tarama başlatılıyor...")

    # 1. S&P 500 ticker listesi
    tickers = get_sp500_tickers()

    # 2. Aşama 1 — Temel filtre
    stage1_results = stage1_filter(
        tickers,
        top_n=top_n_stage1,
        progress_callback=progress_callback,
    )

    # 3. Aşama 2 — Claude analizi
    final_results = stage2_claude_analysis(
        stage1_results,
        progress_callback=progress_callback,
    )

    return final_results[:top_n_final]
