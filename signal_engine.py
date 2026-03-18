# signal_engine.py — Uzman Analist Sinyal Motoru
#
# Ham verileri net, eyleme dönüştürülebilir sinyallere çevirir.
#
# Tasarım felsefesi:
#   - Her sinyal NET olmalı: AL / SAT / BEKLE / AZALT / ARTIR
#   - Çelişkili ifade olmamalı
#   - Her sinyalin bir gerekçesi ve güven skoru var
#   - Dominant sinyal kazanır — çelişki varsa neden kazandığı açıklanır
#
# Sinyal hiyerarşisi (önem sırası):
#   1. Makro rejim    — en büyük ağırlık, tüm sınıfları etkiler
#   2. Varlık sınıfı  — kendi dinamikleri
#   3. Teknik         — momentum ve fiyat yapısı
#   4. Sentiment      — duygusal aşırılıklar contrarian sinyal verir
#
# Güven skoru 1-10:
#   8-10: Güçlü sinyal, birden fazla bağımsız metrik aynı yönü gösteriyor
#   5-7:  Orta sinyal, çoğunluk aynı yönde ama bazı çelişki var
#   1-4:  Zayıf sinyal, belirsizlik yüksek — bekle

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Sinyal Tipleri ───────────────────────────────────────────────────────────

class Signal:
    STRONG_BUY   = "GÜÇLÜ AL"
    BUY          = "AL"
    ADD          = "ARTIR"      # Mevcut pozisyonu büyüt
    HOLD         = "TUT"
    WAIT         = "BEKLE"      # Henüz zamanı değil
    REDUCE       = "AZALT"      # Kısmen çık
    SELL         = "SAT"
    STRONG_SELL  = "GÜÇLÜ SAT"
    NEUTRAL      = "NÖTR"


@dataclass
class AssetSignal:
    """Bir varlık veya varlık sınıfı için üretilen sinyal."""
    asset:       str            # "BTC", "ALTIN", "BIST100", "US_EQUITY"
    signal:      str            # Signal sınıfından
    confidence:  int            # 1-10
    reason:      str            # Ana gerekçe (1-2 cümle, net)
    supporting:  list = field(default_factory=list)   # Destekleyen metrikler
    conflicting: list = field(default_factory=list)   # Çelişen metrikler (varsa)
    action:      str  = ""      # Somut aksiyon önerisi
    timeframe:   str  = "orta"  # kısa | orta | uzun
    color:       str  = "#5a6a7a"


# ─── Renk Haritası ───────────────────────────────────────────────────────────

SIGNAL_COLORS = {
    Signal.STRONG_BUY:  "#00c48c",
    Signal.BUY:         "#4fc3f7",
    Signal.ADD:         "#4fc3f7",
    Signal.HOLD:        "#8a9ab0",
    Signal.WAIT:        "#ffb300",
    Signal.REDUCE:      "#ff8c00",
    Signal.SELL:        "#e74c3c",
    Signal.STRONG_SELL: "#c0392b",
    Signal.NEUTRAL:     "#5a6a7a",
}


# ─── Makro Rejim Analizi ─────────────────────────────────────────────────────

