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
    _application.add_handler(CommandHandler("detay",    cmd_portfoy_detay))
    _application.add_handler(CommandHandler("ekle",     cmd_portfoy_ekle))
    _application.add_handler(CommandHandler("sil",      cmd_portfoy_sil))
    _application.add_handler(CommandHandler("azalt",    cmd_portfoy_azalt))
    _application.add_handler(CommandHandler("guncelle", cmd_portfoy_guncelle))
    _application.add_handler(CommandHandler("makro",    cmd_makro))
    _application.add_handler(CommandHandler("hisse",    cmd_hisse))
    _application.add_handler(CommandHandler("fon",      cmd_fon))
    _application.add_handler(CommandHandler("haber",    cmd_haber))
    _application.add_handler(CommandHandler("tarama",   cmd_tarama))
    _application.add_handler(CommandHandler("durum",    cmd_durum))
    _application.add_handler(CommandHandler("onayla",   cmd_onayla))
    _application.add_handler(CommandHandler("reddet",   cmd_reddet))
    _application.add_handler(CommandHandler("tetikle",  cmd_tetikle))

    # Düz metin mesajları → direktöre ilet (sadece Strateji Odası'ndan)
    _application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    # Fotoğraf ve görsel belge mesajları
    _application.add_handler(
        MessageHandler(filters.PHOTO, handle_message)
    )
    _application.add_handler(
        MessageHandler(filters.Document.IMAGE, handle_message)
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
        # Direktörün geçmişine ekle — bağlam için
        try:
            from chat_director import inject_system_message
            inject_system_message(text, label="OTOMATİK ALARM")
        except Exception:
            pass
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
        "<b>🔍 Analiz Komutları:</b>\n"
        "/makro — Tüm makro göstergeler (VIX, faiz, emtia, endeksler)\n"
        "/makro faiz — Faiz & yield curve & kredi\n"
        "/makro sektor — XLF, XLE, XLK, XLV sektör ETF'leri\n"
        "/makro turkiye — USD/TRY, BIST, TUR ETF\n"
        "/hisse AAPL — FMP ile temel analiz + F/K + direktör yorumu\n"
        "/fon IIH — TEFAS fon güncel fiyatı\n"
        "/haber — Portföy + makro haber brifingı\n"
        "/haber AAPL — Tek hisse haberleri\n"
        "/tarama — Portföy sağlık taraması\n\n"
        "<b>📊 Portföy Komutları:</b>\n"
        "/portfoy — Anlık portföy özeti\n"
        "/detay — Tüm pozisyonlar detaylı\n"
        "/detay crypto — Sadece kripto\n"
        "/ekle AVGO 5 1200 us_equity — Yeni pozisyon ekle\n"
        "/azalt AVGO 5 — 5 hisse sat (kısmi)\n"
        "/sil AVGO — Tüm pozisyonu sil\n"
        "/guncelle AVGO 3 1350 — Adet/maliyet düzelt\n\n"
        "<b>⚙️ Sistem Komutları:</b>\n"
        "/durum — Zamanlayıcı ve sistem durumu\n"
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
        from core.database import SessionLocal
        from core import crud
        import yfinance as yf
        from strategy_data import fetch_usd_try_rate

        usd_try = fetch_usd_try_rate()

        def _get_summary():
            with SessionLocal() as db:
                return crud.get_portfolio_summary(db)

        loop    = asyncio.get_running_loop()
        summary = await loop.run_in_executor(None, _get_summary)

        positions = [p for p in summary["positions"] if p["is_open"]]
        if not positions:
            await update.message.reply_text("Portföy boş.")
            return

        labels = {
            "us_equity": "🇺🇸 ABD Hisse",
            "crypto":    "₿ Kripto",
            "commodity": "🥇 Emtia",
            "tefas":     "🇹🇷 TEFAS",
            "cash":      "💵 Nakit",
        }

        # Varlık sınıfı bazında grupla
        class_data: dict = {}
        for p in positions:
            ac = p["asset_class"]
            if ac not in class_data:
                class_data[ac] = {"cost_usd": 0.0, "realized_pnl": 0.0}
            class_data[ac]["cost_usd"]     += p["cost_usd"]
            class_data[ac]["realized_pnl"] += p["realized_pnl_usd"]

        total_cost = summary["total_cost_usd"]
        total_rpnl = summary["total_realized_pnl_usd"]

        tr_now = datetime.now(timezone(timedelta(hours=3))).strftime("%d %b %Y, %H:%M")
        lines  = [
            f"💼 <b>Portföy Durumu</b> — {tr_now}",
            "━" * 28,
        ]
        for ac, d in sorted(class_data.items(), key=lambda x: -x[1]["cost_usd"]):
            pct = d["cost_usd"] / total_cost * 100 if total_cost > 0 else 0
            lines.append(f"  {labels.get(ac, ac)}: ${d['cost_usd']:,.0f} (%{pct:.1f})")

        lines.append(f"\n  <b>Yatırılan Toplam: ${total_cost:,.0f}</b>")
        if total_rpnl != 0:
            rpnl_sign = "+" if total_rpnl >= 0 else ""
            lines.append(f"  Gerçekleşen P&L:  <b>{rpnl_sign}${total_rpnl:,.0f}</b>")
        lines.append(f"  Açık Pozisyon:    {summary['open_positions']} varlık")

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


async def cmd_portfoy_ekle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Portföye pozisyon ekle.
    Kullanım: /ekle <TICKER> <ADET> <MALIYET> <SINIF>
    Sınıf: us_equity | crypto | commodity | tefas
    Örnek: /ekle AVGO 5 1200 us_equity
    Örnek: /ekle BTC-USD 0.1 85000 crypto
    Örnek: /ekle IIH 10000 3.5 tefas
    """
    args = ctx.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "📝 <b>Kullanım:</b>\n"
            "/ekle TICKER ADET MALİYET [SINIF]\n\n"
            "<b>Örnekler:</b>\n"
            "/ekle AVGO 5 1200 us_equity\n"
            "/ekle BTC-USD 0.1 85000 crypto\n"
            "/ekle IIH 10000 3.5 tefas\n"
            "/ekle ALTIN_GRAM_TRY 100 3200 commodity\n\n"
            "<b>Sınıflar:</b> us_equity | crypto | commodity | tefas",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        ticker   = args[0].upper()
        quantity = float(args[1])
        price    = float(args[2])
        ac       = args[3].lower() if len(args) > 3 else "us_equity"

        valid_classes = ("us_equity", "crypto", "commodity", "tefas", "cash")
        if ac not in valid_classes:
            await update.message.reply_text(
                f"❌ Geçersiz sınıf: <b>{ac}</b>\n"
                f"Geçerli sınıflar: {' | '.join(valid_classes)}",
                parse_mode=ParseMode.HTML,
            )
            return

        currency = "TRY" if ac == "tefas" or "TRY" in ticker else "USD"

        await update.message.reply_text(f"⏳ {ticker} ekleniyor...")

        from strategy_data import fetch_usd_try_rate
        from core.database import SessionLocal
        from core import crud

        usd_try = fetch_usd_try_rate()
        loop    = asyncio.get_running_loop()

        def _buy():
            with SessionLocal() as db:
                txn = crud.buy_asset(
                    db           = db,
                    symbol       = ticker,
                    quantity     = quantity,
                    price        = price,
                    currency     = currency,
                    usd_try_rate = usd_try if currency == "TRY" else 1.0,
                    commission   = 0.0,
                    asset_class  = ac,
                )
                crud.log_event(
                    db         = db,
                    source     = "TELEGRAM_BOT",
                    event_type = "PORTFOLIO_BUY",
                    message    = f"ALIM: {quantity:g}x {ticker} @ {price} {currency} ({ac})",
                    severity   = "INFO",
                    asset_symbol = ticker,
                    metric_value = price,
                )
                return txn

        await loop.run_in_executor(None, _buy)

        cur_sym    = "₺" if currency == "TRY" else "$"
        total_cost = quantity * price
        await update.message.reply_text(
            f"✅ <b>{ticker}</b> portföye eklendi\n"
            f"  Adet:    {quantity:,g}\n"
            f"  Fiyat:   {cur_sym}{price:,.4f}\n"
            f"  Toplam:  {cur_sym}{total_cost:,.2f}\n"
            f"  Sınıf:   {ac}",
            parse_mode=ParseMode.HTML,
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ Hata: {e}\nÖrnek: /ekle AVGO 5 1200 us_equity")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_portfoy_sil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Portföyden pozisyon sil — kar/zarar hesabıyla.
    Kullanım: /sil <TICKER> [SATIS_FIYATI]
    Örnek: /sil ETH-USD 2500
    Örnek: /sil ETH-USD  (fiyat belirtilmezse anlık fiyat kullanılır)
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "📝 <b>Kullanım:</b>\n"
            "/sil TICKER [SATIS_FIYATI]\n\n"
            "<b>Örnekler:</b>\n"
            "/sil ETH-USD 2500 — ETH'yi 2500$'dan sat\n"
            "/sil ETH-USD — anlık fiyattan sat\n"
            "/sil AVGO — AVGO'yu anlık fiyattan sat",
            parse_mode=ParseMode.HTML,
        )
        return

    ticker      = args[0].upper()
    satis_fiyat = float(args[1]) if len(args) >= 2 else None

    await update.message.reply_text(f"⏳ {ticker} hesaplanıyor...")

    try:
        import yfinance as yf
        from core.database import SessionLocal
        from core import crud

        def _get_pos():
            with SessionLocal() as db:
                summary = crud.get_portfolio_summary(db)
                return next((p for p in summary["positions"]
                             if p["symbol"] == ticker and p["is_open"]), None)

        loop   = asyncio.get_running_loop()
        mevcut = await loop.run_in_executor(None, _get_pos)

        if not mevcut:
            await update.message.reply_text(
                f"❌ <b>{ticker}</b> portföyde bulunamadı.", parse_mode=ParseMode.HTML
            )
            return

        adet     = float(mevcut["quantity"])
        avg_cost = float(mevcut["average_cost_usd"])
        currency = mevcut["currency"]

        # Satış fiyatı belirtilmediyse anlık fiyat çek
        if satis_fiyat is None:
            try:
                loop = asyncio.get_running_loop()
                def _get_price():
                    h = yf.Ticker(ticker).history(period="2d")
                    return float(h["Close"].iloc[-1]) if not h.empty else None
                satis_fiyat = await loop.run_in_executor(None, _get_price)
            except Exception:
                satis_fiyat = None

        if satis_fiyat is None:
            await update.message.reply_text(
                f"⚠️ {ticker} için anlık fiyat alınamadı.\n"
                f"Lütfen fiyatı manuel gir: /sil {ticker} FIYAT",
                parse_mode=ParseMode.HTML,
            )
            return

        # Kar/Zarar hesapla
        from strategy_data import fetch_usd_try_rate
        usd_try  = fetch_usd_try_rate()

        maliyet_toplam  = adet * avg_cost
        satis_toplam    = adet * satis_fiyat
        kar_zarar       = satis_toplam - maliyet_toplam
        kar_zarar_pct   = (kar_zarar / maliyet_toplam * 100) if maliyet_toplam > 0 else 0
        kar_zarar_tl    = kar_zarar * usd_try

        kar_emoji = "🟢" if kar_zarar >= 0 else "🔴"
        kar_sign  = "+" if kar_zarar >= 0 else ""

        # Supabase'e satış yaz
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()

        def _full_sell():
            with SessionLocal() as db:
                txn, pnl = crud.sell_asset(
                    db           = db,
                    symbol       = ticker,
                    quantity     = adet,
                    price        = satis_fiyat,
                    currency     = currency,
                    usd_try_rate = usd_try if currency == "TRY" else 1.0,
                )
                crud.log_event(
                    db           = db,
                    source       = "TELEGRAM_BOT",
                    event_type   = "PORTFOLIO_SELL",
                    message      = f"TAM SATIŞ: {adet:g}x {ticker} @ {satis_fiyat} | P&L: {pnl:+.2f} USD",
                    severity     = "INFO",
                    asset_symbol = ticker,
                    metric_value = pnl,
                )
                return pnl

        realized_pnl = await loop.run_in_executor(None, _full_sell)

        maliyet_toplam = adet * avg_cost
        satis_toplam   = adet * satis_fiyat
        kar_zarar_tl   = realized_pnl * usd_try
        kar_emoji = "🟢" if realized_pnl >= 0 else "🔴"
        kar_sign  = "+" if realized_pnl >= 0 else ""
        kar_pct   = (realized_pnl / maliyet_toplam * 100) if maliyet_toplam > 0 else 0

        mesaj = (
            f"{kar_emoji} <b>{ticker} — TAM SATIŞ</b>\n\n"
            f"📊 <b>Satış Özeti:</b>\n"
            f"  Adet:          {adet:,g}\n"
            f"  Alış fiyatı:   ${avg_cost:,.2f}\n"
            f"  Satış fiyatı:  ${satis_fiyat:,.2f}\n\n"
            f"💰 <b>Gerçekleşen Kar/Zarar:</b>\n"
            f"  <b>{kar_sign}${realized_pnl:,.2f} USD ({kar_sign}{kar_pct:.1f}%)</b>\n"
            f"  TL karşılığı: {kar_sign}₺{abs(kar_zarar_tl):,.0f}\n\n"
            f"✅ {ticker} portföyden çıkarıldı."
        )
        await update.message.reply_text(mesaj, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_portfoy_guncelle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Mevcut pozisyonu güncelle (adet ve maliyet).
    Kullanım: /guncelle <TICKER> <YENİ_ADET> <YENİ_MALİYET>
    Örnek: /guncelle AVGO 3 1350
    """
    args = ctx.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Kullanım: /guncelle TICKER YENİ_ADET YENİ_MALİYET\n"
            "Örnek: /guncelle AVGO 3 1350"
        )
        return

    try:
        ticker   = args[0].upper()
        shares   = float(args[1])
        avg_cost = float(args[2])

        await update.message.reply_text(f"⏳ {ticker} güncelleniyor...")

        # Guncelleme: mevcut pozisyonu sil, yeni fiyatla tekrar ekle
        from core.database import SessionLocal
        from core import crud
        from strategy_data import fetch_usd_try_rate

        usd_try = fetch_usd_try_rate()

        def _update():
            with SessionLocal() as db:
                pos = db.query(crud.Portfolio if False else __import__("core.models", fromlist=["Portfolio"]).Portfolio).filter_by(asset_symbol=ticker).first()
                if pos:
                    pos.total_quantity   = shares
                    pos.average_cost     = avg_cost
                    pos.average_cost_usd = avg_cost  # USD varsayım
                    from datetime import datetime, timezone
                    pos.last_updated = datetime.now(timezone.utc)
                    db.commit()
                crud.log_event(
                    db=db, source="TELEGRAM_BOT", event_type="PORTFOLIO_UPDATE",
                    message=f"GÜNCELLEME: {ticker} → {shares:g} adet @ {avg_cost}",
                    severity="INFO", asset_symbol=ticker,
                )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _update)

        await update.message.reply_text(
            f"✅ <b>{ticker}</b> güncellendi\n"
            f"  Yeni adet: {shares:,g}\n"
            f"  Yeni maliyet: {avg_cost:,.4f}",
            parse_mode=ParseMode.HTML,
        )
    except ValueError:
        await update.message.reply_text("❌ Sayı formatı hatalı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_portfoy_detay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Portföyü anlık değerlerle detaylı göster.
    Kullanım: /detay [sinif]
    Örnek: /detay crypto
    """
    args      = ctx.args
    filtre_ac = args[0].lower() if args else None

    await update.message.reply_text("⏳ Anlık fiyatlar çekiliyor...")

    try:
        from core.database import SessionLocal
        from core import crud
        from strategy_data import fetch_usd_try_rate
        import yfinance as yf

        usd_try = fetch_usd_try_rate()

        def _get_positions():
            with SessionLocal() as db:
                s = crud.get_portfolio_summary(db)
                return [p for p in s["positions"] if p["is_open"]]

        loop      = asyncio.get_running_loop()
        raw_pos   = await loop.run_in_executor(None, _get_positions)

        # Supabase formatını eski formata çevir (detay kodu için)
        portfolio = [
            {
                "ticker":      p["symbol"],
                "shares":      p["quantity"],
                "avg_cost":    p["average_cost_usd"],
                "currency":    p["currency"],
                "asset_class": p["asset_class"],
            }
            for p in raw_pos
        ]

        # Filtre
        if filtre_ac:
            if filtre_ac == "us_equity":
                portfolio = [p for p in portfolio
                             if p.get("asset_class", "us_equity") in
                             ("us_equity", "other", "", None)]
            else:
                portfolio = [p for p in portfolio
                             if p.get("asset_class") == filtre_ac]

        if not portfolio:
            await update.message.reply_text("Portföy boş veya filtre eşleşmedi.")
            return

        # Altın fiyatını önceden çek
        gold_usd = 0.0
        try:
            h = yf.Ticker("GC=F").history(period="2d")
            if not h.empty:
                gold_usd = float(h["Close"].iloc[-1])
        except Exception:
            pass

        labels = {
            "us_equity": "🇺🇸 ABD Hisse",
            "crypto":    "₿ Kripto",
            "commodity": "🥇 Emtia",
            "tefas":     "🇹🇷 TEFAS",
            "other":     "🇺🇸 ABD Hisse",
            "":          "🇺🇸 ABD Hisse",
        }

        # Sınıfa göre grupla
        groups: dict[str, list] = {}
        for p in portfolio:
            ac = p.get("asset_class", "us_equity") or "us_equity"
            if ac in ("other", ""):
                ac = "us_equity"
            groups.setdefault(ac, []).append(p)

        lines = ["💼 <b>Portföy Detayı</b>", ""]

        ac_order = ["tefas", "us_equity", "crypto", "commodity", "cash"]
        sorted_groups = sorted(groups.items(),
                               key=lambda x: ac_order.index(x[0])
                               if x[0] in ac_order else 99)

        for ac, positions in sorted_groups:
            ac_cur_total  = 0.0
            ac_cost_total = 0.0
            pos_lines     = []

            for p in positions:
                tk   = p.get("ticker", "?")
                shr  = float(p.get("shares", 0))
                avg  = float(p.get("avg_cost", 0))
                cur  = p.get("currency", "USD")

                # Maliyet (USD)
                cost_usd = shr * avg / usd_try if cur == "TRY" else shr * avg

                # Anlık fiyat çek
                live_price = 0.0
                try:
                    if tk in ("ALTIN_GRAM_TRY", "XAUTRY=X") and gold_usd > 0:
                        live_price = gold_usd * usd_try / 31.1035  # TL/gram
                        cur_val_usd = shr * live_price / usd_try
                    elif ac == "tefas":
                        # TEFAS için fetch_tefas_fund kullan
                        from data.turkey_fetcher import fetch_tefas_fund
                        fd = fetch_tefas_fund(tk)
                        if fd and fd.get("price", 0) > 0:
                            live_price  = float(fd["price"])
                            cur_val_usd = shr * live_price / usd_try
                        else:
                            cur_val_usd = cost_usd
                    else:
                        h = yf.Ticker(tk).history(period="2d")
                        if not h.empty:
                            live_price  = float(h["Close"].iloc[-1])
                            cur_val_usd = shr * live_price / usd_try if cur == "TRY" else shr * live_price
                        else:
                            cur_val_usd = cost_usd
                except Exception:
                    cur_val_usd = cost_usd

                pnl     = cur_val_usd - cost_usd
                pnl_pct = pnl / cost_usd * 100 if cost_usd > 0 else 0
                pnl_e   = "🟢" if pnl >= 0 else "🔴"

                ac_cur_total  += cur_val_usd
                ac_cost_total += cost_usd

                # Fiyat formatı
                if cur == "TRY" and live_price > 0:
                    price_str = f"₺{live_price:,.4f}"
                elif live_price > 0:
                    price_str = f"${live_price:,.2f}"
                else:
                    price_str = "—"

                pos_lines.append(
                    f"  • <b>{tk}</b>: {shr:,g} × {price_str} = "
                    f"${cur_val_usd:,.0f} "
                    f"{pnl_e} ({pnl_pct:+.1f}%)"
                )

            # Sınıf başlığı — toplam + K/Z
            ac_pnl     = ac_cur_total - ac_cost_total
            ac_pnl_pct = ac_pnl / ac_cost_total * 100 if ac_cost_total > 0 else 0
            ac_e       = "🟢" if ac_pnl >= 0 else "🔴"
            lines.append(
                f"<b>{labels.get(ac, ac)}</b> — "
                f"${ac_cur_total:,.0f} "
                f"{ac_e} ({ac_pnl_pct:+.1f}%)"
            )
            lines.extend(pos_lines)
            lines.append("")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_portfoy_azalt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Pozisyonu kısmen azalt — kar/zarar hesabıyla.
    Kullanım: /azalt <TICKER> <SATILAN_ADET> [SATIS_FIYATI]
    Örnek: /azalt ETH-USD 1.5 2500
    """
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "📝 <b>Kullanım:</b>\n"
            "/azalt TICKER SATILAN_ADET [SATIS_FIYATI]\n\n"
            "<b>Örnekler:</b>\n"
            "/azalt ETH-USD 1.5 2500 — 1.5 ETH satış 2500$\n"
            "/azalt ETH-USD 1.5 — anlık fiyattan sat\n"
            "/azalt AVGO 5 185 — 5 AVGO satış 185$\n\n"
            "Tüm pozisyonu satmak için: /sil TICKER [FIYAT]",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        import yfinance as yf
        from core.database import SessionLocal
        from core import crud

        ticker       = args[0].upper()
        satilan_adet = float(args[1])
        satis_fiyat  = float(args[2]) if len(args) >= 3 else None

        def _get_pos():
            with SessionLocal() as db:
                s = crud.get_portfolio_summary(db)
                return next((p for p in s["positions"]
                             if p["symbol"] == ticker and p["is_open"]), None)

        loop   = asyncio.get_running_loop()
        mevcut = await loop.run_in_executor(None, _get_pos)

        if not mevcut:
            await update.message.reply_text(
                f"❌ <b>{ticker}</b> portföyde bulunamadı.", parse_mode=ParseMode.HTML
            )
            return

        mevcut_adet = float(mevcut["quantity"])
        avg_cost    = float(mevcut["average_cost_usd"])

        if satilan_adet >= mevcut_adet:
            await update.message.reply_text(
                f"⚠️ Satmak istediğin adet ({satilan_adet:,g}) mevcut adetten "
                f"({mevcut_adet:,g}) fazla veya eşit.\n"
                f"Tüm pozisyonu satmak için: /sil {ticker} [FIYAT]",
                parse_mode=ParseMode.HTML,
            )
            return

        await update.message.reply_text(f"⏳ {ticker} hesaplanıyor...")

        if satis_fiyat is None:
            try:
                loop = asyncio.get_running_loop()
                def _get_price():
                    h = yf.Ticker(ticker).history(period="2d")
                    return float(h["Close"].iloc[-1]) if not h.empty else None
                satis_fiyat = await loop.run_in_executor(None, _get_price)
            except Exception:
                satis_fiyat = None

        if satis_fiyat is None:
            await update.message.reply_text(
                f"⚠️ {ticker} için anlık fiyat alınamadı.\n"
                f"Manuel gir: /azalt {ticker} {satilan_adet} FIYAT",
                parse_mode=ParseMode.HTML,
            )
            return

        from strategy_data import fetch_usd_try_rate
        from core.database import SessionLocal
        from core import crud

        usd_try = fetch_usd_try_rate()
        currency = mevcut.get("currency", "USD")

        def _sell():
            with SessionLocal() as db:
                txn, pnl = crud.sell_asset(
                    db           = db,
                    symbol       = ticker,
                    quantity     = satilan_adet,
                    price        = satis_fiyat,
                    currency     = currency,
                    usd_try_rate = usd_try if currency == "TRY" else 1.0,
                    commission   = 0.0,
                )
                crud.log_event(
                    db           = db,
                    source       = "TELEGRAM_BOT",
                    event_type   = "PORTFOLIO_SELL",
                    message      = (
                        f"SATIŞ: {satilan_adet:g}x {ticker} @ {satis_fiyat} {currency} | "
                        f"P&L: {pnl:+.2f} USD"
                    ),
                    severity     = "INFO",
                    asset_symbol = ticker,
                    metric_value = pnl,
                )
                return txn, pnl

        loop = asyncio.get_running_loop()
        txn, realized_pnl = await loop.run_in_executor(None, _sell)

        # Portföyden kalan pozisyonu hesapla (UI için)
        yeni_adet     = mevcut_adet - satilan_adet
        maliyet_satis = satilan_adet * avg_cost
        satis_tutari  = satilan_adet * satis_fiyat
        kar_zarar_tl  = realized_pnl * usd_try

        kar_emoji = "🟢" if realized_pnl >= 0 else "🔴"
        kar_sign  = "+" if realized_pnl >= 0 else ""
        kar_pct   = (realized_pnl / (maliyet_satis / (usd_try if currency=="TRY" else 1)) * 100) if maliyet_satis > 0 else 0

        mesaj = (
            f"{kar_emoji} <b>{ticker} — KISMİ SATIŞ</b>\n\n"
            f"📊 <b>Satış Özeti:</b>\n"
            f"  Satılan adet:  {satilan_adet:,g}\n"
            f"  Alış fiyatı:   ${avg_cost:,.2f}\n"
            f"  Satış fiyatı:  ${satis_fiyat:,.2f}\n\n"
            f"💰 <b>Gerçekleşen Kar/Zarar:</b>\n"
            f"  <b>{kar_sign}${realized_pnl:,.2f} USD ({kar_sign}{kar_pct:.1f}%)</b>\n"
            f"  TL karşılığı: {kar_sign}₺{abs(kar_zarar_tl):,.0f}\n\n"
            f"📦 <b>Kalan:</b> {yeni_adet:,g} adet @ ${avg_cost:,.2f}"
        )
        await update.message.reply_text(mesaj, parse_mode=ParseMode.HTML)

    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_makro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Makro göstergeleri — VIX, yield curve, DXY, altın, petrol, bakır, endeksler.
    Kullanım: /makro
    Opsiyonel filtre: /makro faiz | /makro emtia | /makro piyasa
    """
    args    = ctx.args
    filtre  = args[0].lower() if args else None

    await update.message.reply_text("⏳ Makro veriler çekiliyor...")

    try:
        from data.macro_dashboard import fetch_macro_data

        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, fetch_macro_data)

        if not data:
            await update.message.reply_text("❌ Makro veri alınamadı.")
            return

        # Sinyal → emoji
        sig_emoji = {"green": "🟢", "amber": "🟡", "red": "🔴", "neutral": "⚪"}

        # Grup etiketleri
        grup_labels = {
            "fear":      "😨 Volatilite & Korku",
            "rates":     "📊 Faiz & Tahvil",
            "credit":    "💳 Kredi Piyasası",
            "fx":        "💵 Döviz",
            "commodity": "🥇 Emtia",
            "market":    "📈 Endeksler",
            "sector":    "🏭 Sektör ETF'leri",
            "turkey":    "🇹🇷 Türkiye",
        }

        # Filtre → grup eşlemesi
        filtre_map = {
            "faiz":    ["rates", "credit"],
            "emtia":   ["commodity"],
            "piyasa":  ["market"],
            "sektor":  ["sector"],
            "doviz":   ["fx"],
            "turkiye": ["turkey"],
            "korku":   ["fear"],
            "kredi":   ["credit"],
        }

        aktif_gruplar = filtre_map.get(filtre) if filtre else None

        # Gruplara ayır
        gruplar: dict[str, list] = {}
        for key, ind in data.items():
            grp = ind.group
            if aktif_gruplar and grp not in aktif_gruplar:
                continue
            gruplar.setdefault(grp, []).append(ind)

        if not gruplar:
            await update.message.reply_text(
                f"❌ '{filtre}' filtresi için veri bulunamadı.\n"
                "Geçerli filtreler: faiz | emtia | piyasa | doviz | turkiye | korku"
            )
            return

        # Yield curve özel hesap
        yc_text = ""
        if "TNX" in data and "IRX" in data:
            spread = round(data["TNX"].value - data["IRX"].value, 2)
            if spread < 0:
                yc_emoji = "🔴"
                yc_yorum = "İnvert (resesyon sinyali)"
            elif spread < 0.5:
                yc_emoji = "🟡"
                yc_yorum = "Düz eğri (dikkatli)"
            else:
                yc_emoji = "🟢"
                yc_yorum = "Normal (sağlıklı)"
            yc_text = (
                f"\n📐 <b>Yield Curve</b>\n"
                f"  10Y - 3M: <b>{spread:+.2f}%</b>  {yc_emoji} {yc_yorum}\n"
            )

        from datetime import datetime, timezone, timedelta
        tr_now = (datetime.now(timezone.utc) +
                  timedelta(hours=3)).strftime("%d %b %Y, %H:%M")

        lines = [
            f"🌍 <b>Makro Göstergeler</b>",
            f"{'━' * 28}",
            f"📅 {tr_now}",
        ]

        grup_sirasi = ["fear", "rates", "credit", "fx", "commodity", "market", "sector", "turkey"]
        for grp in grup_sirasi:
            if grp not in gruplar:
                continue
            lines.append(f"\n<b>{grup_labels.get(grp, grp)}</b>")
            for ind in gruplar[grp]:
                emoji   = sig_emoji.get(ind.signal, "⚪")
                chg_str = f"({ind.change_pct:+.2f}%)" if ind.change_pct else ""
                val_str = (
                    f"%{ind.value:.2f}" if ind.unit == "%" else
                    f"${ind.value:,.2f}" if ind.unit == "$" else
                    f"{ind.value:,.2f}"
                )
                note = f"\n    <i>{ind.note}</i>" if ind.note else ""
                lines.append(
                    f"  {emoji} <b>{ind.label}</b>: {val_str} {chg_str}{note}"
                )

        if yc_text and (not aktif_gruplar or "rates" in aktif_gruplar):
            lines.append(yc_text)

        lines += [
            f"\n{'━' * 28}",
            "Filtreler: /makro faiz | emtia | piyasa | sektor | doviz | turkiye | korku | kredi",
        ]

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Makro veri hatası: {e}")


async def cmd_tarama(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Haftalık hisse taramasını şimdi çalıştır.
    Kullanım: /tarama
    """
    await update.message.reply_text("⏳ Hisse taraması yapılıyor...")
    try:
        from data.portfolio_scanner import scan_portfolio
        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, scan_portfolio)
        if result:
            for chunk in [result[i:i+4000] for i in range(0, len(result), 4000)]:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("Portföyde US hisse bulunamadı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Tarama hatası: {e}")


