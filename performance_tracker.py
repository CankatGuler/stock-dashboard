# performance_tracker.py — Haftalık Karar Performansı Güncelleyici
#
# GitHub Actions tarafından haftada bir (Pazar 20:00 UTC = Pazartesi 23:00 TR) çalışır.
# Yaptığı işler:
#   1. director_memory.json'daki performans kayıtlarını okur
#   2. Kontrol tarihi geçmiş kayıtlar için yfinance/tefas-crawler'dan güncel fiyat çeker
#   3. Getiriyi ve karar isabetini (DOGRU/YANLIS/NÖTR) hesaplar ve kaydeder
#   4. Güncellenen kararları Telegram'a rapor olarak gönderir
#   5. Direktörün bir sonraki analizine kalibrasyon notu hazırlar

import os
import sys
import logging
from datetime import datetime, timezone

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ─── Fiyat Çekimi ─────────────────────────────────────────────────────────────

def fetch_current_price(ticker: str, currency: str = "USD",
                        usd_try: float = 44.0) -> float:
    """
    Verilen ticker için güncel fiyatı çek.
    TEFAS fonları için tefas-crawler, diğerleri için yfinance kullanır.
    Döndürür: USD cinsinden fiyat (TRY bazlı varlıklar çevrilir).
    """
    import yfinance as yf

    # TEFAS fonu mu? (büyük harf 3 karakter, yfinance'te yok)
    tefas_tickers = {"IIH","NNF","TTE","AOY","AEY","URA","TI1","TSI",
                     "MAC","YAS","GLD","GAF","YAC","NNM"}
    if ticker.upper() in tefas_tickers:
        try:
            from turkey_fetcher import fetch_tefas_fund
            fd = fetch_tefas_fund(ticker.upper())
            if fd and fd.get("price", 0) > 0:
                # TL fiyatı → USD
                return round(float(fd["price"]) / usd_try, 6)
        except Exception as e:
            logger.warning("TEFAS fiyat alınamadı %s: %s", ticker, e)
        return 0.0

    # Altın/Gümüş gram TRY
    if ticker in ("ALTIN_GRAM_TRY", "XAUTRY=X"):
        try:
            hist = yf.Ticker("GC=F").history(period="2d")
            if not hist.empty:
                oz_usd = float(hist["Close"].iloc[-1])
                # gram TL fiyatı (USD'e çevirmeden direkt USD/oz kullan — karşılaştırma aynı baz)
                return round(oz_usd / 31.1035, 4)  # USD/gram
        except Exception as e:
            logger.warning("Altın fiyat alınamadı: %s", e)
        return 0.0

    if ticker in ("GUMUS_GRAM_TRY", "XAGTRY=X"):
        try:
            hist = yf.Ticker("SI=F").history(period="2d")
            if not hist.empty:
                oz_usd = float(hist["Close"].iloc[-1])
                return round(oz_usd / 31.1035, 4)
        except Exception as e:
            logger.warning("Gümüş fiyat alınamadı: %s", e)
        return 0.0

    # Standart yfinance (ABD hisse, kripto, ETF)
    try:
        hist = yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            # TRY bazlı ise USD'ye çevir
            if currency == "TRY":
                return round(price / usd_try, 6)
            return round(price, 4)
    except Exception as e:
        logger.warning("yfinance fiyat alınamadı %s: %s", ticker, e)

    return 0.0


# ─── Telegram Raporu ──────────────────────────────────────────────────────────