def analyze_macro_regime(macro_data: dict) -> AssetSignal:
    """
    Makro ortamı değerlendir ve genel piyasa rejimini belirle.
    Bu sinyal tüm diğer sinyalleri etkileyen çarpan görevi görür.

    Karar ağacı:
    1. VIX + yield curve + credit spread → risk ortamı
    2. Fed politikası → likidite koşulları
    3. Büyüme göstergeleri → ekonomik momentum
    """
    indicators = macro_data.get("indicators", {})
    regime     = macro_data.get("regime", {})

    scores = []     # Pozitif = risk-on, negatif = risk-off
    supporting  = []
    conflicting = []

    # ── VIX ──────────────────────────────────────────────────────────────
    vix_ind = indicators.get("VIX", {})
    vix_val = vix_ind.get("value", 20) if isinstance(vix_ind, dict) else getattr(vix_ind, "value", 20)
    if vix_val >= 30:
        scores.append(-3)
        supporting.append(f"VIX {vix_val:.0f} — yüksek korku, risk-off")
    elif vix_val >= 22:
        scores.append(-1)
        supporting.append(f"VIX {vix_val:.0f} — yükselen gerginlik")
    elif vix_val <= 15:
        scores.append(+2)
        supporting.append(f"VIX {vix_val:.0f} — düşük volatilite, risk iştahı yüksek")
    else:
        scores.append(0)

    # ── Yield Curve ───────────────────────────────────────────────────────
    yc_ind = indicators.get("YIELD_CURVE", {})
    yc_val = yc_ind.get("value", 0) if isinstance(yc_ind, dict) else getattr(yc_ind, "value", 0)
    if yc_val < -0.5:
        scores.append(-2)
        supporting.append(f"Yield curve ters ({yc_val:+.2f}%) — resesyon riski")
    elif yc_val < 0:
        scores.append(-1)
        conflicting.append(f"Hafif ters yield curve ({yc_val:+.2f}%)")
    else:
        scores.append(+1)
        supporting.append(f"Normal yield curve ({yc_val:+.2f}%)")

    # ── Credit Spread ────────────────────────────────────────────────────
    cs_ind = indicators.get("CREDIT_SPREAD", {})
    cs_sig = cs_ind.get("signal", "neutral") if isinstance(cs_ind, dict) else getattr(cs_ind, "signal", "neutral")
    if cs_sig == "red":
        scores.append(-2)
        supporting.append("Credit spread genişliyor — kredi riski artıyor")
    elif cs_sig == "green":
        scores.append(+1)
        supporting.append("Credit spread daralıyor — kredi ortamı iyileşiyor")

    # ── Fed Beklentisi ───────────────────────────────────────────────────
    fw_ind = indicators.get("FED_WATCH", {})
    fw_sig = fw_ind.get("signal", "neutral") if isinstance(fw_ind, dict) else getattr(fw_ind, "signal", "neutral")
    if fw_sig == "green":  # İndirim beklentisi
        scores.append(+2)
        supporting.append("Piyasa faiz indirimi fiyatlıyor — likidite artacak")
    elif fw_sig == "red":  # Artırım beklentisi
        scores.append(-2)
        conflicting.append("Piyasa faiz artırımı fiyatlıyor — likidite sıkışacak")

    # ── Küresel Likidite ─────────────────────────────────────────────────
    liq_ind = indicators.get("LIQUIDITY", {})
    liq_sig = liq_ind.get("signal", "neutral") if isinstance(liq_ind, dict) else getattr(liq_ind, "signal", "neutral")
    if liq_sig == "green":
        scores.append(+1)
        supporting.append("Küresel likidite genişliyor")
    elif liq_sig == "red":
        scores.append(-1)
        conflicting.append("Küresel likidite daralıyor")

    # ── Karar ────────────────────────────────────────────────────────────
    total = sum(scores)
    n     = max(len(scores), 1)
    avg   = total / n

    if avg >= 1.2:
        signal, conf = Signal.BUY,    min(8, 5 + int(avg))
        reason = "Makro ortam RİSK-ON: likidite genişliyor, korku düşük, büyüme destekleniyor."
    elif avg >= 0.4:
        signal, conf = Signal.HOLD,   5
        reason = "Makro ortam NÖTR: karışık sinyaller, büyük pozisyon değişikliği için erken."
    elif avg >= -0.4:
        signal, conf = Signal.WAIT,   5
        reason = "Makro ortam TEMKİNLİ: yön belirsiz, mevcut pozisyonları koru."
    elif avg >= -1.2:
        signal, conf = Signal.REDUCE, min(8, 5 + int(abs(avg)))
        reason = "Makro ortam RİSK-OFF: likidite sıkışıyor veya korku artıyor, pozisyonları azalt."
    else:
        signal, conf = Signal.SELL,   min(9, 6 + int(abs(avg)))
        reason = "Makro ortam STRES: birden fazla uyarı sinyali, savunmaya geç."

    return AssetSignal(
        asset="MAKRO_REJİM",
        signal=signal,
        confidence=conf,
        reason=reason,
        supporting=supporting[:4],
        conflicting=conflicting[:2],
        action="",
        timeframe="kısa",
        color=SIGNAL_COLORS.get(signal, "#5a6a7a"),
    )


# ─── US Equity Sinyali ───────────────────────────────────────────────────────

