# weekly_scanner.py — Haftalık Geniş Evren Tarayıcı
#
# 2 Aşamalı Filtre:
#   Aşama 1 — yfinance ile tara, temel metriklerle top 50'yi seç (ücretsiz)
#   Aşama 2 — Top 50'yi Claude ile analiz et, top 25'i döndür
#
# 3 Ayrı Tarama:
#   - run_weekly_scan    : S&P 500 standart tarama
#   - run_surprise_scan  : 670 liste + 100 Russell, mktCap < 50B sürpriz filtresi
#   - run_portfolio_scan : Portföydeki hisseleri analiz et

import os
import time
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Russell 2000 — 100 Seçme Mid/Small Cap Sürpriz Adayı
# ---------------------------------------------------------------------------
RUSSELL_2000_SAMPLE = [
    # Teknoloji & Yazılım
    "GTLB", "CWAN", "ALKT", "TASK", "ENFN", "BLND", "INTA", "PCVX",
    "RELY", "ALTR", "XMTR", "IONQ", "ARQQ", "QUBT", "RGTI", "SOUN",
    # Sağlık & Biyotek
    "VCEL", "NKTR", "ACCD", "PRVA", "LFST", "HAYW", "HIMS", "DOCS",
    "RXST", "PRCT", "INVA", "ALGM", "ACVA", "AVTE", "PTGX", "ACLX",
    # Finans & Fintech
    "DBTX", "INDI", "OPEN", "UWMC", "PFBC", "CBNK", "FFBC", "TOWN",
    "LCNB", "AMSF", "ESSA", "HTLF", "NBTB", "CTBI", "BSVN", "SMBC",
    # Sanayi & Savunma & Uzay
    "KTOS", "AVAV", "DRS", "RKLB", "ASTS", "ACHR", "JOBY", "LUNR",
    "SPCE", "PL", "RDW", "BKSY", "LILM", "EVEX", "ASTR", "MNTS",
    # Tüketici & Perakende
    "PRPL", "LESL", "LQDT", "XPOF", "FUL", "BARK",
    "CENT", "CATO", "CRVL", "DXPE", "ELEV", "FLXS",
    # Enerji & Temiz Enerji
    "ARRY", "SHLS", "NOVA", "CWEN", "CLNE", "AMRC", "ALTM", "NOG",
    "TALO", "ROCC", "SBOW", "MNRL", "ESTE", "CDEV",
    # Gayrimenkul
    "GMRE", "NREF", "CTRE", "NTST", "PLYM", "UHT", "GOOD",
    # Malzeme & Madencilik
    "MP", "CINT", "LAC", "LTHM", "PLL", "AMMO", "POWL",
]


# ---------------------------------------------------------------------------
# Tüm Tarama Evreni
# ---------------------------------------------------------------------------

def get_full_universe() -> list[str]:
    """670 hisselik kendi listemiz + 100 Russell 2000 seçmesi. Tekrarsız."""
    from utils import SECTOR_TICKERS
    our_list = []
    for tickers in SECTOR_TICKERS.values():
        our_list.extend(tickers)
    combined = list(dict.fromkeys(our_list + RUSSELL_2000_SAMPLE))
    logger.info("Toplam evren: %d hisse", len(combined))
    return combined


def get_sp500_tickers() -> list[str]:
    """Wikipedia'dan S&P 500 listesini çek. Fallback: sabit liste."""
    try:
        import pandas as pd
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        logger.info("S&P 500: %d ticker Wikipedia'dan çekildi", len(tickers))
        return tickers
    except Exception as exc:
        logger.warning("Wikipedia başarısız: %s — fallback", exc)
        return [
            "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","BRK-B","LLY","AVGO",
            "TSLA","JPM","UNH","V","XOM","MA","PG","COST","HD","JNJ",
            "ABBV","BAC","MRK","CVX","KO","PEP","ADBE","CRM","AMD","NFLX",
            "TMO","ACN","MCD","ABT","LIN","TXN","DHR","NEE","ORCL","PM",
            "WMT","CSCO","GE","IBM","INTC","QCOM","HON","UPS","RTX","CAT",
        ]


# ---------------------------------------------------------------------------
# Aşama 1 — Temel Metrik Skoru (yfinance, ücretsiz)
# ---------------------------------------------------------------------------

