import streamlit as st
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

# ─── Thread-Safe Basit Cache ─────────────────────────────────────────────────
# @st.cache_data background thread'de çalışmaz — bu yüzden manuel TTL cache kullanıyoruz
import threading as _threading
import time as _cache_time

_econ_cache: dict = {}
_econ_cache_lock = _threading.Lock()

def _cached(key: str, ttl: int, fn):
    """Thread-safe basit TTL cache. fn çağrısını sarmalamak için kullanılır."""
    now = _cache_time.time()
    with _econ_cache_lock:
        if key in _econ_cache:
            val, ts = _econ_cache[key]
            if now - ts < ttl:
                return val
    result = fn()
    with _econ_cache_lock:
        _econ_cache[key] = (result, now)
    return result


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


# ─── Adım 1: Buffett Göstergesi ──────────────────────────────────────────────
# Wilshire 5000 Toplam Piyasa Değeri / ABD GSYİH
# FRED serileri: WILL5000IND (Wilshire 5000) + GDP (çeyreklik)
# Tarihsel referanslar: Ort ~%100, 2000 zirvesi %148, 2007 zirvesi %105, bugün ~%190-230

def fetch_buffett_indicator() -> dict:
    """
    Buffett Göstergesi = Toplam Piyasa Değeri / GSYİH
    FRED'den Wilshire 5000 (günlük) ve GDP (çeyreklik) çeker.
    
    Yorumlama eşikleri tarihsel kriz dönemleriyle kalibre edilmiştir:
    < %100 → Ucuz (tarihsel ortalama)
    %100-150 → Adil değer aralığı
    %150-200 → Pahalı
    > %200 → Aşırı pahalı (1929/2000 benzeri bölge)
    """
    try:
        # Wilshire 5000 Toplam Piyasa Değeri (milyar dolar)
        r_will = requests.get(f"{FRED_BASE}?id=WILL5000IND", timeout=10)
        # GDP (milyar dolar, çeyreklik)
        r_gdp  = requests.get(f"{FRED_BASE}?id=GDP", timeout=10)

        if r_will.status_code != 200 or r_gdp.status_code != 200:
            raise ValueError("FRED erişim hatası")

        # CSV parse — son satır en güncel veri
        def parse_fred_csv(text):
            lines = [l for l in text.strip().splitlines() if l and not l.startswith('DATE')]
            if not lines:
                return None, None
            last = lines[-1].split(',')
            return last[0], float(last[1]) if last[1] != '.' else None

        will_date, will_val = parse_fred_csv(r_will.text)
        gdp_date,  gdp_val  = parse_fred_csv(r_gdp.text)

        if not will_val or not gdp_val:
            raise ValueError("Veri boş")

        # Buffett Göstergesi = (Piyasa Değeri / Yıllıklaştırılmış GDP) * 100
        # GDP çeyreklik → yıllıklaştır (×4 zaten annualized olarak geliyor FRED'den)
        ratio = (will_val / gdp_val) * 100

        # Sinyal
        if ratio < 100:
            signal, note = "green", f"Tarihi ortalamanın altında — piyasa ucuz bölgede"
        elif ratio < 150:
            signal, note = "neutral", f"Adil değer aralığı — dikkatli seçicilik"
        elif ratio < 200:
            signal, note = "amber", f"Pahalı bölge — 2000 dotcom zirvesinin ({148:.0f}%) üzerinde"
        else:
            signal, note = "red", (
                f"AŞIRI PAHALI — 2000 zirvesi %148, 2007 zirvesi %105. "
                f"Bu seviye tarihte sadece 1929 öncesinde görüldü."
            )

        return {
            "ratio":       round(ratio, 1),
            "wilshire":    round(will_val, 0),
            "gdp":         round(gdp_val, 0),
            "will_date":   will_date,
            "gdp_date":    gdp_date,
            "signal":      signal,
            "note":        note,
            # Tarihsel karşılaştırma için referans noktalar
            "historical": {
                "avg":       100,
                "dot2000":   148,
                "gfc2007":   105,
                "current":   round(ratio, 1),
            }
        }
    except Exception as e:
        logger.warning("Buffett göstergesi alınamadı: %s", e)
        return {}


# ─── Adım 2: Konut Piyasası Verileri ─────────────────────────────────────────
# Yeni Konut Satışları + Mevcut Konut Satışları + MBA Mortgage Başvuruları + Konut Fiyat Endeksi
# FRED serileri: HSN1F (yeni konut), EXSFHSUSQ176S (mevcut konut), CSUSHPISA (Case-Shiller)

