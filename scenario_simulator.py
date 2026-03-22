# scenario_simulator.py — Senaryo Simülasyon Motoru
#
# Gerçek piyasa verisi yerine kullanıcı tanımlı senaryolarla
# strateji direktörünü test eder.
#
# Mimari:
# 1. Senaryo → Sentetik makro veri üret
# 2. Sentetik veriyi sinyal motoruna geçir
# 3. Sinyal motorunu direktöre geçir
# 4. Direktörün rebalancing önerisini al
# 5. Portföy etki analizini hesapla

import logging


# ─── İşlem Maliyeti ve Valör Gerçeklikleri ────────────────────────────────────
# Direktörün zamanlama önerilerine dahil edilir

TRANSACTION_REALITIES = {
    "us_equity": {
        "valör_gün":    0,      # T+0 — ABD hisseleri anlık
        "spread_bps":   5,      # ~5 baz puan alım-satım farkı
        "likit":        True,
        "not":          "T+0 işlem, piyasa açıkken anlık gerçekleşir"
    },
    "crypto": {
        "valör_gün":    0,      # 7/24 anlık
        "spread_bps":   10,     # Kripto spread yüksek olabilir
        "likit":        True,
        "not":          "7/24 işlem. VIX 34 ortamında spread genişleyebilir (+%1-2)"
    },
    "commodity": {
        "valör_gün":    1,      # ETF ise T+0, fiziksel ise daha uzun
        "spread_bps":   3,
        "likit":        True,
        "not":          "GLD/IAU ETF: T+0. Fiziksel altın: T+2. Altın gram TRY: borsa saatlerinde"
    },
    "tefas": {
        "valör_gün":    2,      # T+2 standart
        "spread_bps":   0,      # TEFAS NAV üzerinden, spread yok
        "likit":        False,  # Günlük valör kısıtı var
        "not":          "TEFAS satış emri T+2 valörlüdür. Likidite krizi döneminde gecikmeler olabilir. "
                        "IIH satış → nakit T+2'de gelir → AEY alım T+2 sonrası mümkün. "
                        "Bu 4 günlük boşlukta hedge: mevcut nakit ile altın (commodity) al."
    },
}

from dataclasses import dataclass, field
from typing import Dict, Any

logger = logging.getLogger(__name__)


# ─── Senaryo Tanımları ────────────────────────────────────────────────────────