def score_ticker_fundamentals(ticker: str) -> tuple[float, dict]:
    """yfinance ile temel skor hesapla (0-100)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info

        score = 50.0
        meta = {
            "ticker":          ticker,
            "name":            info.get("longName", ticker),
            "sector":          info.get("sector", "N/A"),
            "industry":        info.get("industry", "N/A"),
            "price":           info.get("currentPrice", 0) or info.get("regularMarketPrice", 0) or 0,
            "market_cap":      info.get("marketCap", 0) or 0,
            "pe":              info.get("trailingPE", 0) or 0,
            "forward_pe":      info.get("forwardPE", 0) or 0,
            "roe":             info.get("returnOnEquity", 0) or 0,
            "fcf":             info.get("freeCashflow", 0) or 0,
            "revenue_growth":  info.get("revenueGrowth", 0) or 0,
            "earnings_growth": info.get("earningsGrowth", 0) or 0,
            "debt_equity":     info.get("debtToEquity", 0) or 0,
            "52w_high":        info.get("fiftyTwoWeekHigh", 0) or 0,
            "analyst_target":  info.get("targetMeanPrice", 0) or 0,
            "recommendation":  info.get("recommendationKey", ""),
            "analyst_count":   info.get("numberOfAnalystOpinions", 0) or 0,
            "beta":            info.get("beta", 0) or 0,
        }

        p, mc, pe, fcf = meta["price"], meta["market_cap"], meta["pe"], meta["fcf"]
        rg, eg, roe    = meta["revenue_growth"], meta["earnings_growth"], meta["roe"]
        de, w52h, tgt  = meta["debt_equity"], meta["52w_high"], meta["analyst_target"]
        rec            = meta["recommendation"]

        if mc > 500e9:   score += 15
        elif mc > 100e9: score += 10
        elif mc > 10e9:  score += 5

        if fcf > 0:   score += 10
        elif fcf < 0: score -= 10

        if 0 < pe < 15:   score += 10
        elif 0 < pe < 25: score += 7
        elif 0 < pe < 40: score += 3
        elif pe > 80:     score -= 8

        if rg > 0.20:   score += 12
        elif rg > 0.10: score += 8
        elif rg > 0.05: score += 4
        elif rg < 0:    score -= 8

        if eg > 0.20:   score += 8
        elif eg > 0.10: score += 5
        elif eg < 0:    score -= 5

        if roe > 0.30:   score += 8
        elif roe > 0.15: score += 5
        elif roe < 0:    score -= 5

        if 0 <= de < 0.5:  score += 5
        elif de > 2.0:     score -= 5

        if p > 0 and w52h > 0:
            prox = p / w52h
            if prox > 0.95:   score += 8
            elif prox > 0.85: score += 4

        if p > 0 and tgt > 0:
            upside = (tgt - p) / p
            if upside > 0.20:    score += 8
            elif upside > 0.10:  score += 4
            elif upside < -0.10: score -= 5

        score += {"strong_buy": 10, "buy": 7, "hold": 0,
                  "underperform": -5, "sell": -8}.get(rec, 0)

        return min(100, max(0, round(score, 1))), meta

    except Exception as exc:
        logger.warning("Skor hesaplanamadı %s: %s", ticker, exc)
        return 40.0, {"ticker": ticker, "name": ticker, "sector": "N/A",
                      "industry": "N/A", "price": 0, "market_cap": 0,
                      "analyst_count": 0, "beta": 0}


def stage1_filter(
    tickers: list[str],
    top_n: int = 50,
    surprise_mode: bool = False,
    progress_callback=None,
) -> list[tuple[float, dict]]:
    """
    Aşama 1: Tüm listeyi tara, top_n seç.
    surprise_mode=True → mktCap > 50B olanları eler.
    """
    scored = []
    total  = len(tickers)

    for idx, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(ticker, idx + 1, total, stage=1)

        score, meta = score_ticker_fundamentals(ticker)

        if surprise_mode and (meta.get("market_cap", 0) or 0) > 50_000_000_000:
            continue

        scored.append((score, meta))
        time.sleep(0.1)

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]
    logger.info("Aşama 1: %d/%d seçildi (surprise=%s)", len(top), total, surprise_mode)
    return top


# ---------------------------------------------------------------------------
# Aşama 2 — Claude Analizi
# ---------------------------------------------------------------------------

STANDARD_PROMPT = """Sen deneyimli bir kantitatif analistsin.
Haftalık perspektiften değerlendir.

ÇIKTI: Sadece JSON:
{
  "nihai_guven_skoru": <0-100>,
  "analiz_ozeti": "<tek cümle, max 120 karakter>",
  "tavsiye": "<Ağırlık Artır | Tut | Azalt>"
}"""

SURPRISE_PROMPT = """Sen mid/small-cap sürpriz fırsatları arayan bir analistsin.
Büyük analistlerin gözden kaçırdığı fırsatları bul.

