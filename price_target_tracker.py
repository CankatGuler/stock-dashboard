# price_target_tracker.py — Analist Fiyat Hedefi Takipçisi
#
# Günlük snapshot → GitHub'a kaydedilir
# Revizyon trendi → hedef yukarı mı aşağı mı gidiyor?
# Upside hesabı → mevcut fiyata göre potansiyel
#
# GitHub dosyası: price_targets.json
# Format:
# {
#   "NVDA": [
#     {"date": "2026-03-14", "mean": 310.0, "high": 400.0, "low": 220.0,
#      "n_analysts": 24, "rec": "buy", "price": 265.0, "upside": 17.0},
#     ...
#   ]
# }

import os
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

GITHUB_FILE = "price_targets.json"
MAX_HISTORY = 90   # Her hisse için max 90 günlük geçmiş


# ─── GitHub okuma/yazma ───────────────────────────────────────────────────────

def _load_targets_from_github() -> dict:
    """GitHub'dan price_targets.json oku."""
    try:
        import requests
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return {}
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_FILE}"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        import base64
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning("Price targets GitHub load failed: %s", e)
        return {}


def _save_targets_to_github(data: dict) -> bool:
    """price_targets.json'ı GitHub'a yaz."""
    try:
        import requests, base64
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return False
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_FILE}"

        content = json.dumps(data, ensure_ascii=False, indent=2)
        encoded = base64.b64encode(content.encode()).decode()

        # SHA al
        sha = None
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": f"price targets update {datetime.now().strftime('%Y-%m-%d')}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(url, headers=headers, json=payload, timeout=15)
        r2.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Price targets GitHub save failed: %s", e)
        return False


# ─── Anlık veri çekme ────────────────────────────────────────────────────────

def fetch_target_snapshot(ticker: str) -> dict | None:
    """
    yfinance'ten analist hedef verisini çek.
    Returns snapshot dict veya None.
    """
    try:
        info  = yf.Ticker(ticker).info
        price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        mean  = float(info.get("targetMeanPrice") or 0)
        high  = float(info.get("targetHighPrice") or 0)
        low   = float(info.get("targetLowPrice") or 0)
        n     = int(info.get("numberOfAnalystOpinions") or 0)
        rec   = (info.get("recommendationKey") or "").replace("_", " ").title()
        rec_m = float(info.get("recommendationMean") or 3.0)

        if mean == 0 or price == 0:
            return None

        upside = round((mean - price) / price * 100, 1)

        return {
            "date":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "price":     round(price, 2),
            "mean":      round(mean, 2),
            "high":      round(high, 2),
            "low":       round(low, 2),
            "n_analysts": n,
            "rec":       rec,
            "rec_mean":  round(rec_m, 2),
            "upside":    upside,
        }
    except Exception as e:
        logger.warning("Target snapshot failed %s: %s", ticker, e)
        return None


# ─── Günlük güncelleme ────────────────────────────────────────────────────────

def update_price_targets(tickers: list[str]) -> dict:
    """
    Tüm ticker listesi için snapshot çek, GitHub'a kaydet.
    Returns güncel data dict.
    """
    data    = _load_targets_from_github()
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = 0

    for ticker in tickers:
        snapshot = fetch_target_snapshot(ticker)
        if not snapshot:
            continue

        history = data.get(ticker, [])

        # Bugün zaten kayıt varsa güncelle, yoksa ekle
        if history and history[-1]["date"] == today:
            history[-1] = snapshot
        else:
            history.append(snapshot)

        # Max 90 gün tut
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]

        data[ticker] = history
        updated += 1
        time.sleep(0.3)

    if updated > 0:
        _save_targets_to_github(data)
        logger.info("Price targets updated: %d tickers", updated)

    return data


# ─── Analiz fonksiyonları ─────────────────────────────────────────────────────