def analyze_us_equity(economic_data: dict, macro_signal: AssetSignal) -> AssetSignal:
    """
    ABD hisse senedi piyasası için sinyal üret.
    Değerleme + sektör rotasyonu + earnings + makro bağlam.
    """
    scores      = []
    supporting  = []
    conflicting = []

    # ── S&P 500 Değerleme ────────────────────────────────────────────────
    val  = economic_data.get("sp500_valuation", {})
    if val:
        fpe     = val.get("forward_pe",  18)
        premium = val.get("premium_pct", 0)
        sig     = val.get("signal", "neutral")
        if sig == "red":    # Pahalı
            scores.append(-2)
            conflicting.append(f"S&P 500 Forward P/E {fpe:.0f}x — tarihsel ortalamanın %{abs(premium):.0f} üzerinde (PAHALI)")
        elif sig == "green":
            scores.append(+2)
            supporting.append(f"S&P 500 değerlemesi cazip ({fpe:.0f}x forward P/E)")
        elif sig == "amber":
            scores.append(-1)
            conflicting.append(f"S&P 500 biraz pahalı ({fpe:.0f}x)")

    # ── Sektör Rotasyonu ─────────────────────────────────────────────────
    sectors = economic_data.get("sector_rotation", {})
    if sectors:
        _secs = sectors.get("sectors", [])
        leaders  = [s["label"] for s in _secs if s.get("rel_1m", 0) > 2][:2]
        laggards = [s["label"] for s in _secs if s.get("rel_1m", 0) < -2][:2]
        if leaders:
            scores.append(+1)
            supporting.append(f"Güçlü sektörler: {', '.join(leaders)}")
        if laggards:
            scores.append(-1)
            conflicting.append(f"Zayıf sektörler: {', '.join(laggards)}")

    # ── Ekonomik Göstergeler ─────────────────────────────────────────────
    econ = economic_data.get("macro_econ", {})
    ism_mfg = econ.get("ISM_MFG")
    if ism_mfg:
        ism_val = ism_mfg.value if hasattr(ism_mfg, "value") else ism_mfg.get("value", 50)
        if ism_val >= 52:
            scores.append(+2)
            supporting.append(f"ISM Manufacturing {ism_val:.0f} — ekonomi büyüyor")
        elif ism_val < 48:
            scores.append(-2)
            conflicting.append(f"ISM Manufacturing {ism_val:.0f} — imalat daralıyor")

    gdp = econ.get("GDP")
    if gdp:
        gdp_val = gdp.value if hasattr(gdp, "value") else gdp.get("value", 2)
        if gdp_val >= 2.5:
            scores.append(+1)
            supporting.append(f"GDP büyümesi %{gdp_val:.1f} — güçlü")
        elif gdp_val < 0:
            scores.append(-3)
            supporting.append(f"GDP %{gdp_val:.1f} — negatif büyüme!")

    # ── VIX term structure ───────────────────────────────────────────────
    ms = economic_data.get("market_structure", {})
    vts = ms.get("vix_term", {})
    if vts:
        vts_sig = vts.get("signal", "neutral")
        if vts_sig == "red":
            scores.append(-2)
            conflicting.append("VIX backwardation — kısa vadeli panik sinyali")
        elif vts_sig == "green":
            scores.append(+1)
            supporting.append("VIX normal contango — piyasa sakin")

    # ── Makro rejim çarpanı ──────────────────────────────────────────────
    macro_mult = {
        Signal.STRONG_BUY: +3, Signal.BUY: +2, Signal.ADD: +1,
        Signal.HOLD: 0, Signal.WAIT: -1, Signal.REDUCE: -2,
        Signal.SELL: -3, Signal.STRONG_SELL: -4, Signal.NEUTRAL: 0,
    }.get(macro_signal.signal, 0)
    scores.append(macro_mult)

    total = sum(scores)
    avg   = total / max(len(scores), 1)

    if avg >= 1.5:
        signal, conf = Signal.BUY,    min(9, 6 + int(avg))
        reason = "ABD hisse piyasası destekleniyor: değerleme makul, büyüme sağlıklı, makro pozitif."
        action = "Kaliteli büyüme hisselerinde pozisyon artır. Analist consesüsü güçlü hisseler öncelikli."
    elif avg >= 0.5:
        signal, conf = Signal.HOLD,   6
        reason = "ABD hisselerinde mevcut pozisyonları koru. Yeni büyük alım için netlik bekleniyor."
        action = "Stop-loss seviyelerini gözden geçir. Seçici alım: sadece en güçlü fundamentaller."
    elif avg >= -0.5:
        signal, conf = Signal.WAIT,   5
        reason = "ABD hisselerinde yön belirsiz. Değerleme yüksek veya makro sinyaller karışık."
        action = "Yeni pozisyon açma. Eldekini koru, FOMC veya earnings netleşmesini bekle."
    elif avg >= -1.5:
        signal, conf = Signal.REDUCE, min(8, 5 + int(abs(avg)))
        reason = "ABD hisselerinde risk artıyor. Değerleme yüksek ve makro baskı var."
        action = "En riskli pozisyonları (yüksek beta, spekülatif) %20-30 küçült. Nakit artır."
    else:
        signal, conf = Signal.SELL,   min(9, 6 + int(abs(avg)))
        reason = "ABD hisselerinde birden fazla uyarı sinyali. Korumacı moda geç."
        action = "Spekülatif pozisyonları kapat. Core hisselerde stop-loss sıkılaştır."

    return AssetSignal(
        asset="ABD_HİSSE",
        signal=signal,
        confidence=conf,
        reason=reason,
        supporting=supporting[:4],
        conflicting=conflicting[:3],
        action=action,
        timeframe="orta",
        color=SIGNAL_COLORS.get(signal, "#5a6a7a"),
    )


# ─── Kripto Sinyali ──────────────────────────────────────────────────────────

