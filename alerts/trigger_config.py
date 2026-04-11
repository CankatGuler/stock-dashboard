# trigger_config.py — Tetikleyici Sistem Konfigürasyonu
#
# Bu dosya, tüm tetikleyici eşiklerini, ATR parametrelerini ve
# rotasyon kurallarını tek bir yerde tanımlar.
# Sistemi ayarlamak için SADECE bu dosyayı düzenlemen yeterli.
#
# Mimari Hatırlatma:
#   Katman 1 → Acil alarmlar (15 dk, 7/24)
#   Katman 2 → Önemli sinyaller (saatte bir, 06:00-23:00)
#   Katman 3 → Günlük sabah özeti (07:30 TR saati)

# ─── Genel Ayarlar ────────────────────────────────────────────────────────────

# Aynı tetikleyici kaç saat içinde tekrar alarm vermez?
COOLDOWN_HOURS = 6

# Gece sessiz saatleri — sadece Katman 1 çalışır (UTC+3 = Türkiye)
QUIET_HOURS_START = 0   # 00:00 TR
QUIET_HOURS_END   = 6   # 06:00 TR

# Günlük özet saati (Türkiye saati, 24h format)
MORNING_SUMMARY_HOUR_TR = 7
MORNING_SUMMARY_MINUTE  = 30

# ATR hesaplama periyodu (gün sayısı)
ATR_PERIOD_DAYS = 14

# ─── Katman 1: Acil Alarm Eşikleri ────────────────────────────────────────────
# Her değer kendi mantık çerçevesinde açıklanmıştır.

LAYER1 = {

    # VIX ani spike
    # ATR bazlı: son 4 saatlik ATR'nin kaç katı olursa alarm verir?
    # Mutlak eşik: VIX bu seviyeyi ilk kez geçerse her zaman alarm ver.
    "vix_spike": {
        "atr_multiplier":     3.0,   # 4h ATR × 3.0 = dinamik eşik
        "absolute_threshold": 32,    # VIX > 32 → her zaman alarm
        "lookback_hours":     4,     # Değişim hesaplama penceresi
        "enabled":            True,
    },

    # BTC ani düşüş
    # Dinamik eşik: 4 saatlik ATR × çarpan kadar düşüş = alarm
    "btc_crash": {
        "atr_multiplier":   2.5,   # Normal volatilitenin 2.5 katı
        "lookback_hours":   4,
        "enabled":          True,
    },

    # USD/TRY ani spike
    # Günlük ATR'nin 1.5 katı = olağandışı TL hareketi
    "usdtry_spike": {
        "atr_multiplier":   1.5,   # Günlük ATR × 1.5
        "lookback_hours":   4,
        "enabled":          True,
    },

    # Stablecoin de-peg — USDT veya USDC
    # ATR mantıklı değil (normal vol ~sıfır), mutlak eşik kullanılır.
    "stablecoin_depeg": {
        "usdt_ticker":        "USDT-USD",
        "usdc_ticker":        "USDC-USD",
        "depeg_threshold":    0.995,   # $0.995 altına düşerse alarm
        "systemic_threshold": 0.990,   # Her ikisi birden düşerse → sistemik kriz
        "enabled":            True,
    },
}

# ─── Katman 2: Önemli Sinyal Eşikleri ─────────────────────────────────────────