def fetch_housing_data() -> dict:
    """
    Konut piyasası bileşik göstergesi.
    
    Yeni Konut Satışları özellikle önemli çünkü:
    1. İleri gösterge — mevcut konut satışlarından 1-3 ay önce hareket eder
    2. Mortgage faiz duyarlılığı yüksek — faiz değişimlerini hızla yansıtır
    3. Üretim zinciri etkisi — mobilya, boya, elektrikli alet talebiyle bağlantılı
    
    587K (Ocak 2026 gerçekleşme) vs 722K beklenti = %18.7 olumsuz sürpriz
    Bu büyüklükte bir sapma piyasada ciddi sinyal.
    """
    result = {}

    # 1. Yeni Konut Satışları (bin adet, aylık yıllıklaştırılmış oran)
    try:
        r = requests.get(f"{FRED_BASE}?id=HSN1F", timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().splitlines()
                     if l and not l.startswith('DATE')]
            # Son 3 veriyi al — trend görmek için
            recent = []
            for line in lines[-3:]:
                parts = line.split(',')
                if len(parts) == 2 and parts[1] != '.':
                    recent.append((parts[0], float(parts[1])))

            if recent:
                cur_date, cur_val = recent[-1]
                prev_val = recent[-2][1] if len(recent) >= 2 else cur_val
                yoy_val  = recent[0][1]  if len(recent) >= 3 else cur_val

                chg_mom = (cur_val - prev_val) / prev_val * 100 if prev_val else 0
                chg_yoy = (cur_val - yoy_val)  / yoy_val  * 100 if yoy_val  else 0

                # 587K vs 722K beklenti örneği — %18.7 hayal kırıklığı
                # Sinyal: 700K+ güçlü, 600-700K nötr, <600K zayıf
                if cur_val >= 700:
                    sig, notu = "green",   "Güçlü konut talebi — faiz baskısı yok"
                elif cur_val >= 600:
                    sig, notu = "neutral", "Orta düzey talep — faiz baskısı hissediliyor"
                elif cur_val >= 500:
                    sig, notu = "amber",   "Zayıf talep — yüksek faiz alımları engelliyor"
                else:
                    sig, notu = "red",     "Konut piyasası donuyor — 2008 benzeri baskı"

                result["yeni_konut"] = EconIndicator(
                    key="YENI_KONUT", label="Yeni Konut Satışları (Yıllık K)",
                    value=round(cur_val, 0), prev=round(prev_val, 0),
                    date=cur_date, signal=sig,
                    note=f"{notu} | Aylık: {chg_mom:+.1f}% | Yıllık: {chg_yoy:+.1f}%"
                )
    except Exception as e:
        logger.warning("Yeni konut satışları alınamadı: %s", e)

    # 2. Mevcut Konut Satışları (milyon adet)
    try:
        r = requests.get(f"{FRED_BASE}?id=EXSFHSUSQ176S", timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().splitlines()
                     if l and not l.startswith('DATE')]
            recent = [(l.split(',')[0], float(l.split(',')[1]))
                      for l in lines[-2:] if l.split(',')[1] != '.']
            if recent:
                cur_date, cur_val = recent[-1]
                prev_val = recent[0][1] if len(recent) >= 2 else cur_val
                chg = (cur_val - prev_val) / prev_val * 100 if prev_val else 0

                sig = "green" if cur_val > 4.5 else ("amber" if cur_val > 3.5 else "red")
                result["mevcut_konut"] = EconIndicator(
                    key="MEVCUT_KONUT", label="Mevcut Konut Satışları (M)",
                    value=round(cur_val, 2), prev=round(prev_val, 2),
                    date=cur_date, signal=sig,
                    note=f"Aylık değişim: {chg:+.1f}% | {'Güçlü' if sig=='green' else 'Zayıf'} talep"
                )
    except Exception as e:
        logger.warning("Mevcut konut satışları alınamadı: %s", e)

    # 3. Case-Shiller Konut Fiyat Endeksi (20 şehir)
    try:
        r = requests.get(f"{FRED_BASE}?id=SPCS20RSA", timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().splitlines()
                     if l and not l.startswith('DATE')]
            recent = [(l.split(',')[0], float(l.split(',')[1]))
                      for l in lines[-13:] if len(l.split(',')) == 2 and l.split(',')[1] != '.']
            if len(recent) >= 2:
                cur_date, cur_val = recent[-1]
                yoy_val  = recent[0][1]
                chg_yoy  = (cur_val - yoy_val) / yoy_val * 100

                sig = "green" if chg_yoy > 5 else ("neutral" if chg_yoy > 0 else "amber")
                result["konut_fiyat"] = EconIndicator(
                    key="KONUT_FIYAT", label="Case-Shiller Konut Fiyat Endeksi",
                    value=round(cur_val, 1), prev=round(yoy_val, 1),
                    date=cur_date, signal=sig,
                    note=f"Yıllık değişim: {chg_yoy:+.1f}% | {'Yükseliş sürüyor' if chg_yoy > 0 else 'Fiyatlar düşüyor'}"
                )
    except Exception as e:
        logger.warning("Konut fiyat endeksi alınamadı: %s", e)

    # 4. 30 Yıllık Mortgage Faizi (Freddie Mac verisi — FRED'den)
    try:
        r = requests.get(f"{FRED_BASE}?id=MORTGAGE30US", timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().splitlines()
                     if l and not l.startswith('DATE')]
            recent = [(l.split(',')[0], float(l.split(',')[1]))
                      for l in lines[-5:] if len(l.split(',')) == 2 and l.split(',')[1] != '.']
            if recent:
                cur_date, cur_val = recent[-1]
                prev_val = recent[0][1] if len(recent) >= 2 else cur_val
                chg = cur_val - prev_val

                # 7%+ konut piyasasını donduruyor
                sig = "green" if cur_val < 5.5 else ("amber" if cur_val < 7 else "red")
                result["mortgage_faiz"] = EconIndicator(
                    key="MORTGAGE30", label="30Y Mortgage Faizi (%)",
                    value=round(cur_val, 2), prev=round(prev_val, 2),
                    date=cur_date, signal=sig,
                    note=(
                        f"{'Konut piyasasını donduruyor' if cur_val >= 7 else 'Baskılı ama sürdürülebilir'} "
                        f"| 4 haftalık değişim: {chg:+.2f}pp"
                    )
                )
    except Exception as e:
        logger.warning("Mortgage faizi alınamadı: %s", e)

    return result


