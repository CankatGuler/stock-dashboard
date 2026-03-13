# analysis_memory.py — Analiz geçmişi GitHub'a kaydedilir
#
# Her analiz sonucu şu yapıda saklanır:
# {
#   "ticker": "NVDA",
#   "date": "2026-03-13",
#   "timestamp": "2026-03-13T18:30:00",
#   "score": 82,
#   "kategori": "Rocket 🚀",
#   "tavsiye": "AL",
#   "ozet": "...",
#   "price": 875.50,
#   "mktCap": 2150000000000
# }
#
# GitHub'da analysis_history.json olarak saklanır (max 500 kayıt, FIFO)

import json
import base64
import os
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

HISTORY_FILE = "analysis_history.json"
MAX_RECORDS  = 500   # toplam max kayıt


def _get_github_config():
    token = os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    return token, repo


def _github_read_history():
    """GitHub'dan analiz geçmişini oku. (records, sha)"""
    token, repo = _get_github_config()
    if not token or not repo:
        return _local_read(), ""

    url     = f"https://api.github.com/repos/{repo}/contents/{HISTORY_FILE}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return [], ""
        resp.raise_for_status()
        data    = resp.json()
        sha     = data.get("sha", "")
        content = base64.b64decode(data["content"]).decode("utf-8")
        records = json.loads(content)
        return records if isinstance(records, list) else [], sha
    except Exception as exc:
        logger.warning("GitHub history read failed: %s", exc)
        return _local_read(), ""


def _github_write_history(records, sha=""):
    """GitHub'a analiz geçmişini yaz."""
    token, repo = _get_github_config()
    if not token or not repo:
        return _local_write(records)

    url     = f"https://api.github.com/repos/{repo}/contents/{HISTORY_FILE}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    content = base64.b64encode(
        json.dumps(records, indent=2, ensure_ascii=False).encode("utf-8")
    ).decode("utf-8")
    payload = {
        "message": f"Update analysis history ({len(records)} records)",
        "content": content,
    }
    if sha:
        payload["sha"] = sha
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("GitHub history write failed: %s", exc)
        return _local_write(records)


def _local_read():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _local_write(records):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ─── Public API ───────────────────────────────────────────────────────────────

def save_analysis_batch(results: list[dict]) -> bool:
    """
    Analiz sonuçlarını geçmişe ekle.
    results: claude_analyzer'dan gelen analiz listesi (_stock_meta içerir)
    """
    records, sha = _github_read_history()

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    ts_str   = now.strftime("%Y-%m-%dT%H:%M:%S")

    for r in results:
        meta = r.get("_stock_meta", {})
        record = {
            "ticker":    r.get("hisse_sembolu", meta.get("ticker", "")),
            "date":      date_str,
            "timestamp": ts_str,
            "score":     r.get("nihai_guven_skoru", 0),
            "kategori":  r.get("kategori", ""),
            "tavsiye":   r.get("tavsiye", ""),
            "ozet":      (r.get("analiz_ozeti", "") or "")[:300],
            "price":     meta.get("price", 0),
            "mktCap":    meta.get("mktCap", 0),
            "revenueGrowth": meta.get("revenueGrowth", 0),
            "peRatio":   meta.get("peRatio", 0),
        }
        records.append(record)

    # Max kayıt sınırı — en eskilerini at
    if len(records) > MAX_RECORDS:
        records = records[-MAX_RECORDS:]

    return _github_write_history(records, sha)


def get_ticker_history(ticker: str, limit: int = 10) -> list[dict]:
    """
    Belirli bir hisse için geçmiş analizleri getir (en yeni önce).
    """
    records, _ = _github_read_history()
    ticker_records = [r for r in records if r.get("ticker", "").upper() == ticker.upper()]
    return list(reversed(ticker_records))[-limit:]


def get_ticker_context_for_claude(ticker: str) -> str:
    """
    Claude'a verilecek geçmiş analiz özeti metni.
    Yoksa boş string döner.
    """
    history = get_ticker_history(ticker, limit=5)
    if not history:
        return ""

    lines = [f"=== {ticker} GEÇMİŞ ANALİZ KAYITLARI (en yeni önce) ==="]
    for h in reversed(history):
        score   = h.get("score", "?")
        date    = h.get("date", "?")
        tavsiye = h.get("tavsiye", "?")
        ozet    = h.get("ozet", "")[:200]
        price   = h.get("price", 0)
        lines.append(
            f"[{date}] Skor: {score}/100 | Tavsiye: {tavsiye} | Fiyat: ${price:.2f}\n"
            f"  Özet: {ozet}"
        )

    # Trend hesapla
    if len(history) >= 2:
        newest = history[0].get("score", 0)
        oldest = history[-1].get("score", 0)
        diff   = newest - oldest
        trend  = f"↑ +{diff}" if diff > 0 else (f"↓ {diff}" if diff < 0 else "→ değişmedi")
        lines.append(f"\nSkor Trendi ({len(history)} analiz): {oldest} → {newest}  {trend}")

    lines.append("=" * 50)
    return "\n".join(lines)


def get_all_history(limit: int = 200) -> list[dict]:
    """Tüm geçmişi döndür (son N kayıt)."""
    records, _ = _github_read_history()
    return list(reversed(records))[:limit]


def get_history_summary() -> dict:
    """Dashboard için özet istatistikler."""
    records, _ = _github_read_history()
    if not records:
        return {"total": 0, "unique_tickers": 0, "last_date": "—"}

    tickers = set(r.get("ticker", "") for r in records)
    last_date = max(r.get("date", "") for r in records)
    return {
        "total":          len(records),
        "unique_tickers": len(tickers),
        "last_date":      last_date,
    }