LAYER2 = {

    # Yield Curve Bull Steepener (Resesyon Tescil Sinyali)
    # Spread son 48 saatte bu kadar normalleştiyse ve 10Y faiz düşüyorsa alarm.
    "yield_curve_bull_steepener": {
        "spread_change_bps":  30,    # 48 saatte 30 baz puan normalleşme
        "require_10y_falling": True,  # 10Y faizin de düşüyor olması şartı
        "lookback_hours":     48,
        "regime":             "BULL_STEEPENER",
        "directoru_senaryo":  "resesyon_tescil",  # Direktörün hangi senaryoyu kullanacağı
        "enabled":            True,
    },

    # Yield Curve Yeniden İnversiyon (Mali Dominans Ön Sinyali)
    # NOT: Bu bir "alım fırsatı" değil, Senaryo 4 (Mali Dominans) tetikleyicisidir.
    # Direktör "emtia artır, SHV al" diyecek, "hisse al" değil.
    "yield_curve_reinversion": {
        "inversion_threshold_bps": -25,  # Spread -25 baz puanın altına düşerse
        "require_short_rising":     True, # Kısa vadeli faizin de yükseliyor olması
        "directoru_senaryo":        "mali_dominans_onsinyali",
        "enabled":                  True,
    },

    # Kripto: Altcoin/BTC Ayrışması (Likidite Şoku Erken Sinyali)
    # BTC yatay/artıda ama altcoinler bu kadar düşüyorsa → erken çıkış sinyali
    "altcoin_btc_divergence": {
        "btc_min_return":        -0.01,  # BTC %-1'den fazla düşmemiş olmalı
        "altcoin_max_return":    -0.03,  # Altcoinler %-3'ten fazla düşmüş
        "lookback_hours":         4,
        "atr_multiplier":         2.0,   # ATR bazlı da desteklenirse daha güçlü sinyal
        "enabled":               True,
    },

    # BIST100 Proxy Düşüş (IIH/NNF Riski)
    "bist_proxy_drop": {
        "ticker":             "XU100.IS",
        "daily_drop_pct":    -4.0,    # Günlük %-4
        "weekly_drop_pct":   -8.0,    # Haftalık %-8
        "enabled":            True,
    },

    # Kripto Funding Rate (Aşırı Isınma / Soğuma)
    # Aşırı pozitif = long birikti, dump riski
    # Aşırı negatif = short birikti, squeeze / dip fırsatı
    "funding_rate": {
        "overheat_threshold": 0.08,    # 8 saatlik funding > %0.08 → aşırı ısınma
        "oversold_threshold": -0.05,   # 8 saatlik funding < -%0.05 → dip fırsatı
        "symbol":             "BTCUSDT",
        "enabled":             True,
    },

    # Open Interest Artışı (Kaldıraçlı Birikme)
    # Fiyat artışıyla birlikte OI çok hızlı büyüyorsa cascade liquidation riski
    "open_interest": {
        "oi_change_pct_4h":  20.0,   # 4 saatte OI > %20 artış
        "require_price_up":   True,   # Fiyat da artıyorsa (kaldıraçlı long birikimi)
        "symbol":            "BTCUSDT",
        "enabled":            True,
    },

    # ── Pozitif Tetikleyiciler (Hücum Moduna Geçiş) ──────────────────────────

    # VIX Normalleşmesi → Risk-On Kapısı
    # 3 günlük ortalama VIX bu eşiğin altına düşerse alarm ver
    "vix_normalization": {
        "threshold":           25,    # VIX 3-gün ort. < 25
        "days_below_required":  3,    # 3 gün boyunca altında kalmalı
        "require_prior_spike":  True, # Öncesinde VIX > 30 görmüş olmalı
        "directoru_senaryo":   "risk_on_pivot",
        "enabled":              True,
    },

    # BTC Dominansı Düşüşe Geçişi → Altcoin Sezonu Açılıyor
    "btc_dominance_cycle": {
        "dominance_drop_pct":  2.0,   # 48 saatte 2 puan düşüş
        "lookback_hours":      48,
        "require_btc_positive": True,  # BTC'nin de artıyor olması gerekir
        "directoru_senaryo":   "altcoin_rotation",
        "enabled":              True,
    },

    # DXY Kırılımı → Riskli Varlıklar ve EM Pozitif
    "dxy_breakdown": {
        "weekly_drop_pct":    -1.5,   # Haftalık %-1.5 düşüş
        "directoru_senaryo":  "dxy_weakening",
        "enabled":             True,
    },

    # Türkiye CDS Düşüşü → Yabancı Sermaye Girişi
    "turkey_cds_drop": {
        "absolute_threshold":    260,   # 260 bps altına düşerse
        "weekly_drop_bps":        40,   # VEYA haftalık 40 bps gerilerse
        "weeks_sustained":          3,  # 3 hafta boyunca ortalamanın 280 altında
        "directoru_senaryo":      "turkey_macro_recovery",
        "enabled":                 True,
    },

    # Kripto Funding Rate Dip Sinyali (negatif funding = dip fırsatı)
    # (funding_rate tetikleyicisinin pozitif tarafı — ayrı işlenecek)
}

# ─── Rotasyon Hiyerarşisi (Cephane Kontrolü) ──────────────────────────────────
# Direktör "AL" diyecekse önce neyi satacağını bilmesi gerekir.
# Risk-off'tan risk-on'a geçişte hangi varlıklar önce satılır?

