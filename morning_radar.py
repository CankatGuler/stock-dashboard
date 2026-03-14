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
    from breakout_scanner  import run_breakout_scan, format_breakout_message

    # ── 1. 52H Kırılma Alarmı ─────────────────────────────────────────────
    logger.info("52H kırılma taraması başlıyor...")
    breakouts = run_breakout_scan()
    if breakouts:
        breakout_msg = format_breakout_message(breakouts)
        ok_b = send_message(breakout_msg)
        logger.info("52H alarmı gönderildi (%d kırılım): %s", len(breakouts), ok_b)
    else:
        logger.info("52H kırılımı yok.")

    # ── 2. İçeriden Alım/Satım Taraması ─────────────────────────────────
    logger.info("Insider taraması başlıyor...")
    try:
        from insider_tracker import run_insider_scan, format_insider_telegram
        from breakout_scanner import load_watchlist

        # Portföy + watchlist tickerları
        _insider_tickers = []
        try:
            from portfolio_manager import load_portfolio
            _port = load_portfolio()
            _insider_tickers += [p["ticker"] for p in _port if p.get("ticker")]
        except Exception:
            pass
        _insider_tickers += load_watchlist()
        _insider_tickers = list(dict.fromkeys(_insider_tickers))[:30]  # Max 30

        if _insider_tickers:
            insider_results = run_insider_scan(_insider_tickers, days=7)
            if insider_results:
                insider_msg = format_insider_telegram(insider_results)
                ok_i = send_message(insider_msg)
                logger.info("Insider alarmı gönderildi (%d hisse): %s", len(insider_results), ok_i)
            else:
                logger.info("Insider: Anlamlı sinyal yok.")
    except Exception as e:
        logger.warning("Insider tarama hatası: %s", e)

    # ── 3. Fırsat Radarı ──────────────────────────────────────────────────
    results = run_radar(
        max_age_hours=8,
        min_radar_score=50,
        max_tickers=20,
    )

    logger.info("%d fırsat bulundu", len(results))

    message = format_radar_summary(results, title=f"🔭 {session_label}")
    ok      = send_message(message)

    if ok:
        logger.info("Radar mesajı başarıyla gönderildi.")
    else:
        logger.error("Radar gönderimi başarısız.")
        sys.exit(1)


if __name__ == "__main__":
    main()
