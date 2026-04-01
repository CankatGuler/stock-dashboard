# macro_dashboard.py — Makro Gösterge Paneli
#
# yfinance üzerinden anlık makro veri çeker:
#   - Korku & Volatilite: VIX, Put/Call proxy
#   - Faiz: 10Y, 2Y (yield curve), Fed Funds yaklaşımı
#   - Dolar & Emtia: DXY, Altın, Petrol, Bakır
#   - Piyasa: S&P 500, Nasdaq
#
# Piyasa Rejimini otomatik hesaplar:
#   RISK_ON / CAUTION / RISK_OFF
#
# Claude analizine otomatik makro bağlam ekler.

import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Ticker tanımları ────────────────────────────────────────────────────────

MACRO_TICKERS = {
    # Korku & Volatilite
    "VIX":    {"ticker": "^VIX",     "label": "VIX — Korku Endeksi",    "unit": "",    "group": "fear"},
    "TNX":    {"ticker": "^TNX",     "label": "10Y ABD Tahvil",          "unit": "%",   "group": "rates"},
    "IRX":    {"ticker": "^IRX",     "label": "3M ABD Tahvil",           "unit": "%",   "group": "rates"},
    "DXY":    {"ticker": "DX-Y.NYB", "label": "DXY — Dolar Endeksi",     "unit": "",    "group": "fx"},
    "GOLD":   {"ticker": "GC=F",     "label": "Altın (XAU/USD)",         "unit": "$",   "group": "commodity"},
    "OIL":    {"ticker": "CL=F",     "label": "Petrol (WTI)",            "unit": "$",   "group": "commodity"},
    "COPPER": {"ticker": "HG=F",     "label": "Bakır (Dr. Copper)",      "unit": "$",   "group": "commodity"},
    "SPX":    {"ticker": "^GSPC",    "label": "S&P 500",                 "unit": "",    "group": "market"},
    "NDX":    {"ticker": "^IXIC",    "label": "Nasdaq Composite",        "unit": "",    "group": "market"},
    "TLT":    {"ticker": "TLT",      "label": "Tahvil ETF (TLT)",        "unit": "$",   "group": "rates"},

    # Sektör ETF'leri
    "XLF":    {"ticker": "XLF",      "label": "XLF — Finans",            "unit": "$",   "group": "sector"},
    "XLE":    {"ticker": "XLE",      "label": "XLE — Enerji",            "unit": "$",   "group": "sector"},
    "XLK":    {"ticker": "XLK",      "label": "XLK — Teknoloji",         "unit": "$",   "group": "sector"},
    "XLV":    {"ticker": "XLV",      "label": "XLV — Sağlık",            "unit": "$",   "group": "sector"},
    "XLI":    {"ticker": "XLI",      "label": "XLI — Sanayi",            "unit": "$",   "group": "sector"},
    "XLP":    {"ticker": "XLP",      "label": "XLP — Savunmacı Tük.",    "unit": "$",   "group": "sector"},
    "XLRE":   {"ticker": "XLRE",     "label": "XLRE — Gayrimenkul",      "unit": "$",   "group": "sector"},

    # Türkiye
    "USDTRY": {"ticker": "USDTRY=X", "label": "USD/TRY",                 "unit": "₺",   "group": "turkey"},
    "TUR":    {"ticker": "TUR",      "label": "TUR ETF (BIST proxy)",    "unit": "$",   "group": "turkey"},
    "BIST":   {"ticker": "XU100.IS", "label": "BIST 100",                "unit": "",    "group": "turkey"},

    # Döviz
    "USDJPY": {"ticker": "JPY=X",    "label": "USD/JPY — Carry Trade",   "unit": "",    "group": "fx"},
    "EURUSD": {"ticker": "EURUSD=X", "label": "EUR/USD",                 "unit": "",    "group": "fx"},

    # Kredi
    "HYG":    {"ticker": "HYG",      "label": "HYG — Yüksek Getiri",    "unit": "$",   "group": "credit"},
    "LQD":    {"ticker": "LQD",      "label": "LQD — Yat. Grade Tahvil","unit": "$",   "group": "credit"},
}


@dataclass
class MacroIndicator:
    key:        str
    label:      str
    value:      float
    prev:       float
    change_pct: float
    unit:       str
    group:      str
    signal:     str = "neutral"   # "green" | "amber" | "red" | "neutral"
    note:       str = ""


def _safe(val, default=0.0):
    try:
        return float(val) if val else default
    except Exception:
        return default


def fetch_macro_data() -> dict[str, MacroIndicator]:
    """
    Tüm makro göstergeleri yfinance'ten çek.
    Returns: {key: MacroIndicator}
    """
    import yfinance as yf

    results = {}
    for key, meta in MACRO_TICKERS.items():
        try:
            fi    = yf.Ticker(meta["ticker"]).fast_info
            price = _safe(getattr(fi, "last_price", 0))
            prev  = _safe(getattr(fi, "previous_close", price) or price)
            chg   = ((price - prev) / prev * 100) if prev else 0

            ind = MacroIndicator(
                key=key,
                label=meta["label"],
                value=round(price, 2),
                prev=round(prev, 2),
                change_pct=round(chg, 2),
                unit=meta["unit"],
                group=meta["group"],
            )
            results[key] = ind
            time.sleep(0.15)
        except Exception as e:
            logger.warning("Macro fetch failed for %s: %s", key, e)

    # Sinyalleri hesapla
    _compute_signals(results)

    # Katman 1 yeni metrikleri ekle
    try:
        extended = fetch_extended_macro()
        results.update(extended)
    except Exception as e:
        logger.warning("Extended macro failed: %s", e)

    return results


