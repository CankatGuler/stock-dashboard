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
    _application.add_handler(CommandHandler("hisse",    cmd_hisse))
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
        "<b>🔍 Analiz Komutları:</b>\n"
        "/hisse AMZN — Temel analiz + haberler + direktör yorumu\n\n"
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
        ticker    = args[0].upper()
        shares    = float(args[1])
        avg_cost  = float(args[2])
        ac        = args[3].lower() if len(args) > 3 else "us_equity"

        # Geçerli sınıf kontrolü
        valid_classes = ("us_equity", "crypto", "commodity", "tefas", "cash")
        if ac not in valid_classes:
            await update.message.reply_text(
                f"❌ Geçersiz sınıf: <b>{ac}</b>\n"
                f"Geçerli sınıflar: {' | '.join(valid_classes)}",
                parse_mode=ParseMode.HTML,
            )
            return

        # Para birimi — TEFAS ve TRY emtia için TRY, diğerleri USD
        currency = "TRY" if ac in ("tefas",) or "TRY" in ticker else "USD"

        await update.message.reply_text(f"⏳ {ticker} ekleniyor...")

        from portfolio_manager import add_position
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: add_position(
                ticker     = ticker,
                shares     = shares,
                avg_cost   = avg_cost,
                asset_class= ac,
                currency   = currency,
                deduct_from_cash=False,  # Telegram'dan eklerken nakit düşme
            )
        )

        total_cost = shares * avg_cost
        cur_symbol = "₺" if currency == "TRY" else "$"
        await update.message.reply_text(
            f"✅ <b>{ticker}</b> portföye eklendi\n"
            f"  Adet: {shares:,g}\n"
            f"  Maliyet: {cur_symbol}{avg_cost:,.4f}\n"
            f"  Toplam: {cur_symbol}{total_cost:,.2f}\n"
            f"  Sınıf: {ac}",
            parse_mode=ParseMode.HTML,
        )
    except ValueError:
        await update.message.reply_text(
            "❌ Sayı formatı hatalı.\n"
            "Örnek: /ekle AVGO 5 1200 us_equity"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_portfoy_sil(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Portföyden pozisyon sil.
    Kullanım: /sil <TICKER>
    Örnek: /sil AVGO
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Kullanım: /sil TICKER\nÖrnek: /sil AVGO"
        )
        return

    ticker = args[0].upper()
    await update.message.reply_text(f"⏳ {ticker} siliniyor...")

    try:
        from portfolio_manager import remove_position
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, remove_position, ticker)
        await update.message.reply_text(
            f"✅ <b>{ticker}</b> portföyden silindi.",
            parse_mode=ParseMode.HTML,
        )
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

        from portfolio_manager import update_position
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_position, ticker, shares, avg_cost)

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
        from portfolio_manager import load_portfolio
        from strategy_data import fetch_usd_try_rate
        import yfinance as yf

        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        usd_try   = fetch_usd_try_rate()

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
                        from turkey_fetcher import fetch_tefas_fund
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
    Pozisyonu kısmen azalt (kısmi satış).
    Kullanım: /azalt <TICKER> <SATILAN_ADET>
    Örnek: /azalt AVGO 5
    """
    args = ctx.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "📝 <b>Kullanım:</b>\n"
            "/azalt TICKER SATILAN_ADET\n\n"
            "<b>Örnekler:</b>\n"
            "/azalt AVGO 5 — AVGO'dan 5 hisse sat\n"
            "/azalt BTC-USD 0.05 — 0.05 BTC sat\n\n"
            "Tüm pozisyonu silmek için: /sil TICKER",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        ticker       = args[0].upper()
        satilan_adet = float(args[1])

        from portfolio_manager import load_portfolio, update_position, remove_position
        portfolio = load_portfolio()

        # Mevcut pozisyonu bul
        mevcut = next((p for p in portfolio if p.get("ticker") == ticker), None)
        if not mevcut:
            await update.message.reply_text(f"❌ <b>{ticker}</b> portföyde bulunamadı.", parse_mode=ParseMode.HTML)
            return

        mevcut_adet = float(mevcut.get("shares", 0))
        if satilan_adet >= mevcut_adet:
            await update.message.reply_text(
                f"⚠️ Satmak istediğin adet ({satilan_adet:,g}) mevcut adetten "
                f"({mevcut_adet:,g}) fazla veya eşit.\n"
                f"Tüm pozisyonu silmek için: /sil {ticker}",
                parse_mode=ParseMode.HTML,
            )
            return

        yeni_adet = mevcut_adet - satilan_adet
        avg_cost  = float(mevcut.get("avg_cost", 0))

        await update.message.reply_text(f"⏳ {ticker} azaltılıyor...")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, update_position, ticker, yeni_adet, avg_cost)

        await update.message.reply_text(
            f"✅ <b>{ticker}</b> azaltıldı\n"
            f"  Satılan: {satilan_adet:,g} adet\n"
            f"  Kalan: {yeni_adet:,g} adet @ ${avg_cost:,.2f}",
            parse_mode=ParseMode.HTML,
        )
    except ValueError:
        await update.message.reply_text("❌ Adet formatı hatalı. Örnek: /azalt AVGO 5")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_hisse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Hisse temel analizi + son haberler + direktör yorumu.
    Kullanım: /hisse <TICKER>
    Örnek: /hisse AMZN
    """
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Kullanım: /hisse TICKER\n"
            "Örnek: /hisse AMZN\n"
            "Örnek: /hisse NVDA"
        )
        return

    ticker = args[0].upper()
    await update.message.reply_text(f"⏳ {ticker} analiz ediliyor...")

    try:
        from stock_analyzer import analyze_ticker
        from chat_director import _build_portfolio_context
        from strategy_data import fetch_usd_try_rate

        usd_try   = fetch_usd_try_rate()
        port_ctx  = _build_portfolio_context(usd_try)

        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, analyze_ticker, ticker, port_ctx[:300]
        )

        # 4096 karakter sınırı için böl
        for chunk in [result[i:i+4000] for i in range(0, len(result), 4000)]:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ {ticker} analiz edilemedi: {e}")


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
        await loop.run_in_executor(None, run_trigger, layer, True)  # manual=True
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
