# strategy_director.py — İki Aşamalı Claude Analiz Motoru
#
# FELSEFE:
#   Tek bir büyük Claude çağrısı yerine, gerçek bir yatırım bankasının
#   çalışma şeklini taklit ediyoruz:
#   - Aşama A: Her alan için uzman analist → kendi alanını derinlemesine inceler
#   - Aşama B: Strateji direktörü → 5 analist raporunu alır, sentezler, karar verir
#
# NEDEN İKİ AŞAMA?
#   Claude'un dikkat kapasitesi sınırlı. 50 metrik + 10 hisse + 3 varlık sınıfı
#   aynı anda verilirse hiçbirini derinlemesine işleyemez.
#   Uzman analistler kendi alanlarında derinleşir, direktör sadece sentez yapar.

import os
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLAUDE_MODEL   = "claude-opus-4-5"
MAX_TOKENS_ANALYST  = 800    # Her analist raporu için — özlü ama derin
MAX_TOKENS_DIRECTOR = 8000   # Direktör için — kapsamlı sentez

# ─── Direktör JSON Şeması (f-string dışında) ──────────────────────────────
_DIRECTOR_JSON_SCHEMA = """
{
  "piyasa_ozeti": "2-3 cümle — dominant tema",
  "analist_sentezi": {
    "makro": {"sinyal": "AL|SAT|BEKLE|TUT|AZALT|ARTIR", "gerekce": "tek cümle"},
    "abd_hisse": {"sinyal": "...", "gerekce": "..."},
    "kripto": {"sinyal": "...", "gerekce": "..."},
    "emtia": {"sinyal": "...", "gerekce": "..."},
    "turkiye": {"sinyal": "...", "gerekce": "..."}
  },
  "celiskiler": [{"baslik": "...", "aciklama": "...", "karar": "...", "kazanan": "..."}],
  "portfoy_aksiyonlari": {
    "hemen_yap": [{"varlik_sinifi": "...", "ticker": "...", "eylem": "...", "miktar_pct": 0, "kaynak": "nakit", "neden": "...", "stop_loss": null, "hedef": null}],
    "kosullu_yap": [{"kosul": "...", "eylem": "...", "ticker": "...", "neden": "..."}],
    "izle_karar_ver": [{"varlik": "...", "izlenecek": "...", "eylem": "..."}],
    "nakit_orani": {"onerilen_pct": 0, "mevcut_pct": 0, "neden": "..."}
  },
  "risk_senaryosu": {
    "tetikleyici": "...", "ilk_24_saat": ["..."],
    "savunma": ["..."],
    "firsat_listesi": [{"ticker": "...", "seviye": 0, "islem": "AL", "neden": "..."}],
    "toparlanma_sinyali": "..."
  },
  "vade_planlari": {
    "kisa": {"sure": "1-3 ay", "baz_senaryo": "...", "risk_senaryosu": "...", "aksiyonlar": ["..."]},
    "orta": {"sure": "3-12 ay", "baz_senaryo": "...", "risk_senaryosu": "...", "aksiyonlar": ["..."]},
    "uzun": {"sure": "1-3 yil", "tema": "...", "pozisyonlama": "..."}
  },
  "yil_sonu_hedefi": {"hedef_pct": 0, "mevcut_pct": 0, "kalan_pct": 0, "gerekan_aylik_pct": 0, "risk_degerlendirmesi": "...", "tavsiye": "..."},
  "senaryo_olasiliklari": {
    "baz":        {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "alternatif": {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "kuyruk":     {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."}
  },
  "harmonize_strateji": "Üç olasılığın ağırlıklı ortalaması olarak özet strateji",
  "korelasyon_sigortasi": {
    "aktif": true,
    "neden": "...",
    "nakit_artirim_pct": 0
  },
  "hisse_mikro_analiz": [
    {"ticker": "...", "etiketler": ["Faiz_indirim_pozitif", "Resesyon_defansif"],
     "fcf_durumu": "yüksek|orta|düşük|N/A", "karar": "KORU|ARTIR|AZALT|SAT",
     "gerekce": "tek cümle"}
  ],
  "tefas_kararlari": [
    {"ticker": "IIH", "icerik": "%90 hisse", "resesyon_risk": "YÜKSEK",
     "karar": "AZALT|TUT|ARTIR", "gerekce": "tek cümle", "valor_notu": "..."}
  ],
  "senaryo_olasiliklari": {
    "baz":        {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "alternatif": {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "kuyruk":     {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."}
  },
  "harmonize_strateji": "Olasılık ağırlıklı tek cümle net karar",
  "korelasyon_sigortasi": {
    "aktif": false, "neden": "...", "nakit_artirim_pct": 0
  },
  "bir_sonraki_kontrol": {
    "tarih": "YYYY-MM-DD",
    "neden": "...",
    "kontrol_sikligi": "günlük|haftalık|aylık",
    "tetikleyiciler": [
      {"tip": "fiyat|takvim|durum", "aciklama": "...", "esik": "...",
       "kontrol_suresi": "24 saat|1 hafta|1 ay içinde"}
    ]
  },
  "nakit_realizasyon_plani": {
    "bugun_t0": "<HESAPLANMIŞ_T0_NAKDE_DÖNÜŞÜM>",
    "t2_tefas": "<HESAPLANMIŞ_T2_TEFAS_SATIŞI>",
    "toplam_hedef": "<SEÇİLEN_NAKİT_HEDEFİ>",
    "tutarli_mi": "<evet_veya_hayir_fark_açıklaması>",
    "not": "<varsa_ek_not>"
  },
  "hard_cap_ihlal": {
    "var_mi": false,
    "ihlal_eden_sinif": "",
    "onerilen_pct": 0,
    "limit_pct": 0,
    "senaryo_istisnasi": "Neden bu senaryoda limit aşılabilir?",
    "alternatif_risk": "İhlal edilirse kötü senaryoda portföy ne kadar zarar görür?"
  }
}

"""



# ─── Claude API Yardımcı Fonksiyonu ──────────────────────────────────────────

def _call_claude(system_prompt: str, user_message: str,
                 max_tokens: int = 1000, retries: int = 2) -> str | None:
    """
    Claude API'ye tek bir çağrı yap.
    Hata durumunda retry ile tekrar dene.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    if not os.getenv("ANTHROPIC_API_KEY", ""):
        logger.error("ANTHROPIC_API_KEY eksik!")
        return None

    for attempt in range(retries + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except Exception as e:
            logger.warning("Claude API attempt %d/%d failed: %s | msg_len=%d",
                           attempt + 1, retries + 1, e, len(user_message))
            if attempt < retries:
                time.sleep(2 ** attempt)
    logger.error("Claude API tüm denemeler başarısız. system_len=%d user_len=%d",
                 len(system_prompt), len(user_message))
    return None


def _safe_json(text: str, fallback: dict = None) -> dict:
    """
    Claude çıktısından JSON parse et.
    Kısmi JSON bile olsa kurtarmaya çalış.
    """
    if not text:
        logger.warning("_safe_json: boş metin")
        return fallback or {}

    original = text
    text = text.strip()

    # Markdown kod bloğu temizle
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # İlk { ile son } arasını al
    first = text.find("{")
    last  = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last+1]

    # Doğrudan parse dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Brace recovery — JSON eksik kapanıyorsa kapat
    open_b  = text.count("{")
    close_b = text.count("}")
    if open_b > close_b:
        text += "}" * (open_b - close_b)
    try:
        return json.loads(text)
    except Exception:
        pass

    # Son çare: sadece piyasa_ozeti çıkarmaya çalış
    try:
        import re
        match = re.search(r'"piyasa_ozeti"\s*:\s*"([^"]+)"', original)
        if match and fallback:
            result = dict(fallback)
            result["piyasa_ozeti"] = match.group(1)
            logger.warning("JSON tam parse edilemedi, sadece piyasa_ozeti kurtarıldı")
            return result
    except Exception:
        pass

    logger.warning("JSON parse tamamen başarısız. İlk 500 karakter: %s", original[:500])
    return fallback or {}


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA A — UZMAN ANALİSTLER
# ═══════════════════════════════════════════════════════════════════════════

# ─── Makro Analist ───────────────────────────────────────────────────────────

MACRO_ANALYST_SYSTEM = """Sen küresel makroekonomik analizde uzmanlaşmış kıdemli bir portföy analistisin.
Fed politikası, küresel likidite döngüleri, kredi piyasaları ve jeopolitik risklerin piyasalara
etkisini değerlendirme konusunda 15 yıllık deneyimin var.

GÖREV SINIRI: Yalnızca sana verilen makroekonomik verileri analiz et. Cross-asset portföy 
kararları verme — bu direktörün işi. Sadece makro ortamı değerlendir.

═══ GETİRİ EĞRİSİ (YIELD CURVE) YORUMLAMA KILAVUZU ═══
Yield curve verisi sana [TIP] etiketiyle gelecek. Aşağıdaki tarihsel ilişkileri uygula:

1. INVERTED (Ters Eğri): 10Y < 3M
   → Yaklaşan resesyon sinyali. Tarihsel: 1980, 1989, 2000, 2007, 2019 öncesinde görüldü.
   → Eğri ne kadar uzun süredir ters kalırsa resesyon riski o kadar yüksek.

2. BULL_STEEPENER — EN KRİTİK SİNYAL:
   Ters eğri NORMALLEŞIYOR + uzun vade faiz DÜŞÜYOR
   → Tarihsel olarak resesyonun BAŞLADIĞININ tescilidir (geç Fed sinyali).
   → 2007/2008 Aralık: eğri normalleşti → Mart 2008 resesyon başladı.
   → 2019/2020: normalleşti → COVID öncesi zaten yavaşlama başlamıştı.
   → Piyasa bu sırada "kurtarıldık" diyebilir ama YANILIR — en tehlikeli iyimserlik tuzağı.
   → Direktöre: "Piyasa normalleşmeyi pozitif okuyabilir, ama bu genellikle zirve öncesi son rallıdır."

3. BEAR_STEEPENER:
   Eğri normalleşiyor + uzun vade faiz YUKARI gidiyor
   → Enflasyon beklentisi veya risk primi artışı.
   → Stagflasyon veya artan borçlanma maliyeti sinyali.
   → Hisseler için orta vadede negatif (discount rate artar).

4. NORMAL (pozitif eğri) + STEEPENING:
   → Büyüme beklentisi güçlü, risk iştahı var.
   → Genellikle ekonomik genişlemenin ortası.

5. FLAT (düzleşen):
   → Büyüme yavaşlıyor, geçiş dönemi.

Bu bilgiyi yorumlarında kullan. "Yield curve normal" demek yetmez —
normalleşmenin YÖNÜnü ve ne anlama geldiğini açıkla.

GÖREV SINIRI: Yalnızca sana verilen makroekonomik verileri analiz et. Cross-asset portföy 
kararları verme — bu direktörün işi. Sadece makro ortamı değerlendir.