async def cmd_hisse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Hisse temel analizi — FMP API ile F/K, piyasa değeri, sektör + direktör yorumu.
    Kullanım: /hisse <TICKER>
    Örnek: /hisse AAPL
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Kullanım: /hisse TICKER\n"
            "Örnek: /hisse AAPL\n"
            "Örnek: /hisse PLTR"
        )
        return

    ticker = args[0].upper()
    await update.message.reply_text(f"⏳ {ticker} analiz ediliyor...")

    try:
        from data.fmp_client import get_full_analysis
        from chat_director import _build_portfolio_context, ask_director
        from strategy_data import fetch_usd_try_rate

        loop   = asyncio.get_running_loop()
        data   = await loop.run_in_executor(None, get_full_analysis, ticker)
        usd_try = fetch_usd_try_rate()

        if not data:
            # FMP başarısız — yfinance ile yedek
            from data.stock_analyzer import analyze_ticker
            port_ctx = _build_portfolio_context(usd_try)
            result   = await loop.run_in_executor(None, analyze_ticker, ticker, port_ctx[:300])
            for chunk in [result[i:i+4000] for i in range(0, len(result), 4000)]:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
            return

        # ── FMP verisi başarıyla geldi ────────────────────────────────────
        price      = data.get("price", 0)
        change_pct = data.get("change_pct", 0)
        pe         = data.get("pe_ratio")
        mktcap     = data.get("market_cap", 0)
        sector     = data.get("sector", "")
        name       = data.get("name", ticker)
        beta       = data.get("beta")
        pb         = data.get("price_to_book")
        roe        = data.get("roe")
        w52_high   = data.get("52w_high")
        w52_low    = data.get("52w_low")

        # Piyasa değeri formatı
        if mktcap >= 1_000_000_000_000:
            mktcap_str = f"${mktcap/1e12:.1f}T"
        elif mktcap >= 1_000_000_000:
            mktcap_str = f"${mktcap/1e9:.1f}B"
        else:
            mktcap_str = f"${mktcap/1e6:.0f}M"

        chg_emoji = "🟢" if change_pct >= 0 else "🔴"
        chg_sign  = "+" if change_pct >= 0 else ""

        lines = [
            f"📊 <b>{name} ({ticker})</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Fiyat:</b> ${price:,.2f}  {chg_emoji} {chg_sign}{change_pct:.2f}%",
            f"🏢 <b>Sektör:</b> {sector}",
            f"💰 <b>Piyasa Değeri:</b> {mktcap_str}",
        ]
        if pe:
            lines.append(f"📈 <b>F/K Oranı:</b> {pe:.1f}x")
        if pb:
            lines.append(f"📚 <b>F/DD:</b> {pb:.1f}x")
        if roe:
            lines.append(f"💹 <b>ROE:</b> %{roe*100:.1f}")
        if beta:
            lines.append(f"⚡ <b>Beta:</b> {beta:.2f}")
        if w52_high and w52_low:
            lines.append(f"📉 <b>52H Aralık:</b> ${w52_low:,.2f} — ${w52_high:,.2f}")

        lines.append("")

        # ── Direktörden yorum ─────────────────────────────────────────────
        port_ctx = _build_portfolio_context(usd_try)
        soru = (
            f"{ticker} ({name}) için kısa bir değerlendirme yap. "
            f"Fiyat: ${price:.2f}, F/K: {pe or 'N/A'}, Sektör: {sector}, "
            f"Piyasa Değeri: {mktcap_str}. "
            f"Portföyüme eklemeli miyim? 3-4 cümle, somut ol."
        )
        yorum = await loop.run_in_executor(None, ask_director, soru)
        lines.append(f"🤖 <b>Direktör Yorumu:</b>\n{yorum}")

        mesaj = "\n".join(lines)
        for chunk in [mesaj[i:i+4000] for i in range(0, len(mesaj), 4000)]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ {ticker} analiz edilemedi: {e}")


