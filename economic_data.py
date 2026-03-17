# economic_data.py — Katman 2 Ekonomik Veri Modülü
#
# FRED API (ücretsiz, key gerektirmez) + yfinance ile:
#   ISM Manufacturing/Services, NFP, CPI, PCE, GDP
#   S&P 500 Forward P/E + Shiller CAPE
#   Sektör Rotasyonu (8 ETF göreceli güç)

import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@dataclass
class EconIndicator:
    key:      str
    label:    str
    value:    float
    prev:     float
    date:     str
    signal:   str
    note:     str
    unit:     str = ""


def _fred_latest(series_id: str, periods: int = 3) -> list[tuple[str, float]]:
    try:
        resp = requests.get(
            FRED_BASE, params={"id": series_id},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15,
        )
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        data = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    data.append((parts[0].strip(), float(parts[1])))
                except ValueError:
                    pass
        data.sort(key=lambda x: x[0], reverse=True)
        return data[:periods]
    except Exception as e:
        logger.warning("FRED %s failed: %s", series_id, e)
        return []


def fetch_ism_manufacturing() -> EconIndicator | None:
    data = _fred_latest("NAPM", periods=3)
    if not data:
        return None
    d, v = data[0]
    p = data[1][1] if len(data) > 1 else v
    if v >= 55:   sig, note = "green",  f"ISM İmalat {v:.1f} — Güçlü büyüme bölgesi"
    elif v >= 50: sig, note = "amber",  f"ISM İmalat {v:.1f} — Büyüme ama zayıflıyor"
    elif v >= 45: sig, note = "amber",  f"ISM İmalat {v:.1f} — Daralma bölgesi, dikkat"
    else:         sig, note = "red",    f"ISM İmalat {v:.1f} — Belirgin daralma"
    return EconIndicator("ISM_MFG","ISM Manufacturing PMI",v,p,d,sig,note)


def fetch_ism_services() -> EconIndicator | None:
    data = _fred_latest("NMFCI", periods=3) or _fred_latest("NMFSDI", periods=3)
    if not data:
        return None
    d, v = data[0]
    p = data[1][1] if len(data) > 1 else v
    if v >= 55:   sig, note = "green", f"ISM Hizmetler {v:.1f} — Güçlü büyüme"
    elif v >= 50: sig, note = "amber", f"ISM Hizmetler {v:.1f} — Büyüme yavaşlıyor"
    else:         sig, note = "red",   f"ISM Hizmetler {v:.1f} — Daralma"
    return EconIndicator("ISM_SVC","ISM Services PMI",v,p,d,sig,note)


def fetch_cpi() -> dict:
    result = {}
    cpi = _fred_latest("CPIAUCSL", periods=13)
    if cpi and len(cpi) >= 13:
        d, v = cpi[0]; ya = cpi[12][1]
        yoy = (v - ya) / ya * 100
        if yoy >= 4.0:   sig, note = "red",   f"CPI %{yoy:.1f} YoY — Yüksek enflasyon"
        elif yoy >= 2.5: sig, note = "amber", f"CPI %{yoy:.1f} YoY — Hedefin üzerinde"
        else:             sig, note = "green", f"CPI %{yoy:.1f} YoY — Hedefe yakın"
        result["CPI"] = EconIndicator("CPI","CPI (YoY)",round(yoy,2),0,d,sig,note,"%")

    core = _fred_latest("CPILFESL", periods=13)
    if core and len(core) >= 13:
        d, v = core[0]; ya = core[12][1]
        yoy = (v - ya) / ya * 100
        if yoy >= 3.5:   sig, note = "red",   f"Çekirdek CPI %{yoy:.1f} — Yapışkan enflasyon"
        elif yoy >= 2.5: sig, note = "amber", f"Çekirdek CPI %{yoy:.1f} — Yavaş düşüş"
        else:             sig, note = "green", f"Çekirdek CPI %{yoy:.1f} — Kontrol altında"
        result["CORE_CPI"] = EconIndicator("CORE_CPI","Çekirdek CPI (YoY)",round(yoy,2),0,d,sig,note,"%")

    return result


