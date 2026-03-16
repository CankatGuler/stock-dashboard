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

    # ── 0. Finansal Takvim Bildirimi ──────────────────────────────────────
    # Bugün ve yarın önemli ekonomik veri/event varsa Telegram'a bildir.
    # Pazartesi ise ayrıca haftalık önizleme de gönderilir.
    logger.info("Finansal takvim kontrol ediliyor...")
    try:
        from financial_calendar import (
            get_todays_and_tomorrows_events,
            format_calendar_telegram,
            format_weekly_preview_telegram,
        )
        from portfolio_manager import load_portfolio
        from breakout_scanner  import load_watchlist

        # Portföy + watchlist hisselerini topla
        _cal_tickers = list(dict.fromkeys(
            [p["ticker"] for p in load_portfolio() if float(p.get("shares", 0)) > 0]
            + load_watchlist()
        ))

        # Bugün / yarın olayları
        _cal_events = get_todays_and_tomorrows_events(tickers=_cal_tickers)
        _cal_msg    = format_calendar_telegram(_cal_events, portfolio_tickers=_cal_tickers)
        if _cal_msg:
            ok_cal = send_message(_cal_msg)
            logger.info("Takvim bildirimi gönderildi: %s", ok_cal)
        else:
            logger.info("Takvim: Bugün/yarın kritik olay yok.")

        # Pazartesi ise haftalık önizleme gönder
        from datetime import datetime
        if datetime.now().weekday() == 0:  # 0 = Pazartesi
            _weekly_msg = format_weekly_preview_telegram(tickers=_cal_tickers)
            if _weekly_msg:
                ok_wk = send_message(_weekly_msg)
                logger.info("Haftalık takvim önizlemesi gönderildi: %s", ok_wk)

    except Exception as e:
        logger.warning("Finansal takvim bildirimi başarısız: %s", e)

    # ── 1. 52H Kırılma Alarmı ─────────────────────────────────────────────
    logger.info("52H kırılma taraması başlıyor...")
    breakouts = run_breakout_scan()
    if breakouts:
        breakout_msg = format_breakout_message(breakouts)
        ok_b = send_message(breakout_msg)
        logger.info("52H alarmı gönderildi (%d kırılım): %s", len(breakouts), ok_b)
    else:
        logger.info("52H kırılımı yok.")

    # ── 2. Fiyat Hedefi Snapshot Güncelleme ─────────────────────────────
    logger.info("Fiyat hedefi snapshot güncelleniyor...")
    try:
        from price_target_tracker import update_price_targets
        from breakout_scanner import load_watchlist
        from portfolio_manager import load_portfolio

        _target_tickers = []
        try:
            _target_tickers += [p["ticker"] for p in load_portfolio() if p.get("ticker")]
        except Exception:
            pass
        try:
            _target_tickers += load_watchlist()
        except Exception:
            pass
        _target_tickers = list(dict.fromkeys(_target_tickers))[:40]

        if _target_tickers:
            update_price_targets(_target_tickers)
            logger.info("Fiyat hedefleri guncellendi: %d hisse", len(_target_tickers))
    except Exception as e:
        logger.warning("Fiyat hedefi guncelleme hatasi: %s", e)

    # ── 3. İçeriden Alım/Satım Taraması ─────────────────────────────────
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