async def cmd_fon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    TEFAS fon fiyatı sorgula.
    Kullanım: /fon <FON_KODU>
    Örnek: /fon IIH
    Örnek: /fon NNF
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "📝 <b>Kullanım:</b>\n"
            "/fon FON_KODU\n\n"
            "<b>Örnekler:</b>\n"
            "/fon IIH — İş Portföy Hisse Senedi Fonu\n"
            "/fon NNF — Nurol Portföy\n"
            "/fon TI1 — Tacirler Portföy",
            parse_mode=ParseMode.HTML,
        )
        return

    fon_kodu = args[0].upper()
    await update.message.reply_text(f"⏳ {fon_kodu} fiyatı çekiliyor...")

    try:
        from data.tefas_client import get_fund_info
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, get_fund_info, fon_kodu)

        if not info:
            await update.message.reply_text(
                f"❌ <b>{fon_kodu}</b> bulunamadı.\n"
                f"Fon kodunu kontrol et (örn: IIH, NNF, TI1)",
                parse_mode=ParseMode.HTML,
            )
            return

        price      = info["price"]
        date_str   = info.get("date", "")
        chg_pct    = info.get("change_1w_pct")
        old_price  = info.get("price_1w_ago")

        lines = [
            f"🇹🇷 <b>{fon_kodu} — TEFAS Fon Fiyatı</b>",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 <b>Güncel Fiyat:</b> ₺{price:.4f}",
            f"📅 <b>Tarih:</b> {date_str}",
        ]

        if chg_pct is not None and old_price is not None:
            chg_emoji = "🟢" if chg_pct >= 0 else "🔴"
            chg_sign  = "+" if chg_pct >= 0 else ""
            lines.append(
                f"{chg_emoji} <b>Haftalık Değişim:</b> "
                f"{chg_sign}{chg_pct:.2f}% (₺{old_price:.4f} → ₺{price:.4f})"
            )

        lines.append(f"\n<i>Kaynak: TEFAS | Veri her iş günü ~18:30 güncellenir</i>")

        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await update.message.reply_text(f"❌ {fon_kodu} fiyatı alınamadı: {e}")


