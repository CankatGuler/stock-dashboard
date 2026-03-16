# financial_calendar.py — Finansal Takvim Sistemi
#
# Bu modül üç tür olayı takip eder:
#   1. Sabit ekonomik takvim (FOMC, NFP, CPI, PCE, ISM...)
#   2. Portföy/watchlist earnings tarihleri (yfinance'ten dinamik)
#   3. Önem derecesi ve sektör etkisi analizi
#
# Yıldız sistemi:
#   ⭐⭐⭐ Kritik — piyasayı derinden etkiler (FOMC, NFP, CPI)
#   ⭐⭐   Önemli — sektörel etki (ISM, PPI, Retail Sales)
#   ⭐     Bilgi — hafif etki (regional Fed, küçük veriler)

import logging
import time
from datetime import datetime, timezone, timedelta, date

import yfinance as yf

logger = logging.getLogger(__name__)


# ─── 2026 Sabit Ekonomik Takvim ──────────────────────────────────────────────
# Kaynaklar: Federal Reserve, BLS, ISM resmi açıklama takvimleri

FIXED_CALENDAR_2026 = [

    # ── FOMC Toplantıları (yılda 8 kez) ──────────────────────────────────
    # Fed faiz kararları piyasanın en kritik olayları
    {"date": "2026-01-29", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Fed faiz kararı ve Powell basın toplantısı. Faiz değişikliği veya hawkish/dovish ton piyasayı derinden etkiler.",
     "sector_impact": {"tech": "negatif" if True else "pozitif", "finans": "pozitif", "tahvil": "negatif"},
     "watch": "Faiz sabit kalırsa tech rallisi, artırılırsa satış dalgası beklenir."},

    {"date": "2026-03-18", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Fed faiz kararı. Mart toplantısı genellikle yıl içi yönü belirler.",
     "sector_impact": {},
     "watch": "Dot plot güncellemesi kritik — 2026 faiz patikası netleşir."},

    {"date": "2026-05-07", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Mayıs Fed toplantısı.",
     "sector_impact": {},
     "watch": "Q1 büyüme verisiyle birlikte değerlendir."},

    {"date": "2026-06-18", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Haziran Fed toplantısı — yıl ortası kritik karar noktası.",
     "sector_impact": {},
     "watch": "Faiz indirimi döngüsü başlıyor mu? Piyasanın en beklediği toplantı."},

    {"date": "2026-07-30", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Temmuz Fed toplantısı.",
     "sector_impact": {},
     "watch": "Yaz sezonu öncesi son büyük Fed kararı."},

    {"date": "2026-09-17", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Eylül Fed toplantısı — sonbahar piyasa sezonu açılışı.",
     "sector_impact": {},
     "watch": "Eylül historik olarak piyasaların en zayıf ayı — ekstra dikkat."},

    {"date": "2026-10-29", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Ekim Fed toplantısı.",
     "sector_impact": {},
     "watch": "Q3 verileriyle faiz patikası yeniden değerlendirilir."},

    {"date": "2026-12-10", "event": "FOMC Kararı",        "category": "fed",   "stars": 3,
     "description": "Yıl sonu Fed toplantısı. 2027 projeksiyonları açıklanır.",
     "sector_impact": {},
     "watch": "Yıl sonu konumlanması için kritik. Dot plot 2027 faiz beklentisini gösterir."},

    # ── NFP — Non-Farm Payrolls (her ayın ilk Cuması) ─────────────────────
    # ABD işgücü piyasasının en önemli göstergesi
    {"date": "2026-01-09", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "ABD tarım dışı istihdam. Güçlü gelirse Fed faiz indirimini erteler, zayıf gelirse indirim hızlanır.",
     "sector_impact": {"tüketim": "pozitif", "finans": "pozitif"},
     "watch": "Beklenti: ~+180K iş. Sapma ±50K piyasayı hareket ettirir."},

    {"date": "2026-02-06", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Ocak ayı istihdam verisi. Ocak sezonsallık düzeltmesi sürpriz yaratabilir.",
     "sector_impact": {},
     "watch": "Ocak NFP'si sezonsallık revizyonu nedeniyle genellikle sürpriz yapar."},

    {"date": "2026-03-06", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Şubat ayı istihdam verisi. FOMC toplantısından 12 gün önce açıklanır.",
     "sector_impact": {},
     "watch": "FOMC öncesi son büyük makro veri — Fed'in kararını doğrudan etkiler."},

    {"date": "2026-04-03", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Mart ayı istihdam verisi.",
     "sector_impact": {},
     "watch": "Q1 bitmesinin hemen ardından — çeyreksel trendin özeti."},

    {"date": "2026-05-01", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Nisan ayı istihdam verisi. FOMC toplantısıyla aynı haftada açıklanır.",
     "sector_impact": {},
     "watch": "FOMC haftası + NFP kombinasyonu = çift volatilite haftası."},

    {"date": "2026-06-05", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Mayıs ayı istihdam verisi.",
     "sector_impact": {},
     "watch": "Yaz sezonu istihdam trendi burada netleşir."},

    {"date": "2026-07-10", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Haziran ayı istihdam verisi.",
     "sector_impact": {},
     "watch": "Fed Haziran kararının ardından — karar doğru muydu?"},

    {"date": "2026-08-07", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Temmuz ayı istihdam verisi. Yaz dönemi sezonsal etkileri.",
     "sector_impact": {},
     "watch": "Yaz istihdamı güçlü olur — sürpriz düşük gelirse dikkat."},

    {"date": "2026-09-04", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Ağustos ayı istihdam verisi. Eylül FOMC'undan önce son kritik veri.",
     "sector_impact": {},
     "watch": "Eylül FOMC kararını şekillendirir."},

    {"date": "2026-10-02", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Eylül ayı istihdam verisi.",
     "sector_impact": {},
     "watch": "Q3 istihdam özeti."},

    {"date": "2026-11-06", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Ekim ayı istihdam verisi.",
     "sector_impact": {},
     "watch": "Q4 başlangıcı istihdam trendi."},

    {"date": "2026-12-04", "event": "NFP İşsizlik Verisi", "category": "macro", "stars": 3,
     "description": "Kasım ayı istihdam verisi. Yıl sonu FOMC öncesi son NFP.",
     "sector_impact": {},
     "watch": "Yılın son önemli makro verisi."},

    # ── CPI — Tüketici Fiyat Endeksi (ayın ortası) ───────────────────────
    # Enflasyon Fed'in ana hedefi — her veri piyasayı etkiler
    {"date": "2026-01-15", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Aralık 2025 enflasyonu. Yılbaşı enflasyon trendi burada netleşir.",
     "sector_impact": {"tech": "negatif_yüksek_gelirse", "enerji": "pozitif"},
     "watch": "Beklentinin üzerinde CPI → Fed faiz artırım beklentisi → tech satışı."},

    {"date": "2026-02-12", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Ocak 2026 CPI. Ocak genellikle fiyat artışı sezonudur.",
     "sector_impact": {},
     "watch": "Ocak CPI tarihsel olarak yüksek gelir — sürpriz riski var."},

    {"date": "2026-03-12", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Şubat 2026 CPI. FOMC toplantısından 6 gün önce.",
     "sector_impact": {},
     "watch": "FOMC öncesi kritik — yüksek gelirse Mart indirim ihtimali sıfırlanır."},

    {"date": "2026-04-10", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Mart 2026 CPI. Q1 enflasyon özeti.",
     "sector_impact": {},
     "watch": "Q1 enflasyon trendi burada görülür."},

    {"date": "2026-05-13", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Nisan 2026 CPI.",
     "sector_impact": {},
     "watch": "FOMC haftasına yakın — çift etki."},

    {"date": "2026-06-11", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Mayıs 2026 CPI. Haziran FOMC'undan önce.",
     "sector_impact": {},
     "watch": "Haziran indirim kararını doğrudan etkiler."},

    {"date": "2026-07-15", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Haziran 2026 CPI.",
     "sector_impact": {},
     "watch": "Yaz ortası enflasyon trendi."},

    {"date": "2026-08-13", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Temmuz 2026 CPI.",
     "sector_impact": {},
     "watch": "Enerji fiyatlarının yaz etkisi görülür."},

    {"date": "2026-09-10", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Ağustos 2026 CPI. Eylül FOMC'undan önce.",
     "sector_impact": {},
     "watch": "Eylül FOMC kararını şekillendirir."},

    {"date": "2026-10-14", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Eylül 2026 CPI. Q3 enflasyon özeti.",
     "sector_impact": {},
     "watch": "Q3 enflasyon trendi — yıl sonu görünümü netleşir."},

    {"date": "2026-11-12", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Ekim 2026 CPI.",
     "sector_impact": {},
     "watch": "Tatil sezonu öncesi fiyat baskısı."},

    {"date": "2026-12-11", "event": "CPI Enflasyon Verisi", "category": "macro", "stars": 3,
     "description": "Kasım 2026 CPI. Yıl sonu FOMC öncesi.",
     "sector_impact": {},
     "watch": "Yılın son CPI verisi."},

    # ── ISM Manufacturing & Services ────────────────────────────────────
    # Ekonomik aktivite için erken uyarı sistemi
    {"date": "2026-01-05", "event": "ISM Manufacturing",   "category": "macro", "stars": 2,
     "description": "Aralık imalat PMI. 50 altı = daralma, üstü = büyüme.",
     "sector_impact": {"sanayi": "yüksek", "hammadde": "orta"},
     "watch": "50 altında gelirse resesyon endişesi artar."},

    {"date": "2026-02-02", "event": "ISM Manufacturing",   "category": "macro", "stars": 2,
     "description": "Ocak imalat PMI.",
     "sector_impact": {},
     "watch": "Yılbaşı imalat trendi."},

    {"date": "2026-01-07", "event": "ISM Services",        "category": "macro", "stars": 2,
     "description": "Aralık hizmetler PMI. ABD ekonomisinin %70'i hizmet sektörü.",
     "sector_impact": {"tüketim": "yüksek", "finans": "orta"},
     "watch": "Hizmetler enflasyonun yapışkan kaldığı alan — dikkatli izle."},

    {"date": "2026-02-04", "event": "ISM Services",        "category": "macro", "stars": 2,
     "description": "Ocak hizmetler PMI.",
     "sector_impact": {},
     "watch": "Ocak hizmetler fiyatları genellikle yükselir."},

    # ── GDP (Gayri Safi Yurt İçi Hasıla) ────────────────────────────────
    {"date": "2026-01-30", "event": "GDP Q4 2025 (Ön)",    "category": "macro", "stars": 3,
     "description": "2025 Q4 büyüme ilk tahmini. Yıl sonu ekonomik gücü gösterir.",
     "sector_impact": {},
     "watch": "%2 altı = zayıf büyüme, %3 üstü = güçlü — Fed tepkisi değişir."},

    {"date": "2026-04-29", "event": "GDP Q1 2026 (Ön)",    "category": "macro", "stars": 3,
     "description": "2026 Q1 büyüme ilk tahmini.",
     "sector_impact": {},
     "watch": "Yılın ilk büyüme verisi — piyasa yönü için kritik."},

    {"date": "2026-07-30", "event": "GDP Q2 2026 (Ön)",    "category": "macro", "stars": 3,
     "description": "2026 Q2 büyüme ilk tahmini.",
     "sector_impact": {},
     "watch": "İki çeyrek üst üste negatif = teknik resesyon tanımı."},

    {"date": "2026-10-29", "event": "GDP Q3 2026 (Ön)",    "category": "macro", "stars": 3,
     "description": "2026 Q3 büyüme ilk tahmini.",
     "sector_impact": {},
     "watch": "Q4 konumlanması için kritik referans."},

    # ── PCE (Fed'in tercih ettiği enflasyon ölçütü) ──────────────────────
    {"date": "2026-01-30", "event": "PCE Enflasyonu",       "category": "macro", "stars": 2,
     "description": "Kişisel tüketim harcamaları fiyat endeksi. Fed'in %2 hedefine göre ölçer.",
     "sector_impact": {},
     "watch": "Core PCE %2.5 üzerinde kalırsa Fed faiz indiremez."},

    {"date": "2026-02-27", "event": "PCE Enflasyonu",       "category": "macro", "stars": 2,
     "description": "Ocak PCE.",
     "sector_impact": {},
     "watch": "CPI'dan sonraki hafta gelir — genellikle CPI ile uyumlu."},

    {"date": "2026-03-27", "event": "PCE Enflasyonu",       "category": "macro", "stars": 2,
     "description": "Şubat PCE. FOMC toplantısından 9 gün önce.",
     "sector_impact": {},
     "watch": "FOMC öncesi son PCE verisi."},

    # ── Jackson Hole (Yıllık Fed Sempozyumu) ────────────────────────────
    {"date": "2026-08-27", "event": "Jackson Hole Sempozyumu", "category": "fed", "stars": 3,
     "description": "Fed başkanı Powell ve küresel merkez bankacıları yıllık toplantısı. Para politikası yönü burada belirlenir.",
     "sector_impact": {},
     "watch": "Powell'ın konuşması FOMC toplantısı kadar kritik — tarihsel olarak büyük hareketler yaratmıştır."},
]

