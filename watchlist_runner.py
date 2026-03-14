# watchlist_runner.py — GitHub Actions Watchlist Günlük Analiz
# Her gün 15:00 TR'de çalışır — ABD piyasası açılmadan önce

import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    logger.info("Watchlist günlük analiz başlatılıyor...")

    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Eksik env değişkenleri: %s", missing)
        sys.exit(1)

    from watchlist_analyzer import run_watchlist_analysis, format_watchlist_telegram
    from telegram_notifier  import send_message

    # Analiz çalıştır
    result = run_watchlist_analysis()
    logger.info(
        "Tarama tamamlandı: %d/%d hisse tetiklendi",
        result["analyzed"], result["total"]
    )

    # Telegram'a gönder
    messages = format_watchlist_telegram(result)
    for i, msg in enumerate(messages):
        ok = send_message(msg)
        if not ok:
            logger.error("Mesaj %d gönderilemedi", i + 1)
        else:
            logger.info("Mesaj %d/%d gönderildi", i + 1, len(messages))

    logger.info("Watchlist raporu tamamlandı.")


if __name__ == "__main__":
    main()
