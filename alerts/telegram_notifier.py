# telegram_notifier.py — Geriye Dönük Uyumluluk Katmanı
#
# YENİ SİSTEMDE: bot.py içindeki send_message_sync() kullanılıyor.
# Bu dosya eski modüllerin (trigger_alerts, trigger_monitor vs.) 
# "from telegram_notifier import send_message" çağrılarını
# yeni bot.py'ye yönlendirmek için burada duruyor.
# Silme — silinirse eski import'lar kırılır.

import os
import logging
import requests

logger = logging.getLogger(__name__)


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Telegram'a mesaj gönder.
    Önce bot.py'nin send_message_sync() fonksiyonunu dener,
    başarısız olursa direkt HTTP isteği yapar (fallback).
    """
    # Yeni sistem: bot.py üzerinden
    try:
        from bot import send_message_sync
        return send_message_sync(text)
    except ImportError:
        pass

    # Fallback: direkt HTTP (bot.py yüklü değilse — GitHub Actions için)
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram credentials eksik.")
        return False

    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            r.raise_for_status()
        except Exception as e:
            logger.error("Telegram hatası: %s", e)
            return False
    return True