def _compute_signals(data: dict[str, MacroIndicator]):
    """Her gösterge için yeşil/sarı/kırmızı sinyal ata."""

    # VIX
    if "VIX" in data:
        v = data["VIX"].value
        if v >= 30:
            data["VIX"].signal = "red"
            data["VIX"].note   = "Kritik korku — piyasada panik var"
        elif v >= 20:
            data["VIX"].signal = "amber"
            data["VIX"].note   = "Yüksek belirsizlik — dikkatli ol"
        else:
            data["VIX"].signal = "green"
            data["VIX"].note   = "Sakin piyasa — risk iştahı var"

    # 10Y Tahvil
    if "TNX" in data:
        v = data["TNX"].value
        if v >= 4.5:
            data["TNX"].signal = "red"
            data["TNX"].note   = "Yüksek faiz — growth hisselerine baskı"
        elif v >= 3.5:
            data["TNX"].signal = "amber"
            data["TNX"].note   = "Orta faiz — değerleme baskısı var"
        else:
            data["TNX"].signal = "green"
            data["TNX"].note   = "Düşük faiz — hisse değerlemelerine destek"

    # Yield Curve (10Y - 3M)
    if "TNX" in data and "IRX" in data:
        spread = data["TNX"].value - data["IRX"].value
        spread = round(spread, 2)
        # IRX zaten yüzde olarak geliyor (x10 çarpanlı bazen)
        # 10Y - 3M spread
        label = f"Yield Curve (10Y−3M): {spread:+.2f}%"
        # Önceki spread değerini hesapla (1 hafta önce) — yön tespiti için
        _prev_spread = 0.0
        try:
            import yfinance as _yf_ys
            _t10 = _yf_ys.Ticker("^TNX").history(period="5d")["Close"]
            _t3m = _yf_ys.Ticker("^IRX").history(period="5d")["Close"]
            if len(_t10) >= 2 and len(_t3m) >= 2:
                _prev_spread = round(float(_t10.iloc[-5]) - float(_t3m.iloc[-5]), 2) if len(_t10) >= 5 else round(float(_t10.iloc[0]) - float(_t3m.iloc[0]), 2)
        except Exception:
            pass

        _direction = spread - _prev_spread  # pozitif = steepening, negatif = flattening

        # Varsayılan değerler — tüm if/elif dalları için güvenli fallback
        _curve_type   = "NORMAL"
        _curve_note   = f"Normal eğri ({spread:+.2f}%) — ekonomi sağlıklı."
        _curve_signal = "green"

        # Eğri tipi belirleme
        if _prev_spread < 0 and spread > _prev_spread:
            # Ters eğriden normalleşmeye → Bull Steepener veya Bear Steepener
            if data.get("TNX") and data["TNX"].value < (data["TNX"].prev if data["TNX"].prev else data["TNX"].value):
                _curve_type = "BULL_STEEPENER"  # Uzun vadeli faiz düşüyor, spread normalleşiyor
                _curve_note = (f"⚠️ BULL STEEPENER TESPİT EDİLDİ ({spread:+.2f}%, önceki {_prev_spread:+.2f}%): "
                               f"Ters eğri normalleşiyor, uzun vade faiz DÜŞÜYOR. "
                               f"Tarihsel olarak %100 resesyon tescil sinyali — "
                               f"Fed 'geç kaldı' demektir (2007/2019 benzeri). "
                               f"Piyasa genellikle 6-18 ay içinde zirveyi test eder.")
                _curve_signal = "red"
            else:
                _curve_type = "BEAR_STEEPENER"  # Uzun vadeli faiz yükseliyor
                _curve_note = (f"⚡ BEAR STEEPENER ({spread:+.2f}%, önceki {_prev_spread:+.2f}%): "
                               f"Uzun vade faiz yükseliyor, eğri normalleşiyor. "
                               f"Enflasyon beklentisi veya risk primi artışı sinyali.")
                _curve_signal = "amber"
        elif spread < -0.5:
            _curve_type  = "INVERTED_DEEP"
            _curve_note  = (f"⚠️ DERİN TERS EĞRİ ({spread:+.2f}%) — Resesyon riski yüksek. "
                            f"Bu eğrinin normalleşmesi (bull steepener) resesyonun başladığını tescil eder.")
            _curve_signal = "red"
        elif spread < 0:
            _curve_type  = "INVERTED_MILD"
            _curve_note  = (f"⚡ Hafif ters curve ({spread:+.2f}%) — dikkat. "
                            f"Normalleşme yönü kritik: bull steepener = resesyon sinyali.")
            _curve_signal = "amber"
        elif _direction > 0.1:
            _curve_type  = "STEEPENING"
            _curve_note  = (f"Normal eğri ({spread:+.2f}%), steepening ({_direction:+.2f}%). "
                            f"Büyüme beklentisi pozitif.")
            _curve_signal = "green"
        else:
            _curve_type  = "NORMAL"
            _curve_note  = f"Normal eğri ({spread:+.2f}%) — ekonomi sağlıklı."
            _curve_signal = "green"

        signal = _curve_signal
        note   = _curve_note

        # Sanal gösterge olarak ekle
        from dataclasses import replace
        data["YIELD_CURVE"] = MacroIndicator(
            key="YIELD_CURVE", label=f"Yield Curve (10Y−3M) [{_curve_type}]",
            value=spread, prev=_prev_spread, change_pct=round(_direction, 2),
            unit="%", group="rates",
            signal=signal, note=note,
        )

    # DXY
    if "DXY" in data:
        v = data["DXY"].value
        chg = data["DXY"].change_pct
        if v >= 105:
            data["DXY"].signal = "red"
            data["DXY"].note   = "Çok güçlü dolar — EM ve çok uluslu şirketler baskılı"
        elif v >= 100:
            data["DXY"].signal = "amber"
            data["DXY"].note   = "Güçlü dolar — ihracat gelirleri olumsuz etkilenir"
        else:
            data["DXY"].signal = "green"
            data["DXY"].note   = "Zayıf dolar — uluslararası şirketlere pozitif"

    # Altın
    if "GOLD" in data:
        chg = data["GOLD"].change_pct
        if chg >= 1.5:
            data["GOLD"].signal = "red"
            data["GOLD"].note   = "Güçlü altın yükselişi — risk-off, piyasada korku var"
        elif chg >= 0:
            data["GOLD"].signal = "amber"
            data["GOLD"].note   = "Altın sakin — belirsizlik orta"
        else:
            data["GOLD"].signal = "green"
            data["GOLD"].note   = "Altın düşüyor — risk iştahı iyileşiyor"

    # Petrol
    if "OIL" in data:
        v = data["OIL"].value
        if v >= 90:
            data["OIL"].signal = "red"
            data["OIL"].note   = "Yüksek petrol — enflasyon baskısı, Fed sıkılaşır"
        elif v >= 70:
            data["OIL"].signal = "amber"
            data["OIL"].note   = "Orta petrol fiyatı — dengeli"
        else:
            data["OIL"].signal = "green"
            data["OIL"].note   = "Düşük petrol — tüketici ve ulaşım sektörüne pozitif"

    # Bakır
    if "COPPER" in data:
        chg = data["COPPER"].change_pct
        v   = data["COPPER"].value
        if chg <= -1.5 or v < 3.5:
            data["COPPER"].signal = "red"
            data["COPPER"].note   = "Bakır düşüyor — küresel büyüme yavaşlaması sinyali"
        elif chg >= 1.5:
            data["COPPER"].signal = "green"
            data["COPPER"].note   = "Bakır yükseliyor — küresel büyüme ivmesi var"
        else:
            data["COPPER"].signal = "amber"
            data["COPPER"].note   = "Bakır yatay — büyüme belirsiz"

    # S&P 500
    if "SPX" in data:
        chg = data["SPX"].change_pct
        if chg <= -1.5:
            data["SPX"].signal = "red"
            data["SPX"].note   = "Piyasa sert düşüyor — risk azalt"
        elif chg >= 1.0:
            data["SPX"].signal = "green"
            data["SPX"].note   = "Güçlü piyasa — momentum olumlu"
        else:
            data["SPX"].signal = "neutral"
            data["SPX"].note   = "Yatay piyasa — yön bekleniyor"


