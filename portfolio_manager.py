# portfolio_manager.py — Portfolio persistence and P&L analytics
#
# Stores portfolio data in a local JSON file (portfolio.json).
# Each position: { ticker, shares, avg_cost, sector, notes }
#
# CSV FORMAT (for bulk import):
#   ticker, shares, avg_cost, sector, notes
#   AAPL,   10,     175.50,   Yapay Zeka,  Ana pozisyon

import csv
import io
import json
import os
from datetime import datetime

PORTFOLIO_FILE = "portfolio.json"
CSV_HEADERS    = ["ticker", "shares", "avg_cost", "sector", "notes"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_portfolio() -> list[dict]:
    """Load portfolio positions from JSON file. Returns empty list if not found."""
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_portfolio(positions: list[dict]) -> bool:
    """Save portfolio positions to JSON file. Returns True on success."""
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(positions, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


def add_position(ticker, shares, avg_cost, sector="Diğer", notes="") -> list[dict]:
    """Add or update a position in the portfolio (weighted average cost)."""
    positions = load_portfolio()
    ticker    = ticker.upper().strip()

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
            save_portfolio(positions)
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
    save_portfolio(positions)
    return positions


def remove_position(ticker: str) -> list[dict]:
    """Remove a position from the portfolio."""
    positions = [p for p in load_portfolio() if p["ticker"] != ticker.upper()]
    save_portfolio(positions)
    return positions


def update_position(ticker: str, shares: float, avg_cost: float) -> list[dict]:
    """Overwrite shares and avg_cost for an existing position."""
    positions = load_portfolio()
    ticker    = ticker.upper().strip()
    for pos in positions:
        if pos["ticker"] == ticker:
            pos["shares"]   = shares
            pos["avg_cost"] = avg_cost
            pos["updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_portfolio(positions)
    return positions


def sell_position(ticker: str, shares_sold: float) -> tuple[list[dict], str]:
    """
    Reduce or close a position after a sale.
    Returns (updated_positions, message).
    """
    positions = load_portfolio()
    ticker    = ticker.upper().strip()
    msg       = ""

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
            save_portfolio(positions)
            return positions, msg

    return positions, f"{ticker} portföyde bulunamadı."


# ---------------------------------------------------------------------------
# CSV Import / Export
# ---------------------------------------------------------------------------

def import_from_csv(csv_bytes: bytes, mode: str = "merge") -> tuple[list[dict], list[str]]:
    """
    Import positions from CSV file bytes.

    mode = "merge"   → Mevcut portföyle birleştir
    mode = "replace" → Portföyü tamamen sıfırla, CSV'yi yükle

    Returns (positions, error_messages)
    """
    errors   = []
    new_rows = []

    try:
        text   = csv_bytes.decode("utf-8-sig")  # BOM-safe (Excel CSV)
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
        save_portfolio(new_rows)
        return new_rows, errors

    # Merge: weighted average for existing tickers
    positions = load_portfolio()
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

    save_portfolio(positions)
    return positions, errors


def export_to_csv(positions: list[dict]) -> bytes:
    """Export current portfolio to CSV bytes for download."""
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_HEADERS,
        extrasaction="ignore",
        lineterminator="\n",
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
    """Return a filled CSV template with example rows."""
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

def enrich_portfolio_with_prices(positions: list[dict], price_map: dict[str, float]) -> list[dict]:
    """Attach live price and P&L fields to each position."""
    enriched    = []
    total_value = 0.0

    for pos in positions:
        ticker    = pos["ticker"]
        shares    = pos.get("shares", 0)
        avg_cost  = pos.get("avg_cost", 0)
        price     = price_map.get(ticker, 0)

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
    """Compute aggregate portfolio metrics."""
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
