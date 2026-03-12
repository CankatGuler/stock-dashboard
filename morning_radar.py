# morning_radar.py — GitHub Actions tarafından günde 2 kez çalıştırılır.
# NYSE saatine göre: açılış öncesi (08:00 ET) ve kapanış öncesi (15:00 ET)

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_session_label() -> str:
    """Çalışma saatine göre seans etiketi döndür."""
    now_utc  = datetime.now(timezone.utc)
    tr_time  = (now_utc + timedelta(hours=3)).strftime("%H:%M")
    us_time  = (now_utc - timedelta(hours=4)).strftime("%H:%M")  # EDT (yaz)
    return f"📈 Radar Taraması (ABD {us_time} ET / TR {tr_time})"


def main():
    session_label = get_session_label()
    logger.info("Radar başlatılıyor: %s", session_label)

    # API key kontrol
    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Eksik environment değişkenleri: %s", missing)
        sys.exit(1)

    from radar_engine      import run_radar
    from telegram_notifier import send_message, format_radar_summary

    # Radar çalıştır
    results = run_radar(
        max_age_hours=8,
        min_radar_score=50,
        max_tickers=20,
    )

    logger.info("%d fırsat bulundu", len(results))

    # Telegram'a gönder
    message = format_radar_summary(results, title=f"🔭 {session_label}")
    ok      = send_message(message)

    if ok:
        logger.info("Telegram mesajı başarıyla gönderildi.")
    else:
        logger.error("Telegram gönderimi başarısız.")
        sys.exit(1)


if __name__ == "__main__":
    main()