def analyze_crypto(crypto_data: dict, macro_signal: AssetSignal) -> AssetSignal:
    """
    Kripto piyasası için sinyal üret.
    On-chain + sentiment + döngüsel konum + makro.
    """
    scores      = []
    supporting  = []
    conflicting = []

    fg = crypto_data.get("fear_greed", {})
    dom= crypto_data.get("dominance",  {})
    hal= crypto_data.get("halving",    {})
    onc= crypto_data.get("onchain",    {})
    stb= crypto_data.get("stablecoin", {})
    ls = crypto_data.get("long_short", {})
    nvt= crypto_data.get("nvt",        {})
    spr= crypto_data.get("sopr",       {})

    # ── Fear & Greed — Contrarian Sinyal ────────────────────────────────
    fg_score = fg.get("score", 50)
    if fg_score <= 20:
        scores.append(+4)   # Aşırı korku = güçlü contrarian AL
        supporting.append(f"Fear & Greed {fg_score}/100 — AŞIRI KORKU. Tarihsel alım bölgesi.")
    elif fg_score <= 35:
        scores.append(+2)
        supporting.append(f"Fear & Greed {fg_score}/100 — Korku bölgesi. Orta vadeli alım fırsatı.")
    elif fg_score >= 80:
        scores.append(-4)   # Aşırı açgözlülük = güçlü contrarian SAT
        conflicting.append(f"Fear & Greed {fg_score}/100 — AŞIRI AÇGÖZLÜLÜK. Tarihsel tepe bölgesi!")
    elif fg_score >= 65:
        scores.append(-2)
        conflicting.append(f"Fear & Greed {fg_score}/100 — Açgözlülük. Dikkatli ol.")

    # ── Halving Döngüsü ──────────────────────────────────────────────────
    hal_sig   = hal.get("signal", "neutral")
    hal_phase = hal.get("phase", "")
    days_since= hal.get("days_since", 0)
    if hal_sig == "green" and days_since <= 365:
        scores.append(+3)
        supporting.append(f"Halving döngüsü: {hal_phase} ({days_since} gün) — tarihsel boğa penceresi.")
    elif hal_sig == "green":
        scores.append(+1)
        supporting.append(f"Halving döngüsü: {hal_phase}")
    elif hal_sig == "amber":
        scores.append(-1)
        conflicting.append(f"Halving döngüsü: {hal_phase} — geç faz, dikkat.")

    # ── MVRV Proxy ───────────────────────────────────────────────────────
    mvrv = onc.get("mvrv_proxy", {})
    mvrv_sig = mvrv.get("signal", "neutral")
    mvrv_val = mvrv.get("value", 1.5)
    if mvrv_sig == "green":
        scores.append(+2)
        supporting.append(f"MVRV {mvrv_val:.2f} — adil değer veya altında.")
    elif mvrv_sig == "red":
        scores.append(-3)
        conflicting.append(f"MVRV {mvrv_val:.2f} — pahalı bölge, tepe riski.")
    elif mvrv_sig == "amber":
        scores.append(-1)
        conflicting.append(f"MVRV {mvrv_val:.2f} — dikkat bölgesine yaklaşıyor.")

    # ── SOPR ─────────────────────────────────────────────────────────────
    sopr_sig = spr.get("signal", "neutral")
    sopr_val = spr.get("sopr_7d", 1.0)
    if sopr_sig == "green" and sopr_val < 1.0:
        scores.append(+2)
        supporting.append(f"SOPR {sopr_val:.3f} < 1 — zarar realizasyonu = dip bölgesi sinyali.")
    elif sopr_sig == "red":
        scores.append(-2)
        conflicting.append(f"SOPR {sopr_val:.3f} yüksek — büyük kâr satışları.")

    # ── NVT ──────────────────────────────────────────────────────────────
    nvt_sig   = nvt.get("signal",    "neutral")
    nvt_ratio = nvt.get("nvt_ratio", 1.0)
    if nvt_sig == "red":
        scores.append(-2)
        conflicting.append(f"NVT {nvt_ratio:.2f} — fiyat ağ kullanımından kopmuş, spekülatif.")
    elif nvt_sig == "green":
        scores.append(+1)
        supporting.append(f"NVT {nvt_ratio:.2f} — ağ yoğun kullanılıyor, değerleme cazip.")

    # ── Long/Short Ratio ────────────────────────────────────────────────
    ls_sig = ls.get("signal", "neutral")
    if ls_sig == "green":   # Short ağırlık = squeeze fırsatı
        scores.append(+1)
        supporting.append("Yüksek short oran — short squeeze potansiyeli.")
    elif ls_sig == "red":   # Long ağırlık = squeeze riski
        scores.append(-1)
        conflicting.append("Yüksek long oran — long squeeze riski.")

    # ── Stablecoin Dominance ────────────────────────────────────────────
    stb_sig   = stb.get("signal", "neutral")
    stb_total = stb.get("total_stable", 8)
    if stb_sig == "green" and stb_total >= 12:
        scores.append(+1)
        supporting.append(f"Stablecoin dominance %{stb_total:.0f} — birikmiş alım gücü var.")

    # ── Makro çarpanı ────────────────────────────────────────────────────
    # Kripto makroya özellikle duyarlı — risk-off dönemlerinde çok sert düşer
    macro_mult = {
        Signal.STRONG_BUY: +3, Signal.BUY: +2, Signal.ADD: +1,
        Signal.HOLD: 0, Signal.WAIT: -1, Signal.REDUCE: -2,
        Signal.SELL: -4, Signal.STRONG_SELL: -5, Signal.NEUTRAL: 0,
    }.get(macro_signal.signal, 0)
    scores.append(macro_mult)

    total = sum(scores)
    avg   = total / max(len(scores), 1)

    if avg >= 1.5:
        signal, conf = Signal.BUY,    min(9, 5 + int(avg * 1.5))
        reason = "Kripto ortamı OLUMLU: aşırı korku/dip sinyalleri + uygun halving fazı + makro destekleyici."
        action = "Kademeli alım başlat. BTC ve quality altcoinlerde pozisyon aç. Toplam kripto ağırlığını artır."
    elif avg >= 0.5:
        signal, conf = Signal.HOLD,   6
        reason = "Kripto ortamında karma sinyaller. Mevcut pozisyonları koru, büyük alım için sabır."
        action = "Eldeki kripto pozisyonlarını tut. Yeni alım için daha güçlü sinyal bekle."
    elif avg >= -0.5:
        signal, conf = Signal.WAIT,   5
        reason = "Kripto piyasasında yön belirsiz. Ne al ne sat — bekle."
        action = "Yeni kripto alımı yapma. Stop-loss seviyelerini gözden geçir."
    elif avg >= -1.5:
        signal, conf = Signal.REDUCE, min(8, 4 + int(abs(avg) * 1.5))
        reason = "Kripto piyasasında uyarı sinyalleri artıyor. Spekülatif pozisyonları küçült."
        action = "Altcoin ağırlığını azalt, BTC ağırlığını artır veya nakite çık."
    else:
        signal, conf = Signal.SELL,   min(9, 5 + int(abs(avg)))
        reason = "Kripto piyasasında birden fazla kırmızı sinyal. Risk-off modu."
        action = "Kripto pozisyonlarını önemli ölçüde azalt. Stablecoin veya nakite geç."

    return AssetSignal(
        asset="KRİPTO",
        signal=signal,
        confidence=conf,
        reason=reason,
        supporting=supporting[:4],
        conflicting=conflicting[:3],
        action=action,
        timeframe="kısa",
        color=SIGNAL_COLORS.get(signal, "#5a6a7a"),
    )