def compute_market_regime(data: dict[str, MacroIndicator]) -> dict:
    """
    Tüm sinyalleri değerlendirip piyasa rejimini belirle.
    Returns: {regime, label, color, description, score}
    """
    red_count    = sum(1 for v in data.values() if v.signal == "red")
    amber_count  = sum(1 for v in data.values() if v.signal == "amber")
    green_count  = sum(1 for v in data.values() if v.signal == "green")
    total        = max(red_count + amber_count + green_count, 1)

    # Ağırlıklı skor: yeşil=+1, nötr=0, sarı=-1, kırmızı=-2
    score = (green_count * 1 + amber_count * -1 + red_count * -2) / total

    if score >= 0.3:
        return {
            "regime":      "RISK_ON",
            "label":       "Risk Al",
            "color":       "#3B6D11",
            "bg":          "#EAF3DE",
            "description": "Piyasa koşulları elverişli. Hisse ağırlığını artırabilirsin. Büyüme ve momentum hisselerine odaklan.",
        }
    elif score >= -0.5:
        return {
            "regime":      "CAUTION",
            "label":       "Temkinli",
            "color":       "#854F0B",
            "bg":          "#FAEEDA",
            "description": "Karışık sinyaller. Mevcut pozisyonları koru, yeni spekülatif alım yapma. Savunmacı hisselere ağırlık ver.",
        }
    else:
        return {
            "regime":      "RISK_OFF",
            "label":       "Riskten Kaç",
            "color":       "#A32D2D",
            "bg":          "#FCEBEB",
            "description": "Piyasa koşulları olumsuz. Pozisyon azalt, nakit ve altın ağırlığını artır. Spekülatif hisselerden çık.",
        }


def build_claude_macro_context(data: dict[str, MacroIndicator], regime: dict) -> str:
    """
    Claude analizine eklenecek makro bağlam metni.
    """
    if not data:
        return ""

    lines = ["=== GÜNCEL MAKRO ORTAM ==="]
    lines.append(f"Piyasa Rejimi: {regime['label']} ({regime['regime']})")
    lines.append(f"Açıklama: {regime['description']}")
    lines.append("")

    groups = {
        "fear":      "Korku & Volatilite",
        "rates":     "Faiz Ortamı",
        "fx":        "Dolar",
        "commodity": "Emtia",
        "market":    "Piyasa",
    }

    for group_key, group_label in groups.items():
        group_items = [v for v in data.values() if v.group == group_key]
        if not group_items:
            continue
        lines.append(f"[{group_label}]")
        for item in group_items:
            signal_str = {"red": "⚠️", "amber": "⚡", "green": "✅", "neutral": "—"}.get(item.signal, "")
            unit = item.unit if item.unit != "$" else ""
            prefix = "$" if item.unit == "%" else ("$" if item.unit == "$" else "")
            lines.append(
                f"  {signal_str} {item.label}: {prefix}{item.value:.2f}{unit} "
                f"({item.change_pct:+.2f}%) — {item.note}"
            )
        lines.append("")

    lines.append("=" * 40)
    return "\n".join(lines)


# ─── Katman 1 Genişletilmiş Makro Metrikler ──────────────────────────────────

