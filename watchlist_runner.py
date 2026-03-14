# watchlist_runner.py — İki Fazlı Watchlist Analiz Sistemi
#
# FAZ 1 — 11:00 TR (08:00 UTC): Erken uyarı, sadece T1+T4, Claude YOK
# FAZ 2 — 23:30 TR (20:30 UTC): Tam analiz, 6 tetikleyici, Claude AKTİF
#
# PHASE=1 python watchlist_runner.py  → Faz 1
# PHASE=2 python watchlist_runner.py  → Faz 2

import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_phase1():
    logger.info("FAZ 1 — Pre-market erken uyarı başlatılıyor...")
    from watchlist_analyzer import run_phase1_scan, format_phase1_telegram
    from telegram_notifier  import send_message

    result = run_phase1_scan()
    logger.info("Faz 1: %d alarm / %d hisse", len(result["alerts"]), result["total"])

    msg = format_phase1_telegram(result)
    ok  = send_message(msg)
    if ok:
        logger.info("Faz 1 Telegram gönderildi.")
    else:
        logger.error("Faz 1 Telegram gönderilemedi.")
        sys.exit(1)


def run_phase2():
    logger.info("FAZ 2 — Kapanış sonrası tam analiz başlatılıyor...")
    from watchlist_analyzer import run_phase2_analysis, format_phase2_telegram
    from telegram_notifier  import send_message

    result   = run_phase2_analysis()
    messages = format_phase2_telegram(result)
    logger.info("Faz 2: %d/%d tetiklendi", result["analyzed"], result["total"])

    for i, msg in enumerate(messages, 1):
        ok = send_message(msg)
        logger.info("Mesaj %d/%d: %s", i, len(messages), "OK" if ok else "HATA")


def main():
    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error("Eksik env: %s", missing)
        sys.exit(1)

    phase = os.getenv("PHASE", "auto")

    if phase == "auto":
        hour_utc = datetime.now(timezone.utc).hour
        if 7 <= hour_utc <= 9:
            phase = "1"
        elif 20 <= hour_utc <= 22:
            phase = "2"
        else:
            logger.info("Çalışma saati dışında (UTC %d). Çıkılıyor.", hour_utc)
            return

    if phase == "1":
        run_phase1()
    elif phase == "2":
        run_phase2()
    else:
        logger.error("Geçersiz PHASE: %s", phase)
        sys.exit(1)


if __name__ == "__main__":
    main()