# ─── Adım 3: Bölgesel Banka + Ticari GYO Stres ───────────────────────────────

def fetch_financial_stress_indicators() -> dict:
    """
    Bölgesel bankacılık sistemi ve ticari gayrimenkul stres göstergeleri.
    
    Neden önemli: 
    - Ticari GYO kredilerinin %70'i bölgesel bankalardan
    - $1.5T ofis/ticari GYO kredisi 2025-2027 vadeye geliyor
    - Ofis boşluk oranı %25+ büyük şehirlerde (COVID kalıcı uzaktan çalışma etkisi)
    - KRE ETF: Bölgesel bankaların sağlığı için gerçek zamanlı barometri
    """
    result = {}

    tickers_config = {
        # Bölgesel Bankalar
        "KRE":   ("Bölgesel Bankalar ETF (KRE)",  "Bölgesel banka stres barometresi — düşüş = CRE kredi baskısı"),
        "KBE":   ("Bankacılık Sektörü ETF (KBE)",  "Geniş bankacılık sektörü — KRE'den ayrışma önemli sinyal"),
        # Ticari Gayrimenkul
        "VNQ":   ("Ticari GYO ETF (VNQ)",           "Ticari gayrimenkul değeri — ofis/perakende ağırlıklı"),
        "CMBS":  ("CMBS ETF (CMBS)",                "Ticari mortgage menkul kıymetleri — spread proxy"),
        # Referans
        "XLF":   ("Finansal Sektör ETF (XLF)",      "Büyük banka referansı — KRE/XLF oranı kritik"),
    }

    import yfinance as yf_fs
    for ticker, (label, note) in tickers_config.items():
        try:
            fi = yf_fs.Ticker(ticker).fast_info
            price   = float(getattr(fi, "last_price",      0) or 0)
            prev    = float(getattr(fi, "previous_close",  price) or price)
            w52h    = float(getattr(fi, "year_high",        price) or price)
            chg_pct = (price - prev) / prev * 100 if prev > 0 else 0
            dd_pct  = (price - w52h) / w52h * 100 if w52h > 0 else 0  # 52 hafta zirvesinden drawdown

            # Bölgesel bankalar için: 52H zirvesinden %20+ düşüş stres sinyali
            if ticker in ("KRE", "KBE"):
                if dd_pct < -30:
                    sig = "red"
                elif dd_pct < -15:
                    sig = "amber"
                else:
                    sig = "green"
            else:
                sig = "green" if chg_pct > 0 else ("amber" if chg_pct > -2 else "red")

            if price > 0:
                result[ticker] = EconIndicator(
                    key=ticker, label=label,
                    value=round(price, 2), prev=round(prev, 2),
                    date="güncel", signal=sig,
                    note=f"{note} | Günlük: {chg_pct:+.1f}% | 52H zirvesinden: {dd_pct:+.1f}%"
                )
        except Exception as e:
            logger.debug("Finansal stres verisi alınamadı [%s]: %s", ticker, e)

    # KRE/XLF Oranı — bölgesel banka ile büyük banka performansı ayrışması
    if "KRE" in result and "XLF" in result:
        kre_v = result["KRE"].value
        xlf_v = result["XLF"].value
        # Normalize edilmiş oran — eğer KRE/XLF oranı düşüyorsa bölgesel bankalar stres altında
        ratio = kre_v / xlf_v if xlf_v > 0 else 0
        result["KRE_XLF_RATIO"] = EconIndicator(
            key="KRE_XLF_RATIO",
            label="Bölgesel/Büyük Banka Oranı (KRE/XLF)",
            value=round(ratio, 3), prev=round(ratio, 3),
            date="güncel",
            signal="amber" if ratio < 1.5 else "green",
            note=(
                "Oran düşüyorsa bölgesel bankalar büyük bankalardan kötü performans gösteriyor "
                "— CRE stresinin sisteme yayıldığı sinyal"
            )
        )

    return result