# ─── Emtia Sinyali ───────────────────────────────────────────────────────────

def analyze_commodity(commodity_data: dict, macro_signal: AssetSignal) -> AssetSignal:
    """
    Emtia piyasası — özellikle altın — için sinyal üret.
    Reel faiz + dolar + jeopolitik + yapısal talep.
    """
    scores      = []
    supporting  = []
    conflicting = []

    grr = commodity_data.get("gold_real_rate",  {})
    cbg = commodity_data.get("cb_gold_proxy",   {})
    oil = commodity_data.get("oil",             {})
    cu  = commodity_data.get("copper",          {})
    udg = commodity_data.get("us_debt_gold",    {})
    geo = commodity_data.get("geo_news",        {})

    # ── Reel Faiz — En Kritik Altın Göstergesi ───────────────────────────
    grr_sig  = grr.get("signal",    "neutral")
    real_rate= grr.get("real_rate", 1.0)
    if real_rate is not None:
        if real_rate <= 0:
            scores.append(+4)   # Negatif reel faiz = altın için en güçlü ortam
            supporting.append(f"Reel faiz %{real_rate:.2f} — NEGATİF. Altın için optimal ortam.")
        elif real_rate <= 0.5:
            scores.append(+2)
            supporting.append(f"Reel faiz %{real_rate:.2f} — düşük. Altın destekleniyor.")
        elif real_rate <= 1.5:
            scores.append(-1)
            conflicting.append(f"Reel faiz %{real_rate:.2f} — nötr-yüksek. Altına baskı olabilir.")
        else:
            scores.append(-2)
            conflicting.append(f"Reel faiz %{real_rate:.2f} — yüksek. Altın nakit tutmaya karşı rekabet kaybediyor.")

    # ── Merkez Bankası Alım Proxy ─────────────────────────────────────────
    cbg_sig = cbg.get("signal", "neutral")
    if cbg_sig == "green":
        scores.append(+2)
        supporting.append(cbg.get("note", "Güçlü kurumsal altın alım sinyali.")[:70])

    # ── Yapısal Boğa Tezi (ABD borç/altın) ──────────────────────────────
    if udg:
        scores.append(+1)   # Uzun vadeli yapısal destek her zaman +1
        supporting.append(f"ABD borç/altın tezi: {udg.get('market_value_t',0):.1f}T$ rezerv, yapısal boğa devam.")

    # ── Petrol Etkisi ─────────────────────────────────────────────────────
    oil_sig = oil.get("signal", "neutral")
    wti     = oil.get("wti", 70)
    if oil_sig == "red" and wti >= 90:
        scores.append(-1)   # Yüksek petrol enflasyon artırır, Fed sıkılaştırır, altına baskı
        conflicting.append(f"Yüksek petrol (${wti:.0f}) enflasyon artırıyor — Fed'i kısıtlıyor.")
    elif wti <= 60:
        scores.append(+1)
        supporting.append(f"Düşük petrol (${wti:.0f}) — enflasyon baskısı azalıyor, Fed için manevra alanı.")

    # ── Altın/Bakır Oranı — Risk Barometresi ─────────────────────────────
    gc_sig = cu.get("gc_signal", "neutral")
    if gc_sig == "red":     # Yüksek oran = resesyon korkusu = altına iyi
        scores.append(+1)
        supporting.append("Altın/Bakır oranı yüksek — resesyon korkusu altını destekliyor.")
    elif gc_sig == "green": # Düşük oran = büyüme = altın görece zayıf
        scores.append(-1)
        conflicting.append("Altın/Bakır oranı düşük — risk iştahı var, altın görece zayıf kalabilir.")

    # ── Jeopolitik Haberler ──────────────────────────────────────────────
    if geo.get("has_alerts"):
        scores.append(+1)
        supporting.append(f"Jeopolitik uyarılar mevcut — emtia güvenli liman talebi artıyor.")

    # ── Makro çarpanı ─────────────────────────────────────────────────────
    # Altın risk-off dönemlerinde güçlenir (ters etki)
    macro_mult = {
        Signal.STRONG_BUY: -1, Signal.BUY: 0, Signal.ADD: 0,
        Signal.HOLD: +1, Signal.WAIT: +1, Signal.REDUCE: +2,
        Signal.SELL: +3, Signal.STRONG_SELL: +3, Signal.NEUTRAL: 0,
    }.get(macro_signal.signal, 0)
    scores.append(macro_mult)

    total = sum(scores)
    avg   = total / max(len(scores), 1)

    if avg >= 1.5:
        signal, conf = Signal.BUY,    min(9, 5 + int(avg * 1.2))
        reason = "Altın için GÜÇlü ortam: negatif/düşük reel faiz + yapısal talep + jeopolitik destek."
        action = "Altın (GLD/IAU) pozisyonunu artır. Toplam portföyde %15-20 altın ağırlığı savunulabilir."
    elif avg >= 0.5:
        signal, conf = Signal.HOLD,   6
        reason = "Altın için destekleyici ortam ama güçlü bir katalizör eksik."
        action = "Mevcut altın pozisyonunu koru. Reel faiz hareketi izle."
    elif avg >= -0.5:
        signal, conf = Signal.WAIT,   5
        reason = "Altın için nötr ortam. Reel faiz yönü netleşmeden büyük hamle yapma."
        action = "Yeni altın alımı için FOMC veya CPI verisini bekle."
    else:
        signal, conf = Signal.REDUCE, min(7, 4 + int(abs(avg)))
        reason = "Yüksek reel faiz ve güçlü dolar altın üzerinde baskı yaratıyor."
        action = "Altın ağırlığını azalt, faiz getirili enstrümanlara bak."

    return AssetSignal(
        asset="EMTİA_ALTIN",
        signal=signal,
        confidence=conf,
        reason=reason,
        supporting=supporting[:4],
        conflicting=conflicting[:3],
        action=action,
        timeframe="uzun",
        color=SIGNAL_COLORS.get(signal, "#5a6a7a"),
    )