def fetch_extended_macro() -> dict:
    """
    Yeni Katman 1 metrikleri:
    - Credit Spread (HYG/LQD proxy)
    - OVX (Petrol Volatilitesi — jeopolitik proxy)
    - MOVE Index proxy (tahvil volatilitesi)
    - USD/JPY (carry trade riski)
    - Global M2 proxy (TLT + SPY + GLD birleşimi)
    - CME FedWatch proxy (FFR futures'dan)

    Returns: {key: MacroIndicator}
    """
    import yfinance as yf
    results = {}

    # ── Credit Spread: HYG (Junk) vs LQD (Investment Grade) ─────────────
    # Fark genişlerse kredi riski artıyor demektir — erken uyarı sinyali
    try:
        hyg_price = float(yf.Ticker("HYG").fast_info.last_price or 0)
        lqd_price = float(yf.Ticker("LQD").fast_info.last_price or 0)
        hyg_prev  = float(getattr(yf.Ticker("HYG").fast_info, "previous_close", hyg_price) or hyg_price)
        lqd_prev  = float(getattr(yf.Ticker("LQD").fast_info, "previous_close", lqd_price) or lqd_price)

        # Göreceli performans: HYG/LQD oranı — düşüyorsa credit spread genişliyor
        if lqd_price > 0 and lqd_prev > 0:
            ratio     = hyg_price / lqd_price
            ratio_prev= hyg_prev / lqd_prev
            ratio_chg = (ratio - ratio_prev) / ratio_prev * 100 if ratio_prev > 0 else 0

            if ratio_chg <= -0.3:
                signal = "red"
                note   = f"Credit spread GENİŞLİYOR — kredi riski artıyor, yatırımcılar güvenli limana kaçıyor"
            elif ratio_chg >= 0.2:
                signal = "green"
                note   = f"Credit spread DARAL IYOR — risk iştahı artıyor, kredi ortamı iyileşiyor"
            else:
                signal = "neutral"
                note   = f"Credit spread stabil — kredi piyasası sakin"

            results["CREDIT_SPREAD"] = MacroIndicator(
                key="CREDIT_SPREAD", label="Credit Spread (HYG/LQD)",
                value=round(ratio, 4), prev=round(ratio_prev, 4),
                change_pct=round(ratio_chg, 2),
                unit="", group="rates",
                signal=signal, note=note,
            )
        time.sleep(0.15)
    except Exception as e:
        logger.debug("Credit spread failed: %s", e)

    # ── OVX: Petrol Volatilitesi — Jeopolitik Proxy ───────────────────────
    # OVX yükselince jeopolitik risk artıyor — Orta Doğu gerilimi, arz şokları
    try:
        ovx = float(yf.Ticker("^OVX").fast_info.last_price or 0)
        if ovx > 0:
            if ovx >= 50:
                signal = "red"
                note   = f"OVX {ovx:.0f} — Yüksek petrol volatilitesi: jeopolitik risk veya arz şoku"
            elif ovx >= 35:
                signal = "amber"
                note   = f"OVX {ovx:.0f} — Orta petrol volatilitesi: dikkat"
            else:
                signal = "green"
                note   = f"OVX {ovx:.0f} — Sakin petrol piyasası: jeopolitik risk düşük"

            results["OVX"] = MacroIndicator(
                key="OVX", label="OVX — Petrol Volatilitesi",
                value=round(ovx, 1), prev=0, change_pct=0,
                unit="", group="fear",
                signal=signal, note=note,
            )
        time.sleep(0.15)
    except Exception as e:
        logger.debug("OVX failed: %s", e)

    # ── USD/JPY: Carry Trade Riski ────────────────────────────────────────
    # Yen güçlenirse carry trade çözülür, küresel likidite ani çekilir
    try:
        usdjpy     = float(yf.Ticker("JPY=X").fast_info.last_price or 0)
        usdjpy_prev= float(getattr(yf.Ticker("JPY=X").fast_info, "previous_close", usdjpy) or usdjpy)
        jpy_chg    = (usdjpy - usdjpy_prev) / usdjpy_prev * 100 if usdjpy_prev > 0 else 0

        if usdjpy > 0:
            if jpy_chg <= -1.0:  # Dolar düşüyor = Yen güçleniyor
                signal = "red"
                note   = f"Yen GÜÇLENIYOR ({usdjpy:.1f}) — carry trade çözülüyor, küresel likidite riski!"
            elif usdjpy >= 155:
                signal = "amber"
                note   = f"USD/JPY {usdjpy:.1f} — Aşırı zayıf yen, BOJ müdahale riski"
            elif usdjpy <= 140:
                signal = "amber"
                note   = f"USD/JPY {usdjpy:.1f} — Güçlü yen, carry trade pozisyonları risk altında"
            else:
                signal = "neutral"
                note   = f"USD/JPY {usdjpy:.1f} — Normal aralıkta"

            results["USDJPY"] = MacroIndicator(
                key="USDJPY", label="USD/JPY — Carry Trade",
                value=round(usdjpy, 2), prev=round(usdjpy_prev, 2),
                change_pct=round(jpy_chg, 2),
                unit="", group="fx",
                signal=signal, note=note,
            )
        time.sleep(0.15)
    except Exception as e:
        logger.debug("USD/JPY failed: %s", e)

    # ── Global M2 Proxy: GLD + TLT + SPY momentum ────────────────────────
    # M2 genişlemesi varlık fiyatlarını şişirir — 2020 örneği
    # Proxy: TLT (tahvil), GLD (altın), SPY (hisse) 1 aylık değişim
    try:
        tlt_info = yf.Ticker("TLT").fast_info
        gld_info = yf.Ticker("GLD").fast_info
        spy_info = yf.Ticker("SPY").fast_info

        tlt_chg = 0.0
        gld_chg = 0.0
        spy_chg = 0.0

        for ticker, fi, chg_ref in [
            ("TLT", tlt_info, None),
            ("GLD", gld_info, None),
            ("SPY", spy_info, None),
        ]:
            p    = float(getattr(fi, "last_price", 0) or 0)
            prev = float(getattr(fi, "previous_close", p) or p)
            if prev > 0:
                c = (p - prev) / prev * 100
                if ticker == "TLT": tlt_chg = c
                elif ticker == "GLD": gld_chg = c
                elif ticker == "SPY": spy_chg = c

        # Likidite skoru: hepsi yükseliyorsa bol likidite
        liquidity_score = (spy_chg + gld_chg - tlt_chg) / 3
        if liquidity_score > 0.5:
            signal = "green"
            note   = f"Likidite GENİŞ — hisse+altın yükseliyor, tahvil baskılı: risk varlıkları destekleniyor"
        elif liquidity_score < -0.5:
            signal = "red"
            note   = f"Likidite DARALIYOR — tahvil yükseliyor, hisse+altın düşüyor: risk-off modu"
        else:
            signal = "neutral"
            note   = f"Likidite NÖTR — karışık sinyaller"

        results["LIQUIDITY"] = MacroIndicator(
            key="LIQUIDITY", label="Küresel Likidite Proxy",
            value=round(liquidity_score, 2), prev=0, change_pct=0,
            unit="", group="market",
            signal=signal, note=note,
        )
        time.sleep(0.15)
    except Exception as e:
        logger.debug("Liquidity proxy failed: %s", e)

    # ── CME FedWatch Proxy: Fed Funds Futures ────────────────────────────
    # ZQ = Fed Funds Futures — piyasanın Fed beklentisi
    # Gerçek CME API yerine, mevcut faiz ile FFR futures farkından tahmin
    try:
        # ZQH26 gibi yakın vadeli fed funds futures
        # Alternatif: SOFR veya FF Futures ETF
        irx  = float(yf.Ticker("^IRX").fast_info.last_price or 0)  # 3M T-Bill ≈ Fed Funds
        tnx  = float(yf.Ticker("^TNX").fast_info.last_price or 0)  # 10Y

        # Basit FedWatch proxy: piyasanın kısa vade beklentisi
        # IRX Fed Funds Rate'e çok yakın — beklenti için forward hesabı
        if irx > 0:
            # Tahmin: piyasa IRX'i hangi yönde fiyatlıyor?
            # IRX'in son değişimine göre Fed hamle beklentisi
            irx_prev = float(getattr(yf.Ticker("^IRX").fast_info, "previous_close", irx) or irx)
            irx_chg  = irx - irx_prev

            if irx_chg < -0.1:
                fed_signal = "green"
                fed_note   = f"Piyasa FAİZ İNDİRİMİ fiyatlıyor — 3M T-Bill düşüyor (şu an %{irx:.2f})"
                fed_expectation = "İndirim Beklentisi"
            elif irx_chg > 0.1:
                fed_signal = "red"
                fed_note   = f"Piyasa FAİZ ARTIRIMI fiyatlıyor — 3M T-Bill yükseliyor (şu an %{irx:.2f})"
                fed_expectation = "Artırım Beklentisi"
            else:
                fed_signal = "neutral"
                fed_note   = f"Fed beklentisi DEĞİŞMEDİ — piyasa sabit fiyatlıyor (3M: %{irx:.2f})"
                fed_expectation = "Değişim Yok"

            results["FED_WATCH"] = MacroIndicator(
                key="FED_WATCH", label=f"Fed Beklentisi ({fed_expectation})",
                value=round(irx, 2), prev=round(irx_prev, 2),
                change_pct=round(irx_chg, 3),
                unit="%", group="rates",
                signal=fed_signal, note=fed_note,
            )
        time.sleep(0.15)
    except Exception as e:
        logger.debug("FedWatch proxy failed: %s", e)

    # ── MOVE Index Proxy: Tahvil Volatilitesi ────────────────────────────
    # MOVE direkt yfinance'te yok, TLT volatilitesi proxy olarak kullanılır
    try:
        tlt_hist = yf.Ticker("TLT").history(period="20d", interval="1d")["Close"]
        if len(tlt_hist) >= 10:
            import statistics
            tlt_returns = [
                (tlt_hist.iloc[i] - tlt_hist.iloc[i-1]) / tlt_hist.iloc[i-1]
                for i in range(1, len(tlt_hist))
            ]
            tlt_vol = statistics.stdev(tlt_returns) * (252 ** 0.5) * 100  # Annualized %

            if tlt_vol >= 15:
                signal = "red"
                note   = f"Tahvil volatilitesi YÜKSEK (%{tlt_vol:.0f} annualized) — MOVE yüksek, faiz belirsizliği çok"
            elif tlt_vol >= 10:
                signal = "amber"
                note   = f"Tahvil volatilitesi ORTA (%{tlt_vol:.0f}) — dikkat"
            else:
                signal = "green"
                note   = f"Tahvil volatilitesi DÜŞÜK (%{tlt_vol:.0f}) — faiz piyasası sakin"

            results["MOVE_PROXY"] = MacroIndicator(
                key="MOVE_PROXY", label="MOVE Proxy (TLT Vol)",
                value=round(tlt_vol, 1), prev=0, change_pct=0,
                unit="%", group="fear",
                signal=signal, note=note,
            )
    except Exception as e:
        logger.debug("MOVE proxy failed: %s", e)

    return results