async def cmd_haber(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Portföy bağlamında kategorize haber brifingı.
    Kullanım:
      /haber              — Tüm portföy + makro brifing
      /haber AAPL         — AAPL için haberler (us_stock varsayılan)
      /haber BTC crypto   — BTC kripto haberleri
      /haber XAU commodity — Altın haberleri
      /haber IIH tr_fund  — TEFAS fon haberleri
    """
    args = ctx.args

    await update.message.reply_text("⏳ Haberler toplanıyor...")

    try:
        from data.news_client import (
            get_global_macro_news, get_local_macro_news,
            get_asset_news, get_daily_news_briefing,
        )

        loop = asyncio.get_running_loop()

        # ── Tek varlık modu: /haber AAPL [tip] ───────────────────────────
        if args:
            symbol     = args[0].upper()
            asset_type = args[1].upper() if len(args) > 1 else "US_STOCK"

            # tip normalize
            type_map = {
                "HISSE": "US_STOCK", "STOCK": "US_STOCK",
                "KRIPTO": "CRYPTO",  "CRYPTO": "CRYPTO",
                "EMTIA": "COMMODITY","COMMODITY": "COMMODITY",
                "FON": "TR_FUND",    "TEFAS": "TR_FUND", "TR_FUND": "TR_FUND",
            }
            asset_type = type_map.get(asset_type, "US_STOCK")

            news = await loop.run_in_executor(
                None, get_asset_news, symbol, asset_type
            )

            if not news:
                await update.message.reply_text(
                    f"📭 <b>{symbol}</b> için haber bulunamadı.",
                    parse_mode=ParseMode.HTML,
                )
                return

            lines = [f"📰 <b>{symbol} Haberleri</b>", "━" * 28, ""]
            for i, n in enumerate(news, 1):
                title   = n.get("title", "")[:120]
                summary = n.get("summary", "")[:200]
                url     = n.get("url", "")
                source  = n.get("source", "")
                date    = n.get("date", "")[:10]
                lines.append(f"<b>{i}. {title}</b>")
                if summary:
                    lines.append(f"  <i>{summary}</i>")
                lines.append(f"  📌 {source} | {date}")
                if url:
                    lines.append(f"  🔗 {url}")
                lines.append("")

            mesaj = "\n".join(lines)
            for chunk in [mesaj[i:i+4000] for i in range(0, len(mesaj), 4000)]:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
            return

        # ── Tam portföy brifing modu: /haber ─────────────────────────────
        briefing = await loop.run_in_executor(None, get_daily_news_briefing)

        mesajlar = []

        # Küresel makro
        makro_g = briefing.get("MAKRO_KURESEL", [])
        if makro_g:
            lines = ["🌍 <b>Küresel Makro Haberler</b>", "━" * 28, ""]
            for i, n in enumerate(makro_g[:4], 1):
                lines.append(f"<b>{i}. {n.get('title','')[:120]}</b>")
                if n.get("summary"):
                    lines.append(f"  <i>{n['summary'][:180]}</i>")
                lines.append(f"  📌 {n.get('source','')} | {n.get('date','')[:10]}")
                lines.append("")
            mesajlar.append("\n".join(lines))

        # Türkiye makro
        makro_t = briefing.get("MAKRO_TURKIYE", [])
        if makro_t:
            lines = ["🇹🇷 <b>Türkiye Makro Haberler</b>", "━" * 28, ""]
            for i, n in enumerate(makro_t[:4], 1):
                lines.append(f"<b>{i}. {n.get('title','')[:120]}</b>")
                if n.get("summary"):
                    lines.append(f"  <i>{n['summary'][:180]}</i>")
                lines.append(f"  📌 {n.get('source','')} | {n.get('date','')[:10]}")
                lines.append("")
            mesajlar.append("\n".join(lines))

        # Portföy özel
        portfoy_haberler = briefing.get("PORTFOY_OZEL", {})
        if portfoy_haberler:
            lines = ["💼 <b>Portföy — Varlığa Özel Haberler</b>", "━" * 28, ""]
            for symbol, news_list in list(portfoy_haberler.items())[:8]:
                if not news_list:
                    continue
                lines.append(f"📌 <b>{symbol}</b>")
                for n in news_list[:2]:
                    lines.append(f"  • {n.get('title','')[:100]}")
                    if n.get("url"):
                        lines.append(f"    🔗 {n['url']}")
                lines.append("")
            mesajlar.append("\n".join(lines))

        if not mesajlar:
            await update.message.reply_text("📭 Haber bulunamadı.")
            return

        for mesaj in mesajlar:
            for chunk in [mesaj[i:i+4000] for i in range(0, len(mesaj), 4000)]:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("cmd_haber hatası: %s", e)
        await update.message.reply_text(f"❌ Haberler alınamadı: {e}")


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
        from alerts.trigger_monitor import run as run_trigger
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, run_trigger, layer, True)  # manual=True
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


# ─── Mesajlar: Direktöre İlet (Metin + Görsel) ────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Strateji Odası'na yazılan metin VE görsel mesajları direktöre iletir.
    Fotoğraf gönderildiğinde Claude Vision API ile analiz yapar.
    """
    chat_id = str(update.effective_chat.id)
    if chat_id != str(STRATEJI_CHAT_ID):
        return

    message = update.message

    # ── Fotoğraf veya görsel belge ────────────────────────────────────────
    if message.photo or (message.document and
                         message.document.mime_type and
                         message.document.mime_type.startswith("image/")):
        caption = (message.caption or "").strip()
        soru    = caption if caption else "Bu görseli analiz et ve portföyüme etkisini değerlendir."

        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            import base64, anthropic, os
            from datetime import datetime, timezone, timedelta
            from chat_director import (
                _build_portfolio_context, _build_memory_context,
                _load_history, _save_history, MAX_HISTORY_TURNS
            )
            from strategy_data import fetch_usd_try_rate

            # Görseli indir
            if message.photo:
                file = await ctx.bot.get_file(message.photo[-1].file_id)
            else:
                file = await ctx.bot.get_file(message.document.file_id)

            file_bytes = await file.download_as_bytearray()
            img_b64    = base64.standard_b64encode(bytes(file_bytes)).decode()

            # Portföy ve hafıza bağlamı
            usd_try = 44.0
            try:
                usd_try = fetch_usd_try_rate()
            except Exception:
                pass

            portfolio_ctx = _build_portfolio_context(usd_try)
            memory_ctx    = _build_memory_context()
            tr_time = (datetime.now(timezone.utc) +
                       timedelta(hours=3)).strftime("%d %B %Y, %H:%M")

            system_prompt = (
                "Sen deneyimli bir portföy strateji direktörüsün. "
                "Kullanıcı sana bir görsel paylaştı. "
                "Görseli dikkatlice oku ve portföy bağlamında somut yorum yap.\n\n"
                f"{portfolio_ctx}\n\n{memory_ctx}\n\n"
                f"TARİH/SAAT: {tr_time} | USD/TRY: {usd_try:.2f}\n\n"
                "Türkçe yanıt ver. Somut ve eyleme dönüştürülebilir ol."
            )

            history = _load_history()
            # Görsel + soru mesajı
            history.append({"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": img_b64
                }},
                {"type": "text", "text": soru}
            ]})

            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

            loop = asyncio.get_running_loop()
            def _call():
                return client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=1500,
                    system=system_prompt,
                    messages=history[-MAX_HISTORY_TURNS * 2:],
                )
            resp   = await loop.run_in_executor(None, _call)
            answer = resp.content[0].text.strip()

            # History'e base64 olmadan kaydet
            history[-1] = {"role": "user", "content": f"[GÖRSEL] {soru}"}
            history.append({"role": "assistant", "content": answer})
            _save_history(history)

            for chunk in [answer[i:i+4000] for i in range(0, len(answer), 4000)]:
                await message.reply_text(chunk, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error("Görsel işleme hatası: %s", e)
            await message.reply_text(
                "⚠️ Görseli işleyemedim. Görseli açıklayan bir metin yazıp tekrar dene."
            )
        return

    # ── Metin mesajı ──────────────────────────────────────────────────────
    user_text = (message.text or "").strip()
    if not user_text:
        return

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        from chat_director import ask_director
        loop     = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, ask_director, user_text)
        for chunk in [response[i:i+4000] for i in range(0, len(response), 4000)]:
            await message.reply_text(chunk, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Direktör yanıt hatası: %s", e)
        await message.reply_text(f"⚠️ Direktör yanıt veremedi: {e}\nLütfen tekrar dene.")