# Sektör etki açıklamaları
SECTOR_IMPACT_TEMPLATES = {
    "fed":   {
        "hawkish": "Tech/growth hisseleri baskı, finans hisseleri toparlanır, dolar güçlenir",
        "dovish":  "Tech/growth hisseleri rallisi, altın yükselir, dolar zayıflar",
    },
    "cpi_high": "Tech değerlemeleri baskı altında, enerji ve emtia hisseleri iyi",
    "cpi_low":  "Risk iştahı artar, büyüme hisseleri toparlanır",
    "nfp_strong": "Tüketici hisseleri pozitif, Fed faiz indirimini erteleyebilir",
    "nfp_weak":   "Resesyon endişesi artar, savunmacı sektörler öne çıkar",
}


# ─── Dinamik Earnings Takvimi ─────────────────────────────────────────────────

def fetch_earnings_for_tickers(tickers: list, days_ahead: int = 60) -> list:
    """
    yfinance'ten hisse earnings tarihlerini çek.
    60 günlük pencerede yaklaşan tüm earnings'leri döndürür.
    """
    events = []
    today  = datetime.now(timezone.utc).date()
    window = today + timedelta(days=days_ahead)

    for ticker in tickers[:25]:  # Rate limit için max 25
        try:
            info = yf.Ticker(ticker).info
            earnings_ts = info.get("earningsTimestamp") or info.get("earningsDate")

            if not earnings_ts:
                continue

            if isinstance(earnings_ts, (int, float)):
                earnings_date = datetime.fromtimestamp(earnings_ts, tz=timezone.utc).date()
            else:
                earnings_date = earnings_ts

            if today <= earnings_date <= window:
                days_until  = (earnings_date - today).days
                company     = info.get("shortName") or ticker
                eps_est     = info.get("forwardEps", 0)
                rev_gr      = float(info.get("revenueGrowth") or 0) * 100

                # Önem derecesi: büyük şirketler veya portföydekiler 3 yıldız
                market_cap = float(info.get("marketCap") or 0)
                stars = 3 if market_cap > 100e9 else (2 if market_cap > 10e9 else 1)

                events.append({
                    "date":        earnings_date.strftime("%Y-%m-%d"),
                    "event":       f"{ticker} Earnings",
                    "category":    "earnings",
                    "stars":       stars,
                    "ticker":      ticker,
                    "company":     company,
                    "days_until":  days_until,
                    "eps_est":     eps_est,
                    "rev_growth":  round(rev_gr, 1),
                    "description": (
                        f"{company} çeyreksel kazanç açıklaması. "
                        f"Beklenen EPS: ${eps_est:.2f}. "
                        f"Gelir büyümesi: %{rev_gr:.0f}."
                    ),
                    "watch": (
                        f"Earnings öncesi pozisyon boyutunu gözden geçir. "
                        f"Miss riski yüksekse stop loss gir."
                    ),
                })
            time.sleep(0.2)
        except Exception as e:
            logger.debug("Earnings fetch failed %s: %s", ticker, e)

    return events