# ─── Sektör Bazlı Savunmacı Hisse Evreni ─────────────────────────────────────
# Claude bu listeden seçerek somut öneri yapar.
# Her varlık sınıfı için temsili ve likit isimler tutuldu.

DEFENSIVE_UNIVERSE = {
    "Sağlık": {
        "ETF": ["XLV", "VHT"],
        "Büyük Sermayeli": [
            ("LLY",  "Eli Lilly — GLP-1 / obezite liderliği, güçlü boru hattı"),
            ("JNJ",  "Johnson & Johnson — çeşitlendirilmiş gelir, güçlü temettü"),
            ("UNH",  "UnitedHealth — sağlık sigortası tekeli, nakit akışı sağlam"),
            ("ABBV", "AbbVie — Humira sonrası geçiş tamamlanıyor, yüksek temettü"),
            ("MRK",  "Merck — Keytruda büyüme motoru, savunmacı profil"),
        ],
        "Dikkat": "Politika riski (ilaç fiyat regülasyonu) değerlemeyi baskılayabilir.",
    },
    "Utilities": {
        "ETF": ["XLU", "VPU"],
        "Büyük Sermayeli": [
            ("NEE",  "NextEra Energy — yenilenebilir enerji liderliği, düzenli temettü"),
            ("SO",   "Southern Company — güney ABD, nükleer kapasite genişliyor"),
            ("DUK",  "Duke Energy — çeşitlendirilmiş altyapı, istikrarlı nakit"),
            ("AEP",  "American Electric Power — yüksek iletim ağı, temettü odaklı"),
            ("ED",   "Consolidated Edison — NYC altyapısı, ultra defansif"),
        ],
        "Dikkat": "Yüksek faiz ortamında utilities hisseleri baskı altına girer — tahvil alternatifi gibi fiyatlanır.",
    },
    "Temel Tüketim": {
        "ETF": ["XLP", "VDC"],
        "Büyük Sermayeli": [
            ("PG",   "Procter & Gamble — fiyat geçirme gücü yüksek, 60+ yıl temettü"),
            ("KO",   "Coca-Cola — marka gücü, global dağıtım, Berkshire tercihi"),
            ("WMT",  "Walmart — deflasyonist dönemde bile güçlü, e-ticaret büyüyor"),
            ("COST", "Costco — üyelik modeli, döngüsel olmayan gelir"),
            ("MO",   "Altria — yüksek temettü, düşük volatilite, tütün nakit akışı"),
        ],
        "Dikkat": "Stagflasyon senaryosunda tüketim baskılanabilir; marka gücü olanlar hayatta kalır.",
    },
    "Enerji": {
        "ETF": ["XLE", "VDE", "OIH"],
        "Büyük Sermayeli": [
            ("XOM",  "ExxonMobil — entegre dev, düşük üretim maliyeti, güçlü temettü"),
            ("CVX",  "Chevron — Permian Basin avantajı, borcunu erken ödüyor"),
            ("COP",  "ConocoPhillips — saf E&P, petrol fiyatına en net maruz kalım"),
            ("PSX",  "Phillips 66 — rafineri marjı yüksek, jet yakıtı talebi artıyor"),
            ("SLB",  "SLB (Schlumberger) — servis şirketi, küresel sondaj döngüsüne bağlı"),
        ],
        "Dikkat": "Petrol $100+ senaryosunda en çok yararlanan ancak timing kritik; çok geç giriş OVX başa çıkıldıktan sonra gelir.",
    },
    "Altın / Değer Deposu": {
        "ETF": ["GLD", "IAU", "GDXJ", "GDX"],
        "Büyük Sermayeli": [
            ("NEM",  "Newmont — dünya no.1 altın madencisi, hedge edilmiş maliyet yapısı"),
            ("AEM",  "Agnico Eagle — Kanada bazlı, düşük jeopolitik risk, güçlü keşif"),
            ("GOLD", "Barrick Gold — büyük ölçek, bakır çeşitlendirmesi var"),
            ("WPM",  "Wheaton Precious Metals — royalty modeli, maliyet volatilitesi yok"),
            ("FNV",  "Franco-Nevada — altın/petrol royalty, düşük operasyonel risk"),
        ],
        "Dikkat": "Altın madencileri altın fiyatına 1.5-2x kaldıraçlı; fiziki altın tercih edilirse GLD/IAU daha temiz.",
    },
    "Kısa Vadeli Tahvil / Para Piyasası": {
        "ETF": ["SHV", "BIL", "SGOV", "TFLO"],
        "Not": "Risksiz getiri ~%3.5-4.5 aralığında; VIX 25+ ortamında nakit alternatifi olarak en güvenli park yeri.",
        "Büyük Sermayeli": [],
    },
}