# ─── Türkiye/BIST Sinyali ────────────────────────────────────────────────────

def analyze_turkey(turkey_data: dict, macro_signal: AssetSignal) -> AssetSignal:
    """
    Türkiye borsası (TEFAS fonları dahil) için sinyal üret.
    Dolar bazlı değerleme + XBANK liderliği + yabancı akış + makro.
    """
    scores      = []
    supporting  = []
    conflicting = []

    val     = turkey_data.get("valuation",  {})
    xbank   = turkey_data.get("xbank",      {})
    macro   = turkey_data.get("macro",      {})
    foreign = turkey_data.get("foreign",    {})
    bist    = turkey_data.get("bist",       {})

    # ── BIST Dolar Bazlı Değerleme — En Kritik ───────────────────────────
    val_sig  = val.get("signal",   "neutral")
    bist_usd = val.get("bist_usd", 900)
    if val_sig == "green" and bist_usd <= 700:
        scores.append(+4)   # Tarihsel ucuzluk
        supporting.append(f"BIST dolar bazlı {bist_usd:.0f} puan — TARİHSEL UCUZLUK. Güçlü uzun vadeli fırsat.")
    elif val_sig == "green":
        scores.append(+2)
        supporting.append(f"BIST dolar bazlı {bist_usd:.0f} puan — değer bölgesinde.")
    elif val_sig == "amber":
        scores.append(0)
        conflicting.append(f"BIST dolar bazlı {bist_usd:.0f} puan — adil değer civarı.")
    elif val_sig == "red":
        scores.append(-2)
        conflicting.append(f"BIST dolar bazlı {bist_usd:.0f} puan — pahalı bölge.")

    # ── XBANK Liderliği ──────────────────────────────────────────────────
    xb_sig = xbank.get("signal", "neutral")
    xb_rel = xbank.get("relative_perf", 0)
    if xb_sig == "green":
        scores.append(+2)
        supporting.append(f"XBANK BIST'i +%{xb_rel:.1f} outperform ediyor — bankacılık liderliği = bullish.")
    elif xb_sig == "red":
        scores.append(-2)
        conflicting.append(f"XBANK BIST'in -%{abs(xb_rel):.1f} gerisinde — bankacılık zayıflığı uyarı sinyali.")
    elif xb_sig == "amber":
        scores.append(-1)
        conflicting.append(f"XBANK BIST'in gerisinde — sektör rotasyonu olumsuz.")

    # ── Reel Faiz ─────────────────────────────────────────────────────────
    rr = macro.get("real_rate", {})
    rr_sig = rr.get("signal", "neutral")
    rr_val = rr.get("value",   0)
    if rr_val is not None:
        if rr_sig == "green" and rr_val > 5:
            scores.append(+2)
            supporting.append(f"Reel faiz %{rr_val:.1f} — yüksek pozitif. TL cazip, sıcak para girişi mümkün.")
        elif rr_sig == "red":
            scores.append(-3)
            conflicting.append(f"Reel faiz %{rr_val:.1f} — derin negatif. TL eriyor, yabancı kaçar.")

    # ── Yabancı Yatırımcı ────────────────────────────────────────────────
    for_sig = foreign.get("signal", "neutral")
    for_rel = foreign.get("relative", 0)
    if for_sig == "green":
        scores.append(+2)
        supporting.append(f"Yabancı yatırımcı ilgisi artıyor — Türkiye EM'yi +%{for_rel:.1f} outperform.")
    elif for_sig == "red":
        scores.append(-2)
        conflicting.append("Yabancı çıkış sinyali — TL ve BIST üzerinde satış baskısı.")

    # ── CDS Proxy ────────────────────────────────────────────────────────
    cds = macro.get("cds_proxy", {})
    cds_sig = cds.get("signal", "neutral")
    if cds_sig == "green":
        scores.append(+1)
        supporting.append("Türkiye risk primi düşüyor — ülke riski azalıyor.")
    elif cds_sig == "red":
        scores.append(-2)
        conflicting.append("Türkiye risk primi artıyor — ülke riski yükseliyor.")

    # ── USD/TRY Trend ────────────────────────────────────────────────────
    usd_try_data = bist.get("USD_TRY", {})
    try_chg      = usd_try_data.get("change", 0)
    if abs(try_chg) >= 1.5:   # Günde %1.5+ TL hareketi alarm
        scores.append(-2)
        conflicting.append(f"USD/TRY %{try_chg:+.1f} — sert kur hareketi, volatilite yüksek.")

    # ── Makro çarpanı ─────────────────────────────────────────────────────
    # Türkiye gelişen piyasa — global risk-off'ta çok sert tepki verir
    macro_mult = {
        Signal.STRONG_BUY: +1, Signal.BUY: +1, Signal.ADD: 0,
        Signal.HOLD: 0, Signal.WAIT: -1, Signal.REDUCE: -3,
        Signal.SELL: -4, Signal.STRONG_SELL: -5, Signal.NEUTRAL: 0,
    }.get(macro_signal.signal, 0)
    scores.append(macro_mult)

    total = sum(scores)
    avg   = total / max(len(scores), 1)

    if avg >= 1.5:
        signal, conf = Signal.BUY,    min(9, 5 + int(avg))
        reason = "BIST için olumlu tablo: dolar bazlı ucuzluk + banka liderliği + yabancı ilgisi artıyor."
        action = "TEFAS hisse senedi fonlarında pozisyon artır. XBANK ağırlıklı fonlar öncelikli."
    elif avg >= 0.5:
        signal, conf = Signal.HOLD,   6
        reason = "BIST değerleme cazip ama katalizör zayıf. Kur riski devam ediyor."
        action = "Mevcut TEFAS pozisyonlarını koru. Kur hareketlerini yakından izle."
    elif avg >= -0.5:
        signal, conf = Signal.WAIT,   5
        reason = "BIST için yön belirsiz. Global risk iştahı netleşmeden hamle yapma."
        action = "TEFAS alımını ertele. XBANK performansını ve yabancı akışını izle."
    elif avg >= -1.5:
        signal, conf = Signal.REDUCE, min(8, 4 + int(abs(avg)))
        reason = "BIST için uyarı sinyalleri var. Kur riski veya yabancı çıkışı başlıyor olabilir."
        action = "TEFAS pozisyonlarını %20-30 azalt. Döviz veya altın tarafına geç."
    else:
        signal, conf = Signal.SELL,   min(9, 5 + int(abs(avg)))
        reason = "BIST için güçlü sat sinyali: global risk-off + kur baskısı + yabancı çıkışı."
        action = "TEFAS pozisyonlarını önemli ölçüde azalt veya tümünü çıkar."

    return AssetSignal(
        asset="TÜRKİYE_BIST",
        signal=signal,
        confidence=conf,
        reason=reason,
        supporting=supporting[:4],
        conflicting=conflicting[:3],
        action=action,
        timeframe="orta",
        color=SIGNAL_COLORS.get(signal, "#5a6a7a"),
    )