def fetch_pce() -> EconIndicator | None:
    data = _fred_latest("PCEPILFE", periods=13)
    if not data or len(data) < 13:
        return None
    d, v = data[0]; ya = data[12][1]
    yoy = (v - ya) / ya * 100
    if yoy >= 3.0:   sig, note = "red",   f"Çekirdek PCE %{yoy:.1f} — Faiz indirimi uzak"
    elif yoy >= 2.3: sig, note = "amber", f"Çekirdek PCE %{yoy:.1f} — Hedefe yaklaşıyor"
    else:             sig, note = "green", f"Çekirdek PCE %{yoy:.1f} — Fed hedefine ulaştı"
    return EconIndicator("CORE_PCE","Çekirdek PCE (YoY)",round(yoy,2),0,d,sig,note,"%")


def fetch_gdp_growth() -> EconIndicator | None:
    data = _fred_latest("A191RL1Q225SBEA", periods=4)
    if not data:
        return None
    d, v = data[0]; p = data[1][1] if len(data) > 1 else v
    if v >= 3.0:   sig, note = "green", f"GDP %{v:.1f} — Güçlü büyüme"
    elif v >= 1.5: sig, note = "amber", f"GDP %{v:.1f} — Yavaş büyüme"
    elif v >= 0:   sig, note = "amber", f"GDP %{v:.1f} — Durgunluk sınırında"
    else:          sig, note = "red",   f"GDP %{v:.1f} — Negatif büyüme! Resesyon riski"
    return EconIndicator("GDP","GDP Büyümesi (QoQ)",round(v,2),round(p,2),d,sig,note,"%")


def fetch_nfp() -> EconIndicator | None:
    data = _fred_latest("PAYEMS", periods=3)
    if not data or len(data) < 2:
        return None
    d, v = data[0]; p = data[1][1]
    chg = v - p
    if chg >= 250:  sig, note = "green", f"NFP +{chg:.0f}K — Çok güçlü istihdam"
    elif chg >= 150: sig, note = "green", f"NFP +{chg:.0f}K — Güçlü istihdam"
    elif chg >= 75: sig, note = "amber", f"NFP +{chg:.0f}K — Zayıf istihdam"
    else:           sig, note = "red",   f"NFP {chg:.0f}K — İstihdam daralıyor"
    return EconIndicator("NFP","Non-Farm Payrolls",round(chg,0),0,d,sig,note,"K")


def fetch_sp500_valuation() -> dict:
    result = {}
    cape = _fred_latest("CAPE", periods=2)
    if cape:
        _, v = cape[0]
        if v >= 35:   sig, note = "red",   f"Shiller CAPE {v:.1f} — Aşırı değerli"
        elif v >= 25: sig, note = "amber", f"Shiller CAPE {v:.1f} — Değerlemeler yüksek"
        else:          sig, note = "green", f"Shiller CAPE {v:.1f} — Makul değerleme"
        result["CAPE"] = EconIndicator("CAPE","Shiller CAPE",round(v,1),0,cape[0][0],sig,note)

    try:
        fpe = float(yf.Ticker("SPY").info.get("forwardPE") or 0)
        if fpe > 0:
            if fpe >= 22:   sig, note = "red",   f"S&P FPE {fpe:.1f}x — Pahalı"
            elif fpe >= 18: sig, note = "amber", f"S&P FPE {fpe:.1f}x — Biraz pahalı"
            else:            sig, note = "green", f"S&P FPE {fpe:.1f}x — Makul"
            result["SP500_FPE"] = EconIndicator("SP500_FPE","S&P 500 Forward P/E",
                                                round(fpe,1),16.5,"",sig,note)
    except Exception as e:
        logger.debug("SPY FPE failed: %s", e)

    return result


SECTOR_ETFS = {
    "XLK":"Teknoloji","XLF":"Finans","XLE":"Enerji","XLV":"Sağlık",
    "XLI":"Sanayi","XLY":"Tüketim Döngüsel","XLP":"Tüketim Savunmacı","XLU":"Kamu Hizmetleri",
}


