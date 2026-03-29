# bot.py — Telegram Bot: Alarm Kanalı + Strateji Odası
#
# İki farklı Telegram kanalını tek bot üzerinden yönetir:
#   ALARM_CHAT_ID  → Sadece otonom sistem yazar (VIX spike, BTC crash vs.)
#   STRATEJI_CHAT_ID → Sen direktörle birebir konuşursun
#
# Eğer tek kanal kullanmak istersen iki değişkeni aynı chat ID'ye ayarla.

import os
import logging
import asyncio
from datetime import datetime, timezone, timedelta

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# ─── Çevre Değişkenleri ───────────────────────────────────────────────────────

TELEGRAM_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALARM_CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")       # Mevcut alarm kanalın
STRATEJI_CHAT_ID     = os.getenv("TELEGRAM_STRATEJI_CHAT_ID",  # Strateji Odası
                                  os.getenv("TELEGRAM_CHAT_ID", ""))  # Fallback: aynı kanal

# Global application referansı — main.py'den erişim için
_application: Application | None = None


# ─── Bot Başlatma / Durdurma ──────────────────────────────────────────────────

async def start_bot():
    """Bot'u başlat ve handler'ları kaydet."""
    global _application

    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN eksik — bot başlatılamadı.")
        return

    _application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # Handler'ları kaydet
    _application.add_handler(CommandHandler("start",    cmd_start))
    _application.add_handler(CommandHandler("help",     cmd_help))
    _application.add_handler(CommandHandler("portfoy",  cmd_portfoy))
    _application.add_handler(CommandHandler("durum",    cmd_durum))
    _application.add_handler(CommandHandler("onayla",   cmd_onayla))
    _application.add_handler(CommandHandler("reddet",   cmd_reddet))
    _application.add_handler(CommandHandler("tetikle",  cmd_tetikle))

    # Düz metin mesajları → direktöre ilet (sadece Strateji Odası'ndan)
    _application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    await _application.initialize()
    await _application.start()
    await _application.updater.start_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,   # Kapalıyken gelen mesajları atla
    )
    logger.info("Telegram bot polling başladı.")


async def stop_bot():
    """Bot'u düzgünce kapat."""
    global _application
    if _application:
        await _application.updater.stop()
        await _application.stop()
        await _application.shutdown()


# ─── Mesaj Gönderme (Diğer Modüllerden Çağrılır) ────────────────────────────