YANIT FORMATI: Aşağıdaki JSON formatında yanıt ver, hiçbir alanı boş bırakma:
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net ve somut — neden bu sinyal?",
  "destekleyen": ["Metrik 1 ne söylüyor", "Metrik 2 ne söylüyor"],
  "riskler": ["Bu sinyali bozabilecek faktör 1", "Faktör 2"],
  "oneri": "Makro ortama göre yatırımcıya somut bir tavsiye",
  "izle": "Önümüzdeki 2 haftada en kritik gösterge nedir ve neden?"
}"""



# ─── Sektör Proxy Haritası ────────────────────────────────────────────────────
# yfinance hisse bazlı FCF/metrik bulamazsa, sektör ETF'i proxy olarak kullanılır

SECTOR_ETF_PROXY = {
    # Sektör adı → (Proxy ETF, açıklama)
    "Technology":           ("XLK",  "Teknoloji sektörü"),
    "Financial Services":   ("XLF",  "Finans sektörü"),
    "Healthcare":           ("XLV",  "Sağlık sektörü"),
    "Energy":               ("XLE",  "Enerji sektörü"),
    "Industrials":          ("XLI",  "Sanayi sektörü"),
    "Consumer Cyclical":    ("XLY",  "Döngüsel tüketim"),
    "Consumer Defensive":   ("XLP",  "Defansif tüketim"),
    "Real Estate":          ("XLRE", "Gayrimenkul"),
    "Utilities":            ("XLU",  "Kamu hizmetleri"),
    "Communication Services":("XLC", "İletişim"),
    "Basic Materials":      ("XLB",  "Hammadde"),
    # Kripto varlıklar — bireysel proxy eşlemesi
    "Cryptocurrency":       ("IBIT", "Geniş kripto proxy"),
    "BTC-USD":              ("IBIT", "Bitcoin spot proxy"),
    "ETH-USD":              ("ETHA", "Ethereum ETF proxy"),
    "SOL-USD":              ("IBIT", "Solana — büyük kripto sepeti proxy"),
    "BNB-USD":              ("IBIT", "BNB — büyük kripto sepeti proxy"),
    "XRP-USD":              ("IBIT", "XRP — büyük kripto sepeti proxy"),
    "AVAX-USD":             ("IBIT", "Avalanche — kripto sepeti proxy"),
    "DOGE-USD":             ("IBIT", "Dogecoin — spekülatif kripto proxy"),
    "PEPE-USD":             ("IBIT", "PEPE — spekülatif kripto proxy"),
    "WIF-USD":              ("IBIT", "WIF — meme kripto proxy"),
    # Emtia pozisyonları
    "ALTIN_GRAM_TRY":       ("GLD",  "Altın ETF proxy — TL bazlı altın"),
    "GUMUS_GRAM_TRY":       ("SLV",  "Gümüş ETF proxy — TL bazlı gümüş"),
    "GC=F":                 ("GLD",  "Altın futures proxy"),
    "SI=F":                 ("SLV",  "Gümüş futures proxy"),
    "CL=F":                 ("USO",  "WTI petrol futures proxy"),
    # TEFAS fonları — ilgili ETF proxy
    "IIH":                  ("EWT",  "Hisse yoğun TEFAS — EM hisse proxy"),
    "AEY":                  ("GLD",  "Altın TEFAS — altın ETF proxy"),
    "TTE":                  ("XLK",  "Teknoloji TEFAS — teknoloji ETF proxy"),
    "MAC":                  ("XLF",  "Banka TEFAS — finans ETF proxy"),
    "GAF":                  ("SHV",  "Kamu tahvil TEFAS — kısa tahvil proxy"),
    "NNF":                  ("IWM",  "Büyüme TEFAS — küçük sermayeli proxy"),
    "YAC":                  ("AOM",  "Dengeli TEFAS — dengeli ETF proxy"),
    # Özel ABD şirket eşlemeleri
    "PLTR": ("XLK",  "Yazılım/AI — Teknoloji proxy"),
    "CRWD": ("XLK",  "Siber güvenlik — Teknoloji proxy"),
    "SOFI": ("XLF",  "Fintech — Finans proxy"),
    "RKLB": ("XLI",  "Uzay/Savunma — Sanayi proxy"),
    "VRT":  ("XLI",  "Veri merkezi altyapı — Sanayi proxy"),
    "AVGO": ("XLK",  "Yarı iletken — Teknoloji proxy"),
    "AMZN": ("XLY",  "E-ticaret/Bulut — Tüketim/Teknoloji proxy"),
    "ZETA": ("XLK",  "Ad-tech — Teknoloji proxy"),
    "NBIS": ("XLK",  "AI chip — Teknoloji proxy"),
    "SCHD": ("VYM",  "Temettü ETF — yüksek temettü proxy"),
    "PPA":  ("XLI",  "Savunma ETF — sanayi proxy"),
}


# ─── Merkezi TEFAS Fon Veri Tabanı ───────────────────────────────────────────
# KAP ve fonun resmi tanıtım belgelerinden derlendi.
# Bilinmeyen fonlar için ASLA tahmin yapma — "BILINMIYOR_SAT" kuralı geçerli.
# Format: kod → (tip, içerik_özeti, resesyon_riski, kur_riski, beta_seviyesi, notlar)

TEFAS_DB = {
    # FORMAT: kod → (tip, içerik, resesyon_riski, kur_riski, beta, not)
    # KUR_RİSKİ: YÜKSEK=TL bazlı zarar görür | DÜŞÜK=yabancı varlık, kur korumalı
    # TL KRİZİNDE KURAL: Kur Riski DÜŞÜK → TL değer kaybı fon TL fiyatını ARTTIRIR

    # ── Yerli Ağırlıklı Hisse Fonları ───────────────────────────────────────
    "IIH":  ("Hisse Yoğun YERLİ",
             "BIST büyük şirket ~%80 yerli + ~%10 yabancı hisse",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Ağırlıklı BIST yerli hisse. TL krizi = çift darbe (BIST düşer + TL erir)."),

    "NNF":  ("Hisse Senedi Birinci YERLİ",
             "BIST hisse ~%90-95 tamamen yerli — TAHVİL DEĞİL",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Agresif YERLİ BIST hisse fonu. TL krizi = tam maruz kalım."),

    "MAC":  ("Hisse Banka/Finans YERLİ",
             "BIST bankacılık ve finans ~%80 yerli",
             "ÇOK_YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Yerli banka hisseleri. Kredi döngüsü + TL krizine çok hassas."),

    "YAS":  ("Hisse Karma YERLİ",
             "Çeşitlendirilmiş BIST ~%80 yerli",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Çeşitlendirilmiş BIST yerli hisse fonu. TL krizinde korumasız."),

    # ── Yabancı Ağırlıklı (Kur Korumalı) Hisse Fonları ──────────────────────
    "TTE":  ("Hisse Teknoloji YABANCI/KUR_KORUMALI",
             "Yabancı teknoloji ~%70-80 (Nasdaq/S&P tekno) + yerli tekno ~%20-30",
             "ORTA", "DÜŞÜK", "ÇOK_YÜKSEK",
             "⚠️ KUR KORUMALI: Ağırlıklı yabancı (Nasdaq) hisse. "
             "TL %30 değer kaybında fon TL fiyatı YUKARI gider. "
             "Türkiye şokunda SATMA — resesyon riski var ama kur koruması sağlar."),

    "AOY":  ("ALTERNATİF ENERJİ YABANCI — ALTIN FONU DEĞİL",
             "Yabancı alternatif/temiz enerji hisseleri ~%80-90 (solar, rüzgar, EV)",
             "ORTA", "DÜŞÜK", "YÜKSEK",
             "⚠️ KRİTİK UYARI: AOY ALTIN FONU DEĞİL. "
             "Alternatif/Temiz Enerji yabancı hisse fonudur — enflasyon hedge değil. "
             "KUR KORUMALI: TL değer kaybında TL fiyatı artar."),

    # ── Altın / Kıymetli Maden Fonları (Kur Korumalı) ────────────────────────
    "AEY":  ("Altın/Kıymetli Maden KUR_KORUMALI",
             "Fiziksel altın + altın ETF ~%80, dolar bazlı",
             "DÜŞÜK", "DÜŞÜK", "ORTA",
             "Gerçek altın fonu. Enflasyon ve döviz hedge. TL değer kaybında TL fiyatı ARTAR."),

    "GLD":  ("Altın ETF KUR_KORUMALI",
             "Fiziksel altın ~%99, dolar bazlı",
             "DÜŞÜK", "DÜŞÜK", "ORTA",
             "Uluslararası altın ETF. Kur korumalı."),

    # ── Dengeli / Karma Fonlar ────────────────────────────────────────────────
    "YAC":  ("Dengeli Karma",
             "Hisse %50 (karma yerli/yabancı) + Tahvil %50",
             "ORTA", "ORTA", "ORTA",
             "Dengeli fon. Yabancı hisse oranı için KAP teyidi önerilir."),

    "NNM":  ("Dengeli Karma",
             "Hisse + Tahvil + Altın — oranlar değişken",
             "ORTA", "ORTA", "ORTA",
             "Karma strateji. KAP aylık raporu teyidi gerekli."),

    # ── TL Bazlı Tahvil / Para Piyasası Fonları ───────────────────────────────
    "GAF":  ("Kamu Menkul Kıymet TL_BAZLI",
             "TL devlet tahvili ~%90",
             "DÜŞÜK", "YÜKSEK", "DÜŞÜK",
             "TL devlet tahvili. TL krizinde dolar bazlı değer erir."),

    "TI1":  ("Tahvil Kısa Vade TL_BAZLI",
             "Kısa vadeli TL tahvil ~%90",
             "DÜŞÜK", "YÜKSEK", "DÜŞÜK",
             "Kısa vadeli TL tahvil. TL krizinde eritici."),

    "TSI":  ("Para Piyasası TL_BAZLI",
             "Kısa vadeli TL menkul kıymet",
             "DÜŞÜK", "YÜKSEK", "ÇOK_DÜŞÜK",
             "Para piyasası benzeri. TL krizinde eritici."),

    # ── Yabancı Emtia / Enerji Fonları (Kur Korumalı) ─────────────────────────
    "URA":  ("Uranyum/Nükleer Enerji YABANCI/KUR_KORUMALI",
             "Yabancı uranyum şirketleri + ETF ~%80 (CCJ, NXE vb.)",
             "ORTA", "DÜŞÜK", "YÜKSEK",
             "Nükleer rönesans. YABANCI şirketler. KUR KORUMALI. Volatil ama yapısal."),
}


# Sözlükte olmayan fonlar için güvenli fallback
TEFAS_UNKNOWN_RULE = (
    "BİLİNMEYEN",
    "İçerik doğrulanmadı — KAP teyidi gerekli",
    "BELİRSİZ",
    "BELİRSİZ",
    "BELİRSİZ",
    "⚠️ UYARI: Bu fon için içerik tahmini YAPILMAMALI. "
    "Pozisyon küçükse koru, büyükse içerik netleşene kadar küçük azalt. "
    "Direktör halüsinasyon üretmemeli."
)


def _fetch_sector_proxy_metrics(ticker: str, sector: str) -> dict:
    """
    Hisse bazlı metrik yoksa sektör ETF proxy'si kullan.
    Döndürür: {beta, fcf_str, note}
    """
    import yfinance as _yf_px
    
    # Proxy ETF'i belirle
    proxy_etf, proxy_label = SECTOR_ETF_PROXY.get(
        ticker,
        SECTOR_ETF_PROXY.get(sector, ("SPY", "Geniş piyasa proxy"))
    )
    
    try:
        etf_info = _yf_px.Ticker(proxy_etf).info
        etf_beta = etf_info.get("beta", "N/A")
        
        # ETF'in 3 aylık performansı FCF proxy olarak
        hist = _yf_px.Ticker(proxy_etf).history(period="3mo")
        if len(hist) >= 2:
            perf_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
            perf_str = f"{perf_3m:+.1f}% (3ay)"
        else:
            perf_str = "N/A"
        
        return {
            "beta":    etf_beta,
            "fcf_str": f"Proxy({proxy_etf}): {perf_str}",
            "note":    f"{proxy_label} → {proxy_etf} proxy kullanıldı",
            "proxy":   True,
        }
    except Exception:
        return {"beta": "N/A", "fcf_str": "N/A", "note": "Proxy alınamadı", "proxy": True}


def analyze_macro_with_claude(macro_data: dict, economic_data: dict) -> dict:
    """Makro analist — Fed, likidite, büyüme, risk ortamı."""
    # Özet veri hazırla — ham sayı değil yorumlanmış metrikler
    indicators = macro_data.get("indicators", {})
    regime     = macro_data.get("regime",     {})

    lines = ["=== MAKRO GÖSTERGELERİN ÖZETI ==="]

    # Sinyal motoru zaten yorumladı — onları kullan
    for key, ind in indicators.items():
        if isinstance(ind, dict) and ind.get("note"):
            sig = ind.get("signal", "neutral")
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.get('label', key)}: {ind.get('note', '')}")
        elif hasattr(ind, "note") and ind.note:
            sig = ind.signal
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.label}: {ind.note}")

    if regime:
        lines.append(f"\nPiyasa Rejimi: {regime.get('label', '—')} — {regime.get('description', '')}")

    # Ekonomik göstergeler ekle
    econ = economic_data.get("macro_econ", {})
    if econ:
        lines.append("\n=== EKONOMİK VERİLER ===")
        for key, ind in econ.items():
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    message = "\n".join(lines)
    result  = _call_claude(MACRO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Makro veri alınamadı",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_macro"
    return parsed


# ─── ABD Hisse Analisti ──────────────────────────────────────────────────────

US_EQUITY_ANALYST_SYSTEM = """Sen ABD hisse senedi piyasalarında uzmanlaşmış kıdemli bir portföy analistisin.
S&P 500 değerlemesi, sektör rotasyonu, kurumsal kazanç döngüleri ve teknik analiz konularında
derinlemesine bilgiye sahipsin.

GÖREV SINIRI: Yalnızca ABD hisse senedi piyasasını analiz et.

KESKİN NİŞANCI MODU — MİKRO METRİK ODAĞI:
Makro görüşün yanında, portföydeki her ABD hissesini aşağıdaki üç filtreden geçir:

1. FCF YİELD & BORÇLULUK (Resesyon Direnci):
   - Serbest nakit akışı getirisi yüksek (>%5) ve borç/özkaynak düşük (<1.0) şirketler
     resesyon döneminde hayatta kalır. Bunları "Defansif Kalite" olarak etiketle.
   - Borç yükü yüksek ve negatif FCF'li şirketler faiz artışında ilk çökenlerdir.

2. AI ÜRETKENLİK İZİ (Revenue per Employee Trendi):
   - Şirketin son 2-4 çeyrekte çalışan başına geliri artıyorsa AI operasyonel kazanım
     sağlıyor demektir. Bu şirketi "AI Verimlilik Lideri" olarak etiketle.
   - Azalıyorsa kalabalık iş gücü maliyeti rekabet avantajını yiyor.

3. MAKRO DUYARLILIK ETİKETİ:
   Her hisse için şu etiketleri kullan:
   - Faiz_indirim_pozitif / Faiz_indirim_negatif
   - Resesyon_defansif / Resesyon_hassas
   - Dolar_zayiflama_pozitif / Dolar_zayiflama_negatif

4. ŞİRKET PROFİLİ NÜANSI (kör nokta önleme):
   Şirketleri yüzeysel kategorizasyonla değil gerçek iş modeline göre değerlendir:
   - AMZN: e-ticaret DEĞİL — gelirin %70+ AWS (kurumsal bulut). Tüketici harcaması sadece %30.
     Stagflasyon/resesyonda AWS kurumsal bulut harcaması tüketiciye göre çok daha dayanıklı.
   - MSFT: Azure + Office SaaS — yapısal talep, resesyon defansif.
   - GOOGL: Reklam geliri döngüsel AMA bulut büyüyor, iki ayrı iş modeli.
   - NVDA: Veri merkezi %80 — tüketici GPU döngüsel, datacenter yapısal.
   - CRWD: SaaS recurring revenue, müşteri churn düşük — siber güvenlik zorunlu harcama.
     Negatif reel faiz ortamında büyüme hissesi DCF değeri ARTAR (iskonto düşer) — sat değil koru.
   - SOFI: Tüketici kredisi — faize çok hassas, resesyonda kredi kayıpları artar.
   - PLTR: Devlet + kurumsal yazılım — resesyona dayanıklı, savunma bütçesi kesilmez.
   - BTC madencileri (IREN, MARA): Enerji maliyeti yüksek, petrol/enerji fiyatına çok hassas.
   Bu nüansları her karar gerekçesine yansıt.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "sektor_gorusu": "Hangi sektör güçlü/zayıf",
  "deger_leme": "Piyasa ucuz mu pahalı mı",
  "hisse_mikro_analiz": [
    {
      "ticker": "TICKER",
      "beta": 0.0,
      "fcf_yield_tahmini": "yüksek|orta|düşük|negatif",
      "borc_durumu": "güçlü|orta|riskli",
      "ai_uretkenlik": "lider|orta|geri_kaliyor",
      "makro_duyarlilik": ["Faiz_indirim_pozitif", "Resesyon_defansif"],
      "aksiyon": "KORU|ARTIR|AZALT|SAT",
      "gerekce": "tek cümle"
    }
  ],
  "destekleyen": ["Faktör 1", "Faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut genel öneri",
  "izle": "Kritik gösterge"
}"""


def analyze_us_equity_with_claude(economic_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """ABD hisse analisti — değerleme, sektör rotasyonu, kazanç."""
    lines = ["=== ABD HİSSE PİYASASI ANALİZİ ==="]

    # Değerleme — economic_data içinde yoksa üst seviye dict'te ara
    val = economic_data.get("sp500_valuation") or economic_data.get("valuation", {})
    if val:
        lines.append(f"S&P 500 Değerleme: {val.get('note', '')}")

    # Sektör rotasyonu
    sr = economic_data.get("sector_rotation") or economic_data.get("sectors", {})
    if sr:
        note = sr.get("rotation_note", "")
        if note:
            lines.append(f"Sektör Rotasyonu: {note}")
        secs = sr.get("sectors", [])
        if secs:
            top3    = sorted(secs, key=lambda x: x.get("rel_1m", 0), reverse=True)[:3]
            bottom3 = sorted(secs, key=lambda x: x.get("rel_1m", 0))[:3]
            lines.append("Lider sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in top3))
            lines.append("Zayıf sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in bottom3))

    # Ekonomik veriler
    econ = economic_data.get("macro_econ", {})
    for key in ["ISM_MFG", "ISM_SVC", "NFP", "GDP"]:
        ind = econ.get(key)
        if ind:
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    # Portföydeki hisseler — mikro metriklerle
    us_positions = [p for p in portfolio_positions
                    if p.get("asset_class", "us_equity") == "us_equity"
                    and float(p.get("shares", 0)) > 0]
    if us_positions:
        lines.append(f"\n=== PORTFÖYDEKİ ABD HİSSELERİ ({len(us_positions)} pozisyon) ===")
        lines.append("Her hisse için FCF yield, beta, borç durumu ve makro duyarlılığını değerlendir.")
        logger.info("ABD hisse mikro analiz: %d pozisyon", len(us_positions))
        
        # yfinance'ten mikro metrikler çek
        try:
            import yfinance as _yf_micro
            for p in us_positions[:10]:
                ticker = p["ticker"]
                cur    = p.get("current_price", p["avg_cost"])
                avg    = p["avg_cost"]
                pnl    = (cur - avg) / avg * 100 if avg > 0 else 0
                shares = float(p.get("shares", 0))
                val    = shares * cur
                
                # Temel metrikler — her alan için ayrı fallback
                try:
                    info = _yf_micro.Ticker(ticker).info
                except Exception:
                    info = {}

                def _safe(val, default="N/A"):
                    import math
                    if val is None: return default
                    try:
                        if isinstance(val, float) and math.isnan(val): return default
                    except Exception: pass
                    return val

                try:
                    beta      = _safe(info.get("beta"), "N/A")
                    beta_str  = f"{beta:.1f}" if isinstance(beta, float) else str(beta)

                    fcf       = float(_safe(info.get("freeCashflow"), 0) or 0)
                    mktcap    = float(_safe(info.get("marketCap"),    0) or 0)
                    fcf_yield = round(fcf / mktcap * 100, 1) if mktcap > 0 and fcf != 0 else 0
                    fcf_str   = f"{fcf_yield:+.1f}%" if fcf_yield != 0 else "N/A"

                    de_raw    = _safe(info.get("debtToEquity"), None)
                    de_str    = f"{float(de_raw):.1f}" if de_raw is not None else "N/A"

                    # ── Current Ratio (Cari Oran) — Zombi filtresi ────────
                    # FCF negatif VEYA Current Ratio < 1.0 → Zombi adayı
                    cr_raw    = _safe(info.get("currentRatio"), None)
                    cr_val    = float(cr_raw) if cr_raw is not None else None
                    cr_str    = f"{cr_val:.2f}" if cr_val is not None else "N/A"

                    # Zombi skoru: 0=sağlıklı, 1=dikkat, 2=zombi
                    zombi_score = 0
                    zombi_flags = []
                    if fcf < 0:
                        zombi_score += 1
                        zombi_flags.append("FCF<0")
                    if cr_val is not None and cr_val < 1.0:
                        zombi_score += 1
                        zombi_flags.append(f"CariOran<1({cr_val:.2f})")
                    if de_raw is not None and float(de_raw) > 200:
                        zombi_score += 1
                        zombi_flags.append("AşırıBorç")

                    zombi_tag = (
                        "🧟 ZOMBİ"   if zombi_score >= 2 else
                        "⚠️ DİKKAT"  if zombi_score == 1 else
                        "✅ SAĞLIKLI"
                    )
                    zombi_note = f"[{zombi_tag}: {', '.join(zombi_flags)}]" if zombi_flags else f"[{zombi_tag}]"

                    rev       = float(_safe(info.get("totalRevenue"),      0) or 0)
                    emp       = float(_safe(info.get("fullTimeEmployees"), 0) or 0)
                    rpe_str   = f"Gelir/Çalışan:${rev/emp/1000:.0f}K" if rev > 0 and emp > 0 else ""

                    lines.append(
                        f"• {ticker}: K/Z %{pnl:+.0f} | Değer:${val:,.0f} | "
                        f"Beta:{beta_str} | FCF:{fcf_str} | CariOran:{cr_str} | "
                        f"Borç/ÖK:{de_str} | {rpe_str} | {zombi_note} | "
                        f"Sektör:{p.get('sector','?')}"
                    )
                except Exception:
                    # yfinance başarısız → sektör proxy kullan
                    try:
                        _px = _fetch_sector_proxy_metrics(ticker, p.get("sector",""))
                        lines.append(
                            f"• {ticker}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} | "
                            f"Beta: {_px['beta']} | FCF: {_px['fcf_str']} | "
                            f"Sektör: {p.get('sector','?')} | [{_px['note']}]"
                        )
                    except Exception:
                        lines.append(
                            f"• {ticker}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} | "
                            f"Beta: N/A | FCF: N/A | Sektör: {p.get('sector','?')}"
                        )
        except Exception:
            for p in us_positions[:8]:
                pnl = ((p.get("current_price", p["avg_cost"]) - p["avg_cost"])
                       / p["avg_cost"] * 100) if p["avg_cost"] > 0 else 0
                lines.append(f"• {p['ticker']}: K/Z %{pnl:+.0f}, Sektör: {p.get('sector','?')}")

    # Sinyal motoru sinyali
    us_sig = signal_summary.get("us_equity", {})
    if us_sig:
        lines.append(f"\nSinyal Motoru: {us_sig.get('signal','?')} (güven: {us_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(US_EQUITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "ABD hisse verisi çekilemedi — portföy pozisyonları ve makro bağlamla değerlendiriliyor",
        "sektor_gorusu": "Veri eksik", "deger_leme": "Veri eksik",
        "destekleyen": [], "riskler": [], "oneri": "Veri eksik — makro bağlama göre değerlendir", "izle": ""
    })
    parsed["_source"] = "claude_us_equity"
    return parsed


# ─── Kripto Analisti ─────────────────────────────────────────────────────────

CRYPTO_ANALYST_SYSTEM = """Sen kripto varlık piyasalarında uzmanlaşmış kıdemli bir analistin.
On-chain metrikler, Bitcoin halving döngüleri, altcoin dinamikleri ve kripto piyasası
psikolojisi konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca kripto piyasasını analiz et. Hisse senetleri, Türkiye veya emtia 
hakkında yorum yapma.