SCENARIOS = {
    "fed_dovish_shock": {
        "isim":    "Fed Sürpriz Faiz İndirimi + İşsizlik Spike",
        "ozet": (
            "Fed beklenmedik şekilde 75-100bp sert indirim yaptı. "
            "Aynı anda işsizlik %4.2'den %5.8'e fırladı (kötü NFP). "
            "Bu kombinasyon panik kesildi mi, resesyon mu başlıyor sorusunu doğuruyor."
        ),
        "tetikleyici": "Fed FOMC açıklaması + NFP verisi aynı hafta",
        "tarihsel_benzer": "2001 Eylül sonrası Fed indirimleri, 2008 Aralık acil indirim",
        # Sentetik makro göstergeler — gerçek değerlere göre sapma
        "macro_overrides": {
            # Faiz ortamı
            "fed_rate":          {"value": 3.75,  "change_pct": -4.5,  "signal": "amber",
                                  "note": "Fed 100bp sürpriz indirim — piyasa 25bp bekliyordu"},
            "treasury_10y":      {"value": 3.85,  "change_pct": -8.2,  "signal": "green",
                                  "note": "Tahvil rallisi — güvenli liman talebi arttı"},
            "treasury_2y":       {"value": 3.20,  "change_pct": -12.0, "signal": "green",
                                  "note": "2Y hızla düşüyor — piyasa daha fazla indirim fiyatlıyor"},
            "yield_curve":       {"value": 0.65,  "change_pct": +180.0,"signal": "neutral",
                                  "note": "Eğri dikleşiyor — resesyon sinyali tersine döndü mü?"},
            # Korku & Volatilite
            "vix":               {"value": 34.0,  "change_pct": +42.0, "signal": "red",
                                  "note": "VIX 34 — belirsizlik çok yüksek, piyasa panikliyor"},
            "ovx":               {"value": 48.0,  "change_pct": -15.0, "signal": "amber",
                                  "note": "Petrol volatilitesi düştü — talep endişesi petrolü baskılıyor"},
            "move_index":        {"value": 145.0, "change_pct": +22.0, "signal": "red",
                                  "note": "Tahvil volatilitesi yüksek — Fed'in adımı sürpriz yarattı"},
            # Dolar & FX
            "dxy":               {"value": 97.2,  "change_pct": -2.8,  "signal": "amber",
                                  "note": "Dolar zayıflıyor — faiz farkı avantajı azaldı"},
            "usdjpy":            {"value": 142.0, "change_pct": -8.5,  "signal": "red",
                                  "note": "Yen güçleniyor — carry trade çözülmesi riski!"},
            # Emtia
            "gold":              {"value": 3380,  "change_pct": +5.2,  "signal": "green",
                                  "note": "Altın güvenli liman talebiyle yükseliyor"},
            "wti_oil":           {"value": 72.0,  "change_pct": -8.0,  "signal": "red",
                                  "note": "Petrol düşüyor — talep yavaşlama beklentisi"},
            "copper":            {"value": 4.12,  "change_pct": -6.5,  "signal": "red",
                                  "note": "Bakır düşüşü büyüme yavaşlaması sinyal veriyor"},
            # Credit
            "credit_spread":     {"value": 520,   "change_pct": +48.0, "signal": "red",
                                  "note": "HY spread genişledi — kredi riski artıyor"},
        },
        # Ekonomik göstergeler
        "economic_overrides": {
            "NFP":    {"value": -85,  "prev": 180,  "note": "İstihdam -85K — beklenti +180K, büyük sürpriz"},
            "ISE":    {"value": 5.8,  "prev": 4.2,  "note": "İşsizlik %5.8 — hızla yükseliyor"},
            "ISM_MFG":{"value": 44.2, "prev": 49.1, "note": "İmalat PMI 44.2 — daralma bölgesinde"},
            "ISM_SVC":{"value": 47.8, "prev": 52.3, "note": "Hizmetler PMI de daralmaya döndü"},
            "GDP":    {"value": -0.4, "prev": 2.1,  "note": "GDP büyüme eksi bölgede — teknik resesyon eşiği"},
        },
        # Her varlık sınıfı üzerindeki beklenen etki
        "asset_impacts": {
            "us_equity": {
                "beklenti":   "Karışık — büyüme endişesi vs ucuz para",
                "kisa_vade":  -8.0,   # % beklenen değişim
                "orta_vade":  +12.0,  # Fed indiriminin gecikmeli etkisi
                "en_iyi":     ["Temettü hisseleri", "Finans", "Utilities"],
                "en_kotu":    ["Döngüsel", "Enerji", "Küçük sermayeli"],
            },
            "crypto": {
                "beklenti":   "Risk-off → kısa vade baskı, ucuz para → orta vade pozitif",
                "kisa_vade":  -15.0,
                "orta_vade":  +25.0,
                "en_iyi":     ["BTC (kıyıya çekilme, dijital altın hikayesi)"],
                "en_kotu":    ["Spekülatif altcoinler (likidite kanalı bozuluyor)"],
            },
            "commodity": {
                "beklenti":   "Altın pozitif, petrol negatif",
                "kisa_vade":  +3.0,   # Altın etkisiyle pozitif
                "orta_vade":  +8.0,
                "en_iyi":     ["Altın", "Gümüş", "TIPS"],
                "en_kotu":    ["Petrol", "Bakır", "Enerji emtiaları"],
            },
            "tefas": {
                "beklenti":   "Türkiye görece izole ama USDJPY çözülmesi TL'yi vurar",
                "kisa_vade":  -5.0,   # Dolar/TL volatilitesi
                "orta_vade":  -2.0,
                "en_iyi":     ["Altın fonları", "Enflasyona endeksli"],
                "en_kotu":    ["Hisse yoğun fonlar", "Dolar bazlı fonlar"],
            },
        },
    },

    "stagflation_shock": {
        "isim":  "Stagflasyon Şoku",
        "ozet":  "Enflasyon yeniden tırmanıyor, büyüme duruyor",
        "macro_overrides": {
            "vix":       {"value": 28.0,  "change_pct": +18.0, "signal": "amber", "note": "Orta korku"},
            "wti_oil":   {"value": 105.0, "change_pct": +12.0, "signal": "red",   "note": "Petrol $105"},
            "copper":    {"value": 3.90,  "change_pct": -3.0,  "signal": "amber", "note": "Bakır zayıf"},
            "gold":      {"value": 3200,  "change_pct": +2.0,  "signal": "green", "note": "Altın sabit"},
            "dxy":       {"value": 103.0, "change_pct": +1.5,  "signal": "green", "note": "Dolar güçlü"},
        },
        "economic_overrides": {
            "CPI_YOY": {"value": 4.8, "prev": 3.1, "note": "CPI yeniden yükseliyor"},
            "GDP":     {"value": 0.3, "prev": 2.1, "note": "Büyüme neredeyse sıfır"},
        },
        "asset_impacts": {
            "us_equity": {"kisa_vade": -12.0, "orta_vade": -5.0},
            "crypto":    {"kisa_vade": -20.0, "orta_vade": -10.0},
            "commodity": {"kisa_vade": +8.0,  "orta_vade": +15.0},
            "tefas":     {"kisa_vade": -8.0,  "orta_vade": -12.0},
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    # SENARYOLARINIZDAKİ 3 SENARYO
    # ══════════════════════════════════════════════════════════════════════

    "yavas_kanama": {
        "isim":   "Yavaş Kanama — Kredi Duvarı ve Zombi Şirketler",
        "ozet": (
            "Borsa nominal olarak çökmüyor ama enflasyondan arındırıldığında yıllarca "
            "yerinde sayıyor. 1970'ler ABD'si ve 1990 sonrası Japonya senaryosu. "
            "$14T kurumsal borç yeniden finansmanı %5-6 faizle yapılmak zorunda — "
            "zombi şirketler nakit akışlarını faize veriyor, büyüme sıfır. "
            "Reel getiri negatif, nominal getiri pozitif görünüyor."
        ),
        "tetikleyici": "Kurumsal tahvil vade dolumu + yüksek faiz kalıcılığı + zombi iflas dalgası",
        "tarihsel_benzer": "1966-1982 ABD (kayıp on yıl), 1990-2010 Japonya (lost decade)",
        "macro_overrides": {
            "vix":         {"value": 18.0,  "change_pct": -5.0,  "signal": "green",
                            "note": "VIX düşük — tehlike görünmüyor, aldatıcı sessizlik"},
            "treasury_10y":{"value": 5.20,  "change_pct": +8.0,  "signal": "red",
                            "note": "10Y yüksek faiz kalıcı — refinansman maliyeti artıyor"},
            "credit_spread":{"value": 580,  "change_pct": +35.0, "signal": "red",
                             "note": "HY spread 580bp — zombi şirket temerrüt riski yükseliyor"},
            "gold":        {"value": 3600,  "change_pct": +8.0,  "signal": "green",
                            "note": "Altın yükseliyor — enflasyon hedge talebi"},
            "copper":      {"value": 3.85,  "change_pct": -8.0,  "signal": "red",
                            "note": "Bakır düşüyor — gerçek büyüme zayıf"},
            "dxy":         {"value": 105.0, "change_pct": +2.0,  "signal": "amber",
                            "note": "Dolar güçlü — sermaye ABD'de kalıyor ama reel değer eriyor"},
            "wti_oil":     {"value": 88.0,  "change_pct": +3.0,  "signal": "amber",
                            "note": "Petrol orta seviyede — talep düşük ama arz kısıtlı"},
        },
        "economic_overrides": {
            "CPI_YOY":  {"value": 4.2,  "prev": 3.1,  "note": "Enflasyon yapışkan — Fed hedefinin üzerinde kalıcı"},
            "GDP":      {"value": 0.8,  "prev": 2.1,  "note": "Büyüme pozitif ama yetersiz — reel büyüme negatif"},
            "ISM_MFG":  {"value": 46.5, "prev": 49.2, "note": "İmalat daralıyor — zombi şirketler yatırım yapmıyor"},
            "NFP":      {"value": 45,   "prev": 180,  "note": "İstihdam yavaşladı — zombi şirketler işe almıyor"},
            "CORP_DEBT":{"value": 14.2, "prev": 13.8, "note": "$14.2T kurumsal borç vadesi dolmakta — refinansman baskısı"},
        },
        "asset_impacts": {
            "us_equity": {
                "kisa_vade": +3.0,   # Nominal yükseliş var
                "orta_vade": -15.0,  # Ama reel kayıp (enflasyon düşüldüğünde)
                "en_iyi":  ["Temettü aristokratları (FCF güçlü)", "Sağlık/Utilities (fiyatlama gücü)", "Değer hisseleri"],
                "en_kotu": ["Zombi şirketler (yüksek borç, negatif FCF)", "Büyüme hisseleri (uzun vadeli nakit akışı iskontolar)", "Küçük sermayeli (refinansman riski)"],
                "not":     "UYARI: Nominal +%3 görünse de enflasyon %4.2 → reel getiri -%1.2",
            },
            "crypto": {
                "kisa_vade": -5.0,
                "orta_vade": +20.0,  # Bitcoin sabit arz → enflasyon hedge
                "en_iyi":  ["BTC (sabit arz, enflasyon hedge)"],
                "en_kotu": ["Spekülatif altcoinler (likidite kurur)"],
            },
            "commodity": {
                "kisa_vade": +6.0,
                "orta_vade": +25.0,  # En iyi reel koruyan varlık
                "en_iyi":  ["Altın (merkez bankası alımları devam)", "Gümüş", "TIPS"],
                "en_kotu": ["Petrol (talep düşük büyümeden)"],
            },
            "tefas": {
                "kisa_vade": +2.0,   # TL nominal yükseliş
                "orta_vade": -20.0,  # Ama dolar bazında kayıp
                "en_iyi":  ["Altın fonları (AEY)", "Enflasyona endeksli tahvil fonları"],
                "en_kotu": ["Hisse yoğun fonlar (IIH — zombi riski)", "TL tahvil fonları (reel negatif)"],
            },
        },
    },

    "likidite_soku": {
        "isim":   "Likidite Şoku — Dash for Cash (Nakide Hücum)",
        "ozet": (
            "Herkes aynı anda nakde dönmek istiyor. VIX saatler içinde 45-50'ye fırlıyor. "
            "Margin call dalgası başlıyor — fonlar zararına satmak yerine EN LİKİT ve "
            "KÂRLİ varlıklarını satıyor: Altın, Bitcoin ve büyük teknoloji. "
            "2008 Eylül ve 2020 Mart'ın tekrarı. Güvenli liman teorisi bu anda çöküyor."
        ),
        "tetikleyici": "Büyük hedge fon iflası veya prime brokerage krizi + margin call zinciri",
        "tarihsel_benzer": "2008 Eylül (Lehman), 2020 Mart (COVID), 2022 Mart (LME nikel)",
        "macro_overrides": {
            "vix":          {"value": 48.0,  "change_pct": +95.0, "signal": "red",
                             "note": "VIX 48 — panik zirvesi. 2020 Mart benzeri"},
            "move_index":   {"value": 185.0, "change_pct": +55.0, "signal": "red",
                             "note": "MOVE 185 — tahvil piyasası da donuyor"},
            "credit_spread":{"value": 820,   "change_pct": +120.0,"signal": "red",
                             "note": "HY spread 820bp — kredi piyasası dondu"},
            "gold":         {"value": 2900,  "change_pct": -12.0, "signal": "red",
                             "note": "ALTIN DÜŞÜYOR — margin call için satılıyor (karşı-sezgisel!)"},
            "treasury_10y": {"value": 3.20,  "change_pct": -22.0, "signal": "green",
                             "note": "10Y rallisi — tek güvenli liman kısa ABD tahvili"},
            "usdjpy":       {"value": 138.0, "change_pct": -10.0, "signal": "red",
                             "note": "Yen güçleniyor — carry trade çözülüyor, global satış"},
            "dxy":          {"value": 108.0, "change_pct": +5.0,  "signal": "amber",
                             "note": "Dolar güçleniyor — nakide hücum = dolara hücum"},
            "wti_oil":      {"value": 58.0,  "change_pct": -25.0, "signal": "red",
                             "note": "Petrol çöküyor — talep panik, margin satışı"},
        },
        "economic_overrides": {
            "VIX_TERM":  {"value": 48.0,  "prev": 22.0, "note": "VIX term yapısı backwardation — anlık panik"},
            "TED_SPREAD":{"value": 185,   "prev": 35,   "note": "TED spread 185bp — bankalar birbirine borç vermiyor"},
            "LIBOR_OIS": {"value": 145,   "prev": 12,   "note": "Fonlama piyasası dondurulmuş"},
            "NFP":       {"value": -250,  "prev": 150,  "note": "İstihdam çöküyor — gerçek ekonomi etkilendi"},
        },
        "asset_impacts": {
            "us_equity": {
                "kisa_vade": -25.0,
                "orta_vade": +35.0,  # Fed müdahalesi sonrası V şekilli toparlanma mümkün
                "en_iyi":  ["Kısa ABD tahvili (SHV, BIL)", "Nakit dolar"],
                "en_kotu": ["Her şey düşüyor — korelasyon 1.0'a gidiyor"],
                "not":     "KRİTİK: İlk 48 saatte kaliteli varlıklar da düşer. Fed müdahalesi bekle.",
            },
            "crypto": {
                "kisa_vade": -40.0,
                "orta_vade": +60.0,
                "en_iyi":  ["BTC (kısa vade düşer ama uzun vade toparlanır)"],
                "en_kotu": ["Tüm altcoinler — likidite yokluğunda %70-80 düşebilir"],
            },
            "commodity": {
                "kisa_vade": -15.0,  # ALTIN DA DÜŞER — margin satışı
                "orta_vade": +20.0,
                "en_iyi":  ["Sonraki aşamada altın — Fed QE sonrası"],
                "en_kotu": ["Altın bile kısa vadede satılır (karşı-sezgisel!)"],
                "not":     "ALTIN PARADOKSU: Likidite krizinde altın önce düşer, sonra toparlanır",
            },
            "tefas": {
                "kisa_vade": -18.0,
                "orta_vade": -5.0,
                "en_iyi":  ["Kamu tahvil fonları (GAF)"],
                "en_kotu": ["IIH, TTE — hisse yoğun fonlar"],
            },
        },
    },

    "mali_dominans": {
        "isim":   "Mali Dominans — İtibari Para Çöküşü (Nominal Melt-Up)",
        "ozet": (
            "Fed bağımsızlığını kaybediyor, devlet borçlarını finanse etmek için "
            "para basıyor. Borsa düşmüyor — çıldırmış gibi yükseliyor (nominal). "
            "Ama ekmek fiyatı borsadan daha hızlı artıyor. "
            "Reel getiri negatif. Türkiye 2021-2022, Weimar, Venezuela örnekleri. "
            "Sabit arzlı varlıklar (BTC, altın) gerçek kazanan."
        ),
        "tetikleyici": "Kongre bütçe krizi + Fed YCC (Yield Curve Control) açıklaması + dolar güven kaybı",
        "tarihsel_benzer": "Türkiye 2021-2022, 1970'ler ABD, Weimar 1921-1923, Venezuela 2016+",
        "macro_overrides": {
            "vix":          {"value": 22.0,  "change_pct": +5.0,  "signal": "amber",
                             "note": "VIX orta — piyasa panik değil, enflasyonla yaşıyor"},
            "gold":         {"value": 5200,  "change_pct": +35.0, "signal": "green",
                             "note": "Altın $5200 — para değer kaybı hedge"},
            "treasury_10y": {"value": 2.80,  "change_pct": -35.0, "signal": "amber",
                             "note": "10Y yapay baskıda — Fed YCC uyguluyor, gerçek faiz negatif"},
            "dxy":          {"value": 88.0,  "change_pct": -12.0, "signal": "red",
                             "note": "Dolar çöküyor — güven kaybı, rezerv para statüsü sorgulanıyor"},
            "wti_oil":      {"value": 145.0, "change_pct": +45.0, "signal": "red",
                             "note": "Petrol $145 — dolar zayıflığı + talep enflasyonu"},
            "copper":       {"value": 6.20,  "change_pct": +25.0, "signal": "green",
                             "note": "Bakır $6.20 — nominal büyüme + dolar zayıflığı"},
            "usdjpy":       {"value": 175.0, "change_pct": +15.0, "signal": "amber",
                             "note": "Dolar-yen yükseliyor — yen de değer kaybediyor"},
        },
        "economic_overrides": {
            "CPI_YOY":   {"value": 12.5, "prev": 3.1,  "note": "CPI %12.5 — çift haneli enflasyon"},
            "GDP_NOMINAL":{"value": 8.5, "prev": 2.1,  "note": "Nominal GDP +%8.5 ama reel +%0.5"},
            "M2_GROWTH": {"value": 18.0, "prev": 4.5,  "note": "M2 para arzı +%18 — para basımı hızlandı"},
            "REAL_RATE":  {"value": -7.5, "prev": 1.2, "note": "Reel faiz -%7.5 — paradan kaç!"},
            "DEBT_GDP":   {"value": 145, "prev": 125,   "note": "Kamu borcu/GDP %145 — sürdürülemez"},
        },
        "asset_impacts": {
            "us_equity": {
                "kisa_vade": +18.0,  # Nominal yükseliş
                "orta_vade": +45.0,  # Nominal çok yüksek ama reel?
                "en_iyi":  ["Reel varlık şirketleri (madencilik, enerji, gayrimenkul)", "Uluslararası geliri yüksek şirketler"],
                "en_kotu": ["Nakit tutan şirketler", "Uzun vadeli sabit gelirli kontratlar"],
                "not":     "UYARI: Nominal +%45 görünse de enflasyon %12.5 → reel getiri sadece +%29",
            },
            "crypto": {
                "kisa_vade": +35.0,
                "orta_vade": +150.0,  # Bitcoin sabit arz — en iyi enflasyon hedge
                "en_iyi":  ["BTC (21M sabit arz — dijital altın)", "ETH (deflationary post-merge)"],
                "en_kotu": ["Stablecoin (dolar değer kaybı direkt yansır)"],
                "not":     "BTC bu senaryoda en iyi varlık — sabit arz vs sonsuz para basımı",
            },
            "commodity": {
                "kisa_vade": +25.0,
                "orta_vade": +80.0,
                "en_iyi":  ["Altın (MB alımları + güven kaybı)", "Gümüş", "Petrol", "Bakır"],
                "en_kotu": ["Nakit (dolar cinsinden tutulan)"],
            },
            "tefas": {
                "kisa_vade": +10.0,   # TL nominal yükseliş
                "orta_vade": -35.0,   # Dolar bazında yıkım
                "en_iyi":  ["Altın fonları (AEY — TL'den kaç)", "Döviz/Eurobond fonları"],
                "en_kotu": ["TL tahvil fonları (GAF)", "Hisse fonları (TL bazlı nominal yükseliş ama dolar kaybı)"],
                "not":     "TEFAS yatırımcısı için en tehlikeli senaryo — TL değer kaybı tüm getiriyi siler",
            },
        },
    },

    # ══════════════════════════════════════════════════════════════════════
    # BENİM ÖNERDİĞİM 3 SENARYO
    # ══════════════════════════════════════════════════════════════════════

    "risk_on_pivot": {
        "isim":   "Risk-On Pivot — Büyüme Patlaması",
        "ozet": (
            "Fed faiz artışı beklenirken enflasyon ani düştü (%2.1'e). "
            "İstihdam güçlü, yapay zeka yatırımları patladı, GDP sürprizi pozitif. "
            "Piyasa tam risk-on moda geçiyor. Direktör defansiften agresife "
            "geçebiliyor mu?"
        ),
        "tetikleyici": "CPI sürpriz düşüş + güçlü NFP + NVDA kazanç patlaması",
        "tarihsel_benzer": "2023 Kasım rallisi, 1995 Soft Landing, 2009 toparlanma başlangıcı",
        "macro_overrides": {
            "vix":         {"value": 13.5,  "change_pct": -38.0, "signal": "green",
                            "note": "VIX 13.5 — tam risk-on, korku yok"},
            "copper":      {"value": 5.40,  "change_pct": +18.0, "signal": "green",
                            "note": "Bakır $5.40 — güçlü büyüme beklentisi"},
            "treasury_10y":{"value": 3.80,  "change_pct": -15.0, "signal": "green",
                            "note": "10Y faiz düşüyor — Fed pivot beklentisi"},
            "dxy":         {"value": 96.0,  "change_pct": -4.5,  "signal": "amber",
                            "note": "Dolar zayıflıyor — risk-on, EM avantajlı"},
            "gold":        {"value": 2800,  "change_pct": -8.0,  "signal": "amber",
                            "note": "Altın düşüyor — risk-on, güvenli liman terk ediliyor"},
            "wti_oil":     {"value": 82.0,  "change_pct": +8.0,  "signal": "amber",
                            "note": "Petrol yükseliyor — güçlü büyüme talebi"},
            "usdjpy":      {"value": 152.0, "change_pct": +3.0,  "signal": "neutral",
                            "note": "Yen zayıfladı — carry trade yeniden aktif"},
        },
        "economic_overrides": {
            "CPI_YOY": {"value": 2.1,  "prev": 3.8, "note": "CPI %2.1 — Fed hedefine ulaştı, sürpriz düşüş"},
            "NFP":     {"value": 320,  "prev": 180, "note": "İstihdam güçlü — %320K, beklenti %190K"},
            "GDP":     {"value": 3.8,  "prev": 2.1, "note": "GDP %3.8 — sürpriz güçlü büyüme"},
            "ISM_MFG": {"value": 54.5, "prev": 48.2,"note": "İmalat genişliyor — yeni siparişler artıyor"},
        },
        "asset_impacts": {
            "us_equity": {
                "kisa_vade": +12.0,
                "orta_vade": +28.0,
                "en_iyi":  ["Yarı iletken (NVDA, AVGO, AMD)", "Yazılım (MSFT, NOW)", "Küçük sermayeli (IWM)"],
                "en_kotu": ["Defansif (XLP, XLU — para çıkışı)", "Altın madencileri"],
            },
            "crypto": {
                "kisa_vade": +25.0,
                "orta_vade": +80.0,
                "en_iyi":  ["BTC", "ETH", "SOL — risk-on altcoinler canlanır"],
                "en_kotu": ["Stablecoin (fırsat maliyeti artar)"],
            },
            "commodity": {
                "kisa_vade": -5.0,   # Altın düşer
                "orta_vade": +8.0,
                "en_iyi":  ["Petrol (talep artışı)", "Bakır (büyüme)"],
                "en_kotu": ["Altın (güvenli liman terk edilir)"],
            },
            "tefas": {
                "kisa_vade": +8.0,
                "orta_vade": +15.0,
                "en_iyi":  ["Hisse yoğun fonlar (IIH, TTE)", "Büyüme hisse fonları"],
                "en_kotu": ["Altın fonları (AEY — geride kalır)"],
            },
        },
    },

    "turkey_shock": {
        "isim":   "Türkiye Spesifik Şok — TL Krizi",
        "ozet": (
            "TL ani %30 değer kaybı. BIST dolar bazında çöküyor. "
            "TCMB acil faiz artışı yapıyor. Türkiye'ye özgü şok — "
            "ABD ve kripto piyasaları görece sakin. "
            "Direktör portföyün Türkiye bacağını bağımsız yönetebiliyor mu?"
        ),
        "tetikleyici": "Siyasi kriz + döviz rezervi erimesi + TCMB güven kaybı",
        "tarihsel_benzer": "Türkiye 2018 (Brunson krizi), 2021 (TCMB başkan değişimi), 2022",
        "macro_overrides": {
            "vix":         {"value": 19.0,  "change_pct": +8.0,  "signal": "amber",
                            "note": "VIX orta — global piyasa sakin, Türkiye spesifik"},
            "usdjpy":      {"value": 149.0, "change_pct": -1.0,  "signal": "neutral",
                            "note": "Yen stabil — carry trade etkilenmiyor"},
            "dxy":         {"value": 104.0, "change_pct": +2.0,  "signal": "amber",
                            "note": "Dolar hafif güçlü — EM baskısı var ama sınırlı"},
            "gold":        {"value": 3420,  "change_pct": +5.0,  "signal": "green",
                            "note": "Altın yükseliyor — EM krizi hedge talebi"},
            "usdtry":      {"value": 52.0,  "change_pct": +30.0, "signal": "red",
                            "note": "USD/TRY 52 — TL %30 değer kaybı (38'den 52'ye)"},
            "bist100":     {"value": 8500,  "change_pct": -25.0, "signal": "red",
                            "note": "BIST dolar bazında -%25 çöktü"},
            "copper":      {"value": 4.50,  "change_pct": 0.0,   "signal": "neutral",
                            "note": "Bakır stabil — Türkiye global büyümeyi etkilemiyor"},
        },
        "economic_overrides": {
            "USDTRY":     {"value": 52.0,  "prev": 38.0,  "note": "TL %36 değer kaybı"},
            "TR_ENFLASYON":{"value": 75.0, "prev": 48.0,  "note": "Türkiye enflasyonu %75'e tırmandı"},
            "TCMB_FAIZ":  {"value": 55.0,  "prev": 47.5,  "note": "TCMB acil 750bp faiz artışı"},
            "CDS_TURKEY": {"value": 520,   "prev": 280,   "note": "Türkiye CDS 520bp — kredi riski arttı"},
            "NFP":        {"value": 180,   "prev": 180,   "note": "ABD istihdamı normal — izole şok"},
        },
        "asset_impacts": {
            "us_equity": {
                "kisa_vade": -2.0,   # Minimal etki
                "orta_vade": +3.0,
                "en_iyi":  ["Büyük ABD şirketleri (Türkiye'ye ihracat minimal)"],
                "en_kotu": ["Türkiye'de büyük operasyonu olan şirketler"],
                "not":     "ABD hisseleri bu senaryoda görece güvenli",
            },
            "crypto": {
                "kisa_vade": +5.0,   # TL'den kaçış kripto'ya
                "orta_vade": +10.0,
                "en_iyi":  ["BTC (Türkiye'de dolarizasyon artıyor)", "USDT kullanımı artar"],
                "en_kotu": [],
            },
            "commodity": {
                "kisa_vade": +8.0,
                "orta_vade": +15.0,
                "en_iyi":  ["Altın gram TRY (hem dolar hem TL bazında kazanır)", "Dolar bazlı emtia"],
                "en_kotu": [],
                "not":     "ALTIN_GRAM_TRY bu senaryoda çift motorlu kazanır: hem dolar artışı hem TL düşüşü",
            },
            "tefas": {
                "kisa_vade": -35.0,  # TL bazlı nominal, dolar bazında çöküş
                "orta_vade": -45.0,
                "en_iyi":  ["Altın fonları (AEY — TL değer kaybına karşı korur)", "Döviz fonları"],
                "en_kotu": ["IIH (BIST çöküşü + TL değer kaybı çift darbe)", "TL tahvil fonları (reel negatif)"],
                "not":     "Türkiye şokunda TEFAS portföyü ciddi risk altında — hızlı aksiyon gerekiyor",
            },
        },
    },
}



def build_scenario_data(
    scenario_key: str,
    portfolio_positions: list,
    portfolio_cash: float,
    user_profile: dict,
    usd_try: float = 38.0,
) -> dict:
    """
    Senaryo parametrelerini gerçek strateji veri formatına dönüştür.
    Direktörün anlayacağı veri paketini oluşturur.
    """
    scenario = SCENARIOS.get(scenario_key)
    if not scenario:
        raise ValueError(f"Bilinmeyen senaryo: {scenario_key}")

    macro_ovr = scenario.get("macro_overrides", {})
    econ_ovr  = scenario.get("economic_overrides", {})

    # Portföy değerini ve dağılımını hesapla
    pos_by_class = {"us_equity": [], "crypto": [], "commodity": [], "tefas": [], "other": []}
    total_val_usd = 0.0

    for p in portfolio_positions:
        ac      = p.get("asset_class", "us_equity")
        shares  = float(p.get("shares", 0))
        avg     = float(p.get("avg_cost", 0))
        cur     = float(p.get("current_price", avg))
        cur_usd = cur / usd_try if p.get("currency") == "TRY" else cur
        val_usd = shares * cur_usd
        total_val_usd += val_usd
        pos_by_class.setdefault(ac, []).append({
            **p, "val_usd": val_usd, "cur_usd": cur_usd
        })

    total_with_cash = total_val_usd + portfolio_cash
    class_weights   = {
        ac: sum(p["val_usd"] for p in pos) / total_with_cash * 100
        for ac, pos in pos_by_class.items()
        if pos
    }

    # Holdings detayı — her sınıf içindeki pozisyonlar ağırlıklı
    holdings_detail = {}
    for ac, pos in pos_by_class.items():
        if not pos:
            continue
        ac_total = sum(p["val_usd"] for p in pos)
        holdings_detail[ac] = sorted([
            {
                "ticker":      p["ticker"],
                "shares":      float(p.get("shares", 0)),
                "avg_cost":    float(p.get("avg_cost", 0)),
                "cur_usd":     round(p["cur_usd"], 2),
                "val_usd":     round(p["val_usd"], 2),
                "weight_in_class": round(p["val_usd"] / ac_total * 100, 1) if ac_total > 0 else 0,
                "weight_in_port":  round(p["val_usd"] / total_with_cash * 100, 2) if total_with_cash > 0 else 0,
                "pnl_pct":     round((p["cur_usd"] - float(p.get("avg_cost", 0))) /
                                     float(p.get("avg_cost", 1)) * 100, 1)
                               if float(p.get("avg_cost", 0)) > 0 else 0,
                "sector":      p.get("sector", ""),
                "asset_class": ac,
            }
            for p in pos
        ], key=lambda x: -x["val_usd"])

    # Senaryo sonrası tahmini değerler
    asset_impacts = scenario.get("asset_impacts", {})
    projected_weights = {}
    projected_total   = portfolio_cash  # nakit değişmez
    for ac, pos in pos_by_class.items():
        if not pos:
            continue
        cur_val    = sum(p["val_usd"] for p in pos)
        impact_pct = asset_impacts.get(ac, {}).get("kisa_vade", 0)
        new_val    = cur_val * (1 + impact_pct / 100)
        projected_total += new_val
        projected_weights[ac] = new_val

    proj_pct = {
        ac: v / projected_total * 100
        for ac, v in projected_weights.items()
    }

    return {
        "scenario_key":   scenario_key,
        "scenario_label": scenario["isim"],
        "scenario_ozet":  scenario["ozet"],
        "tetikleyici":    scenario.get("tetikleyici", ""),
        "tarihsel_benzer":scenario.get("tarihsel_benzer", ""),

        # Sentetik makro — direktörün göreceği
        "macro": {
            "indicators": macro_ovr,
            "regime": {
                "regime":      "RISK_OFF",
                "label":       "Risk-Off (Senaryo)",
                "color":       "#e74c3c",
                "description": scenario["ozet"],
            }
        },

        # Ekonomik veri
        "economic": econ_ovr,

        # Portföy mevcut durumu
        "portfolio": {
            "positions":   portfolio_positions,
            "cash":        portfolio_cash,
            "total_value": total_val_usd,
            "cash_ratio":  portfolio_cash / total_with_cash * 100 if total_with_cash > 0 else 0,
            "analytics": {
                "total_value":    round(total_val_usd, 0),
                "total_with_cash": round(total_with_cash, 0),
                "class_weights":  class_weights,
            }
        },

        # Senaryo etki analizi (direktöre ek bağlam)
        "asset_impacts":      asset_impacts,
        "class_weights_now":  class_weights,
        "class_weights_proj": proj_pct,
        "holdings_detail":    holdings_detail,
        "projected_total":    round(projected_total, 0),
        "projected_loss":     round(projected_total - total_with_cash, 0),

        # Kullanıcı profili
        "user_profile": user_profile,

        # Boş alanlar — direktör sadece yukarıdakilerle çalışır
        "crypto":       {},
        "commodity":    {},
        "turkey":       {},
        "correlations": {},
        "signals":      {},
        "calendar":     [],
    }


def build_scenario_director_prompt(scenario_data: dict) -> str:
    """
    Direktör için özel senaryo prompt'u — gerçek analizden farklı olarak
    senaryo bağlamını ve portföy mevcut durumunu net gösterir.
    """
    sc   = scenario_data
    pa   = sc["portfolio"]["analytics"]
    cw   = sc["class_weights_now"]
    pw   = sc["class_weights_proj"]
    ai   = sc["asset_impacts"]
    prof = sc["user_profile"]

    lines = [
        "═══ ACİL SENARYO SİMÜLASYONU ═══",
        f"Senaryo: {sc['scenario_label']}",
        f"Özet: {sc['scenario_ozet']}",
        f"Tetikleyici: {sc.get('tetikleyici','')}",
        f"Tarihsel Benzer: {sc.get('tarihsel_benzer','')}",
        "",
        "═══ SENTETIK MAKRO ORTAM ═══",
    ]

    for key, ind in sc["macro"]["indicators"].items():
        sig_map = {"red": "⚠️", "amber": "⚡", "green": "✅", "neutral": "—"}
        sig = sig_map.get(ind.get("signal", "neutral"), "—")
        lines.append(
            f"  {sig} {key}: {ind['value']} ({ind.get('change_pct',0):+.1f}%) "
            f"— {ind.get('note','')}"
        )

    lines.append("")
    lines.append("═══ EKONOMİK GÖSTERGELER ═══")
    for key, ind in sc["economic"].items():
        lines.append(f"  {key}: {ind['value']} (önceki: {ind['prev']}) — {ind.get('note','')}")

    lines.append("")
    lines.append("═══ MEVCUT PORTFÖY DURUMU ═══")
    lines.append(f"Toplam Değer: ${pa['total_value']:,.0f} | Nakit: ${sc['portfolio']['cash']:,.0f} (%{sc['portfolio']['cash_ratio']:.1f})")
    lines.append("")
    lines.append("DETAYLI POZİSYON DÖKÜMÜ (Direktör bu veriyi kullanarak SPESIFIK TICKER kararı üretmeli):")

    # Kripto beta ve emtia etiket haritaları — direktöre ek bağlam
    _CRYPTO_BETA = {
        "BTC-USD":0.9,"ETH-USD":1.3,"SOL-USD":1.8,"BNB-USD":1.4,
        "XRP-USD":1.5,"AVAX-USD":1.9,"DOGE-USD":2.2,"PEPE-USD":3.5,
        "WIF-USD":4.0,"JUP-USD":2.8,"INJ-USD":2.5,"SUI-USD":2.3,
    }
    _COMM_LABELS = {
        "ALTIN_GRAM_TRY": "Altın(TRY) [Enflasyon_koruyucu|Resesyon_defansif]",
        "GUMUS_GRAM_TRY": "Gümüş(TRY) [Enflasyon_koruyucu|Sanayi_baglantili]",
        "GC=F": "Altın Futures [Resesyon_defansif]",
        "SI=F": "Gümüş Futures [Sanayi_baglantili]",
        "CL=F": "WTI Petrol [Resesyon_hassas|Jeopolitik_pozitif]",
    }
    _TEFAS_LABELS = {
        "IIH": "%90 BIST+Yabancı Hisse [Resesyon_YUKSEK|Beta_YÜKSEK] — Zombi riskine maruz",
        "NNF": "%90+ BIST Hisse, BİRİNCİ FON [Resesyon_YUKSEK|Beta_YÜKSEK] — TAHVİL DEĞİL, agresif hisse",
        "TTE": "%85 Teknoloji Hisse [Resesyon_YUKSEK|Beta_COK_YÜKSEK] — Faiz hassas",
        "MAC": "%80 Bankacılık [Resesyon_COK_YUKSEK|Beta_YÜKSEK] — Kredi döngüsüne hassas",
        "AEY": "%80 Fiziksel Altın [Resesyon_DUSUK|Beta_ORTA] — Enflasyon hedge",
        "AOY": "%75 Fiziksel Altın [Resesyon_DUSUK|Beta_ORTA] — Enflasyon hedge",
        "GAF": "%90 Devlet Tahvili TL [Resesyon_DUSUK|Beta_DUSUK] — Kur riski var",
        "YAC": "%50 Hisse %50 Tahvil [Resesyon_ORTA|Beta_ORTA]",
        "TI1": "Kısa Vadeli TL Tahvil [Resesyon_DUSUK|Beta_COK_DUSUK]",
        "TSI": "Para Piyasası benzeri [Resesyon_DUSUK|Beta_COK_DUSUK]",
        "URA": "Uranyum/Nükleer [Resesyon_ORTA|Beta_YÜKSEK] — Yapısal tema",
        "NNM": "Karma Fon [Resesyon_ORTA|Beta_ORTA] — İçerik teyit gerekli",
    }
    # Bilinmeyen fon kuralı
    def _tefas_label(kod):
        return _TEFAS_LABELS.get(kod,
            f"⚠️ BİLİNMEYEN FON [{kod}] — İçerik tahmin yapılmaz, koru veya küçük azalt"
        )


    holdings = sc.get("holdings_detail", {})
    for ac, pos_list in sorted(holdings.items(), key=lambda x: -sum(p["val_usd"] for p in x[1])):
        ac_total = sum(p["val_usd"] for p in pos_list)
        ac_pct   = ac_total / max(pa["total_value"] + sc["portfolio"]["cash"], 1) * 100
        lines.append(f"")
        lines.append(f"[{ac.upper()}] — Toplam: ${ac_total:,.0f} (%{ac_pct:.1f})")
        for p in pos_list:
            base = (
                f"  {p['ticker']:16s} | %{p['weight_in_port']:.1f} portföy "
                f"| ${p['val_usd']:,.0f} | K/Z: {p['pnl_pct']:+.1f}%"
            )
            # Varlık sınıfına göre ek bilgi
            if ac == "us_equity":
                extra = f" | Sektör: {p.get('sector','?')}"
            elif ac == "crypto":
                beta = _CRYPTO_BETA.get(p["ticker"], 2.0)
                tag  = "BTC_DEFANSIF" if p["ticker"]=="BTC-USD" else (
                       "ETH_ORTA" if p["ticker"]=="ETH-USD" else "SPEKULATIF_YUKSEK_BETA")
                extra = f" | Beta(BTC=1):{beta:.1f} [{tag}]"
            elif ac == "commodity":
                extra = " | " + _COMM_LABELS.get(p["ticker"], "Emtia")
            elif ac == "tefas":
                extra = " | " + _tefas_label(p["ticker"].upper())
            else:
                extra = ""
            lines.append(base + extra)

    lines.append("")
    lines.append("Varlık Sınıfı Özet:")
    for ac, pct in sorted(cw.items(), key=lambda x: -x[1]):
        lines.append(f"  • {ac}: %{pct:.1f}")

    lines.append("")
    lines.append("═══ SENARYO SONRASI TAHMİNİ ETKİ ═══")
    for ac, impact in ai.items():
        kisa = impact.get("kisa_vade", 0)
        orta = impact.get("orta_vade", 0)
        emoji = "📈" if kisa > 0 else "📉"
        lines.append(
            f"  {emoji} {ac}: Kısa vade {kisa:+.0f}% | Orta vade {orta:+.0f}%"
        )
        if impact.get("en_iyi"):
            lines.append(f"     ✅ Kazananlar: {', '.join(impact['en_iyi'][:2])}")
        if impact.get("en_kotu"):
            lines.append(f"     ❌ Kaybedenler: {', '.join(impact['en_kotu'][:2])}")

    lines.append(f"\nSenaryo sonrası tahmini portföy: ${sc['projected_total']:,.0f} "
                 f"(etki: ${sc['projected_loss']:+,.0f})")

    lines.append("")
    lines.append("═══ KULLANICI PROFİLİ ═══")
    lines.append(f"Risk toleransı: {prof.get('risk_tol','Orta')}")
    lines.append(f"Zaman ufku: {prof.get('time_horizon','Uzun vade')}")
    lines.append(f"Yıl sonu hedef: %{prof.get('year_target_pct', 40):.0f}")

    # Valör ve işlem maliyeti — gerçek dünya kısıtları
    lines.append("")
    lines.append("═══ İŞLEM MALİYETİ VE VALÖR GERÇEKLİKLERİ ═══")
    for ac, tr in TRANSACTION_REALITIES.items():
        lines.append(
            f"  {ac}: Valör T+{tr['valör_gün']} | "
            f"{'Likit' if tr['likit'] else 'Kısıtlı Likidite'} | "
            f"{tr['not']}"
        )
    lines.append(
        "  VALÖR BOŞLUĞU KURALI: Uzun valörlü varlık satışı emri ver → "
        "nakitte hazır para varsa kısa valörlü alternatifi HEMEN al. "
        "Örn: IIH sat (T+2 nakit) → bugün mevcut nakitle altın (GLD) al."
    )

    lines.append("""
═══ DİREKTÖR GÖREVİ ═══
Bu senaryo GERÇEKLEŞIYOR. Yukarıdaki DETAYLI POZİSYON DÖKÜMÜNÜ kullanarak
spesifik ticker bazlı kararlar ver — "ABD hisselerini azalt" değil,
"AVGO'yu tamamen sat (%2.0 portföy), SCHD'yi koru" gibi.

Valör gerçekliklerini hesaba kat:
- TEFAS satışı T+2 → nakdi bugün altın/nakit ile hedge et
- Kripto 7/24 likit → ilk azaltılacak sınıf

JSON formatında yanıtla — schema sistem promptunda.""")

    return "\n".join(lines)