# ─── Takvim Birleştirici ─────────────────────────────────────────────────────

def get_upcoming_events(
    tickers: list = None,
    days_ahead: int = 14,
    min_stars: int = 1,
) -> list:
    """
    Sabit ekonomik takvim + earnings takvimini birleştir.
    Önümüzdeki N gün için önem derecesine göre filtrele.

    Dönüş: Tarihe göre sıralanmış olay listesi
    """
    today   = datetime.now(timezone.utc).date()
    window  = today + timedelta(days=days_ahead)
    today_s = today.strftime("%Y-%m-%d")
    win_s   = window.strftime("%Y-%m-%d")

    # Sabit ekonomik takvimden filtrele
    events = [
        e for e in FIXED_CALENDAR_2026
        if today_s <= e["date"] <= win_s and e.get("stars", 1) >= min_stars
    ]

    # Earnings ekle
    if tickers:
        earnings = fetch_earnings_for_tickers(tickers, days_ahead=days_ahead)
        events.extend([e for e in earnings if e.get("stars", 1) >= min_stars])

    # Tarihe ve önem derecesine göre sırala
    events.sort(key=lambda x: (x["date"], -x.get("stars", 1)))

    # days_until ekle
    for e in events:
        try:
            ev_date       = datetime.strptime(e["date"], "%Y-%m-%d").date()
            e["days_until"] = (ev_date - today).days
        except Exception:
            e["days_until"] = 0

    return events


