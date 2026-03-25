# telegram_notifier.py — Temel Telegram Gönderim Modülü
#
# Bu dosya yalnızca temel send_message fonksiyonunu içerir.
# Tüm alarm formatları trigger_alerts.py'de tanımlanmıştır.
# Eski radar/fırsat alarm formatları (format_radar_summary, format_alert)
# kaldırıldı — yeni tetikleyici sistemle değiştirildi.

import os
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Telegram'a mesaj gönder.
    Token ve Chat ID ortam değişkenlerinden (veya Streamlit Secrets'tan) alınır.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials eksik.")
        return False

    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]

    for chunk in chunks:
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token, method="sendMessage"),
                json={
                    "chat_id":                  chat_id,
                    "text":                     chunk,
                    "parse_mode":               parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
            return False

    return True