async def send_alarm(text: str) -> bool:
    """
    Alarm kanalına mesaj gönder.
    trigger_alerts.py bu fonksiyonu kullanacak (eski send_message() yerine).
    """
    if not _application or not ALARM_CHAT_ID:
        return False
    try:
        await _application.bot.send_message(
            chat_id=ALARM_CHAT_ID,
            text=text[:4096],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error("Alarm gönderilemedi: %s", e)
        return False


async def send_strateji(text: str) -> bool:
    """Strateji Odası'na mesaj gönder."""
    if not _application or not STRATEJI_CHAT_ID:
        return False
    try:
        await _application.bot.send_message(
            chat_id=STRATEJI_CHAT_ID,
            text=text[:4096],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error("Strateji mesajı gönderilemedi: %s", e)
        return False


def send_message_sync(text: str, chat_id: str = None) -> bool:
    """
    Senkron bağlamdan (trigger_monitor gibi) Telegram'a mesaj gönderir.
    Mevcut telegram_notifier.send_message() işlevini üstlenir.
    """
    import requests
    target = chat_id or ALARM_CHAT_ID
    if not TELEGRAM_TOKEN or not target:
        return False
    try:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id":   target,
                    "text":      chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Senkron mesaj hatası: %s", e)
        return False


# ─── Komut Handler'ları ────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Bot ilk başlatıldığında karşılama mesajı."""
    await update.message.reply_text(
        "🤖 <b>Strateji Direktörü aktif.</b>\n\n"
        "Portföyünle ilgili her şeyi sorabilirsin — piyasa yorumları, "
        "senaryo analizleri, varlık kararları. Makale veya haber paylaşırsan "
        "birlikte değerlendiririz.\n\n"
        "<b>Komutlar:</b>\n"
        "/portfoy — Anlık portföy durumu\n"
        "/durum — Sistem ve zamanlayıcı durumu\n"
        "/tetikle 3 — Sabah özetini şimdi gönder\n"
        "/onayla — Son direktör kararını onayla\n"
        "/reddet — Son direktör kararını reddet\n"
        "/help — Bu yardım mesajı",
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_portfoy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Anlık portföy özetini göster."""
    await update.message.reply_text("⏳ Portföy yükleniyor...")
    try:
        from portfolio_manager import load_portfolio
        from strategy_data import fetch_usd_try_rate
        import yfinance as yf

        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        usd_try   = fetch_usd_try_rate()

        # Varlık sınıfı bazında topla
        class_data: dict[str, dict] = {}
        labels = {
            "us_equity": "🇺🇸 ABD Hisse",
            "crypto":    "₿ Kripto",
            "commodity": "🥇 Emtia",
            "tefas":     "🇹🇷 TEFAS",
            "cash":      "💵 Nakit",
        }

        for p in portfolio:
            ac   = p.get("asset_class", "us_equity")
            shr  = float(p.get("shares", 0))
            avg  = float(p.get("avg_cost", 0))
            cur  = p.get("currency", "USD")
            cost = shr * avg / usd_try if cur == "TRY" else shr * avg
            if ac not in class_data:
                class_data[ac] = {"cost": 0.0}
            class_data[ac]["cost"] += cost

        total = sum(d["cost"] for d in class_data.values())
        lines = [f"💼 <b>Portföy Durumu</b> — {datetime.now(timezone(timedelta(hours=3))).strftime('%d %b %Y, %H:%M')}",
                 "━" * 28]
        for ac, d in sorted(class_data.items(), key=lambda x: -x[1]["cost"]):
            pct = d["cost"] / total * 100 if total > 0 else 0
            lines.append(f"  {labels.get(ac, ac)}: ${d['cost']:,.0f} (%{pct:.1f})")
        lines.append(f"\n  <b>Toplam: ${total:,.0f}</b>")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Portföy alınamadı: {e}")


async def cmd_durum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Sistem durumunu göster."""
    from main import scheduler
    jobs = scheduler.get_jobs()
    lines = ["⚙️ <b>Sistem Durumu</b>", "━" * 28]
    for j in jobs:
        next_run = j.next_run_time.strftime("%d %b %H:%M") if j.next_run_time else "—"
        lines.append(f"  • {j.name}: <i>sonraki {next_run}</i>")
    lines.append(f"\n✅ {len(jobs)} görev aktif")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_onayla(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Son direktör kararını onayla."""
    await update.message.reply_text(
        "✅ <b>Onay alındı.</b>\n"
        "Kararı uygulamak için ilgili işlem emirlerini gir. "
        "TEFAS için bugün emir ver (T+2 valör), kripto ve ABD hisseleri için anlık işlem yapabilirsin.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_reddet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Son direktör kararını reddet."""
    await update.message.reply_text(
        "❌ <b>Karar reddedildi.</b>\n"
        "Mevcut pozisyonlar korunuyor. Bir sonraki tetikleyici sinyalinde direktör yeniden analiz yapacak.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_tetikle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manuel tetikleme: /tetikle 3"""
    args = ctx.args
    if not args or not args[0].isdigit() or int(args[0]) not in (1, 2, 3):
        await update.message.reply_text(
            "Kullanım: /tetikle <katman>\nÖrnek: /tetikle 3 → sabah özetini şimdi gönder"
        )
        return
    layer = int(args[0])
    await update.message.reply_text(f"⏳ Katman {layer} çalıştırılıyor...")
    try:
        from trigger_monitor import run as run_trigger
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_trigger, layer)
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


# ─── Serbest Metin: Direktöre İlet ────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Strateji Odası'na yazılan her serbest metin mesajını direktöre iletir.
    Direktör portföy bağlamıyla cevap verir.
    """
    # Sadece Strateji Odası'ndan gelen mesajları işle
    chat_id = str(update.effective_chat.id)
    if chat_id != str(STRATEJI_CHAT_ID):
        return  # Alarm kanalından gelen mesajları yoksay

    user_text = update.message.text
    if not user_text or not user_text.strip():
        return

    # "Yazıyor..." göstergesi
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        from chat_director import ask_director
        response = await asyncio.get_event_loop().run_in_executor(
            None, ask_director, user_text
        )
        # Yanıt 4096 karakteri aşabilir, böl
        for chunk in [response[i:i+4000] for i in range(0, len(response), 4000)]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Direktör yanıt hatası: %s", e)
        await update.message.reply_text(
            f"⚠️ Direktör yanıt veremedi: {e}\n"
            "Lütfen tekrar dene."
        )
