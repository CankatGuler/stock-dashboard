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