def get_todays_and_tomorrows_events(tickers: list = None) -> dict:
    """
    Bugün ve yarınki olayları ayrı ayrı döndür.
    Sabah Telegram mesajı için kullanılır.
    """
    today    = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)
    today_s  = today.strftime("%Y-%m-%d")
    tom_s    = tomorrow.strftime("%Y-%m-%d")

    all_events = get_upcoming_events(tickers=tickers, days_ahead=2, min_stars=1)

    return {
        "today":    [e for e in all_events if e["date"] == today_s],
        "tomorrow": [e for e in all_events if e["date"] == tom_s],
        "date":     today_s,
    }


# ─── Telegram Mesaj Formatı ───────────────────────────────────────────────────

def format_calendar_telegram(events_data: dict, portfolio_tickers: list = None) -> str:
    """
    Sabah takvim bildirimi için Telegram mesajı oluştur.
    Hem bugünkü hem yarınki olaylar dahil edilir.
    """
    today_events = events_data.get("today", [])
    tom_events   = events_data.get("tomorrow", [])
    date_str     = events_data.get("date", "")

    # Hiç olay yoksa kısa mesaj
    if not today_events and not tom_events:
        return ""  # Sessiz — gürültü yaratma

    star_map = {3: "🔴", 2: "🟡", 1: "🔵"}
    cat_map  = {
        "fed":     "🏛 FED",
        "macro":   "📊 MAKRO",
        "earnings":"💼 EARNINGS",
    }

    lines = [f"📅 <b>FİNANSAL TAKVİM — {date_str}</b>\n"]

    if today_events:
        lines.append("⚡ <b>BUGÜN:</b>")
        for e in today_events:
            star_emoji = star_map.get(e.get("stars", 1), "🔵")
            cat_label  = cat_map.get(e.get("category", "macro"), "📊")
            ticker_str = f" ({e['ticker']})" if e.get("ticker") else ""
            lines.append(f"{star_emoji} <b>{cat_label}: {e['event']}{ticker_str}</b>")
            lines.append(f"   <i>{e.get('description','')[:100]}</i>")
            if e.get("watch"):
                lines.append(f"   👁 {e['watch'][:80]}")
        lines.append("")

    if tom_events:
        lines.append("📌 <b>YARIN:</b>")
        for e in tom_events:
            star_emoji = star_map.get(e.get("stars", 1), "🔵")
            cat_label  = cat_map.get(e.get("category", "macro"), "📊")
            ticker_str = f" ({e['ticker']})" if e.get("ticker") else ""
            lines.append(f"{star_emoji} <b>{cat_label}: {e['event']}{ticker_str}</b>")
            lines.append(f"   <i>{e.get('description','')[:100]}</i>")
        lines.append("")

    # Önem derecesi açıklaması
    has_critical = any(e.get("stars", 1) == 3 for e in today_events + tom_events)
    if has_critical:
        lines.append(
            "⚠️ <i>Kritik veri günü — yeni pozisyon açmadan önce veriyi bekle. "
            "Volatilite artabilir.</i>"
        )

    lines.append("\n🔴 Kritik  🟡 Önemli  🔵 Bilgi")
    return "\n".join(lines)


