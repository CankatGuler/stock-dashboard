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


def is_dst_active() -> bool:
    """ABD yaz saati aktif mi? (Mart 2. Pazar – Kasım 1. Pazar)"""
    now  = datetime.now(timezone.utc)
    year = now.year
    mar1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    dst_start = mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)
    nov1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return dst_start <= now < dst_end


def should_run_now() -> tuple[bool, str]:
    """
    Yaz/kış saatine göre yanlış cron tetiklemesini filtrele.
    Yaz (EDT, UTC-4): açılış=12 UTC, kapanış=19 UTC
    Kış (EST, UTC-5): açılış=13 UTC, kapanış=20 UTC
    """
    now_utc_hour = datetime.now(timezone.utc).hour
    dst = is_dst_active()

    if dst and now_utc_hour == 12:
        return True, "🌞 Yaz — Açılış öncesi (ABD 08:00 EDT / TR 15:00)"
    if dst and now_utc_hour == 19:
        return True, "🌞 Yaz — Kapanış öncesi (ABD 15:00 EDT / TR 22:00)"
    if not dst and now_utc_hour == 13:
        return True, "❄️ Kış — Açılış öncesi (ABD 08:00 EST / TR 16:00)"
    if not dst and now_utc_hour == 20:
        return True, "❄️ Kış — Kapanış öncesi (ABD 15:00 EST / TR 23:00)"

    logger.info("Bu saat (%d UTC) mevcut mevsim için geçerli değil, atlanıyor.", now_utc_hour)
    return False, ""


def main():
    # Yaz/kış filtresi
    run, session_label = should_run_now()
    if not run:
        sys.exit(0)

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
        max_age_hours=8,       # Son 8 saatin haberleri
        min_radar_score=60,
        max_tickers=20,
    )

    logger.info("%d fırsat bulundu", len(results))

    # Telegram'a gönder
    title   = f"🔭 {session_label}"
    message = format_radar_summary(results, title=title)
    ok      = send_message(message)

    if ok:
        logger.info("Telegram mesajı başarıyla gönderildi.")
    else:
        logger.error("Telegram gönderimi başarısız.")
        sys.exit(1)


if __name__ == "__main__":
    main()
