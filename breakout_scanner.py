# breakout_scanner.py — 52 Haftalık Yüksek Kırılma Alarmı
#
# Her sabah radarı çalışırken portföy + watchlist hisselerini kontrol eder.
# Güncel fiyat, 52H yükseğine eşit veya üzerindeyse → Telegram bildirimi.
#
# Eşik: fiyat >= 52H * 0.995  (yani %0.5 yakınında da alarm verir)

import os
import json
import base64
import logging
import time
from datetime import datetime, timezone, timedelta

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

BREAKOUT_THRESHOLD = 0.995   # 52H'nin %99.5'i — "kırmak üzere" de alarm verir
WATCHLIST_FILE     = "watchlist.json"


# ─── GitHub helpers ───────────────────────────────────────────────────────────

def _github_config():
    return os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPO", "")


def _gh_read(path):
    token, repo = _github_config()
    if not token or not repo:
        return None, ""
    url  = f"https://api.github.com/repos/{repo}/contents/{path}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        if r.status_code == 404:
            return None, ""
        r.raise_for_status()
        data = r.json()
        return json.loads(base64.b64decode(data["content"]).decode()), data.get("sha", "")
    except Exception as e:
        logger.warning("GitHub read %s failed: %s", path, e)
        return None, ""


def _gh_write(path, obj, sha="", message="update"):
    token, repo = _github_config()
    if not token or not repo:
        return False
    url  = f"https://api.github.com/repos/{repo}/contents/{path}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": message,
        "content": base64.b64encode(
            json.dumps(obj, indent=2, ensure_ascii=False).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=hdrs, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("GitHub write %s failed: %s", path, e)
        return False


# ─── Watchlist API ────────────────────────────────────────────────────────────

def load_watchlist() -> list[str]:
    """Takip listesini yükle. [\"AAPL\", \"NVDA\", ...] formatında."""
    data, _ = _gh_read(WATCHLIST_FILE)
    if isinstance(data, list):
        return [t.upper().strip() for t in data if t]
    # Local fallback
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_watchlist(tickers: list[str]) -> bool:
    """Takip listesini kaydet."""
    tickers = sorted(set(t.upper().strip() for t in tickers if t))
    _, sha = _gh_read(WATCHLIST_FILE)
    ok = _gh_write(WATCHLIST_FILE, tickers, sha, f"Watchlist update ({len(tickers)} tickers)")
    if not ok:
        try:
            with open(WATCHLIST_FILE, "w") as f:
                json.dump(tickers, f, indent=2)
            return True
        except Exception:
            return False
    return ok


def add_to_watchlist(ticker: str) -> bool:
    tickers = load_watchlist()
    ticker  = ticker.upper().strip()
    if ticker not in tickers:
        tickers.append(ticker)
        return save_watchlist(tickers)
    return True


def remove_from_watchlist(ticker: str) -> bool:
    tickers = load_watchlist()
    ticker  = ticker.upper().strip()
    if ticker in tickers:
        tickers.remove(ticker)
        return save_watchlist(tickers)
    return True


# ─── Breakout Detection ───────────────────────────────────────────────────────

def check_breakout(ticker: str) -> dict | None:
    """
    Tek bir hisse için 52H kırılma kontrolü.
    Kırılma varsa dict döner, yoksa None.
    """
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info
        price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        w52h  = float(info.get("fiftyTwoWeekHigh") or 0)
        w52l  = float(info.get("fiftyTwoWeekLow") or 0)

        if price <= 0 or w52h <= 0:
            return None

        # 52H pozisyonu (%)
        range_pct = ((price - w52l) / (w52h - w52l) * 100) if (w52h - w52l) > 0 else 0
        upside_to_high = ((w52h - price) / w52h * 100)

        is_breakout = price >= w52h * BREAKOUT_THRESHOLD

        if not is_breakout:
            return None

        change_pct = float(info.get("regularMarketChangePercent") or 0)
        name       = info.get("shortName") or info.get("longName") or ticker
        volume     = int(info.get("regularMarketVolume") or 0)
        avg_vol    = int(info.get("averageVolume") or 1)
        vol_ratio  = volume / avg_vol if avg_vol > 0 else 1

        return {
            "ticker":      ticker,
            "name":        name,
            "price":       price,
            "w52h":        w52h,
            "w52l":        w52l,
            "range_pct":   round(range_pct, 1),
            "upside":      round(upside_to_high, 2),
            "change_pct":  round(change_pct, 2),
            "vol_ratio":   round(vol_ratio, 2),
            "confirmed":   price >= w52h,   # True = gerçek kırılım, False = yakın
        }
    except Exception as e:
        logger.warning("Breakout check failed for %s: %s", ticker, e)
        return None


def run_breakout_scan(extra_tickers: list[str] | None = None) -> list[dict]:
    """
    Portföy + watchlist + extra_tickers hisselerini tara.
    Kırılım yapan hisseleri döndür.
    """
    # Portföy tickerları
    portfolio_tickers = []
    try:
        port_data, _ = _gh_read("portfolio.json")
        if isinstance(port_data, list):
            portfolio_tickers = [p["ticker"] for p in port_data if "ticker" in p]
    except Exception as e:
        logger.warning("Portfolio read failed: %s", e)

    # Watchlist
    watchlist_tickers = load_watchlist()

    # Hepsini birleştir
    all_tickers = list(dict.fromkeys(
        portfolio_tickers + watchlist_tickers + (extra_tickers or [])
    ))

    logger.info("52H taraması başlıyor: %d hisse", len(all_tickers))

    breakouts = []
    for i, ticker in enumerate(all_tickers):
        result = check_breakout(ticker)
        if result:
            source = []
            if ticker in portfolio_tickers: source.append("portföy")
            if ticker in watchlist_tickers: source.append("watchlist")
            result["source"] = " + ".join(source) if source else "ekstra"
            breakouts.append(result)
            logger.info("🚨 KIRILIM: %s @ $%.2f (52H: $%.2f)", ticker, result["price"], result["w52h"])
        time.sleep(0.3)

    breakouts.sort(key=lambda x: (x["confirmed"], x["range_pct"]), reverse=True)
    logger.info("Tarama tamamlandı: %d kırılım bulundu", len(breakouts))
    return breakouts


# ─── Telegram Formatı ─────────────────────────────────────────────────────────

def format_breakout_message(breakouts: list[dict]) -> str:
    if not breakouts:
        return ""

    now_tr = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
    lines  = [f"🚨 *52 HAFTALIK YÜKSEKLİK ALARMI* — {now_tr} TR\n"]

    for b in breakouts:
        emoji   = "🔥" if b["confirmed"] else "⚡"
        status  = "YENİ ZİRVE" if b["confirmed"] else "ZİRVEYE YAKLAŞIYOR"
        vol_str = f"Hacim {b['vol_ratio']:.1f}x ort." if b["vol_ratio"] >= 1.5 else ""

        lines.append(
            f"{emoji} *{b['ticker']}* — {status}\n"
            f"   Fiyat: ${b['price']:.2f}  ({b['change_pct']:+.1f}%)\n"
            f"   52H Yüksek: ${b['w52h']:.2f}"
            + (f"  (Kalan: %{b['upside']:.1f})" if not b["confirmed"] else " ✅ KIRILDI")
            + f"\n   52H Pozisyon: %{b['range_pct']:.0f}\n"
            + (f"   📊 {vol_str}\n" if vol_str else "")
            + f"   📌 Kaynak: {b['source']}\n"
        )

    if len(breakouts) > 1:
        confirmed = sum(1 for b in breakouts if b["confirmed"])
        lines.append(f"\n_Toplam: {len(breakouts)} alarm ({confirmed} gerçek kırılım)_")

    return "\n".join(lines)