NOT: MVRV, SOPR gibi değerler yfinance'ten hesaplanan proxy değerlerdir, Glassnode'dan 
gerçek on-chain veri değil. Bunu yorumlarında göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dongu_pozisyonu": "Halving döngüsünde neredeyiz?",
  "onchain_ozet": "On-chain metrikler ne söylüyor?",
  "btc_vs_altcoin": "BTC mi altcoin mi tercih edilmeli?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_crypto_with_claude(crypto_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Kripto analisti — on-chain, döngü, sentiment."""
    lines = ["=== KRİPTO PİYASASI ANALİZİ ==="]

    fg  = crypto_data.get("fear_greed",  {})
    dom = crypto_data.get("dominance",   {})
    hal = crypto_data.get("halving",     {})
    onc = crypto_data.get("onchain",     {})
    stb = crypto_data.get("stablecoin",  {})
    ls  = crypto_data.get("long_short",  {})
    nvt = crypto_data.get("nvt",         {})
    spr = crypto_data.get("sopr",        {})
    prc = crypto_data.get("prices",      {})

    if fg.get("note"):   lines.append(f"Fear & Greed: {fg['note']}")
    if hal.get("note"):  lines.append(f"Halving Döngüsü: {hal['note']}")
    if dom.get("dom_note"): lines.append(f"Dominance: {dom['dom_note']}")

    mvrv = onc.get("mvrv_proxy", {})
    if mvrv.get("note"):  lines.append(f"MVRV Proxy: {mvrv['note']}")
    rsi  = onc.get("btc_rsi", {})
    if rsi.get("note"):   lines.append(f"BTC RSI: {rsi['note']}")
    if spr.get("note"):   lines.append(f"SOPR Proxy: {spr['note']}")
    if nvt.get("note"):   lines.append(f"NVT Signal: {nvt['note']}")
    if ls.get("note"):    lines.append(f"Long/Short: {ls['note']}")
    if stb.get("note"):   lines.append(f"Stablecoin: {stb['note']}")

    # BTC fiyatı
    btc = prc.get("BTC", {})
    if btc.get("price"):
        lines.append(f"BTC: ${btc['price']:,.0f} ({btc.get('change_24h',0):+.1f}%), 52H pos: %{btc.get('52h_pos',0):.0f}")

    # Kripto pozisyonları
    crypto_pos = [p for p in portfolio_positions if p.get("asset_class") == "crypto"
                  and float(p.get("shares", 0)) > 0]
    if crypto_pos:
        lines.append("\n=== KRİPTO POZİSYONLARI (MİKRO ANALİZ) ===")
        lines.append("Her token için volatilite seviyesi, beta ve makro duyarlılığını değerlendir.")
        # Kripto beta haritası (BTC=1.0 bazlı)
        CRYPTO_BETA = {
            "BTC-USD": 1.0, "ETH-USD": 1.3, "SOL-USD": 1.8,
            "BNB-USD": 1.4, "XRP-USD": 1.5, "AVAX-USD": 1.9,
            "DOGE-USD": 2.2, "PEPE-USD": 3.5, "WIF-USD": 4.0,
            "JUP-USD": 2.8, "INJ-USD": 2.5, "SUI-USD": 2.3,
        }
        crypto_total = sum(float(p.get("shares",0)) * float(p.get("current_price", p["avg_cost"])) for p in crypto_pos)
        for p in crypto_pos:
            cur  = float(p.get("current_price", p["avg_cost"]))
            avg  = float(p["avg_cost"])
            pnl  = (cur - avg) / avg * 100 if avg > 0 else 0
            val  = float(p.get("shares", 0)) * cur
            pct_in_crypto = val / crypto_total * 100 if crypto_total > 0 else 0
            beta = CRYPTO_BETA.get(p["ticker"], 2.0)  # bilinmeyenler için 2.0
            # Spekülatif mi defansif mi?
            tag = "BTC_DEFANSIF" if p["ticker"] == "BTC-USD" else (
                  "ETH_ORTA" if p["ticker"] == "ETH-USD" else "SPEKULATIF_YUKSEK_BETA")
            # Proxy verisi
            try:
                _px = _fetch_sector_proxy_metrics(p["ticker"], "Cryptocurrency")
                proxy_note = f"Proxy: {_px['fcf_str']}"
            except Exception:
                proxy_note = ""
            lines.append(
                f"• {p['ticker']}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} "
                f"(%{pct_in_crypto:.0f} kripto içi) | Beta(BTC=1): {beta:.1f} | "
                f"[{tag}] | {proxy_note}"
            )

    crypto_sig = signal_summary.get("crypto", {})
    if crypto_sig:
        lines.append(f"\nSinyal Motoru: {crypto_sig.get('signal','?')} (güven: {crypto_sig.get('confidence','?')}/10)")

    # Veri yoksa bile portföy pozisyonları üzerinden analiz yap
    if len(lines) <= 3:
        lines.append("Not: Piyasa verisi çekilemedi. Portföy pozisyonları ve genel makro bağlamla analiz yapılıyor.")

    message = "\n".join(lines)
    result  = _call_claude(CRYPTO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Kripto verisi çekilemedi — genel makro bağlamla değerlendiriliyor",
        "dongu_pozisyonu": "Veri eksik", "onchain_ozet": "Veri eksik", "btc_vs_altcoin": "Veri eksik",
        "destekleyen": [], "riskler": [], "oneri": "Veri eksik — makro bağlama göre değerlendir", "izle": ""
    })
    parsed["_source"] = "claude_crypto"
    return parsed


# ─── Emtia Analisti ──────────────────────────────────────────────────────────

COMMODITY_ANALYST_SYSTEM = """Sen emtia piyasalarında, özellikle altın ve enerji sektöründe
uzmanlaşmış kıdemli bir analistin. Reel faiz dinamikleri, merkez bankası politikaları,
jeopolitik risk ve emtia döngüleri konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca emtia piyasasını analiz et.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "altin_gorusu": "Altın için temel tez nedir?",
  "petrol_gorusu": "Petrol piyasası ne söylüyor?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_commodity_with_claude(commodity_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """Emtia analisti — altın reel faiz, petrol, jeopolitik."""
    lines = ["=== EMTİA PİYASASI ANALİZİ ==="]

    grr = commodity_data.get("gold_real_rate", {})
    cbg = commodity_data.get("cb_gold_proxy",  {})
    udg = commodity_data.get("us_debt_gold",   {})
    oil = commodity_data.get("oil",            {})
    cu  = commodity_data.get("copper",         {})
    geo = commodity_data.get("geo_news",       {})
    prc = commodity_data.get("prices",         {})

    if grr.get("note"): lines.append(f"Reel Faiz: {grr['note']}")
    if cbg.get("note"): lines.append(f"MB Altın Alımı Proxy: {cbg['note']}")
    if udg.get("note"): lines.append(f"ABD Borç/Altın Tezi: {udg['note'][:120]}")
    if oil.get("note"): lines.append(f"Petrol: {oil['note']}")
    if cu.get("gc_note"): lines.append(f"Altın/Bakır Oranı: {cu['gc_note']}")
    if geo.get("note"): lines.append(f"Jeopolitik: {geo['note']}")

    gold = prc.get("GOLD", {})
    if gold.get("price"):
        lines.append(f"Altın: ${gold['price']:,.0f}/oz ({gold.get('change',0):+.1f}%), 52H: %{gold.get('pos_52h',0):.0f}")

    comm_pos = [p for p in portfolio_positions if p.get("asset_class") == "commodity"
                and float(p.get("shares", 0)) > 0]
    if comm_pos:
        lines.append("\n=== EMTİA POZİSYONLARI (MİKRO ANALİZ) ===")
        COMM_TAGS = {
            "ALTIN_GRAM_TRY": ("Altın (TRY gram)",    "GLD",  "Enflasyon_koruyucu Resesyon_defansif Dolar_zayiflama_pozitif"),
            "GUMUS_GRAM_TRY": ("Gümüş (TRY gram)",    "SLV",  "Enflasyon_koruyucu Sanayi_baglantili"),
            "GC=F":           ("Altın Futures",         "GLD",  "Enflasyon_koruyucu Resesyon_defansif"),
            "SI=F":           ("Gümüş Futures",         "SLV",  "Enflasyon_koruyucu Sanayi_baglantili"),
            "CL=F":           ("WTI Petrol",            "USO",  "Resesyon_hassas Jeopolitik_pozitif"),
            "NG=F":           ("Doğal Gaz",             "UNG",  "Enerji_baglantili Mevsimsel"),
        }
        for p in comm_pos:
            cur  = float(p.get("current_price", p["avg_cost"]))
            avg  = float(p["avg_cost"])
            pnl  = (cur - avg) / avg * 100 if avg > 0 else 0
            val  = float(p.get("shares", 0)) * cur
            cur_try = p.get("currency") == "TRY"
            val_note = f"{val:,.0f} TRY" if cur_try else f"${val:,.0f}"
            tag_info = COMM_TAGS.get(p["ticker"], (p["ticker"], "GLD", "Emtia"))
            label, proxy_etf, tags = tag_info
            # Proxy performansı
            try:
                import yfinance as _yf_cm
                hist = _yf_cm.Ticker(proxy_etf).history(period="1mo")
                proxy_perf = (hist["Close"].iloc[-1]/hist["Close"].iloc[0]-1)*100 if len(hist)>=2 else 0
                proxy_note = f"Proxy({proxy_etf}): {proxy_perf:+.1f}% (1ay)"
            except Exception:
                proxy_note = f"Proxy: {proxy_etf}"
            lines.append(
                f"• {p['ticker']} [{label}]: K/Z %{pnl:+.0f} | Değer: {val_note} | "
                f"[{tags}] | {proxy_note}"
            )

    comm_sig = signal_summary.get("commodity", {})
    if comm_sig:
        lines.append(f"\nSinyal Motoru: {comm_sig.get('signal','?')} (güven: {comm_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(COMMODITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "altin_gorusu": "", "petrol_gorusu": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_commodity"
    return parsed


# ─── Türkiye Analisti ─────────────────────────────────────────────────────────

TURKEY_ANALYST_SYSTEM = """Sen Türkiye hisse senedi piyasası ve gelişen piyasalarda uzmanlaşmış
kıdemli bir analistin. BIST dinamikleri, TL/kur riski, TCMB politikası, bankacılık sektörü
ve yabancı yatırımcı akışları konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca Türkiye piyasasını analiz et.

