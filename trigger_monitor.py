# trigger_monitor.py — Tetikleyici İzleme Motoru
#
# GitHub Actions tarafından çalıştırılır:
#   Katman 1: Her 15 dakikada bir  → python trigger_monitor.py --layer 1
#   Katman 2: Her saat başı        → python trigger_monitor.py --layer 2
#   Katman 3: Sabah 07:30 TR       → python trigger_monitor.py --layer 3
#
# Her çalışmada:
#   1. İlgili tetikleyiciler kontrol edilir
#   2. Tetiklenen varsa direktör uyandırılır (Claude API)
#   3. Telegram'a mesaj gönderilir
#   4. Cooldown kaydı güncellenir (GitHub Actions cache veya dosya)

import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# trigger_config'i import et
from trigger_config import (
    LAYER1, LAYER2, COOLDOWN_HOURS, QUIET_HOURS_START, QUIET_HOURS_END,
    MORNING_SUMMARY_HOUR_TR, MORNING_SUMMARY_MINUTE,
    ATR_PERIOD_DAYS, ROTATION_HIERARCHY, MIN_CASH_FOR_BUY_PCT, ASSET_CLASS_MAP,
)

# ─── Cooldown Yönetimi ────────────────────────────────────────────────────────
# Aynı tetikleyicinin kaç saat içinde tekrar alarm vermesini engeller.
# Dosya tabanlı — GitHub Actions runner'da geçici olarak çalışır.
# (Kalıcı hafıza için GitHub repo'ya commit edebiliriz veya basit JSON dosyası)

COOLDOWN_FILE = Path(__file__).parent / ".trigger_cooldowns.json"


