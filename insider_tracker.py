# insider_tracker.py — SEC EDGAR Form 4 İçeriden Alım/Satım Takibi
#
# SEC EDGAR tamamen ücretsiz, resmi API — API key gerektirmez.
# Form 4: Yöneticilerin ve büyük hissedarların işlemlerini raporladığı form.
#
# Kullanılan endpoint:
#   https://efts.sec.gov/LATEST/search-index → Form 4 araması
#   https://data.sec.gov/submissions/CIK{cik}.json → şirket CIK
#   https://www.sec.gov/cgi-bin/browse-edgar → işlem detayları

import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger(__name__)

SEC_HEADERS = {
    "User-Agent": "StockDashboard contact@example.com",  # SEC zorunlu kılıyor
    "Accept-Encoding": "gzip, deflate",
}

# ─── Yönetici unvanı öncelik sıralaması ──────────────────────────────────────

TITLE_PRIORITY = {
    "chief executive officer": 10,
    "ceo":                     10,
    "chief financial officer": 9,
    "cfo":                     9,
    "president":               8,
    "chief operating officer": 7,
    "coo":                     7,
    "director":                5,
    "chief technology officer": 7,
    "cto":                     7,
    "10%":                     6,   # büyük hissedar
    "vp":                      4,
    "vice president":          4,
    "general counsel":         4,
}


def _title_score(title: str) -> int:
    t = title.lower()
    for key, score in TITLE_PRIORITY.items():
        if key in t:
            return score
    return 3


def get_cik(ticker: str) -> str | None:
    """Ticker sembolünden CIK numarasını bul."""
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        ticker_upper = ticker.upper()
        for item in data.values():
            if item.get("ticker", "").upper() == ticker_upper:
                cik = str(item["cik_str"]).zfill(10)
                return cik
    except Exception as e:
        logger.warning("CIK lookup failed for %s: %s", ticker, e)
    return None


def fetch_form4_filings(ticker: str, days: int = 30) -> list[dict]:
    """
    Belirli bir hisse için son N günün Form 4 kayıtlarını çek.
    Returns: list of filing dicts
    """
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date   = datetime.now().strftime("%Y-%m-%d")

    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q=%22{ticker}%22"
        f"&dateRange=custom&startdt={start_date}&enddt={end_date}"
        f"&forms=4"
    )

    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        return hits
    except Exception as e:
        logger.warning("Form 4 fetch failed for %s: %s", ticker, e)
        return []


def parse_form4_transactions(ticker: str, days: int = 30) -> list[dict]:
    """
    SEC EDGAR submissions API üzerinden Form 4 işlemlerini parse et.
    Daha güvenilir ve yapılandırılmış veri kaynağı.
    """
    cik = get_cik(ticker)
    if not cik:
        logger.warning("CIK bulunamadı: %s", ticker)
        return []

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Submissions fetch failed for %s: %s", ticker, e)
        return []

    # Son Form 4 başvurularını bul
    filings = data.get("filings", {}).get("recent", {})
    forms   = filings.get("form", [])
    dates   = filings.get("filingDate", [])
    acc_nos = filings.get("accessionNumber", [])
    reporters = filings.get("reportingOwner", []) if "reportingOwner" in filings else []

    cutoff = datetime.now() - timedelta(days=days)
    results = []

    for i, form in enumerate(forms):
        if form not in ("4", "4/A"):
            continue
        if i >= len(dates):
            continue

        try:
            filing_date = datetime.strptime(dates[i], "%Y-%m-%d")
        except Exception:
            continue

        if filing_date < cutoff:
            continue

        acc_no = acc_nos[i] if i < len(acc_nos) else ""
        acc_clean = acc_no.replace("-", "")

        # Form 4 XML'ini çek
        xml_url = (
            f"https://www.sec.gov/Archives/edgar/full-index/"
            f"{filing_date.year}/{_quarter(filing_date.month)}/"
        )

        # Detaylı parse için XBRL endpoint
        detail_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10"

        results.append({
            "ticker":       ticker,
            "cik":          cik,
            "filing_date":  dates[i],
            "form":         form,
            "acc_no":       acc_no,
            "detail_url":   f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=20",
        })

    return results


def _quarter(month: int) -> str:
    q = (month - 1) // 3 + 1
    return f"QTR{q}"