def fetch_sector_rotation() -> dict:
    result = {}
    try:
        spy_h = yf.Ticker("SPY").history(period="1mo")["Close"]
        spy_1m = (spy_h.iloc[-1]/spy_h.iloc[0]-1)*100 if len(spy_h)>1 else 0
        spy_1w = (spy_h.iloc[-1]/spy_h.iloc[-5]-1)*100 if len(spy_h)>5 else 0
    except Exception:
        spy_1m = spy_1w = 0

    sectors = []
    for etf, label in SECTOR_ETFS.items():
        try:
            h = yf.Ticker(etf).history(period="1mo")["Close"]
            if len(h) < 2:
                continue
            r1m = (h.iloc[-1]/h.iloc[0]-1)*100
            r1w = (h.iloc[-1]/h.iloc[-5]-1)*100 if len(h)>5 else 0
            sectors.append({"etf":etf,"label":label,
                            "ret_1m":round(r1m,2),"ret_1w":round(r1w,2),
                            "rel_1m":round(r1m-spy_1m,2),"rel_1w":round(r1w-spy_1w,2)})
            time.sleep(0.1)
        except Exception:
            pass

    if sectors:
        sectors.sort(key=lambda x: x["rel_1m"], reverse=True)
        leader = sectors[0]["label"]
        if leader in ["Finans","Sanayi","Tüketim Döngüsel"]:
            note = "Para döngüsel sektörlere akıyor — büyüme beklentisi var"
        elif leader in ["Kamu Hizmetleri","Tüketim Savunmacı","Sağlık"]:
            note = "Para savunmacı sektörlere akıyor — risk-off modu"
        else:
            note = f"{leader} öne çıkıyor"

        result = {"sectors":sectors,"spy_1m":round(spy_1m,2),
                  "spy_1w":round(spy_1w,2),"rotation_note":note,
                  "leader":sectors[0],"laggard":sectors[-1]}

    return result


def fetch_put_call_ratio() -> dict:
    """
    Gerçek Put/Call oranı proxy: SPXU/UPRO oranı (bear/bull ETF)
    veya VIX/VIX3M term structure ile hesaplanır.
    PCR > 1.0 = aşırı korku = contrarian alım sinyali
    PCR < 0.7 = aşırı açgözlülük = dikkat
    """
    try:
        import yfinance as yf
        # SPXU (3x bear S&P) vs UPRO (3x bull S&P) hacim oranı
        spxu_fi = yf.Ticker("SPXU").fast_info
        upro_fi = yf.Ticker("UPRO").fast_info
        spxu_vol = float(getattr(spxu_fi, "three_month_average_volume", 0) or 0)
        upro_vol = float(getattr(upro_fi, "three_month_average_volume", 0) or 0)

        if spxu_vol > 0 and upro_vol > 0:
            pcr_proxy = round(spxu_vol / upro_vol, 2)
            if pcr_proxy >= 0.8:
                sig  = "green"
                note = f"Put/Call Proxy: {pcr_proxy:.2f} — Bear ETF talebi yüksek, contrarian ALIM sinyali"
            elif pcr_proxy >= 0.5:
                sig  = "neutral"
                note = f"Put/Call Proxy: {pcr_proxy:.2f} — Dengeli, belirgin sinyal yok"
            else:
                sig  = "amber"
                note = f"Put/Call Proxy: {pcr_proxy:.2f} — Bull ETF hakimiyeti, aşırı iyimserlik riski"
            return {"value": pcr_proxy, "signal": sig, "note": note}
    except Exception as e:
        logger.debug("Put/Call ratio failed: %s", e)
    return {}