def _load_cooldowns() -> dict:
    """Mevcut cooldown kayıtlarını yükle."""
    if COOLDOWN_FILE.exists():
        try:
            return json.loads(COOLDOWN_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_cooldowns(cd: dict) -> None:
    COOLDOWN_FILE.write_text(json.dumps(cd, indent=2))


def _is_in_cooldown(trigger_key: str) -> bool:
    """Bu tetikleyici hâlâ cooldown süresinde mi?"""
    cd = _load_cooldowns()
    last_fired = cd.get(trigger_key)
    if not last_fired:
        return False
    elapsed_hours = (time.time() - last_fired) / 3600
    return elapsed_hours < COOLDOWN_HOURS


def _mark_fired(trigger_key: str) -> None:
    """Tetikleyiciyi çalıştı olarak işaretle."""
    cd = _load_cooldowns()
    cd[trigger_key] = time.time()
    _save_cooldowns(cd)


# ─── Türkiye Saati Kontrolü ───────────────────────────────────────────────────

def _turkey_hour() -> int:
    """Şu anki Türkiye saatini döndür (UTC+3)."""
    return (datetime.now(timezone.utc) + timedelta(hours=3)).hour


def _is_quiet_hours() -> bool:
    """Gece sessiz saatleri mi? (00:00-06:00 TR)"""
    h = _turkey_hour()
    return QUIET_HOURS_START <= h < QUIET_HOURS_END


# ─── ATR Hesaplama ────────────────────────────────────────────────────────────

def calculate_atr(ticker: str, period_days: int = ATR_PERIOD_DAYS,
                  interval: str = "1h") -> float:
    """
    Verilen ticker için ATR (Average True Range) hesapla.

    ATR nedir? Bir varlığın 'normal' volatilitesini ölçer.
    Her mum için True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    ATR = bu değerlerin N-günlük ortalaması.

    interval="1h" ile saatlik ATR, "1d" ile günlük ATR hesaplanır.
    Tetikleyici eşiği = ATR × çarpan olarak kullanılır.
    """
    try:
        import yfinance as yf
        # Yeterli veri için period_days × 2 kadar geçmiş al
        lookback = f"{period_days * 2}d"
        df = yf.download(ticker, period=lookback, interval=interval,
                         progress=False, show_errors=False)
        if df.empty or len(df) < period_days:
            logger.warning("ATR hesabı için yeterli veri yok: %s", ticker)
            return 0.0

        # True Range hesapla
        high  = df["High"]
        low   = df["Low"]
        close = df["Close"].shift(1)  # önceki kapanış

        tr = (high - low).combine(
            (high - close).abs(), max
        ).combine(
            (low - close).abs(), max
        )

        # Son period_days'lik ortalama
        atr = float(tr.tail(period_days * 24 if interval == "1h" else period_days).mean())
        logger.debug("ATR %s (%s): %.4f", ticker, interval, atr)
        return atr

    except Exception as e:
        logger.error("ATR hesaplama hatası (%s): %s", ticker, e)
        return 0.0


def get_price_change(ticker: str, lookback_hours: int) -> tuple[float, float]:
    """
    Son lookback_hours içindeki fiyat değişimini döndür.
    Returns: (mevcut_fiyat, değişim_yüzdesi)

    Yöntem 1: history() — MultiIndex sorunu olmayan, güvenilir yol.
    Yöntem 2: fast_info — sadece anlık fiyat + previousClose (24h için)
    """
    try:
        import yfinance as yf

        # Yöntem 1: history() ile saatlik veri — en güvenilir
        t = yf.Ticker(ticker)
        df = t.history(period="5d", interval="1h")

        if not df.empty and len(df) >= 2:
            current = float(df["Close"].iloc[-1])
            idx     = -lookback_hours if len(df) > lookback_hours else 0
            past    = float(df["Close"].iloc[idx])
            if past > 0:
                return current, (current - past) / past * 100

        # Yöntem 2: fast_info — previousClose ile günlük değişim
        fi = t.fast_info
        current = float(getattr(fi, "last_price", 0) or 0)
        prev    = float(getattr(fi, "previous_close", 0) or 0)
        if current > 0 and prev > 0:
            return current, (current - prev) / prev * 100

        return 0.0, 0.0

    except Exception as e:
        logger.error("Fiyat değişimi hatası (%s): %s", ticker, e)
        return 0.0, 0.0


# ─── Katman 1 Tetikleyicileri ─────────────────────────────────────────────────

def check_vix_spike() -> dict | None:
    """
    VIX ani spike kontrolü.
    Dinamik eşik: 4 saatlik ATR × çarpan
    Mutlak eşik: VIX > 32 (her zaman alarm)
    """
    cfg = LAYER1["vix_spike"]
    if not cfg["enabled"] or _is_in_cooldown("vix_spike"):
        return None

    current_vix, change_pct = get_price_change("^VIX", cfg["lookback_hours"])
    if current_vix <= 0:
        return None

    # Dinamik eşik hesapla
    atr       = calculate_atr("^VIX", interval="1h")
    dyn_threshold = atr * cfg["atr_multiplier"]

    # Mutlak değişim (puan olarak)
    _, vix_4h_ago = get_price_change("^VIX", 4)
    vix_change_abs = current_vix * abs(change_pct) / 100

    triggered      = False
    trigger_reason = ""

    if current_vix >= cfg["absolute_threshold"]:
        triggered      = True
        trigger_reason = f"VIX mutlak eşik aşıldı ({current_vix:.1f} ≥ {cfg['absolute_threshold']})"
    elif dyn_threshold > 0 and vix_change_abs >= dyn_threshold:
        triggered      = True
        trigger_reason = (f"VIX dinamik eşik aşıldı "
                         f"({vix_change_abs:.2f} ≥ ATR×{cfg['atr_multiplier']} = {dyn_threshold:.2f})")

    if triggered:
        _mark_fired("vix_spike")
        return {
            "trigger":    "vix_spike",
            "layer":       1,
            "severity":   "CRITICAL" if current_vix >= 35 else "HIGH",
            "category":   "SAVUNMA",
            "vix":         current_vix,
            "change_pct":  change_pct,
            "reason":      trigger_reason,
            "atr":         atr,
        }
    return None


def check_btc_crash() -> dict | None:
    """BTC ani düşüş — ATR bazlı dinamik eşik."""
    cfg = LAYER1["btc_crash"]
    if not cfg["enabled"] or _is_in_cooldown("btc_crash"):
        return None

    current, change_pct = get_price_change("BTC-USD", cfg["lookback_hours"])
    if current <= 0 or change_pct >= 0:
        return None  # Düşüş yoksa kontrol etme

    atr = calculate_atr("BTC-USD", interval="1h")
    # Düşüşün mutlak değerini ATR ile karşılaştır
    drop_abs      = current * abs(change_pct) / 100
    dyn_threshold = atr * cfg["atr_multiplier"]

    if dyn_threshold > 0 and drop_abs >= dyn_threshold:
        _mark_fired("btc_crash")
        return {
            "trigger":    "btc_crash",
            "layer":       1,
            "severity":   "HIGH",
            "category":   "SAVUNMA",
            "btc_price":   current,
            "change_pct":  change_pct,
            "reason":     (f"BTC {cfg['lookback_hours']}s'de %{change_pct:.1f} düştü "
                          f"(ATR×{cfg['atr_multiplier']}={dyn_threshold:.0f}$ eşiği aşıldı)"),
            "atr":         atr,
        }
    return None


def check_usdtry_spike() -> dict | None:
    """USD/TRY ani spike — günlük ATR × çarpan."""
    cfg = LAYER1["usdtry_spike"]
    if not cfg["enabled"] or _is_in_cooldown("usdtry_spike"):
        return None

    current, change_pct = get_price_change("USDTRY=X", cfg["lookback_hours"])
    if current <= 0 or change_pct <= 0:
        return None  # Sadece TL'nin değer kaybı bizi ilgilendiriyor

    # Günlük ATR kullan (TRY için günlük hareketler daha anlamlı)
    atr           = calculate_atr("USDTRY=X", interval="1d")
    rise_abs      = current * change_pct / 100
    dyn_threshold = atr * cfg["atr_multiplier"]

    if dyn_threshold > 0 and rise_abs >= dyn_threshold:
        _mark_fired("usdtry_spike")
        return {
            "trigger":    "usdtry_spike",
            "layer":       1,
            "severity":   "HIGH",
            "category":   "SAVUNMA",
            "usdtry":      current,
            "change_pct":  change_pct,
            "reason":     (f"USD/TRY {cfg['lookback_hours']}s'de %{change_pct:.1f} arttı "
                          f"(ATR×{cfg['atr_multiplier']}={dyn_threshold:.4f} eşiği aşıldı)"),
            "atr":         atr,
        }
    return None


def check_stablecoin_depeg() -> dict | None:
    """
    USDT/USDC de-peg kontrolü.
    ATR kullanılmaz — stablecoin'in normal volatilitesi ~sıfır olduğu için
    herhangi bir $0.995 altı sapma doğrudan alarm üretir.
    İki stablecoin aynı anda de-peg olursa → sistemik kriz seviyesi.
    """
    cfg = LAYER1["stablecoin_depeg"]
    if not cfg["enabled"] or _is_in_cooldown("stablecoin_depeg"):
        return None

    import yfinance as yf
    depegged = []

    for ticker, name in [(cfg["usdt_ticker"], "USDT"), (cfg["usdc_ticker"], "USDC")]:
        try:
            price = float(yf.Ticker(ticker).fast_info.last_price or 1.0)
            if price < cfg["depeg_threshold"]:
                depegged.append({"name": name, "price": price})
        except Exception as e:
            logger.warning("Stablecoin fiyat hatası (%s): %s", ticker, e)

    if not depegged:
        return None

    _mark_fired("stablecoin_depeg")

    # İkisi de de-peg oldu → sistemik kriz
    if len(depegged) >= 2:
        severity = "CRITICAL"
        reason   = (f"SİSTEMİK KRİZ: Hem USDT ({depegged[0]['price']:.4f}) "
                   f"hem USDC ({depegged[1]['price']:.4f}) de-peg! "
                   f"Kripto piyasasından ACİL çıkış değerlendirin.")
    else:
        severity = "HIGH"
        reason   = (f"{depegged[0]['name']} de-peg: "
                   f"${depegged[0]['price']:.4f} (eşik: ${cfg['depeg_threshold']})")

    return {
        "trigger":    "stablecoin_depeg",
        "layer":       1,
        "severity":    severity,
        "category":   "SAVUNMA",
        "depegged":    depegged,
        "reason":      reason,
        "systemic":   len(depegged) >= 2,
    }


# ─── Katman 2 Tetikleyicileri ─────────────────────────────────────────────────

def check_yield_curve() -> dict | None:
    """
    Yield Curve rejim tespiti.
    Bull Steepener (resesyon tescili) ve yeniden inversiyon (mali dominans)
    iki farklı alarm tipi olarak ele alınır.
    """
    import yfinance as yf

    # Bull Steepener
    cfg_bs = LAYER2["yield_curve_bull_steepener"]
    # Yeniden inversiyon
    cfg_ri = LAYER2["yield_curve_reinversion"]

    try:
        # 10Y ve 3M faizleri çek
        t10 = yf.Ticker("^TNX").history(period="5d")["Close"]
        t3m = yf.Ticker("^IRX").history(period="5d")["Close"]
        if len(t10) < 3 or len(t3m) < 3:
            return None

        current_spread = float(t10.iloc[-1] - t3m.iloc[-1])
        prev_spread    = float(t10.iloc[-3] - t3m.iloc[-3])  # 48 saat önce
        spread_change  = current_spread - prev_spread  # baz puan

        current_10y = float(t10.iloc[-1])
        prev_10y    = float(t10.iloc[-3])
        is_10y_falling = current_10y < prev_10y

        current_3m = float(t3m.iloc[-1])
        prev_3m    = float(t3m.iloc[-3])
        is_3m_rising = current_3m > prev_3m

        # Bull Steepener kontrolü
        if (cfg_bs["enabled"] and not _is_in_cooldown("yield_curve_bull_steepener")
                and prev_spread < 0           # Önce ters eğri olmalı
                and spread_change * 100 >= cfg_bs["spread_change_bps"]  # normalleşiyor
                and (not cfg_bs["require_10y_falling"] or is_10y_falling)):
            _mark_fired("yield_curve_bull_steepener")
            return {
                "trigger":    "yield_curve_bull_steepener",
                "layer":       2,
                "severity":   "HIGH",
                "category":   "SAVUNMA",
                "current_spread": current_spread,
                "prev_spread":    prev_spread,
                "spread_change":  spread_change,
                "10y_falling":    is_10y_falling,
                "reason":        (f"BULL STEEPENER: Ters eğri normalleşiyor "
                                 f"(spread {prev_spread:+.2f}% → {current_spread:+.2f}%, "
                                 f"48s'de {spread_change*100:+.0f} bps). "
                                 f"Tarihsel olarak resesyon tescil sinyali. "
                                 f"Direktör: defansife geç, emtia artır."),
                "direktoru_senaryo": cfg_bs["direktoru_senaryo"],
            }

        # Yeniden inversiyon kontrolü
        # DİKKAT: Bu bir alım fırsatı değil! Mali dominans ön sinyali.
        if (cfg_ri["enabled"] and not _is_in_cooldown("yield_curve_reinversion")
                and current_spread * 100 <= cfg_ri["inversion_threshold_bps"]
                and prev_spread > current_spread  # eğri düzleşmeden inversiyona geçiyor
                and (not cfg_ri["require_short_rising"] or is_3m_rising)):
            _mark_fired("yield_curve_reinversion")
            return {
                "trigger":    "yield_curve_reinversion",
                "layer":       2,
                "severity":   "MEDIUM",
                "category":   "SAVUNMA",
                "current_spread":    current_spread,
                "reason":           (f"YENİDEN İNVERSİYON: Eğri tekrar ters döndü "
                                    f"(spread: {current_spread*100:+.0f} bps). "
                                    f"DİKKAT: Bu alım fırsatı değil — Fed tekrar "
                                    f"sıkılaştırıyor olabilir (Volcker 1979 senaryosu). "
                                    f"Direktör: emtia artır, SHV/BIL al, hisse azalt."),
                "direktoru_senaryo": cfg_ri["direktoru_senaryo"],
            }

    except Exception as e:
        logger.error("Yield curve kontrolü hatası: %s", e)

    return None


def check_altcoin_btc_divergence() -> dict | None:
    """
    Altcoin/BTC ayrışması — likidite şoku erken sinyali.
    BTC yatay/artıda ama altcoinler düşüyorsa, fonlar riskten ilk çıkışı yapıyor.
    """
    cfg = LAYER2["altcoin_btc_divergence"]
    if not cfg["enabled"] or _is_in_cooldown("altcoin_btc_divergence"):
        return None

    try:
        import yfinance as yf
        # Portföydeki altcoin listesini al (BTC ve ETH dışında)
        from portfolio_manager import load_portfolio
        positions = load_portfolio()
        altcoins  = [p["ticker"] for p in positions
                     if p.get("asset_class") == "crypto"
                     and p["ticker"] not in ("BTC-USD", "ETH-USD")
                     and float(p.get("shares", 0)) > 0]

        if not altcoins:
            return None

        # BTC değişimi
        _, btc_change = get_price_change("BTC-USD", cfg["lookback_hours"])
        if btc_change < cfg["btc_min_return"] * 100:
            # BTC de düşüyor → bu tetikleyici değil, genel düşüş
            return None

        # Altcoin ortalama değişimi
        changes = []
        for ticker in altcoins[:10]:  # İlk 10 altcoin
            _, chg = get_price_change(ticker, cfg["lookback_hours"])
            if chg != 0:
                changes.append(chg)

        if not changes:
            return None

        avg_altcoin_change = sum(changes) / len(changes)

        if avg_altcoin_change <= cfg["altcoin_max_return"] * 100:
            _mark_fired("altcoin_btc_divergence")
            return {
                "trigger":    "altcoin_btc_divergence",
                "layer":       2,
                "severity":   "MEDIUM",
                "category":   "SAVUNMA",
                "btc_change":          btc_change,
                "altcoin_avg_change":  avg_altcoin_change,
                "altcoin_count":       len(changes),
                "reason":             (f"ALTCOIN/BTC AYRIMASI: BTC %{btc_change:+.1f} "
                                      f"iken altcoinler ort. %{avg_altcoin_change:.1f}. "
                                      f"Fonlar önce altcoinlerden çıkıyor — "
                                      f"likidite şoku erken sinyali."),
            }
    except Exception as e:
        logger.error("Altcoin divergence hatası: %s", e)

    return None


def check_funding_rate() -> dict | None:
    """
    Binance'ten BTC funding rate çek.
    Aşırı pozitif = uzun kaldıraç birikti → dump riski
    Aşırı negatif = short birikti → dip / squeeze fırsatı
    """
    cfg = LAYER2["funding_rate"]
    if not cfg["enabled"]:
        return None

    try:
        url = (f"https://fapi.binance.com/fapi/v1/fundingRate"
               f"?symbol={cfg['symbol']}&limit=1")
        resp    = requests.get(url, timeout=10)
        data    = resp.json()
        if not data:
            return None

        funding = float(data[0]["fundingRate"])
        ts      = int(data[0]["fundingTime"]) / 1000

        # Aşırı ısınma
        if funding >= cfg["overheat_threshold"] / 100:
            if _is_in_cooldown("funding_rate_hot"):
                return None
            _mark_fired("funding_rate_hot")
            return {
                "trigger":    "funding_rate_hot",
                "layer":       2,
                "severity":   "MEDIUM",
                "category":   "SAVUNMA",
                "funding":     funding,
                "reason":     (f"BTC FUNDING AŞIRI ISINDI: %{funding*100:.3f}/8s. "
                              f"Uzun kaldıraç birikti — ani fiyat düşüşü riski yüksek."),
            }

        # Dip fırsatı
        if funding <= cfg["oversold_threshold"] / 100:
            if _is_in_cooldown("funding_rate_cold"):
                return None
            _mark_fired("funding_rate_cold")
            return {
                "trigger":    "funding_rate_cold",
                "layer":       2,
                "severity":   "LOW",
                "category":   "HUCUM",
                "funding":     funding,
                "reason":     (f"BTC FUNDING NEGATİF: %{funding*100:.3f}/8s. "
                              f"Short birikimi dorukta — short squeeze / dip alım fırsatı."),
            }

    except Exception as e:
        logger.error("Funding rate hatası: %s", e)

    return None


def check_open_interest() -> dict | None:
    """
    Binance BTC Open Interest — kaldıraçlı long birikimi tespiti.
    Fiyat artışıyla birlikte OI çok hızlı büyüyorsa cascade liquidation riski.
    """
    cfg = LAYER2["open_interest"]
    if not cfg["enabled"] or _is_in_cooldown("open_interest"):
        return None

    try:
        # Anlık OI
        url_now  = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={cfg['symbol']}"
        # 4 saat önceki OI (OpenInterest History)
        url_hist = (f"https://fapi.binance.com/futures/data/openInterestHist"
                   f"?symbol={cfg['symbol']}&period=1h&limit=6")

        oi_now  = float(requests.get(url_now, timeout=10).json()["openInterest"])
        hist    = requests.get(url_hist, timeout=10).json()
        if not hist:
            return None

        oi_4h_ago = float(hist[0]["sumOpenInterest"])
        oi_change_pct = (oi_now - oi_4h_ago) / oi_4h_ago * 100 if oi_4h_ago > 0 else 0

        if oi_change_pct < cfg["oi_change_pct_4h"]:
            return None

        # Fiyat da artıyor mu kontrol et
        _, btc_change = get_price_change("BTC-USD", 4)
        if cfg["require_price_up"] and btc_change <= 0:
            return None

        _mark_fired("open_interest")
        return {
            "trigger":    "open_interest",
            "layer":       2,
            "severity":   "MEDIUM",
            "category":   "SAVUNMA",
            "oi_change_pct": oi_change_pct,
            "btc_change":    btc_change,
            "reason":       (f"OI 4 SAATTE %{oi_change_pct:.1f} ARTTI "
                            f"(BTC: %{btc_change:+.1f}). "
                            f"Kaldıraçlı uzun pozisyon birikimi — "
                            f"cascade liquidation riski yüksek."),
        }

    except Exception as e:
        logger.error("Open interest hatası: %s", e)

    return None


def check_vix_normalization() -> dict | None:
    """
    VIX normalleşmesi → Risk-on kapısı.
    3 günlük ortalama VIX eşiğin altında ve öncesinde spike görülmüş olmalı.
    """
    cfg = LAYER2["vix_normalization"]
    if not cfg["enabled"] or _is_in_cooldown("vix_normalization"):
        return None

    try:
        import yfinance as yf
        df = yf.Ticker("^VIX").history(period="10d")["Close"]
        if len(df) < 5:
            return None

        avg_3d = float(df.tail(3).mean())
        max_prior = float(df.head(len(df) - 3).max())

        if avg_3d >= cfg["threshold"]:
            return None
        if cfg["require_prior_spike"] and max_prior < 30:
            return None  # Öncesinde spike olmamışsa sinyal güçsüz

        _mark_fired("vix_normalization")
        return {
            "trigger":    "vix_normalization",
            "layer":       2,
            "severity":   "LOW",
            "category":   "HUCUM",
            "vix_avg_3d":  avg_3d,
            "prior_max":   max_prior,
            "reason":     (f"VIX NORMALLEŞTI: 3 günlük ort. {avg_3d:.1f} "
                          f"(önceki zirve: {max_prior:.1f}). "
                          f"Panik geçiyor — risk-on rotasyon zamanı."),
            "direktoru_senaryo": cfg["direktoru_senaryo"],
        }

    except Exception as e:
        logger.error("VIX normalleşme hatası: %s", e)

    return None


def check_btc_dominance_cycle() -> dict | None:
    """
    BTC dominansı düşüşe geçişi → altcoin sezonu başlıyor.
    BTC dominansı yükselirken: BTC güvenli liman, altcoinlerden kaç.
    BTC dominansı düşerken + BTC artıda: altcoin rotasyon zamanı.
    """
    cfg = LAYER2["btc_dominance_cycle"]
    if not cfg["enabled"] or _is_in_cooldown("btc_dominance_cycle"):
        return None

    try:
        # BTC ve total market cap proxy olarak yfinance kullan
        import yfinance as yf
        # BTC.D doğrudan yfinance'te yok, BTC/toplam yaklaşımını kullanırız
        # Proxy: BTC piyasa değeri / (BTC + ETH + BNB + SOL toplam)
        tickers = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD"]
        prices  = {}
        for t in tickers:
            try:
                info = yf.Ticker(t).fast_info
                prices[t] = float(getattr(info, "market_cap", 0) or 0)
            except Exception:
                pass

        total_cap = sum(prices.values())
        if total_cap <= 0 or "BTC-USD" not in prices:
            return None

        btc_dom_now = prices["BTC-USD"] / total_cap * 100

        # 48 saat önceki dominansı tahmin et (history ile)
        df_btc = yf.Ticker("BTC-USD").history(period="3d")["Close"]
        if len(df_btc) < 2:
            return None

        btc_price_now  = float(df_btc.iloc[-1])
        btc_price_2d   = float(df_btc.iloc[0])
        btc_return_2d  = (btc_price_now - btc_price_2d) / btc_price_2d * 100

        # Basit dominans düşüş proxy: BTC'nin ETH'den az getiri sağlaması
        df_eth = yf.Ticker("ETH-USD").history(period="3d")["Close"]
        if len(df_eth) < 2:
            return None
        eth_return_2d = (float(df_eth.iloc[-1]) - float(df_eth.iloc[0])) / float(df_eth.iloc[0]) * 100

        # BTC'den ETH'ye geçiş var mı?
        dominance_shifting = (eth_return_2d - btc_return_2d) >= cfg["dominance_drop_pct"]

        if dominance_shifting and (not cfg["require_btc_positive"] or btc_return_2d > 0):
            _mark_fired("btc_dominance_cycle")
            return {
                "trigger":    "btc_dominance_cycle",
                "layer":       2,
                "severity":   "LOW",
                "category":   "HUCUM",
                "btc_return":  btc_return_2d,
                "eth_return":  eth_return_2d,
                "reason":     (f"ALTCOIN ROTASYONU BAŞLIYOR: ETH %{eth_return_2d:+.1f} "
                              f"BTC'yi %{btc_return_2d:+.1f} geride bıraktı (48s). "
                              f"BTC dominansı kırılıyor — majör altcoin pozisyonu artır."),
                "direktoru_senaryo": cfg["direktoru_senaryo"],
            }

    except Exception as e:
        logger.error("BTC dominans döngüsü hatası: %s", e)

    return None


def check_turkey_cds() -> dict | None:
    """
    Türkiye CDS (Risk Primi) düşüşü → Yabancı sermaye girişi sinyali.
    CDS verisini doğrudan yfinance'ten çekmek mümkün değil.
    Proxy olarak: TUR ETF (iShares MSCI Turkey) ve USD/TRY tersini kullan.
    Gerçek CDS için CBOE veya Quandl API gerekir — şimdilik proxy yeterli.
    """
    cfg = LAYER2["turkey_cds_drop"]
    if not cfg["enabled"] or _is_in_cooldown("turkey_cds_drop"):
        return None

    try:
        import yfinance as yf
        # Proxy: TUR ETF'in haftalık performansı + TL'nin haftalık güçlenmesi
        tur_hist = yf.Ticker("TUR").history(period="10d")["Close"]
        try_hist = yf.Ticker("USDTRY=X").history(period="10d")["Close"]

        if len(tur_hist) < 5 or len(try_hist) < 5:
            return None

        tur_weekly = (float(tur_hist.iloc[-1]) / float(tur_hist.iloc[-5]) - 1) * 100
        try_weekly = (float(try_hist.iloc[-1]) / float(try_hist.iloc[-5]) - 1) * 100

        # TUR ETF güçlü YE TL güçleniyorsa → Türkiye risk priminin düştüğünün proxy'si
        if tur_weekly >= 4.0 and try_weekly <= -1.5:
            _mark_fired("turkey_cds_drop")
            return {
                "trigger":    "turkey_cds_drop",
                "layer":       2,
                "severity":   "LOW",
                "category":   "HUCUM",
                "tur_weekly":  tur_weekly,
                "try_weekly":  try_weekly,
                "reason":     (f"TÜRKİYE MAKRO İYİLEŞME SİNYALİ: "
                              f"TUR ETF %{tur_weekly:+.1f} (haftalık), "
                              f"TL %{abs(try_weekly):.1f} güçlendi. "
                              f"Yabancı sermaye girişi proxy pozitif. "
                              f"AOY azalt → IIH/NNF artır sinyali."),
                "direktoru_senaryo": cfg["direktoru_senaryo"],
            }

    except Exception as e:
        logger.error("Türkiye CDS proxy hatası: %s", e)

    return None


# ─── Cephane Kontrolü ─────────────────────────────────────────────────────────

def check_ammunition(portfolio: list, usd_try: float) -> dict:
    """
    Direktörün 'AL' diyebilmesi için mevcut cephaneyi kontrol et.
    Portföydeki nakit oranı ve satılabilir defansif varlıkları hesapla.
    """
    try:
        from portfolio_manager import get_total_cash_usd
        cash_info  = get_total_cash_usd(usd_try=usd_try)
        cash_usd   = cash_info.get("total_usd", 0)

        # Toplam portföy değeri (maliyet bazlı — anlık fiyat burada hızlı yaklaşım)
        total_value = sum(
            float(p.get("shares", 0)) * float(p.get("avg_cost", 0)) /
            (usd_try if p.get("currency") == "TRY" else 1)
            for p in portfolio
            if float(p.get("shares", 0)) > 0
        ) + cash_usd

        cash_pct = (cash_usd / total_value * 100) if total_value > 0 else 0

        # Defansif varlıklar (satılabilir — risk-on geçişte fonlama kaynağı)
        defensive_value = 0.0
        defensive_items = []
        for sınıf in ["commodity_gold", "tefas_gold", "cash_bonds"]:
            tickers = ASSET_CLASS_MAP.get(sınıf, {}).get("tickers", [])
            for p in portfolio:
                if p["ticker"] in tickers and float(p.get("shares", 0)) > 0:
                    val = (float(p["shares"]) * float(p.get("avg_cost", 0)) /
                           (usd_try if p.get("currency") == "TRY" else 1))
                    defensive_value += val
                    defensive_items.append(p["ticker"])

        return {
            "cash_usd":        round(cash_usd, 0),
            "cash_pct":        round(cash_pct, 1),
            "total_value":     round(total_value, 0),
            "defensive_value": round(defensive_value, 0),
            "defensive_items": defensive_items,
            "can_buy_directly": cash_pct >= MIN_CASH_FOR_BUY_PCT,
            "needs_rotation":   cash_pct < MIN_CASH_FOR_BUY_PCT,
        }
    except Exception as e:
        logger.error("Cephane kontrolü hatası: %s", e)
        return {"cash_pct": 0, "can_buy_directly": False, "needs_rotation": True}


# ─── Direktör Entegrasyonu ────────────────────────────────────────────────────

def wake_director(triggers: list[dict], portfolio: list,
                  ammo: dict, usd_try: float) -> str:
    """
    Tetiklenen sinyaller için Claude direktörünü uyandır ve analiz üret.
    Birden fazla sinyal aynı anda tetiklendiyse hepsini tek mesajda birleştir.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY eksik!")
        return ""

    client = anthropic.Anthropic(api_key=api_key)

    # Tetikleyici özetini oluştur
    trigger_summary = "\n".join([
        f"- [{t['category']}] {t['trigger'].upper()}: {t['reason']}"
        for t in triggers
    ])

    # Portföy özetini oluştur
    positions_summary = "\n".join([
        f"  {p['ticker']} ({p.get('asset_class','?')}): "
        f"{p.get('shares',0)} adet × ${p.get('avg_cost',0):.2f}"
        for p in portfolio if float(p.get("shares", 0)) > 0
    ])

    # Cephane durumu
    ammo_summary = (
        f"Nakit: ${ammo['cash_usd']:,.0f} (%{ammo['cash_pct']:.1f} portföy)\n"
        f"Defansif varlıklar: ${ammo['defensive_value']:,.0f} "
        f"({', '.join(ammo['defensive_items'][:5])})\n"
        f"Doğrudan alım: {'MÜMKÜN' if ammo['can_buy_directly'] else 'ÖNCE SATMALI'}"
    )

    # Kategorilere göre direktörden ne isteneceğini belirle
    categories    = {t["category"] for t in triggers}
    has_defense   = "SAVUNMA" in categories
    has_offense   = "HUCUM" in categories
    has_critical  = any(t["severity"] == "CRITICAL" for t in triggers)

    if has_critical:
        aksiyon_istegi = "ACİL SAVUNMA: Portföyü derhal koruma altına alacak aksiyonları listele."
    elif has_defense and has_offense:
        aksiyon_istegi = "Karma sinyaller var. Önce riski değerlendir, sonra fırsat varsa rotasyonu öner."
    elif has_defense:
        aksiyon_istegi = "SAVUNMA modu: Risk azaltma ve nakit yaratma aksiyonlarını önceliklendir."
    else:
        aksiyon_istegi = "HÜCUM modu: Hangi defansif varlıktan çıkıp hangi büyüme varlığına gireceğimi söyle."

    system_prompt = """Sen bir portföy strateji direktörüsün.
Tetiklenen piyasa sinyallerine göre SOMUT ve HIZLI aksiyon önerisi üret.
Cevabın kısa ve net olmalı — Telegram mesajına uyacak formatta.
Her aksiyon için: ne yap, hangi varlık, ne kadar, neden.
'Cephane Kontrolü' kuralı: AL diyeceksen nereden para bulunacağını da söyle."""

    user_message = f"""
TETİKLENEN SİNYALLER:
{trigger_summary}

PORTFÖY DURUMU:
{positions_summary}

CEPHANE DURUMU:
{ammo_summary}

1 USD = {usd_try:.2f} TL

GÖREV: {aksiyon_istegi}

JSON formatında yanıt ver:
{{
  "ozet": "2-3 cümle, dominant tema",
  "aksiyonlar": [
    {{"sira": 1, "eylem": "SAT|AL|AZALT|ARTIR|BEKLE", "varlik": "ticker", "miktar": "% veya $", "neden": "tek cümle"}},
    ...
  ],
  "finansman": "Alım için nereden nakit sağlanacak (rotasyon)",
  "oncelik": "ACIL|BUGUN|BU_HAFTA",
  "senaryo": "hangi senaryoya benziyor"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text
    except Exception as e:
        logger.error("Claude API hatası: %s", e)
        return ""


# ─── Sabah Özeti (Katman 3) ───────────────────────────────────────────────────

def generate_morning_summary(portfolio: list, usd_try: float) -> str:
    """
    Günlük sabah özeti — sabah kahveni içerken okuyacağın kapsamlı piyasa raporu.

    İçerik:
    - Piyasa göstergeleri (VIX, SPY, BTC, DXY, Altın, USD/TRY)
    - Rejim tespiti (risk-on/off)
    - Portföy anlık durumu (varlık sınıfı bazında)
    - Bugünün ekonomik takvimi
    - Son 24 saatte tetiklenen alarmlar
    - Günün öncelikli izleme listesi
    """
    import yfinance as yf
    from datetime import datetime, timezone, timedelta

    lines = []
    tr_now = datetime.now(timezone.utc) + timedelta(hours=3)
    lines.append(f"🌅 <b>{tr_now.strftime('%d %B %Y, %A')} — Sabah Özeti</b>")
    lines.append("━" * 32)

    # ── 1. Piyasa Göstergeleri ────────────────────────────────────────────────
    indicators = {
        "^VIX":    ("VIX",          ""),
        "SPY":     ("S&P 500",       "📈"),
        "^NDX":    ("Nasdaq-100",    "💻"),
        "BTC-USD": ("BTC",           "₿"),
        "^TNX":    ("ABD 10Y",       "📊"),
    }

    # DXY — birden fazla ticker dene
    for _dxy_tk in ("DX-Y.NYB", "UUP", "^USD"):
        try:
            _h = yf.Ticker(_dxy_tk).history(period="2d")
            if not _h.empty and len(_h) >= 2:
                indicators[_dxy_tk] = ("DXY", "💵")
                break
        except Exception:
            pass

    # Altın için XAUUSD=X dene, boş dönerse GC=F kullan
    gold_ticker = "XAUUSD=X"
    try:
        _gtest = yf.Ticker("XAUUSD=X").history(period="2d")
        if _gtest.empty:
            gold_ticker = "GC=F"
    except Exception:
        gold_ticker = "GC=F"
    indicators[gold_ticker] = ("Altın (spot)" if gold_ticker == "XAUUSD=X"
                                else "Altın (vadeli)", "🥇")

    market_lines = []
    vix_value    = 0.0
    spy_chg      = 0.0
    btc_price    = 0.0
    btc_chg      = 0.0
    gold_price   = 0.0

    for ticker, (label, emoji) in indicators.items():
        try:
            price, chg = get_price_change(ticker, 24)
            if price <= 0:
                continue

            # Değer formatlama
            if ticker == "^VIX":
                vix_value = price
                val_str   = f"{price:.1f}"
                chg_str   = f"%{chg:+.1f}"
            elif ticker == "BTC-USD":
                btc_price = price
                btc_chg   = chg
                val_str   = f"${price:,.0f}"
                chg_str   = f"%{chg:+.1f}"
            elif ticker in ("XAUUSD=X", "GC=F"):
                gold_price = price
                val_str    = f"${price:,.0f}/oz"
                chg_str    = f"%{chg:+.1f}"
            elif ticker in ("^TNX",):
                val_str = f"%{price:.2f}"
                chg_str = f"{chg:+.0f}bps" if abs(chg) > 0.5 else ""
            else:
                if ticker == "SPY":
                    spy_chg = chg
                val_str = f"${price:.2f}" if price < 1000 else f"${price:,.0f}"
                chg_str = f"%{chg:+.1f}"

            # Renk emoji
            if chg > 0.5:
                dir_e = "🟢"
            elif chg < -0.5:
                dir_e = "🔴"
            else:
                dir_e = "⚪"

            market_lines.append(
                f"  {dir_e} {emoji} <b>{label}</b>: {val_str}"
                + (f" ({chg_str})" if chg_str else "")
            )
        except Exception:
            pass

    # USD/TRY — history ile değişim hesapla
    try:
        _try_hist = yf.Ticker("USDTRY=X").history(period="5d")
        if not _try_hist.empty and len(_try_hist) >= 2:
            _try_now  = float(_try_hist["Close"].iloc[-1])
            _try_prev = float(_try_hist["Close"].iloc[-2])
            _try_chg  = (_try_now - _try_prev) / _try_prev * 100
            _try_e    = "🔴" if _try_chg > 0.1 else ("🟢" if _try_chg < -0.1 else "⚪")
            market_lines.append(
                f"  {_try_e} 🇹🇷 <b>USD/TRY</b>: {_try_now:.2f} (%{_try_chg:+.2f})"
            )
        else:
            market_lines.append(f"  ⚪ 🇹🇷 <b>USD/TRY</b>: {usd_try:.2f}")
    except Exception:
        market_lines.append(f"  ⚪ 🇹🇷 <b>USD/TRY</b>: {usd_try:.2f}")

    lines.append("\n📊 <b>Piyasa Göstergeleri (24s):</b>")
    lines.extend(market_lines)

    # ── 2. Rejim Tespiti ─────────────────────────────────────────────────────
    lines.append("")
    if vix_value >= 30:
        regime_txt = "⚠️ <b>Rejim: PANIK / RISK-OFF</b> — Savunmacı pozisyonlama öncelikli"
    elif vix_value >= 20:
        regime_txt = "⚡ <b>Rejim: TEMKİNLİ</b> — Piyasada gerginlik var, dikkatli ol"
    elif vix_value >= 15:
        regime_txt = "🟡 <b>Rejim: NÖTR</b> — Normal dalgalanma, izleme yeterli"
    else:
        regime_txt = "🟢 <b>Rejim: RISK-ON</b> — İştah yüksek, büyüme varlıkları favori"
    lines.append(f"🧭 {regime_txt}")

    # ── 3. Portföy Anlık Durumu ───────────────────────────────────────────────
    if portfolio:
        lines.append("")
        lines.append("💼 <b>Portföy Durumu:</b>")

        class_labels = {
            "us_equity": "🇺🇸 ABD Hisse",
            "crypto":    "₿ Kripto",
            "commodity": "🥇 Emtia",
            "tefas":     "🇹🇷 TEFAS",
            "cash":      "💵 Nakit",
        }

        class_data = {}

        # ── TEFAS: fetch_tefas_fund ile anlık NAV fiyatı ──────────────────
        tefas_pos = [p for p in portfolio if p.get("asset_class") == "tefas"
                     and float(p.get("shares", 0)) > 0]
        if tefas_pos:
            try:
                from turkey_fetcher import fetch_tefas_fund
                t_val = t_cost = 0.0
                for p in tefas_pos:
                    shr  = float(p.get("shares", 0))
                    avg  = float(p.get("avg_cost", 0))
                    fd   = fetch_tefas_fund(p["ticker"])
                    cur  = float(fd.get("price", avg)) if fd else avg
                    t_val  += shr * cur / usd_try
                    t_cost += shr * avg  / usd_try
                class_data["tefas"] = {"val": t_val, "cost": t_cost}
            except Exception as e:
                logger.warning("TEFAS fiyat hatası: %s", e)
                t_cost = sum(float(p.get("shares",0)) * float(p.get("avg_cost",0))
                             / usd_try for p in tefas_pos)
                class_data["tefas"] = {"val": t_cost, "cost": t_cost}

        # ── ABD Hisse: yfinance history ───────────────────────────────────
        us_pos = [p for p in portfolio
                  if p.get("asset_class") in ("us_equity", "other", "")
                  and float(p.get("shares", 0)) > 0]
        if us_pos:
            us_val = us_cost = 0.0
            for p in us_pos:
                shr  = float(p.get("shares", 0))
                avg  = float(p.get("avg_cost", 0))
                live = avg
                try:
                    hist = yf.Ticker(p["ticker"]).history(period="2d")
                    if not hist.empty:
                        live = float(hist["Close"].iloc[-1])
                except Exception:
                    pass
                us_val  += shr * live
                us_cost += shr * avg
            class_data["us_equity"] = {"val": us_val, "cost": us_cost}

        # ── Kripto: yfinance history ──────────────────────────────────────
        cry_pos = [p for p in portfolio if p.get("asset_class") == "crypto"
                   and float(p.get("shares", 0)) > 0]
        if cry_pos:
            c_val = c_cost = 0.0
            for p in cry_pos:
                shr  = float(p.get("shares", 0))
                avg  = float(p.get("avg_cost", 0))
                live = avg
                try:
                    hist = yf.Ticker(p["ticker"]).history(period="2d")
                    if not hist.empty:
                        live = float(hist["Close"].iloc[-1])
                except Exception:
                    pass
                c_val  += shr * live
                c_cost += shr * avg
            class_data["crypto"] = {"val": c_val, "cost": c_cost}

        # ── Emtia: altın/gümüş TL dönüşümü, diğerleri doğrudan ──────────
        com_pos = [p for p in portfolio if p.get("asset_class") == "commodity"
                   and float(p.get("shares", 0)) > 0]
        if com_pos:
            gold_usd = 0.0
            try:
                hist = yf.Ticker("GC=F").history(period="2d")
                if not hist.empty:
                    gold_usd = float(hist["Close"].iloc[-1])
            except Exception:
                pass
            silver_usd = 0.0
            try:
                hist = yf.Ticker("SI=F").history(period="2d")
                if not hist.empty:
                    silver_usd = float(hist["Close"].iloc[-1])
            except Exception:
                pass

            m_val = m_cost = 0.0
            for p in com_pos:
                shr = float(p.get("shares", 0))
                avg = float(p.get("avg_cost", 0))
                tk  = p.get("ticker", "")
                cur = p.get("currency", "USD")
                if tk in ("ALTIN_GRAM_TRY", "XAUTRY=X") and gold_usd > 0:
                    live_tl = gold_usd * usd_try / 31.1035
                    m_val  += shr * live_tl / usd_try
                    m_cost += shr * avg / usd_try
                elif tk in ("GUMUS_GRAM_TRY", "XAGTRY=X") and silver_usd > 0:
                    live_tl = silver_usd * usd_try / 31.1035
                    m_val  += shr * live_tl / usd_try
                    m_cost += shr * avg / usd_try
                else:
                    live = avg
                    try:
                        hist = yf.Ticker(tk).history(period="2d")
                        if not hist.empty:
                            live = float(hist["Close"].iloc[-1])
                    except Exception:
                        pass
                    div = usd_try if cur == "TRY" else 1.0
                    m_val  += shr * live / div
                    m_cost += shr * avg  / div
            class_data["commodity"] = {"val": m_val, "cost": m_cost}

        # ── Yazdır ───────────────────────────────────────────────────────
        total_val  = sum(d["val"]  for d in class_data.values())
        total_cost = sum(d["cost"] for d in class_data.values())

        for ac, d in sorted(class_data.items(), key=lambda x: -x[1]["val"]):
            label = class_labels.get(ac, ac)
            pnl   = d["val"] - d["cost"]
            ppct  = pnl / d["cost"] * 100 if d["cost"] > 0 else 0
            sign  = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"  {label}: ${d['val']:,.0f} | "
                f"{sign} K/Z: ${pnl:+,.0f} (%{ppct:+.1f})"
            )

        pnl_tot  = total_val - total_cost
        ppct_tot = pnl_tot / total_cost * 100 if total_cost > 0 else 0
        sign     = "🟢" if pnl_tot >= 0 else "🔴"
        lines.append(
            f"  <b>Toplam: ${total_val:,.0f} | "
            f"{sign} K/Z: ${pnl_tot:+,.0f} (%{ppct_tot:+.1f})</b>"
        )

    # ── 4. Kripto Özet ────────────────────────────────────────────────────────
    try:
        url = "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"
        resp    = requests.get(url, timeout=5).json()
        funding = float(resp[0]["fundingRate"]) * 100 if resp else 0
        fund_emoji = "🔥" if funding > 0.05 else ("❄️" if funding < -0.02 else "✅")
        lines.append("")
        lines.append(f"₿ <b>Kripto Özet:</b>")
        lines.append(f"  BTC: ${btc_price:,.0f} (%{btc_chg:+.1f} 24s)")
        lines.append(f"  {fund_emoji} Funding Rate: %{funding:.3f}/8s "
                    f"({'Isınma var' if funding > 0.05 else 'Normal' if funding > -0.02 else 'Short baskısı'})")
    except Exception:
        if btc_price > 0:
            lines.append(f"\n₿ BTC: ${btc_price:,.0f} (%{btc_chg:+.1f})")

    # ── 5. Aktif Alarmlar (Son 24 Saat) ──────────────────────────────────────
    cd = _load_cooldowns()
    recent = [k for k, ts in cd.items() if (time.time() - ts) < 86400]
    if recent:
        lines.append("")
        lines.append(f"⚠️ <b>Son 24s Alarmlar ({len(recent)} adet):</b>")
        for r in recent[:5]:
            lines.append(f"  • {r.replace('_', ' ').title()}")
    else:
        lines.append("")
        lines.append("✅ Son 24 saatte alarm tetiklenmedi")

    # ── 6. Günün Öncelikli İzleme Noktaları ──────────────────────────────────
    lines.append("")
    lines.append("🎯 <b>Bugün İzle:</b>")

    watchlist = []
    if vix_value >= 25:
        watchlist.append("VIX 25 üzerinde — TEFAS hisse fonlarında stop-loss seviyeleri")
    if vix_value < 18 and spy_chg > 0:
        watchlist.append("Risk-on ortam — Nakit oranı gözden geçir, fırsat penceresi açık olabilir")
    if btc_chg < -3:
        watchlist.append(f"BTC %{btc_chg:.1f} — Altcoin pozisyonlarını izle")
    if btc_chg > 3:
        watchlist.append(f"BTC %{btc_chg:+.1f} — Funding rate takip et, aşırı ısınma riski")
    if abs(usd_try - 44) > 1.5:  # Kur belirgin hareket
        watchlist.append(f"USD/TRY {usd_try:.2f} — TEFAS dolar bazlı değer etkileniyor")

    # Günün ekonomik takvimi (basit versiyon)
    try:
        weekday = tr_now.weekday()
        if weekday == 4:  # Cuma
            watchlist.append("Cuma: NFP veya önemli ABD verisi açıklanabilir")
        elif weekday == 2:  # Çarşamba
            watchlist.append("Çarşamba: Fed tutanakları veya EIA petrol stok verisi olabilir")
    except Exception:
        pass

    if not watchlist:
        watchlist.append("Belirgin bir sinyal yok — rutin izleme yeterli")

    for item in watchlist[:4]:
        lines.append(f"  • {item}")

    lines.append("")
    lines.append("━" * 32)

    return "\n".join(lines)


# ─── Ana Çalıştırıcı ──────────────────────────────────────────────────────────

def run(layer: int) -> None:
    """
    Belirtilen katmanın tetikleyicilerini çalıştır.
    GitHub Actions bu fonksiyonu layer argümanıyla çağırır.
    """
    logger.info("Tetikleyici motor başlatılıyor — Katman %d", layer)

    # USD/TRY kuru
    try:
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()
        logger.info("USD/TRY: %.4f", usd_try)
    except Exception as e:
        logger.error("USD/TRY alınamadı: %s", e)
        return  # Kur olmadan devam etme

    # Portföy yükle
    try:
        from portfolio_manager import load_portfolio
        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        logger.info("Portföy yüklendi: %d pozisyon", len(portfolio))
    except Exception as e:
        logger.error("Portföy yüklenemedi: %s", e)
        portfolio = []

    triggered_signals = []

    # ── Katman 1 Kontrolleri ─────────────────────────────────────────────────
    if layer == 1:
        checks = [
            check_vix_spike,
            check_btc_crash,
            check_usdtry_spike,
            check_stablecoin_depeg,
        ]
        for check_fn in checks:
            result = check_fn()
            if result:
                logger.info("TETİKLENDİ: %s — %s", result["trigger"], result["reason"][:80])
                triggered_signals.append(result)

    # ── Katman 2 Kontrolleri ─────────────────────────────────────────────────
    elif layer == 2:
        if _is_quiet_hours():
            logger.info("Sessiz saatler — Katman 2 atlanıyor.")
            return

        checks = [
            check_yield_curve,
            check_altcoin_btc_divergence,
            check_funding_rate,
            check_open_interest,
            check_vix_normalization,
            check_btc_dominance_cycle,
            check_turkey_cds,
        ]
        for check_fn in checks:
            result = check_fn()
            if result:
                logger.info("TETİKLENDİ: %s — %s", result["trigger"], result["reason"][:80])
                triggered_signals.append(result)

    # ── Katman 3: Sabah Özeti ────────────────────────────────────────────────
    elif layer == 3:
        summary = generate_morning_summary(portfolio, usd_try)
        from trigger_alerts import send_morning_summary
        send_morning_summary(summary)
        logger.info("Sabah özeti gönderildi.")
        return

    if not triggered_signals:
        logger.info("Tetiklenen sinyal yok — sessiz.")
        return

    # ── Direktörü Uyandır ────────────────────────────────────────────────────
    ammo = check_ammunition(portfolio, usd_try)
    logger.info("Cephane: nakit %s%%, defansif $%s",
                ammo["cash_pct"], ammo["defensive_value"])

    director_response = wake_director(triggered_signals, portfolio, ammo, usd_try)

    # ── Telegram'a Gönder ────────────────────────────────────────────────────
    from trigger_alerts import format_and_send_alert
    format_and_send_alert(triggered_signals, director_response, ammo, usd_try)


# ─── Giriş Noktası ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tetikleyici İzleme Motoru")
    parser.add_argument("--layer", type=int, choices=[1, 2, 3], required=True,
                        help="Çalıştırılacak katman: 1, 2 veya 3")
    args = parser.parse_args()
    run(args.layer)