ROTATION_HIERARCHY = {
    # Risk-on ortamına geçerken satış sırası (defansiften çıkış)
    "risk_on_exit_order": [
        "commodity_gold",    # Önce altın azalt — güvenli liman ihtiyacı azaldı
        "cash_bonds",        # Nakit ve kısa tahvil (TI1, SHV, BIL)
        "tefas_gold",        # Altın TEFAS fonları (AEY)
    ],

    # Risk-on ortamında alım sırası
    "risk_on_entry_order": [
        "tefas_equity",      # IIH, NNF (BIST hisse yoğun)
        "tefas_tech",        # TTE (yabancı teknoloji)
        "tefas_alt_energy",  # AOY (alternatif enerji — yabancı, faize hassas)
        "us_equity_growth",  # ABD büyüme hisseleri (AVGO, AMZN, AMD)
        "crypto_altcoin",    # Majör altcoinler (SOL, AVAX)
    ],

    # Risk-off ortamına geçerken satış sırası
    "risk_off_exit_order": [
        "crypto_altcoin",    # Önce yüksek beta altcoinler
        "crypto_eth",        # ETH
        "tefas_equity",      # Hisse yoğun TEFAS
        "us_equity_growth",  # ABD büyüme hisseleri
    ],

    # Risk-off ortamında alım sırası
    "risk_off_entry_order": [
        "cash_bonds",        # Nakit ve kısa tahvil (SHV, BIL, TI1)
        "commodity_gold",    # Fiziksel altın / GLD / AEY
        "tefas_gold",        # Altın TEFAS fonları
        "crypto_btc",        # Sadece BTC çekirdeği koru
    ],

    # Mali dominans / yeniden inversiyon senaryosunda
    "mali_dominans_entry_order": [
        "commodity_gold",    # Altın önce
        "commodity_energy",  # Enerji (XLE, petrol)
        "cash_short_bond",   # Kısa vadeli tahvil (SHV, BIL — uzun tahvil değil)
        "crypto_btc",        # BTC (sabit arz = enflasyon hedge)
    ],
}

# ─── Minimum Nakit Eşiği (Alım Önerisi İçin) ─────────────────────────────────
# Direktör "AL" diyebilmesi için portföyde en az bu kadar nakit olmalı.
# Yoksa önce "sat" aksiyonu zorunlu.
MIN_CASH_FOR_BUY_PCT = 5.0   # Portföyün %5'i nakit değilse, al demeden önce sat öner

# ─── Portföy Varlık Sınıfı Etiketleri ────────────────────────────────────────
# Rotasyon hiyerarşisindeki etiketler ile portföy varlıklarının eşleşmesi.
# asset_class ve ticker bazlı eşleşme.
ASSET_CLASS_MAP = {
    "commodity_gold":    {"asset_class": "commodity",
                          "tickers": ["ALTIN_GRAM_TRY","GC=F","GLD","IAU"]},
    "commodity_energy":  {"asset_class": "commodity",
                          "tickers": ["XLE","USO","CL=F"]},
    "cash_bonds":        {"asset_class": "us_equity",
                          "tickers": ["SHV","BIL","SGOV","BND"]},
    "cash_short_bond":   {"asset_class": "us_equity",
                          "tickers": ["SHV","BIL","SGOV"]},
    "tefas_gold":        {"asset_class": "tefas",
                          "tickers": ["AEY","GLD_TL"]},
    "tefas_equity":      {"asset_class": "tefas",
                          "tickers": ["IIH","NNF","MAC","YAS"]},
    "tefas_tech":        {"asset_class": "tefas",
                          "tickers": ["TTE"]},
    "tefas_alt_energy":  {"asset_class": "tefas",
                          "tickers": ["AOY"]},
    "us_equity_growth":  {"asset_class": "us_equity",
                          "tickers": ["AVGO","AMZN","AMD","NVDA","CRWD","VRT"]},
    "crypto_btc":        {"asset_class": "crypto",
                          "tickers": ["BTC-USD"]},
    "crypto_eth":        {"asset_class": "crypto",
                          "tickers": ["ETH-USD"]},
    "crypto_altcoin":    {"asset_class": "crypto",
                          "tickers": []},  # BTC ve ETH dışındaki her şey
}

# ─── GitHub Actions Zamanlama Ayarları ────────────────────────────────────────
# Bu değerler .github/workflows/monitor.yml dosyasına yazılacak.
# Burada referans olarak tutulur.
SCHEDULE = {
    "layer1_cron":   "*/15 * * * *",   # Her 15 dakika
    "layer2_cron":   "0 * * * *",      # Her saat başı
    "layer3_cron":   "30 4 * * *",     # UTC 04:30 = TR 07:30
}
