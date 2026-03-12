# weekly_report.py — GitHub Actions tarafından Pazar 17:00 UTC (TR 20:00) çalıştırılır.
# S&P 500 haftalık taraması yapar, top 25 hisseyi Telegram'a gönderir.

import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def format_weekly_telegram(results: list[dict]) -> list[str]:
    """
    Top 25 listeyi Telegram mesajlarına böl.
    Telegram mesaj limiti 4096 karakter — birden fazla mesaj gönderebiliriz.
    """
    messages = []

    # Başlık mesajı
    now_tr = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    header = (
        f"📊 <b>Haftalık S&P 500 Raporu</b>\n"
        f"<i>{now_tr} — Top {len(results)} Hisse</i>\n\n"
        f"<b>2 Aşamalı Filtre:</b> 500 hisse tarandı → "
        f"Temel metrikle 50'ye indirildi → Claude ile {len(results)} seçildi\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    messages.append(header)

    # Her 5 hisse bir mesaj
    chunk = []
    for i, r in enumerate(results, 1):
        ticker     = r["ticker"]
        name       = r.get("name", ticker)[:25]
        score      = r.get("nihai_guven_skoru", 0)
        fund_score = r.get("fund_score", 0)
        sector     = r.get("sector", "N/A")
        price      = r.get("price", 0)
        rev_gr     = r.get("revenue_growth", 0)
        tavsiye    = r.get("tavsiye", "Tut")
        ozet       = r.get("analiz_ozeti", "")[:120]

        # Emoji
        if score >= 80:   emoji = "🟢"
        elif score >= 65: emoji = "🟡"
        else:             emoji = "🔵"

        tavsiye_map = {"Ağırlık Artır": "⬆️", "Tut": "➡️", "Azalt": "⬇️"}
        tav_emoji   = tavsiye_map.get(tavsiye, "➡️")

        price_str = f"${price:,.2f}" if price else "N/A"
        rev_str   = f"{rev_gr:+.0%}" if rev_gr else "N/A"

        entry = (
            f"\n{emoji} <b>#{i} {ticker}</b> — {score} puan\n"
            f"   {name} | {sector}\n"
            f"   💰 {price_str} | 📈 Gelir: {rev_str}\n"
            f"   🎯 Temel: {fund_score} | {tav_emoji} {tavsiye}\n"
            f"   💬 <i>{ozet}</i>"
        )
        chunk.append(entry)

        if len(chunk) == 5 or i == len(results):
            messages.append("\n".join(chunk))
            chunk = []

    # Footer
    messages.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <a href='https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app'>"
        "Dashboard'u Aç</a>\n"
        "<i>Bir sonraki haftalık rapor: Pazar 20:00 TR</i>"
    )

    return messages


def main():
    logger.info("Haftalık rapor başlatılıyor...")

    # API key kontrol
    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Eksik environment değişkenleri: %s", missing)
        sys.exit(1)

    from weekly_scanner    import run_weekly_scan
    from telegram_notifier import send_message

    # Progress log
    def progress_cb(ticker, idx, total, stage=1):
        if idx % 20 == 0 or idx == total:
            logger.info("Aşama %d: %d/%d — %s", stage, idx, total, ticker)

    # Tarama çalıştır
    results = run_weekly_scan(
        top_n_stage1=50,
        top_n_final=25,
        progress_callback=progress_cb,
    )

    logger.info("Tarama tamamlandı: %d hisse bulundu", len(results))

    if not results:
        send_message("📊 <b>Haftalık Rapor</b>\n\n📭 Bu hafta yeterli veri bulunamadı.")
        return

    # Mesajları gönder
    messages = format_weekly_telegram(results)
    for msg in messages:
        ok = send_message(msg)
        if not ok:
            logger.error("Telegram mesajı gönderilemedi")
            sys.exit(1)

    logger.info("%d Telegram mesajı başarıyla gönderildi", len(messages))


if __name__ == "__main__":
    main()
