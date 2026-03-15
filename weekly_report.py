# weekly_report.py — GitHub Actions Pazar 17:00 UTC (TR 20:00)
#
# 2 Ayrı Rapor:
#   1. Portföy Raporu     — portföydeki hisselerin haftalık değerlendirmesi
#   2. Sürpriz Raporu     — mktCap < 50B, gözden kaçan fırsatlar

import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app"


# ---------------------------------------------------------------------------
# Portföy Raporu Formatı
# ---------------------------------------------------------------------------

def format_portfolio_telegram(results: list[dict], date_str: str) -> list[str]:
    """Portföydeki hisselerin haftalık raporunu formatla."""
    messages = []

    header = (
        f"💼 <b>Haftalık Portföy Raporu</b>\n"
        f"<i>{date_str}</i>\n\n"
        f"Portföyündeki {len(results)} hissenin haftalık değerlendirmesi\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    messages.append(header)

    chunk = []
    for i, r in enumerate(results, 1):
        ticker  = r["ticker"]
        name    = r.get("name", ticker)[:25]
        score   = r.get("nihai_guven_skoru", 0)
        price   = r.get("price", 0)
        tavsiye = r.get("tavsiye", "Tut")
        ozet    = r.get("analiz_ozeti", "")[:120]
        rev_gr  = r.get("revenue_growth", 0)
        mc      = r.get("market_cap", 0) or 0

        emoji = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
        tav_emoji = {"Ağırlık Artır": "⬆️", "Tut": "➡️", "Azalt": "⬇️"}.get(tavsiye, "➡️")
        price_str = f"${price:,.2f}" if price else "N/A"
        rev_str   = f"{rev_gr:+.0%}" if rev_gr else "N/A"
        mc_str    = f"${mc/1e9:.1f}B" if mc else "N/A"

        entry = (
            f"\n{emoji} <b>{ticker}</b> — {score} puan\n"
            f"   {name}\n"
            f"   💰 {price_str} | 📊 {mc_str} | 📈 Gelir: {rev_str}\n"
            f"   {tav_emoji} {tavsiye}\n"
            f"   💬 <i>{ozet}</i>"
        )
        chunk.append(entry)

        if len(chunk) == 5 or i == len(results):
            messages.append("\n".join(chunk))
            chunk = []

    messages.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>"
    )
    return messages


# ---------------------------------------------------------------------------
# Sürpriz Raporu Formatı
# ---------------------------------------------------------------------------

def format_surprise_telegram(results: list[dict], date_str: str) -> list[str]:
    """Sürpriz hisselerin raporunu formatla."""
    messages = []

    header = (
        f"🔭 <b>Haftalık Sürpriz Radar</b>\n"
        f"<i>{date_str}</i>\n\n"
        f"<b>Evren:</b> 770 hisse (kendi liste + Russell 2000)\n"
        f"<b>Filtre:</b> Piyasa değeri &lt; $50B — devleri eledik\n"
        f"<b>Amaç:</b> Gözden kaçan, sıçrama potansiyeli yüksek {len(results)} hisse\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    messages.append(header)

    chunk = []
    for i, r in enumerate(results, 1):
        ticker   = r["ticker"]
        name     = r.get("name", ticker)[:25]
        score    = r.get("nihai_guven_skoru", 0)
        surpriz  = r.get("surpriz_potansiyeli", 0)
        price    = r.get("price", 0)
        mc       = r.get("market_cap", 0) or 0
        tavsiye  = r.get("tavsiye", "Tut")
        ozet     = r.get("analiz_ozeti", "")[:120]
        katalizor = r.get("katalizor", "")[:80]
        sector   = r.get("sector", "N/A")
        analyst_n = r.get("analyst_count", 0)
        beta     = r.get("beta", 0)
        rev_gr   = r.get("revenue_growth", 0)

        # Sürpriz seviyesi
        if surpriz >= 75:   s_emoji = "🚀"
        elif surpriz >= 55: s_emoji = "⚡"
        else:               s_emoji = "💡"

        tav_emoji  = {"Ağırlık Artır": "⬆️", "Tut": "➡️", "Azalt": "⬇️"}.get(tavsiye, "➡️")
        price_str  = f"${price:,.2f}" if price else "N/A"
        mc_str     = f"${mc/1e9:.1f}B" if mc else "N/A"
        rev_str    = f"{rev_gr:+.0%}" if rev_gr else "N/A"
        beta_str   = f"{beta:.2f}" if beta else "N/A"
        cov_str    = f"{analyst_n} analist" if analyst_n else "Az takipli"

        entry = (
            f"\n{s_emoji} <b>#{i} {ticker}</b>\n"
            f"   {name} | {sector}\n"
            f"   💰 {price_str} | 📊 {mc_str} | Beta: {beta_str}\n"
            f"   📈 Gelir: {rev_str} | 👁 {cov_str}\n"
            f"   🎯 Puan: {score} | Sürpriz: {surpriz} | {tav_emoji} {tavsiye}\n"
            f"   💬 <i>{ozet}</i>"
        )
        if katalizor:
            entry += f"\n   ⚡ <i>Katalizör: {katalizor}</i>"

        chunk.append(entry)

        if len(chunk) == 5 or i == len(results):
            messages.append("\n".join(chunk))
            chunk = []

    messages.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Bu liste yatırım tavsiyesi değildir. DYOR.</i>\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>\n"
        "<i>Sonraki rapor: Pazar 20:00 TR</i>"
    )
    return messages



# ---------------------------------------------------------------------------
# Makro Raporu Formatı
# ---------------------------------------------------------------------------