def fetch_vix_term_structure() -> dict:
    """
    VIX term structure: VIX (kısa vade) vs VIX3M (3 ay) vs VIX6M (6 ay).
    Contango (VIX < VIX3M) = normal, piyasa sakin
    Backwardation (VIX > VIX3M) = kısa vadeli panik, piyasa stres altında
    """
    try:
        import yfinance as yf
        vix   = float(yf.Ticker("^VIX").fast_info.last_price or 0)
        vix3m = float(yf.Ticker("^VIX3M").fast_info.last_price or 0)

        if vix <= 0 or vix3m <= 0:
            return {}

        ratio    = round(vix / vix3m, 3)
        spread   = round(vix3m - vix, 2)   # Pozitif = contango (normal)

        if ratio >= 1.15:
            sig  = "red"
            note = (f"VIX Term Structure: {vix:.1f}/{vix3m:.1f} — "
                   f"BACKWARDATION (ratio {ratio:.2f}). Kısa vadeli panik var, piyasa stres altında!")
        elif ratio >= 1.05:
            sig  = "amber"
            note = (f"VIX Term Structure: {vix:.1f}/{vix3m:.1f} — "
                   f"Düzleşme (ratio {ratio:.2f}). Artan kısa vade gerginliği.")
        elif ratio <= 0.85:
            sig  = "green"
            note = (f"VIX Term Structure: {vix:.1f}/{vix3m:.1f} — "
                   f"Derin contango (ratio {ratio:.2f}). Piyasa çok sakin, complacency riski.")
        else:
            sig  = "green"
            note = (f"VIX Term Structure: {vix:.1f}/{vix3m:.1f} — "
                   f"Normal contango (ratio {ratio:.2f}). Sağlıklı yapı.")

        return {
            "vix":    vix,
            "vix3m":  vix3m,
            "ratio":  ratio,
            "spread": spread,
            "signal": sig,
            "note":   note,
        }
    except Exception as e:
        logger.debug("VIX term structure failed: %s", e)
    return {}


def fetch_all_economic_data() -> dict:
    """Tüm Katman 2 ekonomik veriyi topla."""
    logger.info("Ekonomik veri toplanıyor...")
    result = {"macro_econ":{},"valuation":{},"sectors":{},"market_structure":{},"timestamp":datetime.now(timezone.utc).isoformat()}

    for fn, key in [(fetch_ism_manufacturing,"ISM_MFG"),(fetch_ism_services,"ISM_SVC"),
                    (fetch_pce,"CORE_PCE"),(fetch_gdp_growth,"GDP"),(fetch_nfp,"NFP")]:
        r = fn()
        if r: result["macro_econ"][key] = r

    result["macro_econ"].update(fetch_cpi())
    result["valuation"].update(fetch_sp500_valuation())
    result["sectors"] = fetch_sector_rotation()

    # Piyasa yapısı — Put/Call + VIX term structure
    pcr = fetch_put_call_ratio()
    vts = fetch_vix_term_structure()
    if pcr: result["market_structure"]["put_call"] = pcr
    if vts: result["market_structure"]["vix_term"]  = vts

    logger.info("Ekonomik veri: %d gösterge", len(result["macro_econ"]))
    return result


def build_economic_context(econ_data: dict) -> str:
    """Ekonomik veriyi Claude için formatlı string döndür."""
    lines = []

    macro = econ_data.get("macro_econ", {})
    if macro:
        lines.append("=== EKONOMİK GÖSTERGELER (FRED) ===")
        for ind in macro.values():
            if hasattr(ind, "note"):
                u = f" {ind.unit}" if ind.unit else ""
                lines.append(f"  {ind.label}: {ind.value}{u} — {ind.note}")

    val = econ_data.get("valuation", {})
    if val:
        lines.append("\n=== DEĞERLEME ===")
        for ind in val.values():
            if hasattr(ind, "note"):
                lines.append(f"  {ind.label}: {ind.value} — {ind.note}")

    sectors = econ_data.get("sectors", {})
    if sectors.get("sectors"):
        lines.append("\n=== SEKTÖR ROTASYONU (1 Aylık) ===")
        lines.append(f"  {sectors.get('rotation_note','')}")
        for s in sectors["sectors"]:
            t = "↑" if s["rel_1m"] > 0 else "↓"
            lines.append(f"  {t} {s['label']}: {s['ret_1m']:+.1f}% (SPY'a göre {s['rel_1m']:+.1f}%)")

    ms = econ_data.get("market_structure", {})
    if ms:
        lines.append("\n=== PİYASA YAPISI ===")
        pcr = ms.get("put_call", {})
        if pcr.get("note"):
            lines.append(f"  {pcr['note']}")
        vts = ms.get("vix_term", {})
        if vts.get("note"):
            lines.append(f"  {vts['note']}")

    return "\n".join(lines)