ÖNEMLİ: Tüm getiri hesaplamalarında hem TL bazlı hem dolar bazlı değerlendirme yap.
TL bazında kazanç, dolar bazında kayıp olabilir — her zaman dolar bazlı gerçek getiriyi göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dolar_bazli_degerleme": "BIST dolar bazlı ucuz mu pahalı mı?",
  "xbank_gorusu": "XBANK sinyali ne söylüyor?",
  "kur_riski": "TL riski ne durumda?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_turkey_with_claude(turkey_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Türkiye analisti — BIST dolar bazlı, XBANK, kur, yabancı."""
    lines = ["=== TÜRKİYE BORSASI ANALİZİ ==="]

    from turkey_fetcher import build_turkey_prompt
    lines.append(build_turkey_prompt(turkey_data))

    tefas_pos = [p for p in portfolio_positions if p.get("asset_class") == "tefas"
                 and float(p.get("shares", 0)) > 0]
    if tefas_pos:
        lines.append("\n=== TEFAS POZİSYONLARI (LOOK-THROUGH ANALİZİ) ===")
        # Bilinen fon içerik haritası — KAP aylık raporlarından derlendi
        # TEFAS_DB merkezi veri tabanından çek — bilinmeyende UYARI ver
        for p in tefas_pos:
            kod     = p["ticker"].upper()
            db_entry = TEFAS_DB.get(kod, TEFAS_UNKNOWN_RULE)
            tip, icerik, ress_duy, kur_risk, beta, notlar = db_entry
            val_tl  = float(p.get("shares", 0)) * float(p.get("current_price", p.get("avg_cost", 0)))
            bilinmiyor = (tip == "BİLİNMEYEN")
            lines.append(
                f"• {kod} [{tip}]: {p['shares']:,.0f} adet | ~{val_tl:,.0f} TL | "
                f"İçerik: {icerik} | Resesyon: {ress_duy} | Beta: {beta} | Kur: {kur_risk}"
                + (f"\n  ⚠️ {notlar}" if bilinmiyor else f"\n  📋 {notlar[:80]}")
            )
        lines.append("KURAL: Bilinmeyen fon için halüsinasyon/tahmin YASAK. "
                     "İçerik doğrulanana kadar koru veya küçük azalt.")

    tr_sig = signal_summary.get("turkey", {})
    if tr_sig:
        lines.append(f"\nSinyal Motoru: {tr_sig.get('signal','?')} (güven: {tr_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(TURKEY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "dolar_bazli_degerleme": "", "xbank_gorusu": "", "kur_riski": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_turkey"
    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA B — STRATEJİ DİREKTÖRÜ
# ═══════════════════════════════════════════════════════════════════════════

def _build_director_system(user_profile: dict, year_target_pct: float,
                           memory_context: str = "") -> str:
    """
    Direktörün sistem promptunu kullanıcı profiline göre oluştur.
    Kimlik + karar çerçevesi + kişisel parametreler + zorunlu çıktılar.
    memory_context: MemoryManager'dan gelen hafıza bağlamı (prompt'un başına eklenir).
    """
    time_horizon  = user_profile.get("time_horizon",  "1-3 yıl (Uzun Vade)")
    risk_tol      = user_profile.get("risk_tol",      "Orta-Yüksek")
    cash_cycle    = user_profile.get("cash_cycle",    "3 ayda bir")
    goal          = user_profile.get("goal",          "Uzun vadeli büyüme")

    # Hafıza bağlamını promptun en başına enjekte et
    memory_block = (
        f"{memory_context}\n\n"
        if memory_context.strip() else ""
    )

    return f"""{memory_block}Sen çok varlıklı portföy yönetiminde uzmanlaşmış kıdemli bir strateji direktörüsün.
ABD hisse senetleri, kripto varlıklar, emtialar (özellikle altın) ve Türkiye borsası olmak üzere
dört farklı piyasayı eş zamanlı yönetme deneyimine sahipsin.

Beş farklı uzman analistten rapor alıyorsun (makro, ABD hisse, kripto, emtia, Türkiye).
Görevin bu raporları sentezleyip müşteri için kişiselleştirilmiş, somut ve eyleme 
dönüştürülebilir bir strateji üretmek.

═══ KARAR ÇERÇEVESİ HİYERARŞİSİ ═══
Çelişkili sinyaller olduğunda şu öncelik sırasını uygula:
1. MAKRO REJİM — Risk-off modu aktifse bireysel varlık AL sinyalleri ikincil plana düşer
2. KORELASYONsuz ÇEŞİTLENDİRME — Yüksek korelasyonlu varlıklar (BTC/Tech gibi) 
   aynı anda artırılamaz. Bu çeşitlendirme yanılgısıdır.
3. RİSK/ÖDÜL DENGESİ — Her öneride potansiyel kazancı potansiyel kayıpla kıyasla
4. LİKİDİTE — Nakit yetersizse önce en riskli pozisyonlar küçültülür

═══ MÜŞTERİ PROFİLİ ═══
• Zaman ufku: {time_horizon}
• Risk toleransı: {risk_tol} (%20 drawdown tolere edilir)
• Nakit döngüsü: {cash_cycle}
• Hedef: {goal}
• Yıl sonu getiri hedefi: %{year_target_pct:.0f}
• Konum: Türkiye'de yaşıyor — enflasyonu yenmek öncelik, dolar bazlı getiri kritik
• Bu yatırımlar daha büyük bir portföyün parçası

═══ ZORUNLU YANIT ALANLARI ═══
Aşağıdaki her alan dolu olmalı — hiçbirini boş bırakma:

piyasa_ozeti: Piyasada dominant tema nedir? (2-3 cümle, anlaşılır)
analist_sentezi: Her analistin sinyali + tek cümle gerekçe
celiskiler: Analistler arasındaki çelişkileri tespit et ve çöz (hangi görüş neden üstün?)
portfoy_aksiyonlari: Hemen yap / koşullu yap / izle-karar ver
risk_senaryosu: Kötü senaryo tetikleyici + somut adımlar
vade_planlari: Kısa/orta/uzun vade için baz ve risk senaryoları
yil_sonu_hedefi: Hedefe ulaşmak için ne kadar risk gerekiyor?
bir_sonraki_kontrol: Tarih + tetikleyiciler (max 3)
nakit_realizasyon_plani: [KESİNLİKLE ZORUNLU — BOŞ KALIRSA ANALİZ EKSİK SAYILIR]
  ⚠️ Mesajdaki "NAKİT REALİZASYON KONTROLÜ" tablosuna bak.
  Önerilen nakit ağırlığına göre o tablodan doğrudan değerleri kopyala:
  bugun_t0: Önerilen aksiyon planındaki T+0 satışlarından gelecek nakit (kripto+ABD hisse)
  t2_tefas: TEFAS satışlarından T+2'de gelecek nakit
  toplam_hedef: Portföy değeri × önerilen nakit % = $X
  tutarli_mi: (bugun_t0 + t2_tefas + mevcut_nakit) >= toplam_hedef ise "evet", değilse "hayir — $X eksik"

═══ SENARYO OLASILILANDIRMASI (KRİTİK) ═══
Tek bir senaryoya %100 güvenme. Her kararı üç olasılığın matematiksel harmanı yap:

1. BAZI SENARYO (dominant) — en yüksek olasılık, verilerle destekli
2. ALTERNATİF SENARYO — %20-35 ihtimalle gerçekleşebilecek zıt senaryo  
3. KUYRUK RİSKİ — %5-15 ihtimalle ancak çok yıkıcı uç senaryo

Ağırlıklı beklenen getiri = Σ(olasılık × etki). Negatif beklenen değerde agresif pozisyon alma.

═══ DİNAMİK RİSK BÜTÇESİ — SERT LİMİTLER ═══
Piyasa rejimine göre aşılmaması gereken risk sınırları:

RISK-OFF / CAUTION / YAVAŞ KANAMA / LİKİDİTE ŞOKU senaryolarında:
• Kripto (tüm) + Yüksek Beta Hisse (Beta > 1.5) toplamı → ASLA %15'i geçemez
• Nakit + Kısa Tahvil → minimum %15 olmalı
• Hisse yoğun TEFAS (IIH, TTE, NNF, MAC) → toplam TEFAS'ın max %30'u

STAGFLASYON senaryosunda:
• Enerji + Altın + Emtia toplamı → minimum %25 olmalı
• Uzun vadeli tahvil → maksimum %10

MALİ DOMINANS / MELT-UP senaryosunda:
• Nakit (TL) → minimum %0 (nakit TL tutmak en kötü seçim)
• Sabit arzlı varlık (BTC + Altın) → minimum %30 önerilir

RISK-ON senaryosunda:
• Defansif (XLP, XLU benzeri) → maksimum %20 (geri kalmayı önle)
• Kripto + Büyüme Hisse → %40'a kadar çıkabilir

Bu sınırları aştığında portföy önerisini revize et ve neden sınırı aştığını açıkla.

HARD CAP İHLAL KURALI — ÇOK ÖNEMLİ:
Eğer herhangi bir limiti aşıyorsan, JSON çıktısında hard_cap_ihlal alanını ZORUNLU doldur:
  ihlal_eden_sinif: örn "crypto"
  onerilen_pct: önerdiğin yüzde (örn 35)
  limit_pct: senaryo limiti (örn 15)
  senaryo_istisnasi: neden bu senaryoda limit aşılabilir
  alternatif_risk: kötü senaryoda portföy kaybı tahmini
Gerekçesiz hard cap ihlali YASAKTIR. Ya limiti aş (ve gerekçe yaz), ya da limiti doldur.

═══ KORElASYON SİGORTASI ═══
Eğer portföydeki varlık sınıfları arasındaki 30 günlük korelasyon 0.7'yi geçiyorsa
(likidite krizinde hepsi birlikte düşüyorsa), nakit oranı otomatik olarak
önerilen seviyenin 1.5 katına çıkarılmalı. Bunu her analizde kontrol et.

═══ ÇIKTI KURALLARI ═══
• Her aksiyon somut olmalı: "risk azalt" değil, "AVGO pozisyonunu %20 küçült"
• Nakit oranı her zaman belirtilmeli
• Stop-loss ve hedef fiyat mümkün olduğunda verilmeli
• VALÖR KURALI: TEFAS satışı T+2 valörlüdür. "IIH sat" derken
  "nakit 2 gün sonra gelir → bugün mevcut nakitle altın/GLD al" şeklinde
  zamanlama talimatı ver. Kripto ve ABD hisseleri T+0.
• NAKİT MİKRO-KURALI (Pratik Uygulama):
  - Eğer mevcut nakit <%5 ve piyasalar kapalıysa (UTC 21:00-14:30):
    SHV/BIL gibi ETF almayı önerme — işlem beklemede kalır, spread riski var.
    Bunun yerine "nakiti USD mevduat/para piyasasında tut, piyasa açılışında al" de.
  - Eğer nakit <%2 ve acil likidite gerekiyorsa:
    Kripto (7/24 likit) önce sat, ETF ikinci adım olsun.
  - İşlem maliyeti eşiği: $100'ın altındaki nakit hareketleri için ETF önerme,
    komisyon getiriyi yer.
• SPESİFİK TICKER: Portföydeki her hisseyi listede gördüğüne göre
  sınıf değil ticker bazlı karar ver.
• ŞİRKET PROFİLİ NÜANSI — yüzeysel kategorizasyondan kaçın:
  AMZN gelirinin >%70'i AWS (kurumsal bulut) — "tüketici şirketi" değil.
  CRWD SaaS recurring revenue — negatif reel faizde büyüme hissesi DCF değeri artar.
  IREN/BTC madencileri — enerji maliyetine doğrudan bağlı (petrol/elektrik).
  Her hissenin gerçek iş modelini gerekçeye yansıt.
• TEFAS HALÜSINASYON YASAĞI: Sözlükte (TEFAS_DB) olmayan fon için
  içerik TAHMİNİ YAPMA. "Tahvil ağırlıklı gibi görünüyor" demek yasak.
  Bilinmeyen fon → "İçerik doğrulanmadı, koru" de.
• KUR KORUMALI FONLAR (Türkiye şokunda kritik):
  TTE (yabancı teknoloji) ve URA (yabancı uranyum) TL değer kaybında TL fiyatı ARTAR.
  AOY ALTIN FONU DEĞİL — alternatif enerji yabancı hisse fonu.
  Kur Riski DÜŞÜK etiketli fonları TL krizinde SATMA — kur koruması sağlarlar.
• İZOLASYON HATASI: Türkiye şoku gibi lokal krizlerde bile
  ABD hisselerindeki zombi pozisyonları (negatif FCF + düşük current ratio)
  değerlendir. "Türkiye'den izole" gerekçesi zombi filtresini es geçmez.
  Zombi hisseler her senaryoda risk taşır — ayrı ayrı değerlendir.
• ZOMBİ KURALI: FCF < 0 VE (Current Ratio < 1.0 VEYA Borç/ÖK > 200)
  ise şirket zombi — sat. Sadece FCF negatifliği yeterli değil,
  şirkette 3 yıllık nakit varsa zombi değildir.
• SENARYO-SPESİFİK DEĞERLEME MANTIKI:
  - YAVAŞ KANAMA / YÜKSEK FAİZ: Büyüme hisseleri iskonto oranı artar → değerleme
    baskısı gerçek. FCF'si pozitif olan büyüme hisseleri bile P/E sıkışır.
  - MALİ DOMINANS / NEGATİF REEL FAİZ: Tam TERSİ geçerli. Negatif reel faizde
    büyüme hisselerinin DCF değeri ARTAR (iskonto oranı düşer). 2020-2021'de
    teknoloji hisseleri negatif reel faizde 3-5x kazandı. Bu ortamda yüksek
    değerlemeli büyüme hisselerini sadece "çarpan yüksek" diye satma — yanlış.
    Bunun yerine: FCF üretimi var mı? Dolar bazlı geliri var mı? Reel varlık mı?
  - STAGFLASYON: Ne büyüme ne değer işe yarar. Sadece emtia + fiyatlama gücü.
    Emtia önerisi altınla sınırlı kalmamalı — petrol/enerji (XLE, USO, CL=F),
    hammadde (XLB, FCX), tarım da stagflasyonda güçlüdür.
    Portföyde emtia ETF yoksa "ALTIN_GRAM_TRY artır + XLE gibi enerji ETF ekle" de.
  This mantığı her hisse kararında uygula — senaryo tipini değerleme çerçevesine yansıt.
• Türkçe yaz
• JSON formatında yanıt ver — aşağıdaki şemayı kullan:
""" + _DIRECTOR_JSON_SCHEMA
import os
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLAUDE_MODEL   = "claude-opus-4-5"
MAX_TOKENS_ANALYST  = 800    # Her analist raporu için — özlü ama derin
MAX_TOKENS_DIRECTOR = 8000   # Direktör için — kapsamlı sentez


# ─── Claude API Yardımcı Fonksiyonu ──────────────────────────────────────────

def _call_claude(system_prompt: str, user_message: str,
                 max_tokens: int = 1000, retries: int = 2) -> str | None:
    """
    Claude API'ye tek bir çağrı yap.
    Hata durumunda retry ile tekrar dene.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    for attempt in range(retries + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except Exception as e:
            logger.warning("Claude API attempt %d failed: %s", attempt + 1, e)
            if attempt < retries:
                time.sleep(2 ** attempt)  # Exponential backoff
    return None


def _safe_json(text: str, fallback: dict = None) -> dict:
    """
    Claude çıktısından JSON parse et.
    Kısmi JSON bile olsa kurtarmaya çalış.
    """
    if not text:
        logger.warning("_safe_json: boş metin")
        return fallback or {}

    original = text
    text = text.strip()

    # Markdown kod bloğu temizle
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # İlk { ile son } arasını al
    first = text.find("{")
    last  = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last+1]

    # Doğrudan parse dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Brace recovery — JSON eksik kapanıyorsa kapat
    open_b  = text.count("{")
    close_b = text.count("}")
    if open_b > close_b:
        text += "}" * (open_b - close_b)
    try:
        return json.loads(text)
    except Exception:
        pass

    # Son çare: sadece piyasa_ozeti çıkarmaya çalış
    try:
        import re
        match = re.search(r'"piyasa_ozeti"\s*:\s*"([^"]+)"', original)
        if match and fallback:
            result = dict(fallback)
            result["piyasa_ozeti"] = match.group(1)
            logger.warning("JSON tam parse edilemedi, sadece piyasa_ozeti kurtarıldı")
            return result
    except Exception:
        pass

    logger.warning("JSON parse tamamen başarısız. İlk 500 karakter: %s", original[:500])
    return fallback or {}


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA A — UZMAN ANALİSTLER
# ═══════════════════════════════════════════════════════════════════════════

# ─── Makro Analist ───────────────────────────────────────────────────────────

MACRO_ANALYST_SYSTEM = """Sen küresel makroekonomik analizde uzmanlaşmış kıdemli bir portföy analistisin.
Fed politikası, küresel likidite döngüleri, kredi piyasaları ve jeopolitik risklerin piyasalara
etkisini değerlendirme konusunda 15 yıllık deneyimin var.

GÖREV SINIRI: Yalnızca sana verilen makroekonomik verileri analiz et. Cross-asset portföy 
kararları verme — bu direktörün işi. Sadece makro ortamı değerlendir.

═══ GETİRİ EĞRİSİ (YIELD CURVE) YORUMLAMA KILAVUZU ═══
Yield curve verisi sana [TIP] etiketiyle gelecek. Aşağıdaki tarihsel ilişkileri uygula:

1. INVERTED (Ters Eğri): 10Y < 3M
   → Yaklaşan resesyon sinyali. Tarihsel: 1980, 1989, 2000, 2007, 2019 öncesinde görüldü.
   → Eğri ne kadar uzun süredir ters kalırsa resesyon riski o kadar yüksek.

2. BULL_STEEPENER — EN KRİTİK SİNYAL:
   Ters eğri NORMALLEŞIYOR + uzun vade faiz DÜŞÜYOR
   → Tarihsel olarak resesyonun BAŞLADIĞININ tescilidir (geç Fed sinyali).
   → 2007/2008 Aralık: eğri normalleşti → Mart 2008 resesyon başladı.
   → 2019/2020: normalleşti → COVID öncesi zaten yavaşlama başlamıştı.
   → Piyasa bu sırada "kurtarıldık" diyebilir ama YANILIR — en tehlikeli iyimserlik tuzağı.
   → Direktöre: "Piyasa normalleşmeyi pozitif okuyabilir, ama bu genellikle zirve öncesi son rallıdır."

3. BEAR_STEEPENER:
   Eğri normalleşiyor + uzun vade faiz YUKARI gidiyor
   → Enflasyon beklentisi veya risk primi artışı.
   → Stagflasyon veya artan borçlanma maliyeti sinyali.
   → Hisseler için orta vadede negatif (discount rate artar).

4. NORMAL (pozitif eğri) + STEEPENING:
   → Büyüme beklentisi güçlü, risk iştahı var.
   → Genellikle ekonomik genişlemenin ortası.

5. FLAT (düzleşen):
   → Büyüme yavaşlıyor, geçiş dönemi.

Bu bilgiyi yorumlarında kullan. "Yield curve normal" demek yetmez —
normalleşmenin YÖNÜnü ve ne anlama geldiğini açıkla.

GÖREV SINIRI: Yalnızca sana verilen makroekonomik verileri analiz et. Cross-asset portföy 
kararları verme — bu direktörün işi. Sadece makro ortamı değerlendir.

YANIT FORMATI: Aşağıdaki JSON formatında yanıt ver, hiçbir alanı boş bırakma:
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net ve somut — neden bu sinyal?",
  "destekleyen": ["Metrik 1 ne söylüyor", "Metrik 2 ne söylüyor"],
  "riskler": ["Bu sinyali bozabilecek faktör 1", "Faktör 2"],
  "oneri": "Makro ortama göre yatırımcıya somut bir tavsiye",
  "izle": "Önümüzdeki 2 haftada en kritik gösterge nedir ve neden?"
}"""



# ─── Sektör Proxy Haritası ────────────────────────────────────────────────────
# yfinance hisse bazlı FCF/metrik bulamazsa, sektör ETF'i proxy olarak kullanılır

SECTOR_ETF_PROXY = {
    # Sektör adı → (Proxy ETF, açıklama)
    "Technology":           ("XLK",  "Teknoloji sektörü"),
    "Financial Services":   ("XLF",  "Finans sektörü"),
    "Healthcare":           ("XLV",  "Sağlık sektörü"),
    "Energy":               ("XLE",  "Enerji sektörü"),
    "Industrials":          ("XLI",  "Sanayi sektörü"),
    "Consumer Cyclical":    ("XLY",  "Döngüsel tüketim"),
    "Consumer Defensive":   ("XLP",  "Defansif tüketim"),
    "Real Estate":          ("XLRE", "Gayrimenkul"),
    "Utilities":            ("XLU",  "Kamu hizmetleri"),
    "Communication Services":("XLC", "İletişim"),
    "Basic Materials":      ("XLB",  "Hammadde"),
    # Kripto varlıklar — bireysel proxy eşlemesi
    "Cryptocurrency":       ("IBIT", "Geniş kripto proxy"),
    "BTC-USD":              ("IBIT", "Bitcoin spot proxy"),
    "ETH-USD":              ("ETHA", "Ethereum ETF proxy"),
    "SOL-USD":              ("IBIT", "Solana — büyük kripto sepeti proxy"),
    "BNB-USD":              ("IBIT", "BNB — büyük kripto sepeti proxy"),
    "XRP-USD":              ("IBIT", "XRP — büyük kripto sepeti proxy"),
    "AVAX-USD":             ("IBIT", "Avalanche — kripto sepeti proxy"),
    "DOGE-USD":             ("IBIT", "Dogecoin — spekülatif kripto proxy"),
    "PEPE-USD":             ("IBIT", "PEPE — spekülatif kripto proxy"),
    "WIF-USD":              ("IBIT", "WIF — meme kripto proxy"),
    # Emtia pozisyonları
    "ALTIN_GRAM_TRY":       ("GLD",  "Altın ETF proxy — TL bazlı altın"),
    "GUMUS_GRAM_TRY":       ("SLV",  "Gümüş ETF proxy — TL bazlı gümüş"),
    "GC=F":                 ("GLD",  "Altın futures proxy"),
    "SI=F":                 ("SLV",  "Gümüş futures proxy"),
    "CL=F":                 ("USO",  "WTI petrol futures proxy"),
    # TEFAS fonları — ilgili ETF proxy
    "IIH":                  ("EWT",  "Hisse yoğun TEFAS — EM hisse proxy"),
    "AEY":                  ("GLD",  "Altın TEFAS — altın ETF proxy"),
    "TTE":                  ("XLK",  "Teknoloji TEFAS — teknoloji ETF proxy"),
    "MAC":                  ("XLF",  "Banka TEFAS — finans ETF proxy"),
    "GAF":                  ("SHV",  "Kamu tahvil TEFAS — kısa tahvil proxy"),
    "NNF":                  ("IWM",  "Büyüme TEFAS — küçük sermayeli proxy"),
    "YAC":                  ("AOM",  "Dengeli TEFAS — dengeli ETF proxy"),
    # Özel ABD şirket eşlemeleri
    "PLTR": ("XLK",  "Yazılım/AI — Teknoloji proxy"),
    "CRWD": ("XLK",  "Siber güvenlik — Teknoloji proxy"),
    "SOFI": ("XLF",  "Fintech — Finans proxy"),
    "RKLB": ("XLI",  "Uzay/Savunma — Sanayi proxy"),
    "VRT":  ("XLI",  "Veri merkezi altyapı — Sanayi proxy"),
    "AVGO": ("XLK",  "Yarı iletken — Teknoloji proxy"),
    "AMZN": ("XLY",  "E-ticaret/Bulut — Tüketim/Teknoloji proxy"),
    "ZETA": ("XLK",  "Ad-tech — Teknoloji proxy"),
    "NBIS": ("XLK",  "AI chip — Teknoloji proxy"),
    "SCHD": ("VYM",  "Temettü ETF — yüksek temettü proxy"),
    "PPA":  ("XLI",  "Savunma ETF — sanayi proxy"),
}


# ─── Merkezi TEFAS Fon Veri Tabanı ───────────────────────────────────────────
# KAP ve fonun resmi tanıtım belgelerinden derlendi.
# Bilinmeyen fonlar için ASLA tahmin yapma — "BILINMIYOR_SAT" kuralı geçerli.
# Format: kod → (tip, içerik_özeti, resesyon_riski, kur_riski, beta_seviyesi, notlar)

TEFAS_DB = {
    # FORMAT: kod → (tip, içerik, resesyon_riski, kur_riski, beta, not)
    # KUR_RİSKİ: YÜKSEK=TL bazlı zarar görür | DÜŞÜK=yabancı varlık, kur korumalı
    # TL KRİZİNDE KURAL: Kur Riski DÜŞÜK → TL değer kaybı fon TL fiyatını ARTTIRIR

    # ── Yerli Ağırlıklı Hisse Fonları ───────────────────────────────────────
    "IIH":  ("Hisse Yoğun YERLİ",
             "BIST büyük şirket ~%80 yerli + ~%10 yabancı hisse",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Ağırlıklı BIST yerli hisse. TL krizi = çift darbe (BIST düşer + TL erir)."),

    "NNF":  ("Hisse Senedi Birinci YERLİ",
             "BIST hisse ~%90-95 tamamen yerli — TAHVİL DEĞİL",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Agresif YERLİ BIST hisse fonu. TL krizi = tam maruz kalım."),

    "MAC":  ("Hisse Banka/Finans YERLİ",
             "BIST bankacılık ve finans ~%80 yerli",
             "ÇOK_YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Yerli banka hisseleri. Kredi döngüsü + TL krizine çok hassas."),

    "YAS":  ("Hisse Karma YERLİ",
             "Çeşitlendirilmiş BIST ~%80 yerli",
             "YÜKSEK", "YÜKSEK", "YÜKSEK",
             "Çeşitlendirilmiş BIST yerli hisse fonu. TL krizinde korumasız."),

    # ── Yabancı Ağırlıklı (Kur Korumalı) Hisse Fonları ──────────────────────
    "TTE":  ("Hisse Teknoloji YABANCI/KUR_KORUMALI",
             "Yabancı teknoloji ~%70-80 (Nasdaq/S&P tekno) + yerli tekno ~%20-30",
             "ORTA", "DÜŞÜK", "ÇOK_YÜKSEK",
             "⚠️ KUR KORUMALI: Ağırlıklı yabancı (Nasdaq) hisse. "
             "TL %30 değer kaybında fon TL fiyatı YUKARI gider. "
             "Türkiye şokunda SATMA — resesyon riski var ama kur koruması sağlar."),

    "AOY":  ("ALTERNATİF ENERJİ YABANCI — ALTIN FONU DEĞİL",
             "Yabancı alternatif/temiz enerji hisseleri ~%80-90 (solar, rüzgar, EV)",
             "ORTA", "DÜŞÜK", "YÜKSEK",
             "⚠️ KRİTİK UYARI: AOY ALTIN FONU DEĞİL. "
             "Alternatif/Temiz Enerji yabancı hisse fonudur — enflasyon hedge değil. "
             "KUR KORUMALI: TL değer kaybında TL fiyatı artar."),

    # ── Altın / Kıymetli Maden Fonları (Kur Korumalı) ────────────────────────
    "AEY":  ("Altın/Kıymetli Maden KUR_KORUMALI",
             "Fiziksel altın + altın ETF ~%80, dolar bazlı",
             "DÜŞÜK", "DÜŞÜK", "ORTA",
             "Gerçek altın fonu. Enflasyon ve döviz hedge. TL değer kaybında TL fiyatı ARTAR."),

    "GLD":  ("Altın ETF KUR_KORUMALI",
             "Fiziksel altın ~%99, dolar bazlı",
             "DÜŞÜK", "DÜŞÜK", "ORTA",
             "Uluslararası altın ETF. Kur korumalı."),

    # ── Dengeli / Karma Fonlar ────────────────────────────────────────────────
    "YAC":  ("Dengeli Karma",
             "Hisse %50 (karma yerli/yabancı) + Tahvil %50",
             "ORTA", "ORTA", "ORTA",
             "Dengeli fon. Yabancı hisse oranı için KAP teyidi önerilir."),

    "NNM":  ("Dengeli Karma",
             "Hisse + Tahvil + Altın — oranlar değişken",
             "ORTA", "ORTA", "ORTA",
             "Karma strateji. KAP aylık raporu teyidi gerekli."),

    # ── TL Bazlı Tahvil / Para Piyasası Fonları ───────────────────────────────
    "GAF":  ("Kamu Menkul Kıymet TL_BAZLI",
             "TL devlet tahvili ~%90",
             "DÜŞÜK", "YÜKSEK", "DÜŞÜK",
             "TL devlet tahvili. TL krizinde dolar bazlı değer erir."),

    "TI1":  ("Tahvil Kısa Vade TL_BAZLI",
             "Kısa vadeli TL tahvil ~%90",
             "DÜŞÜK", "YÜKSEK", "DÜŞÜK",
             "Kısa vadeli TL tahvil. TL krizinde eritici."),

    "TSI":  ("Para Piyasası TL_BAZLI",
             "Kısa vadeli TL menkul kıymet",
             "DÜŞÜK", "YÜKSEK", "ÇOK_DÜŞÜK",
             "Para piyasası benzeri. TL krizinde eritici."),

    # ── Yabancı Emtia / Enerji Fonları (Kur Korumalı) ─────────────────────────
    "URA":  ("Uranyum/Nükleer Enerji YABANCI/KUR_KORUMALI",
             "Yabancı uranyum şirketleri + ETF ~%80 (CCJ, NXE vb.)",
             "ORTA", "DÜŞÜK", "YÜKSEK",
             "Nükleer rönesans. YABANCI şirketler. KUR KORUMALI. Volatil ama yapısal."),
}


# Sözlükte olmayan fonlar için güvenli fallback
TEFAS_UNKNOWN_RULE = (
    "BİLİNMEYEN",
    "İçerik doğrulanmadı — KAP teyidi gerekli",
    "BELİRSİZ",
    "BELİRSİZ",
    "BELİRSİZ",
    "⚠️ UYARI: Bu fon için içerik tahmini YAPILMAMALI. "
    "Pozisyon küçükse koru, büyükse içerik netleşene kadar küçük azalt. "
    "Direktör halüsinasyon üretmemeli."
)


def _fetch_sector_proxy_metrics(ticker: str, sector: str) -> dict:
    """
    Hisse bazlı metrik yoksa sektör ETF proxy'si kullan.
    Döndürür: {beta, fcf_str, note}
    """
    import yfinance as _yf_px
    
    # Proxy ETF'i belirle
    proxy_etf, proxy_label = SECTOR_ETF_PROXY.get(
        ticker,
        SECTOR_ETF_PROXY.get(sector, ("SPY", "Geniş piyasa proxy"))
    )
    
    try:
        etf_info = _yf_px.Ticker(proxy_etf).info
        etf_beta = etf_info.get("beta", "N/A")
        
        # ETF'in 3 aylık performansı FCF proxy olarak
        hist = _yf_px.Ticker(proxy_etf).history(period="3mo")
        if len(hist) >= 2:
            perf_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
            perf_str = f"{perf_3m:+.1f}% (3ay)"
        else:
            perf_str = "N/A"
        
        return {
            "beta":    etf_beta,
            "fcf_str": f"Proxy({proxy_etf}): {perf_str}",
            "note":    f"{proxy_label} → {proxy_etf} proxy kullanıldı",
            "proxy":   True,
        }
    except Exception:
        return {"beta": "N/A", "fcf_str": "N/A", "note": "Proxy alınamadı", "proxy": True}


def analyze_macro_with_claude(macro_data: dict, economic_data: dict) -> dict:
    """Makro analist — Fed, likidite, büyüme, risk ortamı."""
    # Özet veri hazırla — ham sayı değil yorumlanmış metrikler
    indicators = macro_data.get("indicators", {})
    regime     = macro_data.get("regime",     {})

    lines = ["=== MAKRO GÖSTERGELERİN ÖZETI ==="]

    # Sinyal motoru zaten yorumladı — onları kullan
    for key, ind in indicators.items():
        if isinstance(ind, dict) and ind.get("note"):
            sig = ind.get("signal", "neutral")
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.get('label', key)}: {ind.get('note', '')}")
        elif hasattr(ind, "note") and ind.note:
            sig = ind.signal
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.label}: {ind.note}")

    if regime:
        lines.append(f"\nPiyasa Rejimi: {regime.get('label', '—')} — {regime.get('description', '')}")

    # Ekonomik göstergeler ekle
    econ = economic_data.get("macro_econ", {})
    if econ:
        lines.append("\n=== EKONOMİK VERİLER ===")
        for key, ind in econ.items():
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    message = "\n".join(lines)
    result  = _call_claude(MACRO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Makro veri alınamadı",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_macro"
    return parsed


# ─── ABD Hisse Analisti ──────────────────────────────────────────────────────

US_EQUITY_ANALYST_SYSTEM = """Sen ABD hisse senedi piyasalarında uzmanlaşmış kıdemli bir portföy analistisin.
S&P 500 değerlemesi, sektör rotasyonu, kurumsal kazanç döngüleri ve teknik analiz konularında
derinlemesine bilgiye sahipsin.