# ─── Büyüme / Roket Hisse Evreni (Risk-On, Toparlanma) ──────────────────────
# VIX düşük, kredi spread'leri daralıyor, bakır yükseliyor → para beta'ya akar

GROWTH_UNIVERSE = {
    "Yapay Zeka / Yarı İletken": {
        "ETF": ["SOXX", "SMH", "BOTZ", "AIQ"],
        "Büyük Sermayeli": [
            ("NVDA", "NVIDIA — veri merkezi GPU tekeli, AI boru hattı büyümesi yıllık %100+"),
            ("AVGO", "Broadcom — özel AI chip + ağ altyapısı, güçlü serbest nakit akışı"),
            ("AMD",  "AMD — sunucu CPU ve AI GPU pazar payı kazanıyor"),
            ("TSM",  "TSMC — tüm ileri chip'lerin fabrikası, yapısal talep güvencesi"),
            ("AMAT", "Applied Materials — çip üretim ekipmanı, döngü tepesinde yüksek marj"),
        ],
        "Dikkat": "Tek sektör riski yüksek — NVDA kazanç sezonunda tüm grup etkilenir.",
    },
    "Yazılım / Bulut": {
        "ETF": ["IGV", "WCLD", "BUG"],
        "Büyük Sermayeli": [
            ("MSFT", "Microsoft — Azure + Copilot AI entegrasyonu, recurring gelir modeli"),
            ("CRM",  "Salesforce — enterprise yazılım, AI Agentforce büyüme katalizörü"),
            ("NOW",  "ServiceNow — IT workflow otomasyonu, yüksek net retention"),
            ("PANW", "Palo Alto Networks — siber güvenlik konsolidasyonu, platform hamlesi"),
            ("CRWD", "CrowdStrike — endpoint güvenlik lideri, güçlü ARR büyümesi"),
        ],
        "Dikkat": "Değerleme yüksek; faiz artışı veya büyüme yavaşlaması çarpanları sıkıştırır.",
    },
    "Döngüsel / Sanayi": {
        "ETF": ["XLI", "VIS", "PAVE"],
        "Büyük Sermayeli": [
            ("CAT",  "Caterpillar — altyapı yatırım döngüsü + madencilik talebi"),
            ("DE",   "Deere — tarım makineleri, yeniden stok döngüsünde öncü"),
            ("GE",   "GE Aerospace — uçak motoru talebi güçlü, uzun sipariş defteri"),
            ("VRT",  "Vertiv — veri merkezi soğutma altyapısı, AI talep ötesi büyüme"),
            ("EMR",  "Emerson Electric — otomasyon teknolojileri, stabil nakit akışı"),
        ],
        "Dikkat": "Ekonomi gerçekten toparlanıyorsa bu grup en erken hareket eder; ama sahte rallilerde de erken düşer.",
    },
    "Finans / Bankacılık": {
        "ETF": ["XLF", "KRE", "KBE"],
        "Büyük Sermayeli": [
            ("JPM",  "JPMorgan — en güçlü banka bilançosu, faiz artışından net kazanır"),
            ("BAC",  "Bank of America — faiz duyarlılığı yüksek, faiz düştükçe net gelir artar"),
            ("GS",   "Goldman Sachs — IB/trading döngüsü canlanınca en çok kazanan"),
            ("V",    "Visa — tüketim hacmi proxy, deflationary değil döngüsel büyüme"),
            ("BX",   "Blackstone — alternatif varlık yönetimi, AUM büyümesi"),
        ],
        "Dikkat": "Kredi kalitesi bozulursa banka hisseleri ilk vurulur — tüketici borç verileri izlenmeli.",
    },
    "Küçük Sermayeli / Büyüme (Yüksek Beta)": {
        "ETF": ["IWM", "IJR", "VBK"],
        "Büyük Sermayeli": [
            ("PLTR", "Palantir — kamu/özel AI veri analitiği, yüksek momentum"),
            ("IONQ", "IonQ — kuantum bilişim erken oyunu, spekülatif ama izlemeye değer"),
            ("RKLB", "Rocket Lab — uzay fırlatma altyapısı, SpaceX rakibi"),
            ("HOOD", "Robinhood — perakende yatırımcı aktivitesi proxy, risk-on barometresi"),
            ("COIN", "Coinbase — kripto volume proxy, risk-on dönemde en yüksek beta"),
        ],
        "Dikkat": "Bu sepet risk-on dönemde 3-5x piyasayı döver, risk-off dönemde ise %50+ düşer. Pozisyon boyutu kritik.",
    },
    "Kripto Ekosistemi": {
        "ETF": ["IBIT", "FBTC", "ETHA"],
        "Büyük Sermayeli": [
            ("COIN", "Coinbase — Bitcoin ETF onayından en çok kazanan, hacim odaklı gelir"),
            ("MSTR", "MicroStrategy — kaldıraçlı BTC tutma stratejisi, Bitcoin beta 2x"),
            ("RIOT", "Riot Platforms — Bitcoin madenci, hash rate büyümesi"),
            ("CLSK", "CleanSpark — enerji verimli madencilik, düşük maliyet yapısı"),
        ],
        "Dikkat": "Bu sepet kripto piyasasına 1.5-3x kaldıraçlıdır. Halving döngüsü ve BTC dominansı izlenmeli.",
    },
}