def get_revision_trend(history: list[dict], lookback_days: int = 30) -> dict:
    """
    Son N günde hedef fiyat revizyonunu analiz et.
    Returns trend dict.
    """
    if len(history) < 2:
        return {"direction": "nötr", "change_pct": 0, "description": "Yetersiz veri"}

    # Son kayıt ve N gün önceki kayıt
    latest = history[-1]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    past = None
    for record in reversed(history[:-1]):
        if record["date"] <= cutoff:
            past = record
            break
    if not past:
        past = history[0]

    old_mean = past.get("mean", 0)
    new_mean = latest.get("mean", 0)

    if old_mean == 0:
        return {"direction": "nötr", "change_pct": 0, "description": "Veri yok"}

    change_pct = round((new_mean - old_mean) / old_mean * 100, 1)

    if change_pct >= 10:
        direction = "güçlü_yukarı"
        desc = f"Hedef +%{change_pct:.1f} yukarı revize edildi — analistler çok iyimser"
    elif change_pct >= 3:
        direction = "yukarı"
        desc = f"Hedef +%{change_pct:.1f} yukarı revize edildi"
    elif change_pct <= -10:
        direction = "güçlü_aşağı"
        desc = f"Hedef -%{abs(change_pct):.1f} aşağı çekildi — dikkat!"
    elif change_pct <= -3:
        direction = "aşağı"
        desc = f"Hedef -%{abs(change_pct):.1f} aşağı revize edildi"
    else:
        direction = "nötr"
        desc = "Hedef fiyat stabil"

    return {
        "direction":   direction,
        "change_pct":  change_pct,
        "old_mean":    old_mean,
        "new_mean":    new_mean,
        "description": desc,
        "days":        lookback_days,
    }


def get_consensus_strength(snapshot: dict) -> str:
    """
    Analist konsensüs gücünü metin olarak döndür.
    """
    n   = snapshot.get("n_analysts", 0)
    rec = snapshot.get("rec", "").lower()
    rm  = snapshot.get("rec_mean", 3.0)

    if n == 0:
        return "Analist yok"

    if rm <= 1.5 and n >= 15:
        return f"💪 Çok Güçlü Alım ({n} analist)"
    elif rm <= 2.0 and n >= 8:
        return f"✅ Güçlü Alım ({n} analist)"
    elif rm <= 2.5:
        return f"👍 Alım ({n} analist)"
    elif rm <= 3.0:
        return f"➡️ Tut ({n} analist)"
    elif rm <= 3.5:
        return f"⚠️ Zayıf Tut ({n} analist)"
    else:
        return f"🔴 Satış ({n} analist)"


def get_upside_category(upside: float) -> tuple[str, str]:
    """(kategori, renk) döndür."""
    if upside >= 30:
        return "Yüksek Potansiyel", "#00c48c"
    elif upside >= 15:
        return "İyi Potansiyel", "#4fc3f7"
    elif upside >= 5:
        return "Sınırlı Potansiyel", "#ffb300"
    elif upside >= -5:
        return "Hedefe Yakın", "#8a9ab0"
    else:
        return "Hedefin Üzerinde", "#e74c3c"


def get_all_targets_summary(tickers: list[str]) -> list[dict]:
    """
    Tüm ticker listesi için mevcut hedef özeti + revizyon trendi.
    GitHub'dan okur, yoksa canlı çeker.
    """
    data    = _load_targets_from_github()
    results = []

    for ticker in tickers:
        history = data.get(ticker, [])

        # GitHub'da yok veya eskiyse canlı çek
        if not history:
            snap = fetch_target_snapshot(ticker)
            if snap:
                history = [snap]
            else:
                continue

        latest  = history[-1]
        trend   = get_revision_trend(history, lookback_days=30)
        strength = get_consensus_strength(latest)
        upside  = latest.get("upside", 0)
        up_cat, up_color = get_upside_category(upside)

        # Trend oku
        dir_map = {
            "güçlü_yukarı": ("⬆⬆", "#00c48c"),
            "yukarı":       ("⬆",  "#4fc3f7"),
            "nötr":         ("➡",  "#8a9ab0"),
            "aşağı":        ("⬇",  "#ffb300"),
            "güçlü_aşağı":  ("⬇⬇", "#e74c3c"),
        }
        trend_arrow, trend_color = dir_map.get(trend["direction"], ("➡", "#8a9ab0"))

        results.append({
            "ticker":       ticker,
            "price":        latest.get("price", 0),
            "mean":         latest.get("mean", 0),
            "high":         latest.get("high", 0),
            "low":          latest.get("low", 0),
            "upside":       upside,
            "upside_cat":   up_cat,
            "upside_color": up_color,
            "n_analysts":   latest.get("n_analysts", 0),
            "rec":          latest.get("rec", "—"),
            "consensus":    strength,
            "trend":        trend,
            "trend_arrow":  trend_arrow,
            "trend_color":  trend_color,
            "history":      history,
            "date":         latest.get("date", ""),
        })

    # Upside'a göre sırala
    results.sort(key=lambda x: x["upside"], reverse=True)
    return results
