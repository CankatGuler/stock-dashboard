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


def get_session_label() -> str:
    """Manuel çalıştırmada saat kontrolü yok, otomatik etiket döndür."""
    now_utc_hour = datetime.now(timezone.utc).hour
    dst = is_dst_active()

    if dst:
        if now_utc_hour == 12:
            return "🌞 Yaz — Açılış öncesi (ABD 08:00 EDT / TR 15:00)"
        if now_utc_hour == 19:
            return "🌞 Yaz — Kapanış öncesi (ABD 15:00 EDT / TR 22:00)"
    else:
        if now_utc_hour == 13:
            return "❄️ Kış — Açılış öncesi (ABD 08:00 EST / TR 16:00)"
        if now_utc_hour == 20:
            return "❄️ Kış — Kapanış öncesi (ABD 15:00 EST / TR 23:00)"

    # Manuel çalıştırma veya zamanlanmış dışı — etiket oluştur
    tr_hour = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%H:%M")
    return f"🔭 Manuel Radar Taraması (TR {tr_hour})"


def main():
    # Manuel mi yoksa zamanlanmış mı?
    is_manual = os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"

    # Zamanlanmış çalıştırmada saat filtresi uygula
    if not is_manual:
        now_utc_hour = datetime.now(timezone.utc).hour
        dst = is_dst_active()
        valid_hours = {12, 19} if dst else {13, 20}
        if now_utc_hour not in valid_hours:
            logger.info("Bu saat (%d UTC) geçerli değil, atlanıyor.", now_utc_hour)
            sys.exit(0)

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
        min_radar_score=60,
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