# ─── Stagflasyon Evreni (Özel Durum) ────────────────────────────────────────
STAGFLATION_UNIVERSE = {
    "Enerji (Upstream)": {
        "ETF": ["XLE", "XOP", "OIH"],
        "Büyük Sermayeli": [
            ("XOM",  "ExxonMobil — petrol $90+ senaryosunda en yüksek serbest nakit akışı"),
            ("COP",  "ConocoPhillips — saf E&P, petrol fiyatına net maruz kalım"),
            ("CVX",  "Chevron — düşük üretim maliyeti, güçlü temettü artışı"),
            ("MPC",  "Marathon Petroleum — rafineri marjları yüksek, jet yakıtı talebi"),
            ("DVN",  "Devon Energy — yüksek değişken temettü, Permian Basin varlıkları"),
        ],
        "Dikkat": "Petrol $100+ geçerse enerji hisseleri zirveye yakın olabilir — timing kritik.",
    },
    "Altın / Enflasyon Koruyucu": {
        "ETF": ["GLD", "IAU", "TIP", "TIPS"],
        "Büyük Sermayeli": [
            ("NEM",  "Newmont — maliyet kontrollü madenci, TL olarak enflasyon koruması"),
            ("WPM",  "Wheaton Precious Metals — royalty modeli, düşük maliyet volatilitesi"),
            ("FNV",  "Franco-Nevada — altın+petrol royalty, en savunmacı madenci profili"),
            ("AEM",  "Agnico Eagle — Kanada bazlı, düşük siyasi risk, güçlü keşif"),
        ],
        "Dikkat": "Reel faiz yükselmeye devam ederse altın baskı görür. TIP/TLT oranı izlenmeli.",
    },
    "Hammadde / Emtia": {
        "ETF": ["DJP", "PDBC", "COMT"],
        "Büyük Sermayeli": [
            ("FCX",  "Freeport-McMoRan — bakır liderliği, küresel elektrik talebiyle bağlantılı"),
            ("NUE",  "Nucor — çelik üreticisi, inşaat ve enerji altyapısı talebi"),
            ("CF",   "CF Industries — gübre/azot üreticisi, tarım emtia döngüsü"),
            ("MOS",  "Mosaic — potash/fosfat, gıda fiyatları yükselince kazanır"),
        ],
        "Dikkat": "Stagflasyon uzarsa hammadde şirketleri marj sıkışmasına girer — girdi maliyeti de artar.",
    },
}


# ─── Toparlanma / Geçiş Evreni ───────────────────────────────────────────────
RECOVERY_UNIVERSE = {
    "Döngüsel Liderler": {
        "ETF": ["XLI", "XLB", "XLF"],
        "Büyük Sermayeli": [
            ("CAT",  "Caterpillar — altyapı siparişleri toparlanmanın erken sinyali"),
            ("DE",   "Deere — tarım makineleri yeniden stok döngüsü"),
            ("FCX",  "Freeport — bakır toparlanıyorsa bu hisse hem öncü hem kazanan"),
            ("JPM",  "JPMorgan — kredi döngüsü canlanınca en sağlıklı banka"),
            ("LEN",  "Lennar — konut inşaatı, faiz düştükçe ilk canlanır"),
        ],
        "Dikkat": "Toparlanma sahte ise bu grup ilk düşer. Sinyal teyidi olmadan erken giriş riskli.",
    },
    "Tüketici Takımlığı": {
        "ETF": ["XLY", "VCR"],
        "Büyük Sermayeli": [
            ("AMZN", "Amazon — tüketici harcaması + AWS bulut, çift motor"),
            ("HD",   "Home Depot — konut yenileme döngüsü, faiz hassasiyeti düşüşte azalır"),
            ("NKE",  "Nike — küresel tüketici marka, Çin toparlanmasına bağlı"),
            ("TSLA", "Tesla — hem tüketim hem enerji, yüksek beta büyüme"),
        ],
        "Dikkat": "Tüketici güveni geri gelmedikçe bu sektör performans göstermez.",
    },
}