def fetch_insider_transactions(ticker: str, days: int = 30) -> list[dict]:
    """
    openinsider.com veya SEC EDGAR üzerinden içeriden işlemleri çek.
    openinsider.com en temiz ve parse edilmesi kolay kaynaktır.
    """
    transactions = []

    # openinsider.com — ücretsiz, CSV formatında
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = (
        f"http://openinsider.com/screener?s={ticker}"
        f"&fd={days}&fdr=&td=&tdr=&fdlyl=&daysback={days}"
        f"&xp=1&xs=1&vl=&ocal=&ph=&pl=&sortcol=0&cnt=40&action=1"
    )

    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # HTML tablosunu basit parse et
        if "<table" in html and "Purchase" in html or "Sale" in html:
            import re
            # Tablo satırlarını çek
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            for row in rows[2:]:  # İlk 2 satır başlık
                cols = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                cols = [re.sub(r'<[^>]+>', '', c).strip() for c in cols]

                if len(cols) < 10:
                    continue

                try:
                    # openinsider kolon sırası: Filing Date, Trade Date, Ticker, Company,
                    # Insider Name, Title, Trade Type, Price, Qty, Owned, ΔOwn, Value
                    tx = {
                        "ticker":       ticker,
                        "filing_date":  cols[1] if len(cols) > 1 else "",
                        "trade_date":   cols[2] if len(cols) > 2 else "",
                        "insider_name": cols[5] if len(cols) > 5 else "",
                        "title":        cols[6] if len(cols) > 6 else "",
                        "trade_type":   cols[7] if len(cols) > 7 else "",
                        "price":        _parse_num(cols[8]) if len(cols) > 8 else 0,
                        "qty":          _parse_num(cols[9]) if len(cols) > 9 else 0,
                        "value":        _parse_num(cols[11]) if len(cols) > 11 else 0,
                        "source":       "openinsider",
                    }
                    if tx["trade_type"] in ("P - Purchase", "S - Sale", "P", "S"):
                        transactions.append(tx)
                except Exception:
                    continue

    except Exception as e:
        logger.warning("openinsider fetch failed for %s: %s", ticker, e)

    # Fallback: SEC EDGAR doğrudan
    if not transactions:
        transactions = _fetch_sec_direct(ticker, days)

    return transactions


def _fetch_sec_direct(ticker: str, days: int) -> list[dict]:
    """SEC EDGAR EFTS search fallback."""
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = (
        f"https://efts.sec.gov/LATEST/search-index"
        f"?q=%22{ticker}%22&forms=4"
        f"&dateRange=custom&startdt={start_date}"
    )
    transactions = []
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits[:10]:
            src = hit.get("_source", {})
            transactions.append({
                "ticker":       ticker,
                "filing_date":  src.get("file_date", ""),
                "trade_date":   src.get("period_of_report", ""),
                "insider_name": src.get("display_names", [""])[0] if src.get("display_names") else "",
                "title":        "",
                "trade_type":   "Form 4",
                "price":        0,
                "qty":          0,
                "value":        0,
                "source":       "sec_edgar",
                "detail_url":   f"https://www.sec.gov{src.get('file_path', '')}",
            })
    except Exception as e:
        logger.warning("SEC direct fetch failed for %s: %s", ticker, e)
    return transactions


def _parse_num(s: str) -> float:
    """'$1,234,567' veya '(1,234)' gibi sayıları float'a çevir."""
    try:
        s = s.replace("$", "").replace(",", "").replace("(", "-").replace(")", "").strip()
        return float(s)
    except Exception:
        return 0.0


# ─── Sinyal Skorlama ─────────────────────────────────────────────────────────