# ─── Adım 4: Teminat Borcu Proxy ─────────────────────────────────────────────
# FINRA aylık açıklıyor (gecikme var), yfinance'ten yaklaşık proxy

def fetch_margin_debt_proxy() -> dict:
    """
    Teminat Borcu (Margin Debt) yaklaşık göstergesi.
    
    FINRA resmi verisi aylık ve 6 hafta gecikmeli gelir.
    Proxy yöntemi: Spekülatif ETF'lerin relatif güçünü kullanır.
    
    Tarihsel tehlike seviyeleri:
    1929 öncesi: Teminat borcu / GSYİH = %12
    2000 öncesi: %2.7 (tarihsel zirve o dönem için)
    2007 öncesi: %2.5
    2024-2026: ~%3.0 (yaklaşık FRED MARGIN verisi)
    
    Senaryo yorumu belgenin çok isabetli tespitiyle örtüşüyor:
    Bu oran yüksek olduğunda kaldıraç çözülmesi sarmalı çok hızlı gerçekleşir.
    """
    result = {}

    try:
        # FRED'den margin debt verisi (BOGMBASE yaklaşık proxy)
        # Resmi seri: MARGDEBT (FINRA verisinden türetilmiş)
        r = requests.get(f"{FRED_BASE}?id=BOGMBASE", timeout=10)
        if r.status_code == 200:
            lines = [l for l in r.text.strip().splitlines()
                     if l and not l.startswith('DATE')]
            if lines:
                last = lines[-1].split(',')
                if last[1] != '.':
                    base_val = float(last[1])
                    result["monetary_base"] = {
                        "value": round(base_val, 0),
                        "date":  last[0],
                        "note":  "Fed parasal baz (milyar dolar) — yüksekse likiditeli ortam"
                    }
    except Exception as e:
        logger.debug("Parasal baz alınamadı: %s", e)

    # Spekülatif aktivite proxy: Yüksek beta hisseler / Düşük beta oranı
    # TQQQ (3x NASDAQ) / QQQ oranının yüksekliği spekülatif iştahı gösterir
    try:
        import yfinance as yf_md
        tqqq_fi = yf_md.Ticker("TQQQ").fast_info
        qqq_fi  = yf_md.Ticker("QQQ").fast_info

        tqqq_p = float(getattr(tqqq_fi, "last_price", 0) or 0)
        qqq_p  = float(getattr(qqq_fi,  "last_price", 0) or 0)

        tqqq_h52 = float(getattr(tqqq_fi, "year_high", tqqq_p) or tqqq_p)
        tqqq_l52 = float(getattr(tqqq_fi, "year_low",  tqqq_p) or tqqq_p)

        # 52H aralığındaki pozisyon — spekülatif aktivite göstergesi
        if tqqq_h52 > tqqq_l52:
            spec_position = (tqqq_p - tqqq_l52) / (tqqq_h52 - tqqq_l52) * 100
        else:
            spec_position = 50

        if spec_position > 80:
            sig  = "red"
            notu = "Spekülatif aktivite zirveye yakın — kaldıraç fazla birikmiş olabilir"
        elif spec_position > 60:
            sig  = "amber"
            notu = "Orta-yüksek spekülatif aktivite — dikkatli izle"
        else:
            sig  = "green"
            notu = "Spekülatif aktivite makul seviyede"

        result["spec_activity"] = EconIndicator(
            key="SPEC_ACTIVITY",
            label="Spekülatif Aktivite Proxy (TQQQ Pozisyon %)",
            value=round(spec_position, 1), prev=50.0,
            date="güncel", signal=sig, note=notu
        )
    except Exception as e:
        logger.debug("Spekülatif aktivite proxy alınamadı: %s", e)

    return result



