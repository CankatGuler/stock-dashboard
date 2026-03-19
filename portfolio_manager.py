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
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
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
        raw = json.loads(content)
        # Yeni format: {"positions": [...], "cash": 0.0}
        if isinstance(raw, dict) and "positions" in raw:
            positions = raw.get("positions", [])
        elif isinstance(raw, list):
            positions = raw
        else:
            positions = []
        return positions, sha
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
    # Nakit miktarını koru — mevcut dosyadan oku
    existing_cash = 0.0
    try:
        _raw_resp = requests.get(
            f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}",
            headers=headers, timeout=10
        )
        if _raw_resp.status_code == 200:
            _raw = json.loads(base64.b64decode(_raw_resp.json()["content"]).decode())
            if isinstance(_raw, dict):
                existing_cash = float(_raw.get("cash", 0.0))
    except Exception:
        pass

    full_data = {"positions": positions, "cash": existing_cash}
    content = base64.b64encode(
        json.dumps(full_data, indent=2, ensure_ascii=False).encode("utf-8")
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
            if isinstance(data, dict) and "positions" in data:
                return data.get("positions", [])
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
    """Load portfolio from GitHub (with local fallback).
    Shares <= 0 olan pozisyonlar otomatik olarak filtrelenir —
    satılmış hisseler hiçbir zaman döndürülmez.
    """
    positions, _ = _github_read()
    return [p for p in positions if float(p.get("shares", 0)) > 0]


def save_portfolio(positions: list[dict]) -> bool:
    """Save portfolio to GitHub (with local fallback)."""
    _, sha = _github_read()
    return _github_write(positions, sha)


def add_position(ticker, shares, avg_cost, sector="Diğer", notes="",
                 deduct_from_cash=True, asset_class="us_equity",
                 currency="USD") -> list[dict]:
    """
    Add or update a position (weighted average cost).
    asset_class: us_equity | crypto | commodity | tefas | other
    currency:    USD | TRY
    deduct_from_cash=True ise alım tutarı nakitten düşülür.
    """
    positions, cash, sha = _read_full_portfolio()
    ticker = ticker.upper().strip()
    purchase_total = shares * avg_cost

    # TEFAS için nakit düşme — TRY bazlı, USD'ye çevirmeden
    # Kripto ve emtia için normal USD nakit düşme
    if currency == "TRY":
        deduct_from_cash = False  # TRY varlıklar USD nakitten düşülmez

    for pos in positions:
        if pos["ticker"] == ticker:
            old_val  = pos["shares"] * pos["avg_cost"]
            new_val  = shares * avg_cost
            total_sh = pos["shares"] + shares
            pos["avg_cost"]    = (old_val + new_val) / total_sh if total_sh else avg_cost
            pos["shares"]      = total_sh
            pos["sector"]      = sector
            pos["notes"]       = notes
            pos["asset_class"] = asset_class
            pos["currency"]    = currency
            pos["updated"]     = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_cash = (cash - purchase_total) if deduct_from_cash else cash
            _write_full_portfolio(positions, new_cash, sha)
            return positions

    positions.append({
        "ticker":      ticker,
        "shares":      shares,
        "avg_cost":    avg_cost,
        "sector":      sector,
        "notes":       notes,
        "asset_class": asset_class,
        "currency":    currency,
        "added":       datetime.now().strftime("%Y-%m-%d %H:%M"),
        "updated":     datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    new_cash = (cash - purchase_total) if deduct_from_cash else cash
    _write_full_portfolio(positions, new_cash, sha)
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


def sell_position(ticker: str, shares_sold: float, sell_price: float = 0.0) -> tuple[list[dict], str]:
    """
    Pozisyon azalt veya kapat.
    sell_price > 0 ise K/Z hesaplanır ve mesaja eklenir.
    """
    positions, sha = _github_read()
    ticker = ticker.upper().strip()

    for i, pos in enumerate(positions):
        if pos["ticker"] == ticker:
            avg_cost  = pos.get("avg_cost", 0)
            remaining = pos["shares"] - shares_sold

            # K/Z hesapla
            pnl_str = ""
            if sell_price > 0 and avg_cost > 0:
                pnl_per_share = sell_price - avg_cost
                pnl_total     = pnl_per_share * shares_sold
                pnl_pct       = (pnl_per_share / avg_cost) * 100
                sign          = "+" if pnl_total >= 0 else ""
                emoji         = "✅" if pnl_total >= 0 else "🔴"
                pnl_str = (
                    f" {emoji} Satış K/Z: {sign}${pnl_total:,.2f} "
                    f"({sign}{pnl_pct:.2f}% / hisse başı {sign}${pnl_per_share:.2f})"
                )

            if remaining <= 0:
                positions.pop(i)
                msg = f"{ticker} tamamen kapatıldı.{pnl_str}"
            else:
                pos["shares"]  = remaining
                pos["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                msg = f"{ticker}: {remaining:.4f} adet kaldı.{pnl_str}"

            # Satış gelirini nakite ekle
            sale_proceeds = (sell_price * shares_sold) if sell_price > 0 else 0.0
            _, cur_cash, _ = _read_full_portfolio()
            _write_full_portfolio(positions, cur_cash + sale_proceeds, sha)
            return positions, msg

    return positions, f"{ticker} portföyde bulunamadı."


# ---------------------------------------------------------------------------
# Cash Management
# ---------------------------------------------------------------------------

def _read_full_portfolio() -> tuple[list[dict], float, str]:
    """
    Returns (positions, cash, sha).
    Hem eski list formatını hem yeni dict formatını destekler.
    """
    token, repo = _get_github_config()
    if not token or not repo:
        positions = _local_read()
        cash = _local_read_cash()
        return positions, cash, ""

    url     = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 404:
            return [], 0.0, ""
        resp.raise_for_status()
        data    = resp.json()
        sha     = data.get("sha", "")
        raw     = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
        if isinstance(raw, dict) and "positions" in raw:
            return raw.get("positions", []), float(raw.get("cash", 0.0)), sha
        elif isinstance(raw, list):
            return raw, 0.0, sha
        return [], 0.0, sha
    except Exception as exc:
        logger.warning("Full portfolio read failed: %s", exc)
        return _local_read(), _local_read_cash(), ""


def _write_full_portfolio(positions: list[dict], cash: float, sha: str = "") -> bool:
    """Positions + cash birlikte yaz."""
    token, repo = _get_github_config()
    # Mevcut cash_accounts'ı koru
    try:
        _existing = _read_raw_portfolio()
        _accounts = _existing.get("cash_accounts", {}) if isinstance(_existing, dict) else {}
    except Exception:
        _accounts = {}
    full_data = {
        "positions":     positions,
        "cash":          round(float(cash), 2),
        "cash_accounts": _accounts,
    }

    if not token or not repo:
        return _local_write_full(full_data)

    url     = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    encoded = base64.b64encode(
        json.dumps(full_data, indent=2, ensure_ascii=False).encode("utf-8")
    ).decode("utf-8")
    payload = {"message": f"Portfolio update (cash: ${cash:.2f})", "content": encoded}
    if sha:
        payload["sha"] = sha
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Full portfolio write failed: %s", exc)
        return _local_write_full(full_data)


def _local_read_cash() -> float:
    if not os.path.exists(PORTFOLIO_FILE):
        return 0.0
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return float(data.get("cash", 0.0))
    except Exception:
        pass
    return 0.0


def _local_write_full(full_data: dict) -> bool:
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_cash() -> float:
    """Mevcut nakit miktarını döndür."""
    _, cash, _ = _read_full_portfolio()
    return cash


def set_cash(amount: float) -> bool:
    """Nakiti doğrudan belirli bir değere ayarla."""
    positions, _, sha = _read_full_portfolio()
    return _write_full_portfolio(positions, max(0.0, amount), sha)

def _read_raw_portfolio() -> dict:
    """Ham portfolio.json içeriğini dict olarak döndür."""
    token, repo = _get_github_config()
    if token and repo:
        try:
            url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
            hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            resp = requests.get(url, headers=hdrs, timeout=10)
            if resp.status_code == 200:
                raw = json.loads(base64.b64decode(resp.json()["content"]).decode("utf-8"))
                return raw if isinstance(raw, dict) else {}
        except Exception:
            pass
    # Local fallback
    try:
        with open("portfolio.json") as f:
            raw = json.load(f)
            return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def get_cash_accounts() -> dict:
    """
    Tüm nakit hesaplarını döndür. Negatif değerler sıfıra yuvarlanır.
    {
      "usd":           float,  # ABD hisse / genel USD nakit
      "crypto_usd":    float,  # Kripto borsa nakiti (USD)
      "commodity_usd": float,  # Emtia hesabı (USD)
      "tefas_try":     float,  # TEFAS / Türkiye TL nakiti
    }
    """
    raw = _read_raw_portfolio()
    accounts = raw.get("cash_accounts", {})
    # Eski "cash" alanı negatifse 0 kullan (kripto alımları düşüyordu)
    legacy_cash = max(0.0, float(raw.get("cash", 0.0)))
    return {
        "usd":           max(0.0, float(accounts.get("usd",           legacy_cash))),
        "crypto_usd":    max(0.0, float(accounts.get("crypto_usd",    0.0))),
        "commodity_usd": max(0.0, float(accounts.get("commodity_usd", 0.0))),
        "tefas_try":     max(0.0, float(accounts.get("tefas_try",     0.0))),
    }


def set_cash_account(account: str, amount: float) -> bool:
    """
    Belirli bir nakit hesabını güncelle.
    account: "usd" | "crypto_usd" | "commodity_usd" | "tefas_try"
    """
    amount = max(0.0, float(amount))
    token, repo = _get_github_config()

    raw = _read_raw_portfolio()
    accounts = raw.get("cash_accounts", {})
    accounts[account] = round(amount, 2)

    # usd değişirse eski cash alanını da güncelle (geriye uyumluluk)
    if account == "usd":
        raw["cash"] = round(amount, 2)

    raw["cash_accounts"] = accounts
    encoded = base64.b64encode(
        json.dumps(raw, indent=2, ensure_ascii=False).encode()
    ).decode()

    if token and repo:
        try:
            url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_PATH}"
            hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            sha  = requests.get(url, headers=hdrs, timeout=10).json().get("sha", "")
            payload = {"message": f"Cash update: {account}={amount:.2f}",
                       "content": encoded, "sha": sha}
            resp = requests.put(url, headers=hdrs, json=payload, timeout=15)
            return resp.status_code in (200, 201)
        except Exception as e:
            logger.warning("set_cash_account GitHub write failed: %s", e)

    # Local fallback
    try:
        with open("portfolio.json", "w") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_total_cash_usd(usd_try: float = 32.0) -> dict:
    """
    Tüm nakit hesaplarını USD bazında topla.
    Returns: {total_usd, breakdown, usd_try}
    """
    accts = get_cash_accounts()
    breakdown = {
        "ABD / USD":  accts["usd"],
        "Kripto":     accts["crypto_usd"],
        "Emtia":      accts["commodity_usd"],
        "TEFAS (TL)": accts["tefas_try"] / usd_try,
    }
    total = sum(breakdown.values())
    return {
        "total_usd":   round(total, 2),
        "breakdown":   breakdown,
        "raw_accounts": accts,
        "usd_try":     usd_try,
    }




def add_cash(amount: float, reason: str = "") -> tuple[float, str]:
    """Nakit ekle (para yatırma veya satış geliri)."""
    positions, cash, sha = _read_full_portfolio()
    new_cash = cash + amount
    _write_full_portfolio(positions, new_cash, sha)
    msg = f"${amount:,.2f} nakit eklendi. Yeni bakiye: ${new_cash:,.2f}"
    if reason:
        msg = f"{reason} — {msg}"
    return new_cash, msg


def deduct_cash(amount: float, reason: str = "") -> tuple[float, str]:
    """Nakit düş (hisse alımı veya para çekme)."""
    positions, cash, sha = _read_full_portfolio()
    new_cash = cash - amount
    _write_full_portfolio(positions, new_cash, sha)
    msg = f"${amount:,.2f} nakit düşüldü. Yeni bakiye: ${new_cash:,.2f}"
    if reason:
        msg = f"{reason} — {msg}"
    return new_cash, msg


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