GÖREV SINIRI: Yalnızca ABD hisse senedi piyasasını analiz et.

KESKİN NİŞANCI MODU — MİKRO METRİK ODAĞI:
Makro görüşün yanında, portföydeki her ABD hissesini aşağıdaki üç filtreden geçir:

1. FCF YİELD & BORÇLULUK (Resesyon Direnci):
   - Serbest nakit akışı getirisi yüksek (>%5) ve borç/özkaynak düşük (<1.0) şirketler
     resesyon döneminde hayatta kalır. Bunları "Defansif Kalite" olarak etiketle.
   - Borç yükü yüksek ve negatif FCF'li şirketler faiz artışında ilk çökenlerdir.

2. AI ÜRETKENLİK İZİ (Revenue per Employee Trendi):
   - Şirketin son 2-4 çeyrekte çalışan başına geliri artıyorsa AI operasyonel kazanım
     sağlıyor demektir. Bu şirketi "AI Verimlilik Lideri" olarak etiketle.
   - Azalıyorsa kalabalık iş gücü maliyeti rekabet avantajını yiyor.

3. MAKRO DUYARLILIK ETİKETİ:
   Her hisse için şu etiketleri kullan:
   - Faiz_indirim_pozitif / Faiz_indirim_negatif
   - Resesyon_defansif / Resesyon_hassas
   - Dolar_zayiflama_pozitif / Dolar_zayiflama_negatif

4. ŞİRKET PROFİLİ NÜANSI (kör nokta önleme):
   Şirketleri yüzeysel kategorizasyonla değil gerçek iş modeline göre değerlendir:
   - AMZN: e-ticaret DEĞİL — gelirin %70+ AWS (kurumsal bulut). Tüketici harcaması sadece %30.
     Stagflasyon/resesyonda AWS kurumsal bulut harcaması tüketiciye göre çok daha dayanıklı.
   - MSFT: Azure + Office SaaS — yapısal talep, resesyon defansif.
   - GOOGL: Reklam geliri döngüsel AMA bulut büyüyor, iki ayrı iş modeli.
   - NVDA: Veri merkezi %80 — tüketici GPU döngüsel, datacenter yapısal.
   - CRWD: SaaS recurring revenue, müşteri churn düşük — siber güvenlik zorunlu harcama.
     Negatif reel faiz ortamında büyüme hissesi DCF değeri ARTAR (iskonto düşer) — sat değil koru.
   - SOFI: Tüketici kredisi — faize çok hassas, resesyonda kredi kayıpları artar.
   - PLTR: Devlet + kurumsal yazılım — resesyona dayanıklı, savunma bütçesi kesilmez.
   - BTC madencileri (IREN, MARA): Enerji maliyeti yüksek, petrol/enerji fiyatına çok hassas.
   Bu nüansları her karar gerekçesine yansıt.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "sektor_gorusu": "Hangi sektör güçlü/zayıf",
  "deger_leme": "Piyasa ucuz mu pahalı mı",
  "hisse_mikro_analiz": [
    {
      "ticker": "TICKER",
      "beta": 0.0,
      "fcf_yield_tahmini": "yüksek|orta|düşük|negatif",
      "borc_durumu": "güçlü|orta|riskli",
      "ai_uretkenlik": "lider|orta|geri_kaliyor",
      "makro_duyarlilik": ["Faiz_indirim_pozitif", "Resesyon_defansif"],
      "aksiyon": "KORU|ARTIR|AZALT|SAT",
      "gerekce": "tek cümle"
    }
  ],
  "destekleyen": ["Faktör 1", "Faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut genel öneri",
  "izle": "Kritik gösterge"
}"""


def analyze_us_equity_with_claude(economic_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """ABD hisse analisti — değerleme, sektör rotasyonu, kazanç."""
    lines = ["=== ABD HİSSE PİYASASI ANALİZİ ==="]

    # Değerleme — economic_data içinde yoksa üst seviye dict'te ara
    val = economic_data.get("sp500_valuation") or economic_data.get("valuation", {})
    if val:
        lines.append(f"S&P 500 Değerleme: {val.get('note', '')}")

    # Sektör rotasyonu
    sr = economic_data.get("sector_rotation") or economic_data.get("sectors", {})
    if sr:
        note = sr.get("rotation_note", "")
        if note:
            lines.append(f"Sektör Rotasyonu: {note}")
        secs = sr.get("sectors", [])
        if secs:
            top3    = sorted(secs, key=lambda x: x.get("rel_1m", 0), reverse=True)[:3]
            bottom3 = sorted(secs, key=lambda x: x.get("rel_1m", 0))[:3]
            lines.append("Lider sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in top3))
            lines.append("Zayıf sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in bottom3))

    # Ekonomik veriler
    econ = economic_data.get("macro_econ", {})
    for key in ["ISM_MFG", "ISM_SVC", "NFP", "GDP"]:
        ind = econ.get(key)
        if ind:
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    # Portföydeki hisseler — mikro metriklerle
    us_positions = [p for p in portfolio_positions
                    if p.get("asset_class", "us_equity") == "us_equity"
                    and float(p.get("shares", 0)) > 0]
    if us_positions:
        lines.append(f"\n=== PORTFÖYDEKİ ABD HİSSELERİ ({len(us_positions)} pozisyon) ===")
        lines.append("Her hisse için FCF yield, beta, borç durumu ve makro duyarlılığını değerlendir.")
        logger.info("ABD hisse mikro analiz: %d pozisyon", len(us_positions))
        
        # yfinance'ten mikro metrikler çek
        try:
            import yfinance as _yf_micro
            for p in us_positions[:10]:
                ticker = p["ticker"]
                cur    = p.get("current_price", p["avg_cost"])
                avg    = p["avg_cost"]
                pnl    = (cur - avg) / avg * 100 if avg > 0 else 0
                shares = float(p.get("shares", 0))
                val    = shares * cur
                
                # Temel metrikler — her alan için ayrı fallback
                try:
                    info = _yf_micro.Ticker(ticker).info
                except Exception:
                    info = {}

                def _safe(val, default="N/A"):
                    import math
                    if val is None: return default
                    try:
                        if isinstance(val, float) and math.isnan(val): return default
                    except Exception: pass
                    return val

                try:
                    beta      = _safe(info.get("beta"), "N/A")
                    beta_str  = f"{beta:.1f}" if isinstance(beta, float) else str(beta)

                    fcf       = float(_safe(info.get("freeCashflow"), 0) or 0)
                    mktcap    = float(_safe(info.get("marketCap"),    0) or 0)
                    fcf_yield = round(fcf / mktcap * 100, 1) if mktcap > 0 and fcf != 0 else 0
                    fcf_str   = f"{fcf_yield:+.1f}%" if fcf_yield != 0 else "N/A"

                    de_raw    = _safe(info.get("debtToEquity"), None)
                    de_str    = f"{float(de_raw):.1f}" if de_raw is not None else "N/A"

                    # ── Current Ratio (Cari Oran) — Zombi filtresi ────────
                    # FCF negatif VEYA Current Ratio < 1.0 → Zombi adayı
                    cr_raw    = _safe(info.get("currentRatio"), None)
                    cr_val    = float(cr_raw) if cr_raw is not None else None
                    cr_str    = f"{cr_val:.2f}" if cr_val is not None else "N/A"

                    # Zombi skoru: 0=sağlıklı, 1=dikkat, 2=zombi
                    zombi_score = 0
                    zombi_flags = []
                    if fcf < 0:
                        zombi_score += 1
                        zombi_flags.append("FCF<0")
                    if cr_val is not None and cr_val < 1.0:
                        zombi_score += 1
                        zombi_flags.append(f"CariOran<1({cr_val:.2f})")
                    if de_raw is not None and float(de_raw) > 200:
                        zombi_score += 1
                        zombi_flags.append("AşırıBorç")

                    zombi_tag = (
                        "🧟 ZOMBİ"   if zombi_score >= 2 else
                        "⚠️ DİKKAT"  if zombi_score == 1 else
                        "✅ SAĞLIKLI"
                    )
                    zombi_note = f"[{zombi_tag}: {', '.join(zombi_flags)}]" if zombi_flags else f"[{zombi_tag}]"

                    rev       = float(_safe(info.get("totalRevenue"),      0) or 0)
                    emp       = float(_safe(info.get("fullTimeEmployees"), 0) or 0)
                    rpe_str   = f"Gelir/Çalışan:${rev/emp/1000:.0f}K" if rev > 0 and emp > 0 else ""

                    lines.append(
                        f"• {ticker}: K/Z %{pnl:+.0f} | Değer:${val:,.0f} | "
                        f"Beta:{beta_str} | FCF:{fcf_str} | CariOran:{cr_str} | "
                        f"Borç/ÖK:{de_str} | {rpe_str} | {zombi_note} | "
                        f"Sektör:{p.get('sector','?')}"
                    )
                except Exception:
                    # yfinance başarısız → sektör proxy kullan
                    try:
                        _px = _fetch_sector_proxy_metrics(ticker, p.get("sector",""))
                        lines.append(
                            f"• {ticker}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} | "
                            f"Beta: {_px['beta']} | FCF: {_px['fcf_str']} | "
                            f"Sektör: {p.get('sector','?')} | [{_px['note']}]"
                        )
                    except Exception:
                        lines.append(
                            f"• {ticker}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} | "
                            f"Beta: N/A | FCF: N/A | Sektör: {p.get('sector','?')}"
                        )
        except Exception:
            for p in us_positions[:8]:
                pnl = ((p.get("current_price", p["avg_cost"]) - p["avg_cost"])
                       / p["avg_cost"] * 100) if p["avg_cost"] > 0 else 0
                lines.append(f"• {p['ticker']}: K/Z %{pnl:+.0f}, Sektör: {p.get('sector','?')}")

    # Sinyal motoru sinyali
    us_sig = signal_summary.get("us_equity", {})
    if us_sig:
        lines.append(f"\nSinyal Motoru: {us_sig.get('signal','?')} (güven: {us_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(US_EQUITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "ABD hisse verisi çekilemedi — portföy pozisyonları ve makro bağlamla değerlendiriliyor",
        "sektor_gorusu": "Veri eksik", "deger_leme": "Veri eksik",
        "destekleyen": [], "riskler": [], "oneri": "Veri eksik — makro bağlama göre değerlendir", "izle": ""
    })
    parsed["_source"] = "claude_us_equity"
    return parsed


# ─── Kripto Analisti ─────────────────────────────────────────────────────────

CRYPTO_ANALYST_SYSTEM = """Sen kripto varlık piyasalarında uzmanlaşmış kıdemli bir analistin.
On-chain metrikler, Bitcoin halving döngüleri, altcoin dinamikleri ve kripto piyasası
psikolojisi konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca kripto piyasasını analiz et. Hisse senetleri, Türkiye veya emtia 
hakkında yorum yapma.