def fetch_all_economic_data() -> dict:
    """
    Tüm Katman 2 ekonomik veriyi topla.
    Yeni eklenenler: Buffett Göstergesi, Konut Piyasası, Bölgesel Banka/CRE Stres,
                     Teminat Borcu Proxy
    """
    logger.info("Ekonomik veri toplanıyor (genişletilmiş Katman 2)...")
    result = {
        "macro_econ":      {},
        "valuation":       {},
        "sectors":         {},
        "market_structure":{},
        "housing":         {},
        "financial_stress":{},
        "systemic_risk":   {},
        "timestamp":       datetime.now(timezone.utc).isoformat()
    }

    # Mevcut temel göstergeler
    for fn, key in [(fetch_ism_manufacturing,"ISM_MFG"),(fetch_ism_services,"ISM_SVC"),
                    (fetch_pce,"CORE_PCE"),(fetch_gdp_growth,"GDP"),(fetch_nfp,"NFP")]:
        r = fn()
        if r: result["macro_econ"][key] = r

    result["macro_econ"].update(fetch_cpi())
    result["valuation"].update(fetch_sp500_valuation())
    result["sectors"] = fetch_sector_rotation()

    # Piyasa yapısı
    pcr = fetch_put_call_ratio()
    vts = fetch_vix_term_structure()
    if pcr: result["market_structure"]["put_call"] = pcr
    if vts: result["market_structure"]["vix_term"]  = vts

    # ── YENİ: Buffett Göstergesi ─────────────────────────────────────────
    try:
        _buffett = fetch_buffett_indicator()
        if _buffett:
            result["valuation"]["buffett"] = _buffett
            result["systemic_risk"]["buffett"] = _buffett
            logger.info("Buffett göstergesi: %.1f", _buffett.get("ratio", 0))
    except Exception as e:
        logger.warning("Buffett göstergesi alınamadı: %s", e)

    # ── YENİ: Konut Piyasası ─────────────────────────────────────────────
    try:
        _housing = fetch_housing_data()
        result["housing"].update(_housing)
        result["macro_econ"].update(_housing)
        logger.info("Konut verisi: %d gösterge", len(_housing))
    except Exception as e:
        logger.warning("Konut verisi alınamadı: %s", e)

    # ── YENİ: Bölgesel Banka + CRE Stres ─────────────────────────────────
    try:
        _stress = fetch_financial_stress_indicators()
        result["financial_stress"].update(_stress)
        logger.info("Finansal stres: %d gösterge", len(_stress))
    except Exception as e:
        logger.warning("Finansal stres alınamadı: %s", e)

    # ── YENİ: Teminat Borcu Proxy ─────────────────────────────────────────
    try:
        _margin = fetch_margin_debt_proxy()
        result["systemic_risk"].update(_margin)
        if "spec_activity" in _margin:
            result["macro_econ"]["SPEC_ACTIVITY"] = _margin["spec_activity"]
    except Exception as e:
        logger.warning("Teminat borcu proxy alınamadı: %s", e)

    logger.info("Katman 2 tamamlandı: %d temel + %d konut + %d stres gösterge",
                len(result["macro_econ"]), len(result["housing"]),
                len(result["financial_stress"]))
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