# ─── Portföy Bütünleştirici Sinyal ──────────────────────────────────────────

def generate_portfolio_signal(
    macro_signal:    AssetSignal,
    us_signal:       AssetSignal,
    crypto_signal:   AssetSignal,
    commodity_signal:AssetSignal,
    turkey_signal:   AssetSignal,
    portfolio_data:  dict = None,
    year_target_pct: float = 40.0,
) -> dict:
    """
    Tüm sinyalleri birleştirip cross-asset portföy kararı üret.
    Çelişkileri tespit et ve çöz.
    """
    signals = {
        "makro":    macro_signal,
        "abd":      us_signal,
        "kripto":   crypto_signal,
        "emtia":    commodity_signal,
        "turkiye":  turkey_signal,
    }

    # ── Çelişki Tespiti ──────────────────────────────────────────────────
    conflicts = []

    # Kripto + ABD hisse aynı anda AL sinyali → çeşitlendirme yanılgısı
    if (crypto_signal.signal in (Signal.BUY, Signal.ADD, Signal.STRONG_BUY) and
        us_signal.signal in (Signal.BUY, Signal.ADD, Signal.STRONG_BUY)):
        conflicts.append({
            "title": "Kripto & ABD Hisse — Çeşitlendirme Yanılgısı",
            "detail": "Her iki sınıf AL sinyali veriyor ama korelasyonları yüksek (%0.6-0.8). "
                     "Risk-off geldiğinde ikisi de birlikte düşer.",
            "resolution": "İkisini birden artırma. Önce hangisinin risk/ödül oranı daha iyi olduğuna karar ver.",
        })

    # Makro risk-off + herhangi bir varlık AL → çelişki
    if macro_signal.signal in (Signal.SELL, Signal.STRONG_SELL, Signal.REDUCE):
        buy_assets = [k for k, v in signals.items()
                     if v.signal in (Signal.BUY, Signal.STRONG_BUY, Signal.ADD)
                     and k != "makro"]
        if buy_assets:
            conflicts.append({
                "title": f"Makro risk-off ama {'/'.join(buy_assets)} AL sinyali",
                "detail": "Makro ortam satışa işaret ediyor ama bazı varlık sınıfları alım sinyali veriyor.",
                "resolution": "Makro sinyale ağırlık ver. Bireysel varlık sinyalleri yanlış olabilir. "
                             "Sadece gerçekten bağımsız olan varlıklarda (örn. altın) al sinyalini dikkate al.",
            })

    # ── Özet Sinyal ──────────────────────────────────────────────────────
    signal_scores = {
        Signal.STRONG_BUY: 4, Signal.BUY: 3, Signal.ADD: 2,
        Signal.HOLD: 1, Signal.WAIT: 0, Signal.REDUCE: -2,
        Signal.SELL: -3, Signal.STRONG_SELL: -4, Signal.NEUTRAL: 0,
    }

    # Ağırlıklı ortalama (makro 2x ağırlıklı)
    weights = {"makro": 2.0, "abd": 1.5, "kripto": 1.0, "emtia": 1.0, "turkiye": 1.0}
    total_w = sum(weights.values())
    weighted_score = sum(
        signal_scores.get(s.signal, 0) * weights[k]
        for k, s in signals.items()
    ) / total_w

    if weighted_score >= 2:
        overall = Signal.BUY
        summary = "Portföy için genel görünüm OLUMLU. Yatırım ortamı risk almayı destekliyor."
    elif weighted_score >= 0.5:
        overall = Signal.HOLD
        summary = "Portföy için genel görünüm NÖTR. Mevcut pozisyonları koru, büyük değişiklik yapma."
    elif weighted_score >= -0.5:
        overall = Signal.WAIT
        summary = "Portföy için genel görünüm TEMKİNLİ. Risk azalt, netlik bekle."
    elif weighted_score >= -2:
        overall = Signal.REDUCE
        summary = "Portföy için UYARI: risk azaltma zamanı. Nakit ve hedge ağırlığını artır."
    else:
        overall = Signal.SELL
        summary = "Portföy için GÜÇLÜ UYARI: birden fazla varlık sınıfında baskı var."

    # ── Yıl Sonu Hedefi Bağlamı ──────────────────────────────────────────
    target_context = ""
    if portfolio_data:
        port_val   = portfolio_data.get("analytics", {}).get("total_value", 0)
        start_val  = portfolio_data.get("start_value", port_val)
        if start_val > 0 and port_val > 0:
            current_ret = (port_val - start_val) / start_val * 100
            remaining   = year_target_pct - current_ret
            if remaining > 0:
                target_context = (
                    f"Yıl sonu hedefine kalan: %{remaining:.1f}. "
                    f"Bu ortamda {'agresif pozisyon' if weighted_score >= 1 else 'temkinli yaklaşım'} uygun."
                )

    return {
        "overall_signal":  overall,
        "overall_summary": summary,
        "weighted_score":  round(weighted_score, 2),
        "signals":         signals,
        "conflicts":       conflicts,
        "target_context":  target_context,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "color":           SIGNAL_COLORS.get(overall, "#5a6a7a"),
    }