NOT: MVRV, SOPR gibi değerler yfinance'ten hesaplanan proxy değerlerdir, Glassnode'dan 
gerçek on-chain veri değil. Bunu yorumlarında göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dongu_pozisyonu": "Halving döngüsünde neredeyiz?",
  "onchain_ozet": "On-chain metrikler ne söylüyor?",
  "btc_vs_altcoin": "BTC mi altcoin mi tercih edilmeli?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_crypto_with_claude(crypto_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Kripto analisti — on-chain, döngü, sentiment."""
    lines = ["=== KRİPTO PİYASASI ANALİZİ ==="]

    fg  = crypto_data.get("fear_greed",  {})
    dom = crypto_data.get("dominance",   {})
    hal = crypto_data.get("halving",     {})
    onc = crypto_data.get("onchain",     {})
    stb = crypto_data.get("stablecoin",  {})
    ls  = crypto_data.get("long_short",  {})
    nvt = crypto_data.get("nvt",         {})
    spr = crypto_data.get("sopr",        {})
    prc = crypto_data.get("prices",      {})

    if fg.get("note"):   lines.append(f"Fear & Greed: {fg['note']}")
    if hal.get("note"):  lines.append(f"Halving Döngüsü: {hal['note']}")
    if dom.get("dom_note"): lines.append(f"Dominance: {dom['dom_note']}")

    mvrv = onc.get("mvrv_proxy", {})
    if mvrv.get("note"):  lines.append(f"MVRV Proxy: {mvrv['note']}")
    rsi  = onc.get("btc_rsi", {})
    if rsi.get("note"):   lines.append(f"BTC RSI: {rsi['note']}")
    if spr.get("note"):   lines.append(f"SOPR Proxy: {spr['note']}")
    if nvt.get("note"):   lines.append(f"NVT Signal: {nvt['note']}")
    if ls.get("note"):    lines.append(f"Long/Short: {ls['note']}")
    if stb.get("note"):   lines.append(f"Stablecoin: {stb['note']}")

    # BTC fiyatı
    btc = prc.get("BTC", {})
    if btc.get("price"):
        lines.append(f"BTC: ${btc['price']:,.0f} ({btc.get('change_24h',0):+.1f}%), 52H pos: %{btc.get('52h_pos',0):.0f}")

    # Kripto pozisyonları
    crypto_pos = [p for p in portfolio_positions if p.get("asset_class") == "crypto"
                  and float(p.get("shares", 0)) > 0]
    if crypto_pos:
        lines.append("\n=== KRİPTO POZİSYONLARI (MİKRO ANALİZ) ===")
        lines.append("Her token için volatilite seviyesi, beta ve makro duyarlılığını değerlendir.")
        # Kripto beta haritası (BTC=1.0 bazlı)
        CRYPTO_BETA = {
            "BTC-USD": 1.0, "ETH-USD": 1.3, "SOL-USD": 1.8,
            "BNB-USD": 1.4, "XRP-USD": 1.5, "AVAX-USD": 1.9,
            "DOGE-USD": 2.2, "PEPE-USD": 3.5, "WIF-USD": 4.0,
            "JUP-USD": 2.8, "INJ-USD": 2.5, "SUI-USD": 2.3,
        }
        crypto_total = sum(float(p.get("shares",0)) * float(p.get("current_price", p["avg_cost"])) for p in crypto_pos)
        for p in crypto_pos:
            cur  = float(p.get("current_price", p["avg_cost"]))
            avg  = float(p["avg_cost"])
            pnl  = (cur - avg) / avg * 100 if avg > 0 else 0
            val  = float(p.get("shares", 0)) * cur
            pct_in_crypto = val / crypto_total * 100 if crypto_total > 0 else 0
            beta = CRYPTO_BETA.get(p["ticker"], 2.0)  # bilinmeyenler için 2.0
            # Spekülatif mi defansif mi?
            tag = "BTC_DEFANSIF" if p["ticker"] == "BTC-USD" else (
                  "ETH_ORTA" if p["ticker"] == "ETH-USD" else "SPEKULATIF_YUKSEK_BETA")
            # Proxy verisi
            try:
                _px = _fetch_sector_proxy_metrics(p["ticker"], "Cryptocurrency")
                proxy_note = f"Proxy: {_px['fcf_str']}"
            except Exception:
                proxy_note = ""
            lines.append(
                f"• {p['ticker']}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} "
                f"(%{pct_in_crypto:.0f} kripto içi) | Beta(BTC=1): {beta:.1f} | "
                f"[{tag}] | {proxy_note}"
            )

    crypto_sig = signal_summary.get("crypto", {})
    if crypto_sig:
        lines.append(f"\nSinyal Motoru: {crypto_sig.get('signal','?')} (güven: {crypto_sig.get('confidence','?')}/10)")

    # Veri yoksa bile portföy pozisyonları üzerinden analiz yap
    if len(lines) <= 3:
        lines.append("Not: Piyasa verisi çekilemedi. Portföy pozisyonları ve genel makro bağlamla analiz yapılıyor.")

    message = "\n".join(lines)
    result  = _call_claude(CRYPTO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Kripto verisi çekilemedi — genel makro bağlamla değerlendiriliyor",
        "dongu_pozisyonu": "Veri eksik", "onchain_ozet": "Veri eksik", "btc_vs_altcoin": "Veri eksik",
        "destekleyen": [], "riskler": [], "oneri": "Veri eksik — makro bağlama göre değerlendir", "izle": ""
    })
    parsed["_source"] = "claude_crypto"
    return parsed


# ─── Emtia Analisti ──────────────────────────────────────────────────────────

COMMODITY_ANALYST_SYSTEM = """Sen emtia piyasalarında, özellikle altın ve enerji sektöründe
uzmanlaşmış kıdemli bir analistin. Reel faiz dinamikleri, merkez bankası politikaları,
jeopolitik risk ve emtia döngüleri konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca emtia piyasasını analiz et.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "altin_gorusu": "Altın için temel tez nedir?",
  "petrol_gorusu": "Petrol piyasası ne söylüyor?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_commodity_with_claude(commodity_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """Emtia analisti — altın reel faiz, petrol, jeopolitik."""
    lines = ["=== EMTİA PİYASASI ANALİZİ ==="]

    grr = commodity_data.get("gold_real_rate", {})
    cbg = commodity_data.get("cb_gold_proxy",  {})
    udg = commodity_data.get("us_debt_gold",   {})
    oil = commodity_data.get("oil",            {})
    cu  = commodity_data.get("copper",         {})
    geo = commodity_data.get("geo_news",       {})
    prc = commodity_data.get("prices",         {})

    if grr.get("note"): lines.append(f"Reel Faiz: {grr['note']}")
    if cbg.get("note"): lines.append(f"MB Altın Alımı Proxy: {cbg['note']}")
    if udg.get("note"): lines.append(f"ABD Borç/Altın Tezi: {udg['note'][:120]}")
    if oil.get("note"): lines.append(f"Petrol: {oil['note']}")
    if cu.get("gc_note"): lines.append(f"Altın/Bakır Oranı: {cu['gc_note']}")
    if geo.get("note"): lines.append(f"Jeopolitik: {geo['note']}")

    gold = prc.get("GOLD", {})
    if gold.get("price"):
        lines.append(f"Altın: ${gold['price']:,.0f}/oz ({gold.get('change',0):+.1f}%), 52H: %{gold.get('pos_52h',0):.0f}")

    comm_pos = [p for p in portfolio_positions if p.get("asset_class") == "commodity"
                and float(p.get("shares", 0)) > 0]
    if comm_pos:
        lines.append("\n=== EMTİA POZİSYONLARI (MİKRO ANALİZ) ===")
        COMM_TAGS = {
            "ALTIN_GRAM_TRY": ("Altın (TRY gram)",    "GLD",  "Enflasyon_koruyucu Resesyon_defansif Dolar_zayiflama_pozitif"),
            "GUMUS_GRAM_TRY": ("Gümüş (TRY gram)",    "SLV",  "Enflasyon_koruyucu Sanayi_baglantili"),
            "GC=F":           ("Altın Futures",         "GLD",  "Enflasyon_koruyucu Resesyon_defansif"),
            "SI=F":           ("Gümüş Futures",         "SLV",  "Enflasyon_koruyucu Sanayi_baglantili"),
            "CL=F":           ("WTI Petrol",            "USO",  "Resesyon_hassas Jeopolitik_pozitif"),
            "NG=F":           ("Doğal Gaz",             "UNG",  "Enerji_baglantili Mevsimsel"),
        }
        for p in comm_pos:
            cur  = float(p.get("current_price", p["avg_cost"]))
            avg  = float(p["avg_cost"])
            pnl  = (cur - avg) / avg * 100 if avg > 0 else 0
            val  = float(p.get("shares", 0)) * cur
            cur_try = p.get("currency") == "TRY"
            val_note = f"{val:,.0f} TRY" if cur_try else f"${val:,.0f}"
            tag_info = COMM_TAGS.get(p["ticker"], (p["ticker"], "GLD", "Emtia"))
            label, proxy_etf, tags = tag_info
            # Proxy performansı
            try:
                import yfinance as _yf_cm
                hist = _yf_cm.Ticker(proxy_etf).history(period="1mo")
                proxy_perf = (hist["Close"].iloc[-1]/hist["Close"].iloc[0]-1)*100 if len(hist)>=2 else 0
                proxy_note = f"Proxy({proxy_etf}): {proxy_perf:+.1f}% (1ay)"
            except Exception:
                proxy_note = f"Proxy: {proxy_etf}"
            lines.append(
                f"• {p['ticker']} [{label}]: K/Z %{pnl:+.0f} | Değer: {val_note} | "
                f"[{tags}] | {proxy_note}"
            )

    comm_sig = signal_summary.get("commodity", {})
    if comm_sig:
        lines.append(f"\nSinyal Motoru: {comm_sig.get('signal','?')} (güven: {comm_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(COMMODITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "altin_gorusu": "", "petrol_gorusu": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_commodity"
    return parsed


# ─── Türkiye Analisti ─────────────────────────────────────────────────────────

TURKEY_ANALYST_SYSTEM = """Sen Türkiye hisse senedi piyasası ve gelişen piyasalarda uzmanlaşmış
kıdemli bir analistin. BIST dinamikleri, TL/kur riski, TCMB politikası, bankacılık sektörü
ve yabancı yatırımcı akışları konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca Türkiye piyasasını analiz et.

