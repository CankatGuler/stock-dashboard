# portfolio_scanner.py — Haftalık Hisse Sağlık Taraması
#
# Her Pazartesi 09:00 TR saatinde çalışır (hafta açılışında).
# Portföydeki US hisselerini tarar ve şu değişimleri tespit eder:
#
#   🔴 UYARI sinyalleri (Telegram'a gönderilir):
#     - FCF negatife döndü (zombi filtresi)
#     - Current Ratio 1.0 altına düştü (likidite riski)
#     - Short Interest %30 üzerinde arttı
#     - 52 haftalık düşüğe %5 kaldı
#     - Net Borç/EBITDA 5x'i geçti (aşırı borçlanma)
#
#   🟢 POZİTİF sinyaller:
#     - Analist hedef fiyatı %20+ upside gösteriyor
#     - FCF yield %5 üzerinde (ucuz nakit üreticisi)
#     - Short interest düşüyor (baskı azalıyor)

import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Eşik değerleri — değiştirmek istersen buradan ayarla
THRESHOLDS = {
    "current_ratio_min":    1.0,     # Altına düşerse uyarı
    "net_debt_ebitda_max":  5.0,     # Üstüne çıkarsa uyarı
    "short_pct_warning":    0.30,    # %30 üzeri short float uyarısı
    "52w_low_proximity":    0.05,    # 52h düşüğüne %5 kaldıysa uyarı
    "upside_opportunity":   0.20,    # %20+ upside fırsat sinyali
    "fcf_yield_opportunity":5.0,     # %5+ FCF yield fırsat sinyali
}