def send_performance_report(results: list[dict], kalibrasyon: str) -> None:
    """
    Güncellenen performans kararlarını Telegram'a gönder.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("Telegram credentials eksik — rapor gönderilemedi.")
        return

    if not results and not kalibrasyon:
        logger.info("Gönderilecek performans güncellemesi yok.")
        return

    tr_now = (datetime.now(timezone.utc)).strftime("%d %b %Y")
    lines  = [
        f"📊 <b>Haftalık Karar Performansı — {tr_now}</b>",
        "━" * 30,
    ]

    if results:
        # Sonuçları grupla: DOGRU / YANLIS / NÖTR
        dogru  = [r for r in results if r.get("karar_isabeti") == "DOGRU"]
        yanlis = [r for r in results if r.get("karar_isabeti") == "YANLIS"]
        ntr    = [r for r in results if r.get("karar_isabeti") == "NÖTR"]

        lines.append(
            f"\n✅ {len(dogru)} doğru | "
            f"❌ {len(yanlis)} yanlış | "
            f"⚪ {len(ntr)} nötr "
            f"({len(results)} karar değerlendirildi)"
        )

        # Yanlış kararları detaylı göster — öğrenme için kritik
        if yanlis:
            lines.append("\n❌ <b>Yanlış Kararlar (Kalibrasyon İçin):</b>")
            for r in yanlis:
                getiri = r.get("getiri_pct", 0)
                lines.append(
                    f"  {r['tarih']} | {r['eylem']} {r['varlik']} "
                    f"@ {r['baslangic_fiyat']:.4f} → {r['kontrol_fiyat']:.4f} "
                    f"({getiri:+.1f}%) — Direktör erken/yanlış sinyal üretmiş"
                )

        # Doğru kararları da göster
        if dogru:
            lines.append("\n✅ <b>Doğru Kararlar:</b>")
            for r in dogru[:5]:  # Max 5 göster
                getiri = r.get("getiri_pct", 0)
                lines.append(
                    f"  {r['tarih']} | {r['eylem']} {r['varlik']} "
                    f"({getiri:+.1f}%)"
                )

    # Kalibrasyon özeti
    if kalibrasyon:
        lines.append(f"\n🧠 <b>Direktör Kalibrasyon Notu:</b>")
        lines.append(f"<i>{kalibrasyon}</i>")

    lines.append("\n━" * 30)
    lines.append("Bu veriler direktörün bir sonraki analizine otomatik enjekte edilecek.")

    msg = "\n".join(lines)

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4000],
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info("Performans raporu Telegram'a gönderildi.")
    except Exception as e:
        logger.error("Telegram gönderi hatası: %s", e)


# ─── Ana Çalıştırıcı ──────────────────────────────────────────────────────────

def run() -> None:
    """
    Tüm performans kayıtlarını güncelle.
    1. Bekleyen kayıtların ticker listesini çıkar
    2. Her ticker için güncel fiyat çek
    3. update_performance() ile güncelle
    4. Telegram'a rapor gönder
    """
    logger.info("Performans takibi başlatılıyor...")

    # USD/TRY kuru
    try:
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()
        logger.info("USD/TRY: %.4f", usd_try)
    except Exception as e:
        logger.error("USD/TRY alınamadı: %s", e)
        return

    # Hafıza yükle
    from director_memory import memory

    perf_kayitlar = memory._data.get("performance", [])
    if not perf_kayitlar:
        logger.info("Performans kaydı yok — ilk analizden sonra oluşacak.")
        return

    # Bekleyen kayıtların ticker'larını bul
    from datetime import date
    today = date.today()

    bekleyen_tickers: dict[str, str] = {}  # ticker → currency
    for kayit in perf_kayitlar:
        if kayit.get("kontrol_fiyat") is not None:
            continue  # Zaten güncellenmiş
        try:
            kontrol_tarihi = datetime.fromisoformat(
                kayit["kontrol_tarihi"]
            ).date()
        except Exception:
            continue
        if today >= kontrol_tarihi:
            tk  = kayit.get("varlik", "")
            cur = kayit.get("currency", "USD")
            if tk:
                bekleyen_tickers[tk] = cur

    if not bekleyen_tickers:
        logger.info("Kontrol tarihi geçmiş kayıt yok — henüz beklemede.")
        return

    logger.info("%d farklı varlık için fiyat çekilecek: %s",
                len(bekleyen_tickers), list(bekleyen_tickers.keys()))

    # Fiyatları çek ve güncelle
    tum_guncellenenler = []
    for ticker, currency in bekleyen_tickers.items():
        guncel_fiyat = fetch_current_price(ticker, currency, usd_try)
        if guncel_fiyat <= 0:
            logger.warning("Fiyat alınamadı, atlanıyor: %s", ticker)
            continue

        logger.info("Fiyat: %s = %.4f", ticker, guncel_fiyat)
        guncellenenler = memory.update_performance(ticker, guncel_fiyat)
        tum_guncellenenler.extend(guncellenenler)

    logger.info("Toplam %d kayıt güncellendi.", len(tum_guncellenenler))

    # Kalibrasyon özetini al
    kalibrasyon = memory._hesapla_kalibrasyon()

    # Telegram'a rapor gönder
    send_performance_report(tum_guncellenenler, kalibrasyon)

    # Özet log
    if tum_guncellenenler:
        dogru  = sum(1 for r in tum_guncellenenler if r.get("karar_isabeti") == "DOGRU")
        yanlis = sum(1 for r in tum_guncellenenler if r.get("karar_isabeti") == "YANLIS")
        logger.info("Sonuç: %d doğru, %d yanlış, %d nötr",
                    dogru, yanlis, len(tum_guncellenenler) - dogru - yanlis)


# ─── Giriş Noktası ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()
