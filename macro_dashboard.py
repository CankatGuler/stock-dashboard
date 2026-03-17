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
        if spread < -0.5:
            signal = "red"
            note   = f"Derin ters curve ({spread:+.2f}%) — resesyon riski yüksek"
        elif spread < 0:
            signal = "amber"
            note   = f"Hafif ters curve ({spread:+.2f}%) — dikkat"
        else:
            signal = "green"
            note   = f"Normal curve ({spread:+.2f}%) — ekonomi sağlıklı"

        # Sanal gösterge olarak ekle
        from dataclasses import replace
        data["YIELD_CURVE"] = MacroIndicator(
            key="YIELD_CURVE", label="Yield Curve (10Y−3M)",
            value=spread, prev=0, change_pct=0,
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