ÖNEMLİ: Tüm getiri hesaplamalarında hem TL bazlı hem dolar bazlı değerlendirme yap.
TL bazında kazanç, dolar bazında kayıp olabilir — her zaman dolar bazlı gerçek getiriyi göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dolar_bazli_degerleme": "BIST dolar bazlı ucuz mu pahalı mı?",
  "xbank_gorusu": "XBANK sinyali ne söylüyor?",
  "kur_riski": "TL riski ne durumda?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_turkey_with_claude(turkey_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Türkiye analisti — BIST dolar bazlı, XBANK, kur, yabancı."""
    lines = ["=== TÜRKİYE BORSASI ANALİZİ ==="]

    from turkey_fetcher import build_turkey_prompt
    lines.append(build_turkey_prompt(turkey_data))

    tefas_pos = [p for p in portfolio_positions if p.get("asset_class") == "tefas"
                 and float(p.get("shares", 0)) > 0]
    if tefas_pos:
        lines.append("\n=== TEFAS POZİSYONLARI (LOOK-THROUGH ANALİZİ) ===")
        # Bilinen fon içerik haritası — KAP aylık raporlarından derlendi
        # TEFAS_DB merkezi veri tabanından çek — bilinmeyende UYARI ver
        for p in tefas_pos:
            kod     = p["ticker"].upper()
            db_entry = TEFAS_DB.get(kod, TEFAS_UNKNOWN_RULE)
            tip, icerik, ress_duy, kur_risk, beta, notlar = db_entry
            val_tl  = float(p.get("shares", 0)) * float(p.get("current_price", p.get("avg_cost", 0)))
            bilinmiyor = (tip == "BİLİNMEYEN")
            lines.append(
                f"• {kod} [{tip}]: {p['shares']:,.0f} adet | ~{val_tl:,.0f} TL | "
                f"İçerik: {icerik} | Resesyon: {ress_duy} | Beta: {beta} | Kur: {kur_risk}"
                + (f"\n  ⚠️ {notlar}" if bilinmiyor else f"\n  📋 {notlar[:80]}")
            )
        lines.append("KURAL: Bilinmeyen fon için halüsinasyon/tahmin YASAK. "
                     "İçerik doğrulanana kadar koru veya küçük azalt.")

    tr_sig = signal_summary.get("turkey", {})
    if tr_sig:
        lines.append(f"\nSinyal Motoru: {tr_sig.get('signal','?')} (güven: {tr_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(TURKEY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "dolar_bazli_degerleme": "", "xbank_gorusu": "", "kur_riski": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_turkey"
    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA B — STRATEJİ DİREKTÖRÜ
# ═══════════════════════════════════════════════════════════════════════════

def _build_director_system(user_profile: dict, year_target_pct: float,
                           memory_context: str = "") -> str:
    """
    Direktörün sistem promptunu kullanıcı profiline göre oluştur.
    Kimlik + karar çerçevesi + kişisel parametreler + zorunlu çıktılar.
    memory_context: MemoryManager'dan gelen hafıza bağlamı (prompt'un başına eklenir).
    """
    time_horizon  = user_profile.get("time_horizon",  "1-3 yıl (Uzun Vade)")
    risk_tol      = user_profile.get("risk_tol",      "Orta-Yüksek")
    cash_cycle    = user_profile.get("cash_cycle",    "3 ayda bir")
    goal          = user_profile.get("goal",          "Uzun vadeli büyüme")

    # Hafıza bağlamını promptun en başına enjekte et
    memory_block = (
        f"{memory_context}\n\n"
        if memory_context.strip() else ""
    )

    return f"""{memory_block}Sen çok varlıklı portföy yönetiminde uzmanlaşmış kıdemli bir strateji direktörüsün.
ABD hisse senetleri, kripto varlıklar, emtialar (özellikle altın) ve Türkiye borsası olmak üzere
dört farklı piyasayı eş zamanlı yönetme deneyimine sahipsin.

Beş farklı uzman analistten rapor alıyorsun (makro, ABD hisse, kripto, emtia, Türkiye).
Görevin bu raporları sentezleyip müşteri için kişiselleştirilmiş, somut ve eyleme 
dönüştürülebilir bir strateji üretmek.

═══ KARAR ÇERÇEVESİ HİYERARŞİSİ ═══
Çelişkili sinyaller olduğunda şu öncelik sırasını uygula:
1. MAKRO REJİM — Risk-off modu aktifse bireysel varlık AL sinyalleri ikincil plana düşer
2. KORELASYONsuz ÇEŞİTLENDİRME — Yüksek korelasyonlu varlıklar (BTC/Tech gibi) 
   aynı anda artırılamaz. Bu çeşitlendirme yanılgısıdır.
3. RİSK/ÖDÜL DENGESİ — Her öneride potansiyel kazancı potansiyel kayıpla kıyasla
4. LİKİDİTE — Nakit yetersizse önce en riskli pozisyonlar küçültülür

═══ MÜŞTERİ PROFİLİ ═══
• Zaman ufku: {time_horizon}
• Risk toleransı: {risk_tol} (%20 drawdown tolere edilir)
• Nakit döngüsü: {cash_cycle}
• Hedef: {goal}
• Yıl sonu getiri hedefi: %{year_target_pct:.0f}
• Konum: Türkiye'de yaşıyor — enflasyonu yenmek öncelik, dolar bazlı getiri kritik
• Bu yatırımlar daha büyük bir portföyün parçası

═══ ZORUNLU YANIT ALANLARI ═══
Aşağıdaki her alan dolu olmalı — hiçbirini boş bırakma:

piyasa_ozeti: Piyasada dominant tema nedir? (2-3 cümle, anlaşılır)
analist_sentezi: Her analistin sinyali + tek cümle gerekçe
celiskiler: Analistler arasındaki çelişkileri tespit et ve çöz (hangi görüş neden üstün?)
portfoy_aksiyonlari: Hemen yap / koşullu yap / izle-karar ver
risk_senaryosu: Kötü senaryo tetikleyici + somut adımlar
vade_planlari: Kısa/orta/uzun vade için baz ve risk senaryoları
yil_sonu_hedefi: Hedefe ulaşmak için ne kadar risk gerekiyor?
bir_sonraki_kontrol: Tarih + tetikleyiciler (max 3)
nakit_realizasyon_plani: [KESİNLİKLE ZORUNLU — BOŞ KALIRSA ANALİZ EKSİK SAYILIR]
  ⚠️ Mesajdaki "NAKİT REALİZASYON KONTROLÜ" tablosuna bak.
  Önerilen nakit ağırlığına göre o tablodan doğrudan değerleri kopyala:
  bugun_t0: Önerilen aksiyon planındaki T+0 satışlarından gelecek nakit (kripto+ABD hisse)
  t2_tefas: TEFAS satışlarından T+2'de gelecek nakit
  toplam_hedef: Portföy değeri × önerilen nakit % = $X
  tutarli_mi: (bugun_t0 + t2_tefas + mevcut_nakit) >= toplam_hedef ise "evet", değilse "hayir — $X eksik"

═══ SENARYO OLASILILANDIRMASI (KRİTİK) ═══
Tek bir senaryoya %100 güvenme. Her kararı üç olasılığın matematiksel harmanı yap:

1. BAZI SENARYO (dominant) — en yüksek olasılık, verilerle destekli
2. ALTERNATİF SENARYO — %20-35 ihtimalle gerçekleşebilecek zıt senaryo  
3. KUYRUK RİSKİ — %5-15 ihtimalle ancak çok yıkıcı uç senaryo

Ağırlıklı beklenen getiri = Σ(olasılık × etki). Negatif beklenen değerde agresif pozisyon alma.

═══ DİNAMİK RİSK BÜTÇESİ — SERT LİMİTLER ═══
Piyasa rejimine göre aşılmaması gereken risk sınırları:

RISK-OFF / CAUTION / YAVAŞ KANAMA / LİKİDİTE ŞOKU senaryolarında:
• Kripto (tüm) + Yüksek Beta Hisse (Beta > 1.5) toplamı → ASLA %15'i geçemez
• Nakit + Kısa Tahvil → minimum %15 olmalı
• Hisse yoğun TEFAS (IIH, TTE, NNF, MAC) → toplam TEFAS'ın max %30'u

STAGFLASYON senaryosunda:
• Enerji + Altın + Emtia toplamı → minimum %25 olmalı
• Uzun vadeli tahvil → maksimum %10

MALİ DOMINANS / MELT-UP senaryosunda:
• Nakit (TL) → minimum %0 (nakit TL tutmak en kötü seçim)
• Sabit arzlı varlık (BTC + Altın) → minimum %30 önerilir

RISK-ON senaryosunda:
• Defansif (XLP, XLU benzeri) → maksimum %20 (geri kalmayı önle)
• Kripto + Büyüme Hisse → %40'a kadar çıkabilir

Bu sınırları aştığında portföy önerisini revize et ve neden sınırı aştığını açıkla.

HARD CAP İHLAL KURALI — ÇOK ÖNEMLİ:
Eğer herhangi bir limiti aşıyorsan, JSON çıktısında hard_cap_ihlal alanını ZORUNLU doldur:
  ihlal_eden_sinif: örn "crypto"
  onerilen_pct: önerdiğin yüzde (örn 35)
  limit_pct: senaryo limiti (örn 15)
  senaryo_istisnasi: neden bu senaryoda limit aşılabilir
  alternatif_risk: kötü senaryoda portföy kaybı tahmini
Gerekçesiz hard cap ihlali YASAKTIR. Ya limiti aş (ve gerekçe yaz), ya da limiti doldur.

═══ KORElASYON SİGORTASI ═══
Eğer portföydeki varlık sınıfları arasındaki 30 günlük korelasyon 0.7'yi geçiyorsa
(likidite krizinde hepsi birlikte düşüyorsa), nakit oranı otomatik olarak
önerilen seviyenin 1.5 katına çıkarılmalı. Bunu her analizde kontrol et.

═══ ÇIKTI KURALLARI ═══
• Her aksiyon somut olmalı: "risk azalt" değil, "AVGO pozisyonunu %20 küçült"
• Nakit oranı her zaman belirtilmeli
• Stop-loss ve hedef fiyat mümkün olduğunda verilmeli
• VALÖR KURALI: TEFAS satışı T+2 valörlüdür. "IIH sat" derken
  "nakit 2 gün sonra gelir → bugün mevcut nakitle altın/GLD al" şeklinde
  zamanlama talimatı ver. Kripto ve ABD hisseleri T+0.
• NAKİT MİKRO-KURALI (Pratik Uygulama):
  - Eğer mevcut nakit <%5 ve piyasalar kapalıysa (UTC 21:00-14:30):
    SHV/BIL gibi ETF almayı önerme — işlem beklemede kalır, spread riski var.
    Bunun yerine "nakiti USD mevduat/para piyasasında tut, piyasa açılışında al" de.
  - Eğer nakit <%2 ve acil likidite gerekiyorsa:
    Kripto (7/24 likit) önce sat, ETF ikinci adım olsun.
  - İşlem maliyeti eşiği: $100'ın altındaki nakit hareketleri için ETF önerme,
    komisyon getiriyi yer.
• SPESİFİK TICKER: Portföydeki her hisseyi listede gördüğüne göre
  sınıf değil ticker bazlı karar ver.
• ŞİRKET PROFİLİ NÜANSI — yüzeysel kategorizasyondan kaçın:
  AMZN gelirinin >%70'i AWS (kurumsal bulut) — "tüketici şirketi" değil.
  CRWD SaaS recurring revenue — negatif reel faizde büyüme hissesi DCF değeri artar.
  IREN/BTC madencileri — enerji maliyetine doğrudan bağlı (petrol/elektrik).
  Her hissenin gerçek iş modelini gerekçeye yansıt.
• TEFAS HALÜSINASYON YASAĞI: Sözlükte (TEFAS_DB) olmayan fon için
  içerik TAHMİNİ YAPMA. "Tahvil ağırlıklı gibi görünüyor" demek yasak.
  Bilinmeyen fon → "İçerik doğrulanmadı, koru" de.
• İZOLASYON HATASI: Türkiye şoku gibi lokal krizlerde bile
  ABD hisselerindeki zombi pozisyonları (negatif FCF + düşük current ratio)
  değerlendir. "Türkiye'den izole" gerekçesi zombi filtresini es geçmez.
  Zombi hisseler her senaryoda risk taşır — ayrı ayrı değerlendir.
• ZOMBİ KURALI: FCF < 0 VE (Current Ratio < 1.0 VEYA Borç/ÖK > 200)
  ise şirket zombi — sat. Sadece FCF negatifliği yeterli değil,
  şirkette 3 yıllık nakit varsa zombi değildir.
• SENARYO-SPESİFİK DEĞERLEME MANTIKI:
  - YAVAŞ KANAMA / YÜKSEK FAİZ: Büyüme hisseleri iskonto oranı artar → değerleme
    baskısı gerçek. FCF'si pozitif olan büyüme hisseleri bile P/E sıkışır.
  - MALİ DOMINANS / NEGATİF REEL FAİZ: Tam TERSİ geçerli. Negatif reel faizde
    büyüme hisselerinin DCF değeri ARTAR (iskonto oranı düşer). 2020-2021'de
    teknoloji hisseleri negatif reel faizde 3-5x kazandı. Bu ortamda yüksek
    değerlemeli büyüme hisselerini sadece "çarpan yüksek" diye satma — yanlış.
    Bunun yerine: FCF üretimi var mı? Dolar bazlı geliri var mı? Reel varlık mı?
  - STAGFLASYON: Ne büyüme ne değer işe yarar. Sadece emtia + fiyatlama gücü.
    Emtia önerisi altınla sınırlı kalmamalı — petrol/enerji (XLE, USO, CL=F),
    hammadde (XLB, FCX), tarım da stagflasyonda güçlüdür.
    Portföyde emtia ETF yoksa "ALTIN_GRAM_TRY artır + XLE gibi enerji ETF ekle" de.
  This mantığı her hisse kararında uygula — senaryo tipini değerleme çerçevesine yansıt.
• Türkçe yaz
• JSON formatında yanıt ver — aşağıdaki şemayı kullan:

""" + _DIRECTOR_JSON_SCHEMA


def _build_director_message(
    macro_report:     dict,
    us_report:        dict,
    crypto_report:    dict,
    commodity_report: dict,
    turkey_report:    dict,
    portfolio_state:  dict,
    correlations:     dict,
    signal_summary:   dict,
    financial_calendar: list,
    year_target_pct:  float,
    all_data:         dict = None,
) -> str:
    """
    Direktöre gönderilecek kullanıcı mesajını oluştur.
    Ham metrikler değil — yorumlanmış analist raporları.
    """
    lines = []

    # ── 5 Analist Raporu ─────────────────────────────────────────────────
    lines.append("═══ ANALİST RAPORLARI ═══\n")

    reports = [
        ("MAKRO ANALİST",     macro_report),
        ("ABD HİSSE ANALİSTİ", us_report),
        ("KRİPTO ANALİSTİ",   crypto_report),
        ("EMTİA ANALİSTİ",    commodity_report),
        ("TÜRKİYE ANALİSTİ", turkey_report),
    ]

    for title, rep in reports:
        # ana_gerekcce veya ana_gerekce — her iki yazım da kabul edilir
        _ana_key = "ana_gerekcce" if rep.get("ana_gerekcce") else "ana_gerekce"
        if not rep or not rep.get(_ana_key):
            lines.append(f"[{title}] — Veri alınamadı\n")
            continue
        sinyal = rep.get("sinyal", "?")
        guven  = rep.get("guven",  "?")
        ana    = rep.get(_ana_key, "")
        oneri  = rep.get("oneri", "")
        izle   = rep.get("izle",  "")
        # Her analist için özlü format — token tasarrufu
        lines.append(f"[{title}] {sinyal} ({guven}/10): {ana}")
        dest = rep.get("destekleyen", [])[:2]
        risk = rep.get("riskler", [])[:2]
        if dest: lines.append("  ✅ " + " | ".join(dest))
        if risk: lines.append("  ⚠️ " + " | ".join(risk))
        if oneri: lines.append(f"  → Öneri: {oneri[:150]}")
        if izle:  lines.append(f"  → İzle: {izle[:100]}")
        lines.append("")

    # ── Korelasyon Özeti ─────────────────────────────────────────────────
    # Korelasyon analizi + sigorta sinyali
    corr_prompt = correlations.get("prompt", "") if correlations else ""
    if corr_prompt:
        lines.append("═══ KORELASYON ANALİZİ ═══")
        lines.append(corr_prompt[:400])
        lines.append("")

    # Korelasyon sigortası — kritik eşik kontrolü
    try:
        if correlations:
            pairs = correlations.get("cross_asset_pairs", {})
            high_corr = []
            for pair_key, pair_data in pairs.items():
                corr_val = float(pair_data.get("corr_30d", 0) or 0)
                if abs(corr_val) > 0.70:
                    high_corr.append(f"{pair_key}: {corr_val:.2f}")
            if len(high_corr) >= 3:
                lines.append(
                    f"⚠️ KORElASYON SİGORTASI TETİKLENDİ: "
                    f"{len(high_corr)} varlık çifti 0.70 üzerinde korelasyon gösteriyor. "
                    f"({', '.join(high_corr[:3])}) "
                    f"Nakit oranı önerilen seviyenin 1.5 katına çıkarılmalı!"
                )
    except Exception:
        pass

    # ── Portföy Mevcut Durumu — Detaylı Döküm ───────────────────────────
    pa        = portfolio_state.get("analytics", {})
    positions = portfolio_state.get("positions", [])
    cash      = float(portfolio_state.get("cash", 0))

    total_val = (sum(
        float(p.get("shares",0)) * float(p.get("current_price", p.get("avg_cost",0)))
        for p in positions
    ) + cash)

    _usd_try_rate = float(portfolio_state.get("usd_try", 0) or 
                          portfolio_state.get("exchange_rate", 0) or 38.0)
    lines.append("═══ PORTFÖY DETAYLI DÖKÜM (SPESİFİK TICKER KARARLARI İÇİN) ═══")
    lines.append(
        f"Toplam: ${total_val:,.0f} | Nakit: ${cash:,.0f} "
        f"(%{cash/max(total_val,1)*100:.1f}) | "
        f"K/Z: ${pa.get('total_pnl',0):,.0f} (%{pa.get('total_pnl_pct',0):.1f}) | "
        f"1 USD = {_usd_try_rate:.1f} TL (TRY varlıklar bu kur ile USD'ye çevrildi)"
    )

    # Yardımcı etiket haritaları
    _CRYPTO_BETA = {
        "BTC-USD":0.9,"ETH-USD":1.3,"SOL-USD":1.8,"BNB-USD":1.4,
        "XRP-USD":1.5,"AVAX-USD":1.9,"DOGE-USD":2.2,"PEPE-USD":3.5,
        "WIF-USD":4.0,"JUP-USD":2.8,"INJ-USD":2.5,"SUI-USD":2.3,
    }
    _COMM_LABELS = {
        "ALTIN_GRAM_TRY": "[Enflasyon_koruyucu|Resesyon_defansif|Dolar_zayiflama_pozitif]",
        "GUMUS_GRAM_TRY": "[Enflasyon_koruyucu|Sanayi_baglantili]",
        "GC=F":  "[Resesyon_defansif|Enflasyon_koruyucu]",
        "SI=F":  "[Sanayi_baglantili|Enflasyon_koruyucu]",
        "CL=F":  "[Resesyon_hassas|Jeopolitik_pozitif]",
    }
    # TEFAS_DB'den dinamik etiket üret
    _TEFAS_LABELS = {
        kod: f"{v[1]} → [Resesyon_{v[2]}_risk|Beta_{v[4]}]"
        for kod, v in TEFAS_DB.items()
    }

    # Sınıf bazında grupla ve listele
    class_groups = {}
    for p in positions:
        ac  = p.get("asset_class", "us_equity")
        cur = float(p.get("current_price", p.get("avg_cost", 0)))
        avg = float(p.get("avg_cost", 0))
        val = float(p.get("shares", 0)) * cur
        pnl = (cur - avg) / avg * 100 if avg > 0 else 0
        class_groups.setdefault(ac, []).append({
            "ticker": p.get("ticker",""), "val": val,
            "pnl": pnl, "cur": cur, "avg": avg,
            "sector": p.get("sector",""),
            "currency": p.get("currency","USD"),
        })

    for ac, pos_list in sorted(class_groups.items(),
                                key=lambda x: -sum(p["val"] for p in x[1])):
        ac_total = sum(p["val"] for p in pos_list)
        ac_pct   = ac_total / max(total_val, 1) * 100
        lines.append(f"")
        # TRY ağırlıklı sınıflar için TL göster
        _ac_has_try = any(p.get("currency","USD") == "TRY" for p in pos_list)
        _ac_total_str = f"{ac_total:,.0f} TL" if (_ac_has_try and ac in ("tefas","commodity")) else f"${ac_total:,.0f}"
        lines.append(f"[{ac.upper()}] Toplam: {_ac_total_str} (%{ac_pct:.1f})")

        for p in sorted(pos_list, key=lambda x: -x["val"]):
            tk       = p["ticker"]
            is_try   = (p.get("currency","USD") == "TRY")
            # TRY varlıklar: değeri TL cinsinden göster, USD ağırlık için portföy %'si kullan
            val_disp = (f"{p['val']:,.0f} TL" if is_try
                       else f"${p['val']:,.0f}")
            base = (f"  {tk:16s} | %{p['val']/max(total_val,1)*100:.1f} portföy"
                    f" | {val_disp} | K/Z:{p['pnl']:+.1f}%")

            if ac == "us_equity":
                extra = f" | Sektör:{p['sector']}" if p['sector'] else ""
            elif ac == "crypto":
                beta = _CRYPTO_BETA.get(tk, 2.0)
                tag  = ("BTC_DEFANSIF" if tk == "BTC-USD" else
                        "ETH_ORTA"     if tk == "ETH-USD" else
                        "SPEKULATIF_YUKSEK_BETA")
                extra = f" | Beta(BTC=1):{beta:.1f} [{tag}]"
            elif ac == "commodity":
                extra = " | " + _COMM_LABELS.get(tk, "[Emtia]")
            elif ac == "tefas":
                _db = TEFAS_DB.get(tk.upper(), TEFAS_UNKNOWN_RULE)
                _tip, _icerik, _ress, _kur, _beta, _not = _db
                _bilinmiyor = (_tip == "BİLİNMEYEN")
                extra = (
                    f" | [{_tip}] {_icerik} | "
                    f"Resesyon:{_ress} | Beta:{_beta} | Kur:{_kur}"
                    + (f" | ⚠️ BİLİNMEYEN: {_not[:60]}" if _bilinmiyor
                       else f" | 📋 {_not[:50]}")
                )
            else:
                extra = ""
            lines.append(base + extra)

    lines.append("")
    lines.append("KURAL: Yukarıdaki spesifik ticker listesini kullanarak karar ver.")
    lines.append("'ABD hisselerini azalt' değil → 'AVGO sat, SCHD koru' gibi.")

    # Mikro-maliyet uyarısı — küçük pozisyonlar için
    _kucuk_pozisyonlar = [
        p for ac in class_groups.values()
        for p in ac
        if p["val"] < 500 and p["val"] > 0
    ]
    if _kucuk_pozisyonlar:
        lines.append("")
        lines.append("═══ MİKRO-MALİYET UYARISI ═══")
        lines.append(
            "Aşağıdaki pozisyonlar $500 altında. SAT kararı vermeden önce "
            "komisyon + spread + vergi etkisini hesapla. "
            "Net kazanç < $20 ise işlem maliyetine değmeyebilir — 'KORU' tercih et:"
        )
        for p in sorted(_kucuk_pozisyonlar, key=lambda x: x["val"]):
            _komisyon_tahmini = max(1.0, p["val"] * 0.001)  # ~%0.1 komisyon tahmini
            _min_fayda = _komisyon_tahmini * 3  # En az 3x komisyon fayda olmalı
            lines.append(
                f"  • {p['ticker']:12s}: ${p['val']:,.0f} | "
                f"Tahmini komisyon: ~${_komisyon_tahmini:.1f} | "
                f"Satış için minimum fayda gereksinimi: ~${_min_fayda:.0f}"
            )
        lines.append(
            "KURAL: Pozisyon değeri < $500 ve beklenen fayda < $50 ise SAT önerme. "
            "Bunun yerine 'Yeni alım yaparken bu pozisyonu birleştir' de."
        )

    # ── Nakit realizasyon kontrolü ─────────────────────────────────────
    # Direktör nakit hedefi belirlediğinde bunun matematiksel olarak
    # mevcut satışlarla karşılanıp karşılanamayacağını kontrol et
    lines.append("")
    lines.append("═══ NAKİT REALİZASYON KONTROLÜ ═══")
    _us_val    = sum(p["val"] for p in class_groups.get("us_equity", []))
    _crypto_val= sum(p["val"] for p in class_groups.get("crypto", []))
    _comm_val  = sum(p["val"] for p in class_groups.get("commodity", []))
    _tefas_val = sum(p["val"] for p in class_groups.get("tefas", []))
    # Olası nakit hedeflerine göre önceden hesaplama yap
    _t0_max   = _us_val + _crypto_val + _comm_val
    _t2_max   = _tefas_val
    _total_liq = cash + _t0_max + _t2_max

    lines.append(
        f"Mevcut nakit: ${cash:,.0f} (%{cash/max(total_val,1)*100:.1f})"
    )
    lines.append(
        f"T+0 satılabilir maksimum: ${_t0_max:,.0f} "
        f"(ABD hisse ${_us_val:,.0f} + Kripto ${_crypto_val:,.0f} + Emtia ${_comm_val:,.0f})"
    )
    lines.append(f"T+2 satılabilir maksimum: ${_t2_max:,.0f} (TEFAS)")
    lines.append(f"Toplam likidite potansiyeli: ${_total_liq:,.0f}")
    lines.append("")

    # Nakit hedef senaryoları — direktöre hazır matematik
    for _hedef_pct in [15, 25, 40, 55]:
        _hedef_dolar = total_val * _hedef_pct / 100
        _ek_ihtiyac  = max(0, _hedef_dolar - cash)
        _t0_karsilar = min(_ek_ihtiyac, _t0_max)
        _t2_karsilar = min(max(0, _ek_ihtiyac - _t0_karsilar), _t2_max)
        _karsilanamaz = max(0, _ek_ihtiyac - _t0_karsilar - _t2_karsilar)
        _durum = "✅ Karşılanabilir" if _karsilanamaz == 0 else f"❌ ${_karsilanamaz:,.0f} eksik"
        lines.append(
            f"  %{_hedef_pct} nakit hedefi = ${_hedef_dolar:,.0f} | "
            f"Ek ihtiyaç: ${_ek_ihtiyac:,.0f} | "
            f"T+0'dan: ${_t0_karsilar:,.0f} | T+2'den: ${_t2_karsilar:,.0f} | {_durum}"
        )

    lines.append("")
    lines.append("")
    lines.append("► NAKİT REALİZASYON PLANI DOLDURMA TALİMATI:")
    lines.append(
        "1. Portföy aksiyon planındaki önerilen nakit ağırlığını belirle (örn %20)"
    )
    lines.append(
        f"2. Yukarıdaki tablodan o satırı bul:"
        f" T+0'dan gelecek nakit + T+2'den TEFAS nakdi + mevcut nakit = hedef mi?"
    )
    lines.append(
        "3. nakit_realizasyon_plani JSON alanını MUTLAKA doldur:"
        " bugun_t0 = 'Hangi varlıklar T+0 satılıyor ve ne kadar nakit gelir?'"
        " t2_tefas = 'Hangi TEFAS fonları satılıyor ve T+2'de ne kadar nakit gelir?'"
        " toplam_hedef = 'Hedef $ tutarı'"
        " tutarli_mi = 'Matematik tutuyor mu?'"
    )
    lines.append("❌ BU ALAN BOŞ KALIRSA ANALİZ TAMAMLANMIŞ SAYILMAZ.")

    # ── Yaklaşan Önemli Olaylar ─────────────────────────────────────────
    if financial_calendar:
        critical = [e for e in financial_calendar if e.get("stars", 1) >= 3][:3]
        if critical:
            lines.append("\n═══ YAKLAŞAN KRİTİK OLAYLAR ═══")
            for e in critical:
                lines.append(f"• {e['date']}: {e['event']} ({e.get('days_until',0)} gün)")

    # ── Tarihsel Kriz Karşılaştırması ────────────────────────────────────
    _crisis_ctx = all_data.get("crisis_context", "") if isinstance(all_data, dict) else ""
    if _crisis_ctx:
        lines.append(_crisis_ctx)
    elif all_data and isinstance(all_data, dict):
        _comps = all_data.get("crisis_comparisons", [])
        if _comps:
            lines.append("\n═══ TARİHSEL BENZERLİK ═══")
            for c in _comps[:2]:
                lines.append(
                    f"• {c['label']}: %{c['similarity_pct']:.0f} benzerlik | "
                    f"Risk: {c['risk_level']} | Tetikleyici: {c['trigger']}"
                )

    # ── Sistematik Risk Göstergeleri ─────────────────────────────────────
    _sys = all_data.get("systemic_risk", {}) if isinstance(all_data, dict) else {}
    _buffett = _sys.get("buffett", {})
    if isinstance(_buffett, dict) and _buffett.get("ratio"):
        lines.append(f"\nBuffett Göstergesi: %{_buffett['ratio']:.0f} "
                     f"(ort. %100, 2000 zirvesi %148, 2007 %105) — {_buffett.get('note','')[:80]}")

    _finstress = all_data.get("financial_stress", {}) if isinstance(all_data, dict) else {}
    if _finstress:
        kre = _finstress.get("KRE")
        if kre and hasattr(kre, "note"):
            lines.append(f"Bölgesel Banka Stres (KRE): {kre.note[:80]}")

    # ── Yıl Sonu Hedefi Bağlamı ─────────────────────────────────────────
    lines.append(f"\n═══ YIL SONU HEDEFİ ═══")
    lines.append(f"Hedef: %{year_target_pct:.0f} | Mevcut portföy: ${pa.get('total_value',0):,.0f}")

    # ── Direktöre Yanıtlaması Gereken Sorular ───────────────────────────
    lines.append("""
═══ YANITMANI GEREKTİREN SORULAR ═══
1. Bu portföy için şu an en doğru strateji ne? (piyasa_ozeti)
2. Analistlerin çelişkilerini nasıl çözüyorsun? (celiskiler)
3. Hemen, koşullu ve bekle olarak aksiyonları sırala (portfoy_aksiyonlari)
4. Risk senaryosu gelirse ne yapmalıyım? (risk_senaryosu)
5. Kısa/orta/uzun vadede ne yapmalıyım? (vade_planlari)
6. Yıl sonu hedefine ulaşmak için yeterli risk alıyor muyum? (yil_sonu_hedefi)
7. Bir sonraki ne zaman ve neye bakmalıyım? (bir_sonraki_kontrol)

Yanıtını aşağıdaki JSON formatında ver:""")

    lines.append("""
════════════════════════════════════
Yukarıdaki analist raporlarını sentezle ve sistem promptundaki JSON formatında yanıt ver.
Tüm alanları doldur, hiçbirini boş bırakma. Sadece JSON döndür, açıklama ekleme.
""")
    return "\n".join(lines)


def run_director(
    macro_report:       dict,
    us_report:          dict,
    crypto_report:      dict,
    commodity_report:   dict,
    turkey_report:      dict,
    portfolio_state:    dict,
    correlations:       dict,
    signal_summary:     dict,
    financial_calendar: list,
    user_profile:       dict,
    year_target_pct:    float = 40.0,
    all_data:           dict = None,
) -> dict:
    """
    Strateji direktörü — 5 analist raporunu alıp sentezler.
    Hafıza sistemi entegrasyonu: analiz öncesi bağlam enjekte eder,
    analiz sonrası kararı kaydeder.
    """
    # ── Hafıza Bağlamını Oluştur (Prompt Enjeksiyonu) ──────────────────────
    memory_context = ""
    try:
        from director_memory import memory as _memory
        # Mevcut piyasa verilerini al (hafıza karşılaştırması için)
        _macro = all_data.get("macro", {}) if all_data else {}
        _inds  = _macro.get("indicators", {})
        _vix   = _inds.get("VIX", {})
        _btc_d = (all_data.get("crypto", {}).get("prices", {}).get("BTC", {})
                  if all_data else {})
        _cur_vix = float(_vix.get("value", 0) if isinstance(_vix, dict) else 0)
        _cur_btc = float(_btc_d.get("price", 0) if isinstance(_btc_d, dict) else 0)
        _cur_try = float(portfolio_state.get("usd_try", 0))

        memory_context = _memory.build_context(
            mevcut_vix=_cur_vix,
            mevcut_btc=_cur_btc,
            mevcut_try=_cur_try,
        )
        if memory_context:
            logger.info("Hafıza bağlamı enjekte edildi (%d karakter)", len(memory_context))
    except Exception as e:
        logger.warning("Hafıza bağlamı üretilemedi (devam ediliyor): %s", e)

    # ── Direktör Analizini Çalıştır ────────────────────────────────────────
    system  = _build_director_system(user_profile, year_target_pct, memory_context)
    message = _build_director_message(
        macro_report, us_report, crypto_report,
        commodity_report, turkey_report,
        portfolio_state, correlations, signal_summary,
        financial_calendar, year_target_pct,
        all_data=all_data,
    )

    logger.info("Direktör analizi başlıyor...")
    result = _call_claude(system, message, MAX_TOKENS_DIRECTOR, retries=2)

    parsed = _safe_json(result, {
        "piyasa_ozeti": "Direktör analizi alınamadı.",
        "analist_sentezi": {},
        "celiskiler": [],
        "portfoy_aksiyonlari": {
            "hemen_yap": [], "kosullu_yap": [],
            "izle_karar_ver": [],
            "nakit_orani": {"onerilen_pct": 15, "mevcut_pct": 0, "neden": "Varsayılan"}
        },
        "risk_senaryosu": {
            "tetikleyici": "VIX 30+ veya S&P %8 düşüş",
            "ilk_24_saat": ["Spekülatif pozisyonları %50 küçült"],
            "savunma": ["Nakidi %30'a çıkar"],
            "firsat_listesi": [],
            "toparlanma_sinyali": "VIX 20 altına düşünce"
        },
        "vade_planlari": {
            "kisa": {"sure": "1-3 ay", "baz_senaryo": "", "risk_senaryosu": "", "aksiyonlar": []},
            "orta": {"sure": "3-12 ay", "baz_senaryo": "", "risk_senaryosu": "", "aksiyonlar": []},
            "uzun": {"sure": "1-3 yıl", "tema": "", "pozisyonlama": ""},
        },
        "yil_sonu_hedefi": {
            "hedef_pct": year_target_pct, "mevcut_pct": 0,
            "kalan_pct": year_target_pct, "gerekan_aylik_pct": 0,
            "risk_degerlendirmesi": "", "tavsiye": ""
        },
        "bir_sonraki_kontrol": {
            "tarih": "", "neden": "", "tetikleyiciler": []
        }
    })

    parsed["_generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["_analyst_reports"] = {
        "makro":   macro_report,
        "abd":     us_report,
        "kripto":  crypto_report,
        "emtia":   commodity_report,
        "turkiye": turkey_report,
    }

    logger.info("Direktör analizi tamamlandı.")

    # ── Kararı Hafızaya Kaydet ─────────────────────────────────────────────
    try:
        from director_memory import memory as _memory

        # Rejim tespiti
        _rejim = parsed.get("piyasa_ozeti", "")[:50] or "Belirsiz"
        # Analiz sinyalinden rejimi çıkar
        _sentez = parsed.get("analist_sentezi", {})
        _makro_sig = _sentez.get("makro", {}).get("sinyal", "")
        if _makro_sig in ("SAT", "AZALT"):
            _rejim_etiket = "Savunma"
        elif _makro_sig in ("AL", "ARTIR"):
            _rejim_etiket = "Risk-On"
        else:
            _rejim_etiket = "Nötr/Bekle"

        # Aksiyonları hafıza formatına dönüştür
        _pa       = parsed.get("portfoy_aksiyonlari", {})
        _aksiyonlar = []
        for _item in (_pa.get("hemen_yap", []) + _pa.get("kosullu_yap", [])):
            _tk = _item.get("ticker") or _item.get("varlik", "")
            _ey = _item.get("eylem", "")
            _mp = _item.get("miktar_pct") or _item.get("miktar", 0)
            if _tk and _ey:
                _aksiyonlar.append({
                    "varlik":     _tk,
                    "eylem":      _ey,
                    "miktar_pct": _mp,
                    "fiyat":      0,  # Anlık fiyat burada yok — trigger_monitor tarafından doldurulabilir
                })

        # Mevcut piyasa değerleri
        _macro_raw = all_data.get("macro", {}) if all_data else {}
        _inds_raw  = _macro_raw.get("indicators", {})
        _vix_val   = float(_inds_raw.get("VIX", {}).get("value", 0) if isinstance(_inds_raw.get("VIX"), dict) else 0)
        _btc_val   = float((all_data.get("crypto", {}).get("prices", {}).get("BTC", {}).get("price", 0)) if all_data else 0)
        _try_val   = float(portfolio_state.get("usd_try", 0))

        _memory.save_decision(
            vix             = _vix_val,
            btc_fiyat       = _btc_val,
            usdtry          = _try_val,
            rejim           = _rejim_etiket,
            ana_aksiyonlar  = _aksiyonlar[:10],
            ozet            = parsed.get("piyasa_ozeti", "")[:200],
            trigger_kaynagi = "strateji_analizi",
        )
        logger.info("Direktör kararı hafızaya kaydedildi: %s", _rejim_etiket)
    except Exception as e:
        logger.warning("Hafıza kayıt hatası (analiz etkilenmedi): %s", e)

    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# ANA ORKESTRATÖR — İki Aşamanın Koordinasyonu
# ═══════════════════════════════════════════════════════════════════════════

def run_two_phase_analysis(
    all_data:        dict,
    progress_callback = None,  # Streamlit progress güncellemesi için
) -> dict:
    """
    İki aşamalı analizi baştan sona yürüt.

    all_data içermeli: macro, economic, crypto, commodity, turkey,
                       portfolio, correlations, signals, calendar, user_profile

    progress_callback(step: int, total: int, message: str) formatında çağrılır.
    """
    total_steps = 7  # 5 analist + 1 direktör + 1 hazırlık
    step        = 0

    def _progress(msg: str):
        nonlocal step
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, msg)
        logger.info("Analiz adımı %d/%d: %s", step, total_steps, msg)

    portfolio_positions = all_data.get("portfolio", {}).get("positions", [])
    user_profile        = all_data.get("user_profile", {})
    year_target         = float(user_profile.get("year_target_pct", 40.0))
    signal_summary      = {}

    # Sinyal motoru çıktılarını özetle
    signals_raw = all_data.get("signals", {})
    for key in ["macro", "us_equity", "crypto", "commodity", "turkey"]:
        s = signals_raw.get(key)
        if s:
            signal_summary[key] = {
                "signal":     s.signal     if hasattr(s, "signal")     else s.get("signal",    "?"),
                "confidence": s.confidence if hasattr(s, "confidence") else s.get("confidence", 5),
                "reason":     s.reason     if hasattr(s, "reason")     else s.get("reason",    ""),
            }

    # ── Aşama A: 5 Uzman Analist ─────────────────────────────────────────
    _progress("Makro analist çalışıyor...")
    macro_report = analyze_macro_with_claude(
        all_data.get("macro",    {}),
        all_data.get("economic", {}),
    )
    time.sleep(0.5)

    _progress("ABD hisse analisti çalışıyor...")
    us_report = analyze_us_equity_with_claude(
        all_data.get("economic", {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Kripto analisti çalışıyor...")
    crypto_report = analyze_crypto_with_claude(
        all_data.get("crypto",  {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Emtia analisti çalışıyor...")
    commodity_report = analyze_commodity_with_claude(
        all_data.get("commodity", {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Türkiye analisti çalışıyor...")
    turkey_report = analyze_turkey_with_claude(
        all_data.get("turkey",  {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    # ── Aşama B: Strateji Direktörü ──────────────────────────────────────
    _progress("Strateji direktörü sentez yapıyor...")
    director_output = run_director(
        macro_report       = macro_report,
        us_report          = us_report,
        crypto_report      = crypto_report,
        commodity_report   = commodity_report,
        turkey_report      = turkey_report,
        portfolio_state    = all_data.get("portfolio",    {}),
        correlations       = all_data.get("correlations", {}),
        signal_summary     = signal_summary,
        financial_calendar = all_data.get("calendar",    []),
        user_profile       = user_profile,
        year_target_pct    = year_target,
        all_data           = all_data,
    )

    return {
        "success":         True,
        "director":        director_output,
        "analyst_reports": {
            "makro":   macro_report,
            "abd":     us_report,
            "kripto":  crypto_report,
            "emtia":   commodity_report,
            "turkiye": turkey_report,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