# ─── Ana Fonksiyon ───────────────────────────────────────────────────────────

def generate_all_signals(
    macro_data:       dict,
    economic_data:    dict,
    crypto_data:      dict,
    commodity_data:   dict,
    turkey_data:      dict,
    portfolio_data:   dict = None,
    year_target_pct:  float = 40.0,
) -> dict:
    """
    Tüm sinyalleri üret ve birleştir.
    Her varlık sınıfı için net sinyal + portföy özet sinyali.
    """
    logger.info("Sinyal üretimi başlıyor...")

    macro    = analyze_macro_regime(macro_data)
    us_eq    = analyze_us_equity(economic_data,  macro)
    crypto   = analyze_crypto(crypto_data,        macro)
    commodity= analyze_commodity(commodity_data,  macro)
    turkey   = analyze_turkey(turkey_data,         macro)

    portfolio= generate_portfolio_signal(
        macro, us_eq, crypto, commodity, turkey,
        portfolio_data, year_target_pct,
    )

    logger.info("Sinyal üretimi tamamlandı. Genel: %s", portfolio["overall_signal"])
    return {
        "macro":     macro,
        "us_equity": us_eq,
        "crypto":    crypto,
        "commodity": commodity,
        "turkey":    turkey,
        "portfolio": portfolio,
    }
