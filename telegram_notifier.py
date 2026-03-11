# telegram_notifier.py — Telegram Bot Bildirimleri

import os
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Telegram'a mesaj gönder."""
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials eksik.")
        return False

    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token, method="sendMessage"),
            json={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.error("Telegram gönderim hatası: %s", exc)
        return False


def format_radar_summary(results: list[dict], title: str = "🔭 Sabah Radar Özeti") -> str:
    """Radar sonuçlarını Telegram mesajına dönüştür."""
    if not results:
        return f"{title}\n\n📭 Bugün önemli bir fırsat tespit edilmedi."

    lines = [f"<b>{title}</b>", f"<i>{len(results)} fırsat bulundu</i>", ""]

    for r in results[:10]:  # Max 10 hisse
        ticker       = r["ticker"]
        radar_score  = r["radar_score"]
        haber_etkisi = r["haber_etkisi"]
        surpriz      = r["surpriz_faktoru"]
        neden        = r["neden"]
        tavsiye      = r["tavsiye"]
        price        = r["price"]

        # Emoji
        if radar_score >= 80:   emoji = "🟢"
        elif radar_score >= 65: emoji = "🟡"
        else:                   emoji = "🔵"

        tavsiye_emoji = {"İncele": "👀", "Takibe Al": "📌", "Önemsiz": "💤"}.get(tavsiye, "")

        price_str = f"${price:,.2f}" if price else "N/A"

        lines.append(
            f"{emoji} <b>{ticker}</b> — <b>{radar_score}</b> puan | {price_str}\n"
            f"   📰 Haber: {haber_etkisi} | 💫 Sürpriz: {surpriz}\n"
            f"   💬 {neden[:100]}\n"
            f"   {tavsiye_emoji} <i>{tavsiye}</i>"
        )
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <a href='https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app'>Dashboard'u Aç</a>")

    return "\n".join(lines)


def format_alert(ticker: str, radar_score: float, neden: str, price: float = 0) -> str:
    """Anlık fırsat alarmı mesajı."""
    price_str = f"${price:,.2f}" if price else "N/A"
    return (
        f"🚨 <b>FIRSAT ALARMI: {ticker}</b>\n\n"
        f"📊 Radar Puanı: <b>{radar_score}</b>\n"
        f"💰 Fiyat: {price_str}\n"
        f"💬 {neden}\n\n"
        f"📊 <a href='https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app'>Dashboard'u Aç</a>"
    )