def format_weekly_preview_telegram(tickers: list = None) -> str:
    """
    Haftanın önemli olaylarını Pazartesi sabahı Telegram'a gönder.
    7 günlük pencere, tüm önemli olaylar.
    """
    events = get_upcoming_events(tickers=tickers, days_ahead=7, min_stars=2)
    if not events:
        return ""

    star_map = {3: "🔴", 2: "🟡"}
    cat_map  = {"fed": "🏛 FED", "macro": "📊 MAKRO", "earnings": "💼 EARNINGS"}

    lines = ["🗓 <b>BU HAFTA FİNANSAL TAKVİM</b>\n"]
    for e in events:
        star_emoji = star_map.get(e.get("stars", 1), "🟡")
        cat_label  = cat_map.get(e.get("category", "macro"), "📊")
        day_str    = e["date"][8:10] + "." + e["date"][5:7]
        days_left  = e.get("days_until", 0)
        ticker_str = f" ({e['ticker']})" if e.get("ticker") else ""
        days_label = "bugün" if days_left == 0 else (f"{days_left} gün sonra" if days_left > 0 else "")
        lines.append(
            f"{star_emoji} <b>{day_str}</b> — {cat_label}: {e['event']}{ticker_str}"
            + (f" <i>({days_label})</i>" if days_label else "")
        )

    lines.append("\n<i>Strateji sekmesinde detaylı takvim görüntüleyebilirsin.</i>")
    return "\n".join(lines)