def get_regime_stock_context(regime: str, vix: float = 20.0,
                              copper_chg: float = 0.0) -> str:
    """
    Piyasa rejimine göre doğru hisse evrenini seçip Claude'a verir.

    Karar mantığı:
    - RISK_ON / BULL      → Büyüme/Roket hisseleri ön planda
    - RISK_OFF / CAUTION  → Defansif hisseler ön planda
    - STAGFLATION         → Enerji + Altın ön planda
    - RECOVERY            → Döngüsel + Teknoloji karışımı
    - Geçiş zone (VIX 18-25 arası)  → Her iki evren de gösterilir
    """
    lines = ["\n=== REJİME GÖRE HİSSE EVRENİ ==="]
    lines.append(f"Aktif rejim: {regime} | VIX: {vix:.1f} | Bakır değişim: {copper_chg:+.1f}%")
    lines.append("Claude bu listeden somut ticker önerisi yapmalıdır.")

    # ── Rejim kararı ──────────────────────────────────────────────────────
    # VIX ve bakır birlikte rejimi teyit eder
    is_risk_on    = regime in ("RISK_ON", "BULL") or (vix < 18 and copper_chg > 1.0)
    is_risk_off   = regime in ("RISK_OFF",) or vix > 25
    is_caution    = regime == "CAUTION" or (18 <= vix <= 25)
    is_stagflation= regime == "STAGFLATION" or (copper_chg < -2.0 and vix > 22)
    is_recovery   = regime in ("RECOVERY", "TRANSITION") or (copper_chg > 2.0 and vix < 22)

    if is_stagflation:
        lines.append("⚠️ STAGFLASYON REJİMİ — Büyüme değil, enflasyon koruması öncelikli")
        lines.append("Önerilen ağırlık: Enerji %25 | Altın %20 | Defansif %30 | Nakit %25\n")
        for sector, info in STAGFLATION_UNIVERSE.items():
            _format_sector(lines, sector, info, max_stocks=3)
        lines.append("--- Destekleyici Defansif ---")
        for sector in ["Sağlık", "Temel Tüketim"]:
            _format_sector(lines, sector, DEFENSIVE_UNIVERSE.get(sector, {}), max_stocks=2)

    elif is_risk_on:
        lines.append("🚀 RISK-ON REJİMİ — Büyüme ve momentum hisseleri öne çıkar")
        lines.append("Önerilen ağırlık: Büyüme Hisse %50 | Döngüsel %20 | Kripto %10 | Nakit %20\n")
        for sector in ["Yapay Zeka / Yarı İletken", "Yazılım / Bulut",
                       "Döngüsel / Sanayi", "Finans / Bankacılık"]:
            _format_sector(lines, sector, GROWTH_UNIVERSE.get(sector, {}), max_stocks=3)

    elif is_recovery:
        lines.append("🔄 TOPARLANMA REJİMİ — Döngüsel hisseler liderliğe geçiyor")
        lines.append("Önerilen ağırlık: Döngüsel %30 | Teknoloji %25 | Defansif %20 | Nakit %25\n")
        for sector, info in RECOVERY_UNIVERSE.items():
            _format_sector(lines, sector, info, max_stocks=3)
        lines.append("--- Büyüme Kataloğundan ---")
        for sector in ["Yapay Zeka / Yarı İletken", "Finans / Bankacılık"]:
            _format_sector(lines, sector, GROWTH_UNIVERSE.get(sector, {}), max_stocks=2)

    elif is_risk_off:
        lines.append("🛡️ RISK-OFF REJİMİ — Sermaye koruması, defansif pozisyonlanma")
        lines.append("Önerilen ağırlık: Nakit/Tahvil %30 | Defansif %40 | Altın %15 | Enerji %15\n")
        for sector in ["Kısa Vadeli Tahvil / Para Piyasası", "Sağlık",
                       "Utilities", "Temel Tüketim", "Altın / Değer Deposu"]:
            _format_sector(lines, sector, DEFENSIVE_UNIVERSE.get(sector, {}), max_stocks=3)

    else:  # CAUTION / geçiş
        lines.append("⚡ TEMKİN REJİMİ — Karışık sinyaller, her iki yön hazırlığı")
        lines.append("Önerilen ağırlık: Defansif %35 | Kaliteli Büyüme %25 | Nakit %25 | Altın %15\n")
        lines.append("--- Defansif Taraf ---")
        for sector in ["Kısa Vadeli Tahvil / Para Piyasası", "Sağlık", "Altın / Değer Deposu"]:
            _format_sector(lines, sector, DEFENSIVE_UNIVERSE.get(sector, {}), max_stocks=2)
        lines.append("--- Kaliteli Büyüme (Seçici) ---")
        for sector in ["Yazılım / Bulut", "Yapay Zeka / Yarı İletken"]:
            _format_sector(lines, sector, GROWTH_UNIVERSE.get(sector, {}), max_stocks=2)

    lines.append("=" * 50)
    return "\n".join(lines)


def _format_sector(lines: list, sector: str, info: dict, max_stocks: int = 3):
    """Sektör bilgisini Claude prompt'u için formatla."""
    if not info:
        return
    etfler   = info.get("ETF", [])
    hisseler = info.get("Büyük Sermayeli", [])
    dikkat   = info.get("Dikkat", "") or info.get("Not", "")

    lines.append(f"[{sector}]")
    if etfler:
        lines.append(f"  ETF alternatifi: {', '.join(etfler)}")
    for ticker, desc in hisseler[:max_stocks]:
        lines.append(f"  • {ticker}: {desc}")
    if dikkat:
        lines.append(f"  ⚠ {dikkat}")
    lines.append("")


# Geriye uyumluluk için eski fonksiyon adını koru
def get_defensive_context_for_claude(regime: str) -> str:
    """Eski API — get_regime_stock_context'e yönlendir."""
    return get_regime_stock_context(regime)