def score_transactions(transactions: list[dict]) -> dict:
    """
    İşlem listesini analiz et ve sinyal skoru üret.

    Returns:
        {
          "signal":       "BULLISH" | "BEARISH" | "MIXED" | "NEUTRAL",
          "score":        -10 ile +10 arası,
          "buy_count":    int,
          "sell_count":   int,
          "buy_value":    float,
          "sell_value":   float,
          "cluster":      bool,    # 3+ kişi aynı yönde
          "ceo_involved": bool,
          "summary":      str,
          "transactions": list,
        }
    """
    if not transactions:
        return {
            "signal": "NEUTRAL", "score": 0, "summary": "Form 4 kaydı bulunamadı.",
            "buy_count": 0, "sell_count": 0, "buy_value": 0, "sell_value": 0,
            "cluster": False, "ceo_involved": False, "transactions": [],
        }

    buys  = [t for t in transactions if "P" in t.get("trade_type", "").upper() or "purchase" in t.get("trade_type", "").lower()]
    sells = [t for t in transactions if "S" in t.get("trade_type", "").upper() or "sale" in t.get("trade_type", "").lower()]

    buy_value  = sum(abs(t.get("value", 0) or t.get("price", 0) * t.get("qty", 0)) for t in buys)
    sell_value = sum(abs(t.get("value", 0) or t.get("price", 0) * t.get("qty", 0)) for t in sells)

    # Üst yönetici kontrolü
    ceo_involved = any(
        _title_score(t.get("title", "")) >= 8
        for t in transactions
    )

    # Cluster: 3+ kişi aynı yönde
    cluster_buy  = len(set(t.get("insider_name", "") for t in buys)) >= 3
    cluster_sell = len(set(t.get("insider_name", "") for t in sells)) >= 3

    # Skor hesapla (-10 ile +10)
    score = 0
    score += min(len(buys), 5) * 1.5        # Her alım +1.5 (max 5 alım)
    score -= min(len(sells), 5) * 1.0        # Her satış -1.0
    score += 2 if ceo_involved and buys else 0
    score -= 1 if ceo_involved and sells else 0
    score += 2 if cluster_buy else 0
    score -= 2 if cluster_sell else 0
    score += min(buy_value / 1_000_000, 3)   # Her $1M alım +1 (max +3)
    score -= min(sell_value / 5_000_000, 2)  # Her $5M satış -1 (max -2)
    score = max(-10, min(10, round(score, 1)))

    # Sinyal belirle
    if score >= 3:
        signal = "BULLISH"
    elif score <= -3:
        signal = "BEARISH"
    elif score > 0:
        signal = "HAFIF OLUMLU"
    elif score < 0:
        signal = "HAFIF OLUMSUZ"
    else:
        signal = "NÖTR"

    # Özet metin
    parts = []
    if buys:
        parts.append(f"{len(buys)} alım (${buy_value/1000:.0f}K)")
    if sells:
        parts.append(f"{len(sells)} satış (${sell_value/1000:.0f}K)")
    if ceo_involved:
        parts.append("CEO/CFO dahil")
    if cluster_buy:
        parts.append("küme alımı ⚡")
    if cluster_sell:
        parts.append("küme satışı ⚠️")

    summary = " · ".join(parts) if parts else "İşlem yok"

    return {
        "signal":       signal,
        "score":        score,
        "buy_count":    len(buys),
        "sell_count":   len(sells),
        "buy_value":    buy_value,
        "sell_value":   sell_value,
        "cluster":      cluster_buy or cluster_sell,
        "cluster_buy":  cluster_buy,
        "cluster_sell": cluster_sell,
        "ceo_involved": ceo_involved,
        "summary":      summary,
        "transactions": transactions,
    }


# ─── Toplu Tarama ────────────────────────────────────────────────────────────

def run_insider_scan(tickers: list[str], days: int = 14) -> list[dict]:
    """
    Ticker listesi için içeriden işlem taraması yap.
    Sadece anlamlı sinyal olanları döndür.
    """
    results = []
    for ticker in tickers:
        try:
            txs    = fetch_insider_transactions(ticker, days=days)
            scored = score_transactions(txs)
            scored["ticker"] = ticker

            # Sadece gerçek sinyal olanları dahil et
            if scored["buy_count"] > 0 or scored["sell_count"] > 0:
                results.append(scored)

            time.sleep(0.5)   # SEC rate limit saygısı
        except Exception as e:
            logger.warning("Insider scan failed for %s: %s", ticker, e)

    # Skora göre sırala (en güçlü sinyal önce)
    results.sort(key=lambda x: abs(x["score"]), reverse=True)
    return results


# ─── Telegram Formatı ────────────────────────────────────────────────────────

def format_insider_telegram(results: list[dict], title: str = "") -> str:
    """İçeriden işlem sonuçlarını Telegram mesajına çevir."""
    from datetime import timezone
    now_tr = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    lines = [f"🔎 *İÇERİDEN ALIM/SATIM ALARMI* — {title or now_tr}\n"]

    bullish = [r for r in results if r["score"] >= 2]
    bearish = [r for r in results if r["score"] <= -2]

    if bullish:
        lines.append("*📈 ALIM SİNYALLERİ:*")
        for r in bullish:
            emoji = "🔥" if r["score"] >= 5 else "⚡"
            ceo_str = " 👔 CEO/CFO" if r["ceo_involved"] else ""
            cluster_str = " 🔗 Küme alımı" if r["cluster_buy"] else ""
            lines.append(
                f"{emoji} *{r['ticker']}* — Skor: +{r['score']}\n"
                f"   {r['buy_count']} alım · ${r['buy_value']/1000:.0f}K{ceo_str}{cluster_str}\n"
                f"   {r['summary']}"
            )
        lines.append("")

    if bearish:
        lines.append("*📉 SATIŞ SİNYALLERİ:*")
        for r in bearish:
            emoji = "🚨" if r["score"] <= -5 else "⚠️"
            ceo_str = " 👔 CEO/CFO" if r["ceo_involved"] else ""
            cluster_str = " 🔗 Küme satışı" if r["cluster_sell"] else ""
            lines.append(
                f"{emoji} *{r['ticker']}* — Skor: {r['score']}\n"
                f"   {r['sell_count']} satış · ${r['sell_value']/1000:.0f}K{ceo_str}{cluster_str}\n"
                f"   {r['summary']}"
            )
        lines.append("")

    if not bullish and not bearish:
        lines.append("_Bu dönemde anlamlı içeriden işlem sinyali bulunamadı._")

    lines.append(f"\n_Son {14} gün · SEC Form 4 verisi_")
    return "\n".join(lines)
