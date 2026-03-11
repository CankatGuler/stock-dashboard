# portfolio_manager.py — Portfolio with GitHub-backed persistent storage
#
# Saves portfolio.json to GitHub repo via API so data survives
# Streamlit Cloud restarts. Falls back to local file if no GitHub token.

import csv
import io
import json
import os
import base64
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

PORTFOLIO_FILE = "portfolio.json"
CSV_HEADERS    = ["ticker", "shares", "avg_cost", "sector", "notes"]

# GitHub API settings (from env/secrets)
GITHUB_TOKEN = ""
GITHUB_REPO  = ""
GITHUB_PATH  = "portfolio.json"


def _get_github_config() -> tuple[str, str]:
    """Get GitHub token and repo from environment."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")   # e.g. "CankatGuler/stock-dashboard"
    return token, repo


def _github_read() -> tuple[list[dict], str]:
    """
    Read portfolio.json from GitHub repo.
    Returns (positions, sha) — sha needed for updates.
    """
    token, repo = _get_github_config()
    if not token or not repo:
        return _local_read(), ""

    url     = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return [], ""   # file doesn't exist yet
        resp.raise_for_status()
        data    = resp.json()
        sha     = data.get("sha", "")
        content = base64.b64decode(data["content"]).decode("utf-8")
        positions = json.loads(content)
        return positions if isinstance(positions, list) else [], sha
    except Exception as exc:
        logger.warning("GitHub read failed: %s — falling back to local.", exc)
        return _local_read(), ""


def _github_write(positions: list[dict], sha: str = "") -> bool:
    """
    Write portfolio.json to GitHub repo.
    sha must be provided for updates (empty string for new file).
    """
    token, repo = _get_github_config()
    if not token or not repo:
        return _local_write(positions)

    url     = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }
    content = base64.b64encode(
        json.dumps(positions, indent=2, ensure_ascii=False).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": f"Update portfolio — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": content,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        # Also save locally as cache
        _local_write(positions)
        return True
    except Exception as exc:
        logger.warning("GitHub write failed: %s — saving locally only.", exc)
        _local_write(positions)
        return False


# ---------------------------------------------------------------------------
# Local file fallback
# ---------------------------------------------------------------------------

def _local_read() -> list[dict]:
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _local_write(positions: list[dict]) -> bool:
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_portfolio() -> list[dict]:
    """Load portfolio from GitHub (with local fallback)."""
    positions, _ = _github_read()
    return positions


def save_portfolio(positions: list[dict]) -> bool:
    """Save portfolio to GitHub (with local fallback)."""
    _, sha = _github_read()
    return _github_write(positions, sha)


def add_position(ticker, shares, avg_cost, sector="Diğer", notes="") -> list[dict]:
    """Add or update a position (weighted average cost)."""
    positions, sha = _github_read()
    ticker = ticker.upper().strip()

    for pos in positions:
        if pos["ticker"] == ticker:
            old_val  = pos["shares"] * pos["avg_cost"]
            new_val  = shares * avg_cost
            total_sh = pos["shares"] + shares
            pos["avg_cost"] = (old_val + new_val) / total_sh if total_sh else avg_cost
            pos["shares"]   = total_sh
            pos["sector"]   = sector
            pos["notes"]    = notes
            pos["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
            _github_write(positions, sha)
            return positions

    positions.append({
        "ticker":   ticker,
        "shares":   shares,
        "avg_cost": avg_cost,
        "sector":   sector,
        "notes":    notes,
        "added":    datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    _github_write(positions, sha)
    return positions


def remove_position(ticker: str) -> list[dict]:
    positions, sha = _github_read()
    positions = [p for p in positions if p["ticker"] != ticker.upper()]
    _github_write(positions, sha)
    return positions


def update_position(ticker: str, shares: float, avg_cost: float) -> list[dict]:
    positions, sha = _github_read()
    ticker = ticker.upper().strip()
    for pos in positions:
        if pos["ticker"] == ticker:
            pos["shares"]   = shares
            pos["avg_cost"] = avg_cost
            pos["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    _github_write(positions, sha)
    return positions


def sell_position(ticker: str, shares_sold: float) -> tuple[list[dict], str]:
    positions, sha = _github_read()
    ticker = ticker.upper().strip()

    for i, pos in enumerate(positions):
        if pos["ticker"] == ticker:
            remaining = pos["shares"] - shares_sold
            if remaining <= 0:
                positions.pop(i)
                msg = f"{ticker} tamamen kapatıldı."
            else:
                pos["shares"]  = remaining
                pos["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                msg = f"{ticker}: {remaining:.4f} adet kaldı."
            _github_write(positions, sha)
            return positions, msg

    return positions, f"{ticker} portföyde bulunamadı."


# ---------------------------------------------------------------------------
# CSV Import / Export
# ---------------------------------------------------------------------------

def import_from_csv(csv_bytes: bytes, mode: str = "merge") -> tuple[list[dict], list[str]]:
    errors   = []
    new_rows = []

    try:
        text   = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))

        for i, row in enumerate(reader, start=2):
            row    = {k.strip().lower(): (v.strip() if v else "") for k, v in row.items() if k}
            ticker = row.get("ticker", "").upper().strip()
            if not ticker:
                errors.append(f"Satır {i}: Ticker boş — atlandı.")
                continue
            try:
                shares   = float(row.get("shares",   0))
                avg_cost = float(row.get("avg_cost", 0))
            except ValueError:
                errors.append(f"Satır {i} ({ticker}): Geçersiz sayı — atlandı.")
                continue
            if shares <= 0 or avg_cost <= 0:
                errors.append(f"Satır {i} ({ticker}): Adet/Maliyet > 0 olmalı — atlandı.")
                continue

            new_rows.append({
                "ticker":   ticker,
                "shares":   shares,
                "avg_cost": avg_cost,
                "sector":   row.get("sector", "Diğer") or "Diğer",
                "notes":    row.get("notes",  ""),
                "added":    datetime.now().strftime("%Y-%m-%d %H:%M"),
                "updated":  datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    except Exception as exc:
        errors.append(f"CSV okuma hatası: {exc}")
        return load_portfolio(), errors

    if mode == "replace":
        _, sha = _github_read()
        _github_write(new_rows, sha)
        return new_rows, errors

    positions, sha = _github_read()
    for new in new_rows:
        found = False
        for pos in positions:
            if pos["ticker"] == new["ticker"]:
                old_val  = pos["shares"] * pos["avg_cost"]
                new_val  = new["shares"] * new["avg_cost"]
                total_sh = pos["shares"] + new["shares"]
                pos["avg_cost"] = (old_val + new_val) / total_sh if total_sh else new["avg_cost"]
                pos["shares"]   = total_sh
                pos["sector"]   = new["sector"]
                pos["notes"]    = new["notes"]
                pos["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
                found = True
                break
        if not found:
            positions.append(new)

    _github_write(positions, sha)
    return positions, errors


def export_to_csv(positions: list[dict]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=CSV_HEADERS,
        extrasaction="ignore", lineterminator="\n",
    )
    writer.writeheader()
    for pos in positions:
        writer.writerow({
            "ticker":   pos.get("ticker", ""),
            "shares":   pos.get("shares", 0),
            "avg_cost": pos.get("avg_cost", 0),
            "sector":   pos.get("sector", "Diğer"),
            "notes":    pos.get("notes", ""),
        })
    return output.getvalue().encode("utf-8")


def generate_csv_template() -> bytes:
    sample = (
        "ticker,shares,avg_cost,sector,notes\n"
        "AAPL,10,175.50,Yapay Zeka,Örnek pozisyon\n"
        "NVDA,5,620.00,Semiconductor,\n"
        "LMT,3,450.00,Savunma Sanayii,\n"
    )
    return sample.encode("utf-8")


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def enrich_portfolio_with_prices(positions: list[dict], price_map: dict) -> list[dict]:
    enriched    = []
    total_value = 0.0

    for pos in positions:
        ticker   = pos["ticker"]
        shares   = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        price    = price_map.get(ticker, 0)

        current_value = shares * price
        cost_basis    = shares * avg_cost
        pnl_dollar    = current_value - cost_basis
        pnl_pct       = (pnl_dollar / cost_basis * 100) if cost_basis else 0

        enriched.append({
            **pos,
            "current_price": price,
            "current_value": current_value,
            "cost_basis":    cost_basis,
            "pnl_dollar":    pnl_dollar,
            "pnl_pct":       pnl_pct,
        })
        total_value += current_value

    for pos in enriched:
        pos["weight_pct"] = (pos["current_value"] / total_value * 100) if total_value else 0

    enriched.sort(key=lambda x: x["current_value"], reverse=True)
    return enriched


def portfolio_summary(enriched: list[dict]) -> dict:
    total_value   = sum(p["current_value"] for p in enriched)
    total_cost    = sum(p["cost_basis"]    for p in enriched)
    total_pnl     = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    winners       = [p for p in enriched if p["pnl_pct"] >= 0]
    losers        = [p for p in enriched if p["pnl_pct"] <  0]
    best          = max(enriched, key=lambda x: x["pnl_pct"], default=None)
    worst         = min(enriched, key=lambda x: x["pnl_pct"], default=None)

    return {
        "total_value":   total_value,
        "total_cost":    total_cost,
        "total_pnl":     total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "num_positions": len(enriched),
        "winners":       len(winners),
        "losers":        len(losers),
        "best":          best,
        "worst":         worst,
    }