ÇIKTI: Sadece JSON:
{
  "nihai_guven_skoru": <0-100>,
  "surpriz_potansiyeli": <0-100>,
  "analiz_ozeti": "<tek cümle, max 120 karakter>",
  "katalizor": "<sürpriz yapabilecek tek etken, max 80 karakter>",
  "tavsiye": "<Ağırlık Artır | Tut | Azalt>"
}"""


def stage2_claude_analysis(
    stage1_results: list[tuple[float, dict]],
    progress_callback=None,
    model: str = "claude-opus-4-5",
    surprise_mode: bool = False,
) -> list[dict]:
    """Aşama 2: Top 50'yi Claude ile analiz et."""
    import json, re, anthropic

    client  = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    results = []
    system  = SURPRISE_PROMPT if surprise_mode else STANDARD_PROMPT

    for idx, (fund_score, meta) in enumerate(stage1_results):
        ticker = meta["ticker"]
        if progress_callback:
            progress_callback(ticker, idx + 1, len(stage1_results), stage=2)

        mc = meta.get("market_cap", 0) or 0
        user_msg = f"""HİSSE: {ticker} — {meta.get('name','')}
Sektör: {meta.get('sector','N/A')} / {meta.get('industry','N/A')}
Fiyat: ${meta.get('price',0):.2f} | Piyasa Değeri: ${mc/1e9:.1f}B
PE: {meta.get('pe',0):.1f} | Forward PE: {meta.get('forward_pe',0):.1f}
ROE: {meta.get('roe',0):.1%} | Beta: {meta.get('beta',0):.2f}
Gelir Büyümesi: {meta.get('revenue_growth',0):.1%}
Kazanç Büyümesi: {meta.get('earnings_growth',0):.1%}
FCF: ${meta.get('fcf',0)/1e9:.2f}B
Borç/Özsermaye: {meta.get('debt_equity',0):.2f}
Analist Sayısı: {meta.get('analyst_count',0)} | Tavsiye: {meta.get('recommendation','N/A')}
Temel Skor: {fund_score}"""

        try:
            msg = client.messages.create(
                model=model, max_tokens=300, system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = msg.content[0].text if msg.content else ""
            raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw).strip()
            data = json.loads(raw)
            data.setdefault("nihai_guven_skoru", 0)
            data.setdefault("analiz_ozeti", "")
            data.setdefault("tavsiye", "Tut")
            data.setdefault("surpriz_potansiyeli", 0)
            data.setdefault("katalizor", "")
            data["nihai_guven_skoru"] = max(0, min(100, int(data["nihai_guven_skoru"])))
            data.update({
                "ticker": ticker, "name": meta.get("name", ticker),
                "sector": meta.get("sector", "N/A"), "industry": meta.get("industry", "N/A"),
                "price": meta.get("price", 0), "market_cap": mc,
                "fund_score": fund_score, "pe": meta.get("pe", 0),
                "revenue_growth": meta.get("revenue_growth", 0),
                "fcf": meta.get("fcf", 0), "recommendation": meta.get("recommendation", ""),
                "analyst_count": meta.get("analyst_count", 0), "beta": meta.get("beta", 0),
            })
            results.append(data)
        except Exception as exc:
            logger.warning("Claude analizi başarısız %s: %s", ticker, exc)

        time.sleep(0.3)

    sort_key = "surpriz_potansiyeli" if surprise_mode else "nihai_guven_skoru"
    results.sort(key=lambda x: x.get(sort_key, 0), reverse=True)
    logger.info("Aşama 2 tamamlandı: %d hisse", len(results))
    return results


# ---------------------------------------------------------------------------
# Ana Tarama Fonksiyonları
# ---------------------------------------------------------------------------

def run_weekly_scan(top_n_stage1=50, top_n_final=25, progress_callback=None) -> list[dict]:
    """Standart S&P 500 haftalık tarama."""
    logger.info("Standart haftalık tarama başlatılıyor...")
    tickers = get_sp500_tickers()
    s1 = stage1_filter(tickers, top_n=top_n_stage1, surprise_mode=False,
                       progress_callback=progress_callback)
    return stage2_claude_analysis(s1, progress_callback=progress_callback)[:top_n_final]


def run_surprise_scan(top_n_stage1=50, top_n_final=25, progress_callback=None) -> list[dict]:
    """
    Sürpriz tarama — 670 liste + 100 Russell 2000.
    mktCap < 50B filtresi ile Google/Microsoft gibi devleri eler.
    surpriz_potansiyeli'ne göre sıralanır.
    """
    logger.info("Sürpriz tarama başlatılıyor (mktCap < 50B)...")
    tickers = get_full_universe()
    s1 = stage1_filter(tickers, top_n=top_n_stage1, surprise_mode=True,
                       progress_callback=progress_callback)
    return stage2_claude_analysis(s1, progress_callback=progress_callback,
                                   surprise_mode=True)[:top_n_final]


def run_portfolio_scan(tickers: list[str], progress_callback=None) -> list[dict]:
    """Portföy taraması — sadece verilen hisseler, mktCap filtresi yok."""
    logger.info("Portföy taraması başlatılıyor: %d hisse", len(tickers))
    s1 = stage1_filter(tickers, top_n=len(tickers), surprise_mode=False,
                       progress_callback=progress_callback)
    return stage2_claude_analysis(s1, progress_callback=progress_callback)