def format_macro_telegram(macro_data: dict, regime: dict, date_str: str) -> str:
    """Makro gösterge özetini Telegram formatına çevir."""
    rc = regime.get("label", "Bilinmiyor")
    rdesc = regime.get("description", "")

    lines = [
        f"🌍 <b>Haftalık Makro Özet</b>",
        f"<i>{date_str}</i>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"📊 <b>Piyasa Rejimi: {rc}</b>",
        f"<i>{rdesc}</i>",
        f"",
    ]

    signal_groups = {
        "fear":      ("😰 Korku & Volatilite", ["VIX", "YIELD_CURVE"]),
        "rates":     ("💵 Faiz Ortamı",        ["TNX", "IRX"]),
        "fx":        ("💱 Dolar",              ["DXY"]),
        "commodity": ("🏭 Emtia",              ["GOLD", "OIL", "COPPER"]),
        "market":    ("📈 Piyasa",             ["SPX", "NDX"]),
    }

    emoji_map = {"green": "🟢", "amber": "🟡", "red": "🔴", "neutral": "⚪"}

    for group_key, (group_label, keys) in signal_groups.items():
        group_lines = []
        for k in keys:
            if k not in macro_data:
                continue
            ind = macro_data[k]
            val   = ind.value if hasattr(ind, "value") else ind.get("value", 0)
            chg   = ind.change_pct if hasattr(ind, "change_pct") else ind.get("change_pct", 0)
            sig   = ind.signal if hasattr(ind, "signal") else ind.get("signal", "neutral")
            note  = ind.note if hasattr(ind, "note") else ind.get("note", "")
            unit  = ind.unit if hasattr(ind, "unit") else ind.get("unit", "")
            label = ind.label if hasattr(ind, "label") else ind.get("label", k)
            prefix = "$" if unit == "$" else ""
            suffix = unit if unit != "$" else ""
            em = emoji_map.get(sig, "⚪")
            group_lines.append(
                f"  {em} {label}: {prefix}{val:.2f}{suffix} ({chg:+.2f}%)"
            )
        if group_lines:
            lines.append(f"<b>{group_label}</b>")
            lines.extend(group_lines)
            lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ana Fonksiyon
# ---------------------------------------------------------------------------

def main():
    logger.info("Haftalık rapor başlatılıyor...")

    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Eksik env değişkenleri: %s", missing)
        sys.exit(1)

    from weekly_scanner    import run_surprise_scan, run_portfolio_scan
    from portfolio_manager import load_portfolio
    from telegram_notifier import send_message

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    def progress_cb(ticker, idx, total, stage=1):
        if idx % 25 == 0 or idx == total:
            logger.info("Aşama %d: %d/%d — %s", stage, idx, total, ticker)

    # ── RAPOR 1: Portföy ──────────────────────────────────────────────────
    logger.info("Portföy raporu hazırlanıyor...")
    try:
        port         = load_portfolio()
        port_tickers = [p["ticker"] for p in port if p.get("ticker")]
    except Exception as e:
        logger.warning("Portföy yüklenemedi: %s", e)
        port_tickers = []

    if port_tickers:
        port_results = run_portfolio_scan(port_tickers, progress_callback=progress_cb)
        if port_results:
            msgs = format_portfolio_telegram(port_results, date_str)
            for msg in msgs:
                if not send_message(msg):
                    logger.error("Portföy mesajı gönderilemedi")
            logger.info("Portföy raporu gönderildi: %d hisse", len(port_results))
        else:
            send_message(f"💼 <b>Portföy Raporu</b>\n\n📭 Veri alınamadı.")
    else:
        send_message(f"💼 <b>Portföy Raporu</b>\n\n📭 Portföyünüzde hisse bulunamadı.")

    # ── RAPOR 0: Makro Özet ──────────────────────────────────────────────
    logger.info("Makro raporu hazırlanıyor...")
    try:
        from macro_dashboard import fetch_macro_data, compute_market_regime
        macro_data   = fetch_macro_data()
        macro_regime = compute_market_regime(macro_data)

        # Makro snapshot'ı hafızaya kaydet
        try:
            from analysis_memory import save_macro_snapshot
            save_macro_snapshot(macro_data, macro_regime)
        except Exception as e:
            logger.warning("Makro snapshot kaydedilemedi: %s", e)

        macro_msg = format_macro_telegram(macro_data, macro_regime, date_str)
        if not send_message(macro_msg):
            logger.error("Makro mesajı gönderilemedi")
        else:
            logger.info("Makro raporu gönderildi.")
    except Exception as e:
        logger.error("Makro raporu hatası: %s", e)
        send_message(f"🌍 <b>Makro Özet</b>\n\n⚠️ Veriler alınamadı: {e}")

    # ── RAPOR 2: Sürpriz Hisseler ─────────────────────────────────────────
    logger.info("Sürpriz tarama başlatılıyor...")
    surprise_results = run_surprise_scan(
        top_n_stage1=50,
        top_n_final=25,
        progress_callback=progress_cb,
    )

    if surprise_results:
        msgs = format_surprise_telegram(surprise_results, date_str)
        for msg in msgs:
            if not send_message(msg):
                logger.error("Sürpriz mesajı gönderilemedi")
        logger.info("Sürpriz raporu gönderildi: %d hisse", len(surprise_results))
    else:
        send_message(f"🔭 <b>Sürpriz Radar</b>\n\n📭 Bu hafta yeterli sürpriz adayı bulunamadı.")

    logger.info("Haftalık rapor tamamlandı.")


if __name__ == "__main__":
    main()
