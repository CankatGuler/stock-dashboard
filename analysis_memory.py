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
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

HISTORY_FILE = "analysis_history.json"
MAX_RECORDS  = 500   # toplam max kayıt


def _get_github_config():
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
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


def get_top_tickers(limit: int = 10) -> list[dict]:
    """
    En çok analiz edilen hisseleri döndür.
    Her hisse için: ticker, count, latest_score, trend, latest_tavsiye
    """
    records, _ = _github_read_history()
    if not records:
        return []

    from collections import defaultdict
    ticker_data = defaultdict(list)
    for r in records:
        tk = r.get("ticker", "")
        if tk:
            ticker_data[tk].append(r)

    result = []
    for tk, recs in ticker_data.items():
        recs_sorted = sorted(recs, key=lambda x: x.get("timestamp", x.get("date", "")))
        latest = recs_sorted[-1]
        latest_score = latest.get("score", 0)

        # Trend: son skor - ilk skor (en az 2 analiz varsa)
        if len(recs_sorted) >= 2:
            first_score = recs_sorted[0].get("score", 0)
            trend = latest_score - first_score
        else:
            trend = 0

        result.append({
            "ticker":          tk,
            "count":           len(recs_sorted),
            "latest_score":    latest_score,
            "latest_tavsiye":  latest.get("tavsiye", "—"),
            "latest_date":     latest.get("date", ""),
            "trend":           trend,
        })

    # Önce en çok analiz edilenler, eşitlik durumunda en yüksek skor
    result.sort(key=lambda x: (-x["count"], -x["latest_score"]))
    return result[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Makro Snapshot Kayıt / Okuma
# ─────────────────────────────────────────────────────────────────────────────

MACRO_HISTORY_FILE = "macro_history.json"
MAX_MACRO_RECORDS  = 200


def _github_read_macro() -> tuple[list[dict], str]:
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return _local_read_json(MACRO_HISTORY_FILE), ""
    url  = f"https://api.github.com/repos/{repo}/contents/{MACRO_HISTORY_FILE}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        if r.status_code == 404:
            return [], ""
        r.raise_for_status()
        data = r.json()
        return json.loads(base64.b64decode(data["content"]).decode()), data.get("sha", "")
    except Exception as e:
        logger.warning("macro_history read failed: %s", e)
        return _local_read_json(MACRO_HISTORY_FILE), ""


def _github_write_macro(records: list[dict], sha: str = "") -> bool:
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return _local_write_json(MACRO_HISTORY_FILE, records)
    url  = f"https://api.github.com/repos/{repo}/contents/{MACRO_HISTORY_FILE}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"Macro snapshot ({len(records)} records)",
        "content": base64.b64encode(
            json.dumps(records, indent=2, ensure_ascii=False).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=hdrs, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("macro_history write failed: %s", e)
        return _local_write_json(MACRO_HISTORY_FILE, records)


def _local_read_json(filename: str) -> list[dict]:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _local_write_json(filename: str, data) -> bool:
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def save_macro_snapshot(macro_data: dict, regime: dict) -> bool:
    """
    Makro gösterge anlık görüntüsünü kaydet.
    macro_data: {key: MacroIndicator} (dataclass değil dict olarak serialize edilmiş)
    """
    records, sha = _github_read_macro()
    now = datetime.utcnow()

    snapshot = {
        "date":      now.strftime("%Y-%m-%d"),
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "regime":    regime.get("regime", ""),
        "label":     regime.get("label", ""),
        "indicators": {
            k: {
                "value":      v.value if hasattr(v, "value") else v.get("value", 0),
                "change_pct": v.change_pct if hasattr(v, "change_pct") else v.get("change_pct", 0),
                "signal":     v.signal if hasattr(v, "signal") else v.get("signal", ""),
                "note":       v.note if hasattr(v, "note") else v.get("note", ""),
            }
            for k, v in macro_data.items()
        }
    }

    records.append(snapshot)
    if len(records) > MAX_MACRO_RECORDS:
        records = records[-MAX_MACRO_RECORDS:]

    return _github_write_macro(records, sha)


def get_macro_history(limit: int = 52) -> list[dict]:
    """Son N makro snapshot'ı döndür (en yeni önce)."""
    records, _ = _github_read_macro()
    return list(reversed(records))[:limit]


def get_macro_snapshot_by_date(target_date: str) -> dict | None:
    """
    Belirli bir tarihe en yakın makro snapshot'ı bul.
    target_date: 'YYYY-MM-DD'
    """
    records, _ = _github_read_macro()
    if not records:
        return None
    records_sorted = sorted(records, key=lambda x: x.get("date", ""))
    # En yakın tarihi bul
    best = min(records_sorted, key=lambda x: abs(
        (datetime.strptime(x["date"], "%Y-%m-%d") -
         datetime.strptime(target_date, "%Y-%m-%d")).days
    ))
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Portföy Analizi Hafızası
# ─────────────────────────────────────────────────────────────────────────────

PORTFOLIO_ANALYSIS_FILE = "portfolio_analysis_history.json"
MAX_PORTFOLIO_RECORDS   = 100


def save_portfolio_analysis(
    analysis_type: str,      # "risk" | "scenario" | "correlation"
    analysis_text: str,
    portfolio_snapshot: list[dict],
    macro_regime: str = "",
    scenario: str = "",
    extra: dict = None,
) -> bool:
    """Portföy analizini hafızaya kaydet."""
    records, sha = _read_portfolio_analysis_history()
    now = datetime.utcnow()

    record = {
        "date":               now.strftime("%Y-%m-%d"),
        "timestamp":          now.strftime("%Y-%m-%dT%H:%M:%S"),
        "type":               analysis_type,
        "analysis":           analysis_text[:2000],
        "macro_regime":       macro_regime,
        "scenario":           scenario,
        "tickers":            [p.get("ticker", "") for p in portfolio_snapshot],
        "total_value":        sum(p.get("current_value", 0) for p in portfolio_snapshot),
        "position_count":     len(portfolio_snapshot),
        "extra":              extra or {},
    }

    records.append(record)
    if len(records) > MAX_PORTFOLIO_RECORDS:
        records = records[-MAX_PORTFOLIO_RECORDS:]

    return _write_portfolio_analysis_history(records, sha)


def _read_portfolio_analysis_history() -> tuple[list[dict], str]:
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return _local_read_json(PORTFOLIO_ANALYSIS_FILE), ""
    url  = f"https://api.github.com/repos/{repo}/contents/{PORTFOLIO_ANALYSIS_FILE}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=hdrs, timeout=10)
        if r.status_code == 404:
            return [], ""
        r.raise_for_status()
        data = r.json()
        return json.loads(base64.b64decode(data["content"]).decode()), data.get("sha", "")
    except Exception as e:
        logger.warning("portfolio_analysis read failed: %s", e)
        return _local_read_json(PORTFOLIO_ANALYSIS_FILE), ""


def _write_portfolio_analysis_history(records: list[dict], sha: str = "") -> bool:
    token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return _local_write_json(PORTFOLIO_ANALYSIS_FILE, records)
    url  = f"https://api.github.com/repos/{repo}/contents/{PORTFOLIO_ANALYSIS_FILE}"
    hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "message": f"Portfolio analysis update ({len(records)} records)",
        "content": base64.b64encode(
            json.dumps(records, indent=2, ensure_ascii=False).encode()
        ).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=hdrs, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("portfolio_analysis write failed: %s", e)
        return _local_write_json(PORTFOLIO_ANALYSIS_FILE, records)


def get_portfolio_analysis_history(
    analysis_type: str = None,
    limit: int = 20
) -> list[dict]:
    """Portföy analiz geçmişini getir."""
    records, _ = _read_portfolio_analysis_history()
    if analysis_type:
        records = [r for r in records if r.get("type") == analysis_type]
    return list(reversed(records))[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Karşılaştırma Motoru
# ─────────────────────────────────────────────────────────────────────────────

def find_comparison_record(
    ticker: str,
    weeks_ago: int = 1,
) -> dict | None:
    """
    Bir hisse için N hafta önceki analiz kaydını bul.
    """
    records, _ = _github_read_history()
    ticker_records = [r for r in records if r.get("ticker", "").upper() == ticker.upper()]
    if not ticker_records:
        return None

    target_date = datetime.utcnow() - __import__("datetime").timedelta(weeks=weeks_ago)
    target_str  = target_date.strftime("%Y-%m-%d")

    best = min(
        ticker_records,
        key=lambda x: abs(
            (datetime.strptime(x["date"], "%Y-%m-%d") - target_date).days
        )
    )

    # Eğer hedef tarihten çok uzaksa None döndür (2 haftalık tolerans)
    if abs((datetime.strptime(best["date"], "%Y-%m-%d") - target_date).days) > 14:
        return None
    return best


def build_comparison_context(
    ticker: str,
    current_record: dict,
    past_record: dict,
    past_macro: dict = None,
    current_macro: dict = None,
) -> str:
    """
    İki analiz kaydını karşılaştıran Claude prompt context'i oluştur.
    """
    lines = [
        f"=== {ticker} ANALİZ KARŞILAŞTIRMASI ===",
        "",
        f"GÜNCEL ({current_record.get('date', '?')}):",
        f"  Skor: {current_record.get('score', '?')}/100",
        f"  Tavsiye: {current_record.get('tavsiye', '?')}",
        f"  Fiyat: ${current_record.get('price', 0):.2f}",
        f"  Özet: {current_record.get('ozet', '')[:200]}",
        "",
        f"GEÇMİŞ ({past_record.get('date', '?')}):",
        f"  Skor: {past_record.get('score', '?')}/100",
        f"  Tavsiye: {past_record.get('tavsiye', '?')}",
        f"  Fiyat: ${past_record.get('price', 0):.2f}",
        f"  Özet: {past_record.get('ozet', '')[:200]}",
        "",
    ]

    # Değişimleri hesapla
    score_diff = current_record.get("score", 0) - past_record.get("score", 0)
    price_diff_pct = 0
    if past_record.get("price", 0) > 0:
        price_diff_pct = (
            (current_record.get("price", 0) - past_record.get("price", 0))
            / past_record.get("price", 0) * 100
        )

    lines.append(f"DEĞİŞİMLER:")
    lines.append(f"  Skor: {past_record.get('score')} → {current_record.get('score')} ({score_diff:+d})")
    lines.append(f"  Fiyat: ${past_record.get('price', 0):.2f} → ${current_record.get('price', 0):.2f} ({price_diff_pct:+.1f}%)")

    # Makro bağlamı
    if past_macro and current_macro:
        lines.append("")
        lines.append("MAKRO ORTAM DEĞİŞİMİ:")
        for key in ["VIX", "TNX", "DXY", "SPX"]:
            p_ind = past_macro.get("indicators", {}).get(key, {})
            c_ind = current_macro.get("indicators", {}).get(key, {})
            if p_ind and c_ind:
                p_val = p_ind.get("value", 0)
                c_val = c_ind.get("value", 0)
                lines.append(f"  {key}: {p_val:.2f} → {c_val:.2f}")
        lines.append(f"  Rejim: {past_macro.get('label', '?')} → {current_macro.get('label', '?')}")

    lines.append("=" * 40)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# HAFTALIK RAPOR ARŞİVİ
# ─────────────────────────────────────────────────────────────────────────────

WEEKLY_REPORT_FILE = "weekly_report_archive.json"
MAX_WEEKLY_REPORTS = 52   # 1 yıllık geçmiş


def _load_weekly_archive() -> list:
    """GitHub'dan haftalık rapor arşivini oku."""
    try:
        import requests, base64, os, json
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            if os.path.exists(WEEKLY_REPORT_FILE):
                with open(WEEKLY_REPORT_FILE) as f:
                    return json.load(f)
            return []
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url  = f"https://api.github.com/repos/{repo}/contents/{WEEKLY_REPORT_FILE}"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning("Weekly archive load failed: %s", e)
        return []


def _save_weekly_archive(data: list) -> bool:
    """Haftalık rapor arşivini GitHub'a yaz."""
    try:
        import requests, base64, os, json
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")

        # Lokal fallback
        with open(WEEKLY_REPORT_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if not token or not repo:
            return True

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url     = f"https://api.github.com/repos/{repo}/contents/{WEEKLY_REPORT_FILE}"
        content = json.dumps(data, ensure_ascii=False, indent=2)
        encoded = base64.b64encode(content.encode()).decode()

        sha = None
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": f"weekly report archive {datetime.now().strftime('%Y-%m-%d')}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(url, headers=headers, json=payload, timeout=15)
        r2.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Weekly archive save failed: %s", e)
        return False


def save_weekly_report(
    report_type: str,            # "portfolio" | "surprise" | "macro"
    results: list,               # Hisse analiz sonuçları listesi
    macro_snapshot: dict = None, # Makro ortam snapshot
    summary_text: str = "",      # Kısa özet metin
) -> bool:
    """
    Haftalık raporu arşive kaydet.

    Her kayıt:
    {
      "id":          "2026-03-16_portfolio",
      "date":        "2026-03-16",
      "week":        "2026-W11",
      "type":        "portfolio",
      "summary":     "...",
      "result_count": 15,
      "results":     [...],
      "macro":       {...},
      "saved_at":    "2026-03-16T17:00:00Z"
    }
    """
    archive = _load_weekly_archive()
    today   = datetime.now(timezone.utc)

    record = {
        "id":           f"{today.strftime('%Y-%m-%d')}_{report_type}",
        "date":         today.strftime("%Y-%m-%d"),
        "week":         today.strftime("%Y-W%W"),
        "type":         report_type,
        "summary":      summary_text,
        "result_count": len(results),
        "results":      results[:30],   # Max 30 hisse kaydet
        "macro":        macro_snapshot or {},
        "saved_at":     today.isoformat(),
    }

    # Aynı gün aynı tip varsa güncelle
    existing_idx = next(
        (i for i, r in enumerate(archive) if r.get("id") == record["id"]),
        None
    )
    if existing_idx is not None:
        archive[existing_idx] = record
    else:
        archive.append(record)

    # Max 52 hafta tut
    if len(archive) > MAX_WEEKLY_REPORTS:
        archive = archive[-MAX_WEEKLY_REPORTS:]

    ok = _save_weekly_archive(archive)
    logger.info("Weekly report saved: %s (%d results)", record["id"], len(results))
    return ok


def get_weekly_reports(report_type: str = None, limit: int = 20) -> list:
    """
    Haftalık rapor arşivinden kayıtları getir.
    report_type=None → tüm tipler
    """
    archive = _load_weekly_archive()
    if report_type:
        archive = [r for r in archive if r.get("type") == report_type]
    # En yeni önce
    archive.sort(key=lambda x: x.get("date", ""), reverse=True)
    return archive[:limit]


def get_weekly_report_by_id(report_id: str) -> dict | None:
    """ID'ye göre tek rapor getir."""
    archive = _load_weekly_archive()
    for r in archive:
        if r.get("id") == report_id:
            return r
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STRATEJİ ARŞİVİ
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_HISTORY_FILE = "strategy_history.json"
MAX_STRATEGIES = 20  # Son 20 strateji


def _load_strategy_archive() -> list:
    """GitHub'dan strateji arşivini oku — weekly archive ile aynı pattern."""
    try:
        import requests, base64, os, json
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            if os.path.exists(STRATEGY_HISTORY_FILE):
                with open(STRATEGY_HISTORY_FILE) as f:
                    return json.load(f)
            return []
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url     = f"https://api.github.com/repos/{repo}/contents/{STRATEGY_HISTORY_FILE}"
        resp    = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning("Strategy archive load failed: %s", e)
        return []


def _save_strategy_archive(data: list) -> bool:
    """Strateji arşivini GitHub'a yaz."""
    try:
        import requests, base64, os, json
        token = os.getenv("GH_PAT", "") or os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO", "")

        # Lokal fallback
        with open(STRATEGY_HISTORY_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if not token or not repo:
            return True

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        url     = f"https://api.github.com/repos/{repo}/contents/{STRATEGY_HISTORY_FILE}"
        encoded = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode()
        ).decode()

        sha = None
        r   = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": f"strategy archive {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(url, headers=headers, json=payload, timeout=15)
        r2.raise_for_status()
        logger.info("Strategy archive saved to GitHub.")
        return True
    except Exception as e:
        logger.warning("Strategy archive save failed: %s", e)
        return False


def save_strategy_to_archive(
    strategy: dict,
    portfolio_value: float,
    cash: float,
    summary: str = "",
) -> bool:
    """
    Üretilen stratejiyi arşive kaydet.
    Her kayıt:
    {
      "id":              "2026-03-17_001",
      "date":            "2026-03-17",
      "generated_at":    "2026-03-17T19:45:00Z",
      "portfolio_value": 5911.0,
      "cash":            933.0,
      "summary":         "FOMC öncesi temkinli duruş...",
      "strategy":        { ...Claude çıktısı... }
    }
    """
    archive = _load_strategy_archive()
    now     = datetime.now(timezone.utc)

    # Aynı gün birden fazla strateji olabilir — ID'ye sıra no ekle
    today_s   = now.strftime("%Y-%m-%d")
    today_cnt = sum(1 for r in archive if r.get("date", "") == today_s)

    record = {
        "id":              f"{today_s}_{today_cnt+1:03d}",
        "date":            today_s,
        "generated_at":    now.isoformat(),
        "portfolio_value": round(portfolio_value, 2),
        "cash":            round(cash, 2),
        "summary":         summary or strategy.get("ozet", "")[:150],
        "strategy":        strategy,
    }

    archive.append(record)
    if len(archive) > MAX_STRATEGIES:
        archive = archive[-MAX_STRATEGIES:]

    ok = _save_strategy_archive(archive)
    logger.info("Strategy saved: %s", record["id"])
    return ok


def get_strategy_history(limit: int = 10) -> list:
    """Strateji arşivini en yeni önce döndür."""
    archive = _load_strategy_archive()
    archive.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
    return archive[:limit]