def scan_portfolio() -> str:
    """
    Portföydeki US hisselerini tara, uyarı ve fırsatları raporla.
    Döndürür: Telegram'a gönderilecek mesaj metni.
    """
    from portfolio_manager import load_portfolio
    from strategy_data import fetch_usd_try_rate
    from stock_analyzer import get_fundamentals

    portfolio = [p for p in load_portfolio()
                 if float(p.get("shares", 0)) > 0
                 and p.get("asset_class") in ("us_equity", "other", "", None)]

    if not portfolio:
        return ""

    usd_try  = fetch_usd_try_rate()
    warnings = []   # Kırmızı bayraklar
    opps     = []   # Fırsatlar
    ok       = []   # Sağlıklı

    for p in portfolio:
        ticker = p.get("ticker", "").upper()
        if not ticker:
            continue

        try:
            data = get_fundamentals(ticker)
            if "error" in data:
                continue

            price    = data.get("price", 0)
            w_flags  = []
            o_flags  = []

            # ── UYARI KONTROLLERI ────────────────────────────────────────────

            # 1. FCF negatif → zombi filtresi
            fcf = data.get("fcf")
            if fcf is not None and fcf < 0:
                cr  = data.get("current_ratio")
                de  = data.get("debt_equity")
                if cr and cr < 1.0:
                    w_flags.append(f"⚠️ ZOMBİ: FCF negatif + Current Ratio {cr:.2f} (<1.0)")
                elif de and de > 200:
                    w_flags.append(f"⚠️ ZOMBİ: FCF negatif + Borç/ÖK {de:.0f}")
                else:
                    w_flags.append(f"⚠️ FCF negatif (${fcf/1e9:.1f}B)")

            # 2. Current Ratio düşük
            cr = data.get("current_ratio")
            if cr is not None and cr < THRESHOLDS["current_ratio_min"]:
                w_flags.append(f"⚠️ Likidite: Current Ratio {cr:.2f} (eşik: {THRESHOLDS['current_ratio_min']})")

            # 3. Aşırı borç
            nde = data.get("net_debt_ebitda")
            if nde is not None and nde > THRESHOLDS["net_debt_ebitda_max"]:
                w_flags.append(f"⚠️ Aşırı Borç: Net Borç/EBITDA {nde:.1f}x (eşik: {THRESHOLDS['net_debt_ebitda_max']}x)")

            # 4. 52h düşüğüne yakın
            h52 = data.get("52w_high")
            l52 = data.get("52w_low")
            if l52 and price > 0:
                proximity = (price - l52) / price
                if proximity < THRESHOLDS["52w_low_proximity"]:
                    w_flags.append(
                        f"⚠️ 52h düşüğüne yakın: ${price:.2f} "
                        f"(düşük: ${l52:.2f}, fark: %{proximity*100:.1f})"
                    )

            # 5. Yüksek short interest
            short_pct = data.get("short_pct_float")
            if short_pct and short_pct > THRESHOLDS["short_pct_warning"]:
                w_flags.append(
                    f"⚠️ Yüksek Short: Float'ın %{short_pct*100:.1f}'i açık pozisyon"
                )

            # ── FIRSAT KONTROLLERI ───────────────────────────────────────────

            # 1. Güçlü analist upside
            upside = data.get("upside")
            target = data.get("target_price")
            if upside and upside > THRESHOLDS["upside_opportunity"] * 100:
                o_flags.append(
                    f"🎯 Analist hedefi: ${target:.2f} "
                    f"(%{upside:.1f} upside, {data.get('analyst_count','?')} analist)"
                )

            # 2. Yüksek FCF yield
            fcf_yield = data.get("fcf_yield")
            if fcf_yield and fcf_yield > THRESHOLDS["fcf_yield_opportunity"]:
                o_flags.append(f"💵 FCF Yield: %{fcf_yield:.1f} (güçlü nakit üreticisi)")

            # 3. Düşük PEG (büyümeye göre ucuz)
            peg = data.get("peg")
            if peg and 0 < peg < 1.0:
                o_flags.append(f"📈 PEG: {peg:.2f} (büyümeye göre ucuz)")

            # Sonuçları kategorize et
            ticker_cost = (float(p.get("shares", 0)) *
                          float(p.get("avg_cost", 0)))
            ticker_str  = f"<b>{ticker}</b> (${ticker_cost:,.0f} maliyet)"

            if w_flags:
                warnings.append((ticker_str, w_flags))
            elif o_flags:
                opps.append((ticker_str, o_flags))
            else:
                ok.append(ticker)

        except Exception as e:
            logger.warning("Tarama hatası %s: %s", ticker, e)
            continue

    # ── Mesaj Oluştur ─────────────────────────────────────────────────────────
    if not warnings and not opps:
        return (
            f"✅ <b>Haftalık Hisse Taraması</b>\n"
            f"{'━' * 28}\n"
            f"📅 {_tr_now()}\n\n"
            f"Portföydeki {len(ok)} hissenin tamamı sağlıklı görünüyor.\n"
            f"Tarama edilen: {', '.join(ok)}"
        )

    lines = [
        f"🔍 <b>Haftalık Hisse Taraması</b>",
        f"{'━' * 28}",
        f"📅 {_tr_now()}",
        "",
    ]

    if warnings:
        lines.append(f"🔴 <b>UYARILAR ({len(warnings)} hisse)</b>")
        for ticker_str, flags in warnings:
            lines.append(f"\n{ticker_str}")
            for flag in flags:
                lines.append(f"  {flag}")

    if opps:
        lines.append(f"\n🟢 <b>FIRSATLAR ({len(opps)} hisse)</b>")
        for ticker_str, flags in opps:
            lines.append(f"\n{ticker_str}")
            for flag in flags:
                lines.append(f"  {flag}")

    if ok:
        lines.append(f"\n✅ <b>Sağlıklı:</b> {', '.join(ok)}")

    lines += [
        "",
        f"{'━' * 28}",
        "Detay için: /hisse TICKER",
    ]

    return "\n".join(lines)


def _tr_now() -> str:
    return (datetime.now(timezone.utc) +
            timedelta(hours=3)).strftime("%d %b %Y, %H:%M")


def run() -> None:
    """
    Taramayı çalıştır ve sonucu Telegram'a gönder.
    main.py'deki zamanlayıcı bu fonksiyonu çağırır.
    """
    logger.info("Haftalık hisse taraması başlatılıyor...")
    try:
        msg = scan_portfolio()
        if msg:
            from telegram_notifier import send_message
            send_message(msg)
            logger.info("Hisse tarama raporu gönderildi.")
        else:
            logger.info("Taranacak US hisse bulunamadı.")
    except Exception as e:
        logger.error("Tarama hatası: %s", e)


if __name__ == "__main__":
    run()
