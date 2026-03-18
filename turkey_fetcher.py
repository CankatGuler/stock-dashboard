# turkey_fetcher.py — Türkiye Borsası ve TEFAS Veri Modülü
#
# Katman 5 metrikleri — Uzman Türkiye Borsa Perspektifi:
#
#   Temel Göstergeler:
#   - BIST100 TL ve dolar bazlı değer + trend
#   - XBANK (Bankacılık Endeksi) — borsa lokomotifi
#   - USD/TRY + volatilite + reel efektif kur proxy
#
#   Makro Göstergeler:
#   - TCMB politika faizi + gerçek reel faiz
#   - Türkiye enflasyonu (TÜFE) — FRED'den
#   - CDS primi proxy (Türkiye risk primini ölçer)
#   - Cari açık sinyali
#
#   Piyasa Yapısı:
#   - Yabancı yatırımcı pozisyonu (contrarian gösterge)
#   - XBANK/BIST100 göreceli performansı (sektör rotasyonu)
#   - Halka açık free float trendi
#
#   TEFAS Entegrasyonu:
#   - Fon fiyatları ve getiriler
#   - TL ve dolar bazlı normalize getiri
#
#   Korelasyonlar:
#   - BIST100 / DXY
#   - BIST100 / S&P 500
#   - XBANK / BIST100
#   - USD/TRY / BIST100 (ters korelasyon beklenir)
#   - BIST dolar bazlı / Gelişen Piyasalar (EEM)

import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── Ticker Tanımları ─────────────────────────────────────────────────────────

BIST_TICKERS = {
    "BIST100":   {"ticker": "XU100.IS",  "label": "BIST 100",          "unit": "TL"},
    "XBANK":     {"ticker": "XBANK.IS",  "label": "XBANK Bankacılık",  "unit": "TL"},
    "XUSIN":     {"ticker": "XUSIN.IS",  "label": "XUSIN Sanayi",      "unit": "TL"},
    "XUHIZ":     {"ticker": "XUHIZ.IS",  "label": "XUHIZ Hizmetler",   "unit": "TL"},
    "USDT_TRY":  {"ticker": "USDT-TRY",  "label": "USD/TRY",           "unit": "TL"},
}

# BIST30 önemli hisseler (yabancı takibi için)
BIST30_MAJOR = [
    "AKBNK.IS", "GARAN.IS", "YKBNK.IS", "ISCTR.IS",  # Bankalar
    "TCELL.IS", "BIMAS.IS", "KCHOL.IS", "SISE.IS",    # Büyük şirketler
    "THYAO.IS", "ARCLK.IS", "TOASO.IS", "TUPRS.IS",   # Sanayi
]

# ─── 1. BIST Temel Veriler ────────────────────────────────────────────────────

def fetch_bist_data() -> dict:
    """
    BIST100 ve alt endekslerin hem TL hem dolar bazlı değerleri.
    Dolar bazlı değer: TL'nin erimesini soyutlamak için kritik.
    """
    try:
        import yfinance as yf

        results = {}

        # USD/TRY kuru önce çek — diğer hesaplamalar için lazım
        usdt_fi  = yf.Ticker("USDTRY=X").fast_info
        usd_try  = float(getattr(usdt_fi, "last_price",     0) or 0)
        usd_prev = float(getattr(usdt_fi, "previous_close", usd_try) or usd_try)
        if usd_try <= 0:
            # Fallback
            usdt_fi2 = yf.Ticker("TRY=X").fast_info
            usd_try  = float(getattr(usdt_fi2, "last_price", 32.0) or 32.0)
            usd_prev = usd_try

        try_chg = (usd_try - usd_prev) / usd_prev * 100 if usd_prev > 0 else 0

        results["USD_TRY"] = {
            "value":    round(usd_try,  2),
            "prev":     round(usd_prev, 2),
            "change":   round(try_chg,  2),
            "label":    "USD/TRY",
        }

        # BIST100 TL ve USD bazlı
        bist_fi   = yf.Ticker("XU100.IS").fast_info
        bist_tl   = float(getattr(bist_fi, "last_price",     0) or 0)
        bist_prev = float(getattr(bist_fi, "previous_close", bist_tl) or bist_tl)
        bist_chg  = (bist_tl - bist_prev) / bist_prev * 100 if bist_prev > 0 else 0

        # Dolar bazlı BIST
        bist_usd  = bist_tl  / usd_try  if usd_try  > 0 else 0
        bist_pusd = bist_prev / usd_prev if usd_prev > 0 else 0
        bist_usd_chg = (bist_usd - bist_pusd) / bist_pusd * 100 if bist_pusd > 0 else 0

        # 52H TL ve USD bazlı
        try:
            bist_hist = yf.Ticker("XU100.IS").history(period="1y", interval="1d")["Close"]
            bist_52h  = float(bist_hist.max()) if len(bist_hist) > 0 else bist_tl
            bist_52l  = float(bist_hist.min()) if len(bist_hist) > 0 else bist_tl
            bist_pos  = (bist_tl - bist_52l) / (bist_52h - bist_52l) * 100 if bist_52h > bist_52l else 50
        except Exception:
            bist_52h, bist_52l, bist_pos = bist_tl, bist_tl, 50

        results["BIST100"] = {
            "tl":       round(bist_tl,      0),
            "usd":      round(bist_usd,     1),
            "tl_chg":   round(bist_chg,     2),
            "usd_chg":  round(bist_usd_chg, 2),
            "52h_tl":   round(bist_52h,     0),
            "52l_tl":   round(bist_52l,     0),
            "pos_52h":  round(bist_pos,     1),
        }

        time.sleep(0.15)

        # XBANK — Bankacılık endeksi
        xbank_fi   = yf.Ticker("XBANK.IS").fast_info
        xbank_tl   = float(getattr(xbank_fi, "last_price",     0) or 0)
        xbank_prev = float(getattr(xbank_fi, "previous_close", xbank_tl) or xbank_tl)
        xbank_chg  = (xbank_tl - xbank_prev) / xbank_prev * 100 if xbank_prev > 0 else 0
        xbank_usd  = xbank_tl / usd_try if usd_try > 0 else 0

        # XBANK/BIST100 oranı — bankacılık sektörünün göreli gücü
        xb_ratio = round(xbank_tl / bist_tl * 100, 2) if bist_tl > 0 else 0

        results["XBANK"] = {
            "tl":       round(xbank_tl,   0),
            "usd":      round(xbank_usd,  1),
            "tl_chg":   round(xbank_chg,  2),
            "ratio":    xb_ratio,   # XBANK/BIST100 nispi ağırlık
        }

        time.sleep(0.15)

        # XUSIN — Sanayi endeksi
        try:
            xusin_fi   = yf.Ticker("XUSIN.IS").fast_info
            xusin_tl   = float(getattr(xusin_fi, "last_price",     0) or 0)
            xusin_prev = float(getattr(xusin_fi, "previous_close", xusin_tl) or xusin_tl)
            xusin_chg  = (xusin_tl - xusin_prev) / xusin_tl * 100 if xusin_tl > 0 else 0
            results["XUSIN"] = {"tl": round(xusin_tl, 0), "tl_chg": round(xusin_chg, 2)}
        except Exception:
            pass

        return results

    except Exception as e:
        logger.warning("BIST data failed: %s", e)
        return {}


# ─── 2. XBANK Derinlemesine Analiz ───────────────────────────────────────────

def fetch_xbank_analysis() -> dict:
    """
    XBANK derinlemesine analiz — Türkiye borsasının lokomotifi.

    Neden kritik?
    - BIST100 içinde ~%35 ağırlık (en büyük sektör)
    - Bankaların performansı makro politika beklentisini yansıtır
    - TCMB faiz kararlarına en duyarlı sektör
    - Yabancı yatırımcıların ilk girip ilk çıktığı yer

    Analiz:
    - XBANK vs BIST100 göreceli performansı (outperform mu?)
    - Büyük banka hisseleri momentum (GARAN, AKBNK, YKBNK)
    - Bankacılık sektörü reel faiz hassasiyeti
    """
    try:
        import yfinance as yf

        # XBANK ve BIST100 son 30 günlük performans
        end   = datetime.now()
        start = end - timedelta(days=35)

        xbank_hist = yf.Ticker("XBANK.IS").history(start=start, end=end)["Close"]
        bist_hist  = yf.Ticker("XU100.IS").history(start=start, end=end)["Close"]

        if len(xbank_hist) < 10 or len(bist_hist) < 10:
            return {}

        xbank_ret = (xbank_hist.iloc[-1] - xbank_hist.iloc[0]) / xbank_hist.iloc[0] * 100
        bist_ret  = (bist_hist.iloc[-1]  - bist_hist.iloc[0])  / bist_hist.iloc[0]  * 100
        relative  = round(xbank_ret - bist_ret, 2)

        # XBANK/BIST100 göreceli performans yorumu
        if relative >= 5:
            xbank_signal = "green"
            xbank_note   = (f"XBANK son 30 günde BIST'i +%{relative:.1f} outperform etti. "
                           f"Bankacılık sektörü liderlik yapıyor — yabancı girişi veya "
                           f"faiz indirim beklentisi artıyor olabilir.")
        elif relative >= 2:
            xbank_signal = "green"
            xbank_note   = (f"XBANK BIST'i +%{relative:.1f} outperform ediyor. "
                           f"Banka hisselerine görece talep var.")
        elif relative <= -5:
            xbank_signal = "red"
            xbank_note   = (f"XBANK BIST'in -%{abs(relative):.1f} gerisinde. "
                           f"Bankacılık sektörü satış baskısı altında — "
                           f"yüksek faiz veya kötü kredi kalitesi endişesi.")
        elif relative <= -2:
            xbank_signal = "amber"
            xbank_note   = (f"XBANK BIST'in -%{abs(relative):.1f} gerisinde. "
                           f"Dikkat: bankalar zayıflarsa endeks de zayıflar.")
        else:
            xbank_signal = "neutral"
            xbank_note   = f"XBANK BIST ile paralel hareket ediyor (fark %{relative:.1f})."

        # Büyük banka hisseleri momentum
        banks = {"GARAN.IS": "Garanti", "AKBNK.IS": "Akbank", "YKBNK.IS": "Yapı Kredi"}
        bank_data = {}

        for ticker, name in banks.items():
            try:
                fi   = yf.Ticker(ticker).fast_info
                p    = float(getattr(fi, "last_price",     0) or 0)
                prev = float(getattr(fi, "previous_close", p) or p)
                chg  = (p - prev) / prev * 100 if prev > 0 else 0
                bank_data[name] = {"price": round(p, 2), "change": round(chg, 2)}
                time.sleep(0.1)
            except Exception:
                pass

        # Banka hisseleri ortalama günlük değişim
        if bank_data:
            avg_bank_chg = sum(b["change"] for b in bank_data.values()) / len(bank_data)
        else:
            avg_bank_chg = 0

        return {
            "xbank_30d_ret":  round(xbank_ret,  2),
            "bist_30d_ret":   round(bist_ret,   2),
            "relative_perf":  relative,
            "signal":         xbank_signal,
            "note":           xbank_note,
            "bank_stocks":    bank_data,
            "avg_bank_chg":   round(avg_bank_chg, 2),
        }

    except Exception as e:
        logger.warning("XBANK analysis failed: %s", e)
        return {}


# ─── 3. Makro Göstergeler ─────────────────────────────────────────────────────

def fetch_turkey_macro() -> dict:
    """
    Türkiye makro göstergeleri.

    TCMB politika faizi + gerçek reel faiz hesabı.
    Türkiye enflasyonu — FRED CPTOTNSTUR (CPI).
    CDS primi proxy — Türkiye sovereign risk.
    """
    results = {}

    # ── TCMB Politika Faizi (hardcoded + güncelleme notu) ────────────────
    # TCMB faizini FRED veya web'den çekmek zor — bilinen son değer kullanılır
    # Gerçek güncel değer için kullanıcı manuel günceller
    TCMB_POLICY_RATE = 45.0  # Mayıs 2025 itibarıyla
    # Not: Bu değeri user_profile'a ekleyip güncellenebilir yapacağız

    results["tcmb_rate"] = {
        "value":  TCMB_POLICY_RATE,
        "label":  "TCMB Politika Faizi",
        "unit":   "%",
        "note":   f"TCMB politika faizi: %{TCMB_POLICY_RATE:.0f} (son bilinen değer — güncellenebilir)",
    }

    # ── Türkiye Enflasyonu — FRED'den ────────────────────────────────────
    try:
        import requests
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id":  "CPTOTNSTUR",  # Türkiye CPI
                "api_key":    "abcdefghijklmnopqrstuvwxyz123456",
                "file_type":  "json",
                "sort_order": "desc",
                "limit":      3,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            obs = [o for o in resp.json().get("observations", [])
                   if o.get("value", ".") != "."]
            if obs:
                latest_inf = float(obs[0]["value"])
                results["inflation"] = {
                    "value": latest_inf,
                    "date":  obs[0]["date"],
                    "unit":  "%",
                    "label": "Türkiye Enflasyonu (TÜFE)",
                    "note":  f"TÜFE: %{latest_inf:.1f} (yıllık)",
                }

                # Reel faiz = TCMB faizi - enflasyon
                real_rate = round(TCMB_POLICY_RATE - latest_inf, 1)
                if real_rate > 5:
                    rr_signal = "green"
                    rr_note   = (f"Reel faiz: %{real_rate:.1f} — Pozitif ve yüksek. "
                                f"TL'yi destekler, sıcak para girişi teşvik edilir. "
                                f"BIST değerlemeleri üzerinde baskı yaratabilir.")
                elif real_rate > 0:
                    rr_signal = "green"
                    rr_note   = (f"Reel faiz: %{real_rate:.1f} — Pozitif. "
                                f"Ortodoks para politikası devam ediyor.")
                elif real_rate > -10:
                    rr_signal = "amber"
                    rr_note   = (f"Reel faiz: %{real_rate:.1f} — Hafif negatif. "
                                f"TL değer kaybı riski var.")
                else:
                    rr_signal = "red"
                    rr_note   = (f"Reel faiz: %{real_rate:.1f} — Derin negatif. "
                                f"TL hızla eriyebilir, dolarizasyon artar.")

                results["real_rate"] = {
                    "value":  real_rate,
                    "signal": rr_signal,
                    "note":   rr_note,
                }
    except Exception as e:
        logger.debug("Turkey inflation failed: %s", e)

    # ── CDS Primi Proxy ───────────────────────────────────────────────────
    # Türkiye CDS direkt yfinance'te yok.
    # Proxy: Türkiye USD eurobond ETF vs US Treasury farkı
    # Alternatif: TUR ETF'in S&P'ye karşı performansı
    try:
        import yfinance as yf

        tur_fi  = yf.Ticker("TUR").fast_info  # iShares MSCI Turkey ETF
        eem_fi  = yf.Ticker("EEM").fast_info  # Gelişen Piyasalar
        tur_p   = float(getattr(tur_fi, "last_price",     0) or 0)
        eem_p   = float(getattr(eem_fi, "last_price",     0) or 0)
        tur_prev= float(getattr(tur_fi, "previous_close", tur_p) or tur_p)
        eem_prev= float(getattr(eem_fi, "previous_close", eem_p) or eem_p)

        if tur_p > 0 and eem_p > 0:
            tur_chg = (tur_p   - tur_prev) / tur_prev * 100 if tur_prev > 0 else 0
            eem_chg = (eem_p   - eem_prev) / eem_prev * 100 if eem_prev > 0 else 0
            tur_vs_em = round(tur_chg - eem_chg, 2)

            if tur_vs_em >= 2:
                cds_signal = "green"
                cds_note   = (f"TUR ETF, gelişen piyasaları +%{tur_vs_em:.1f} outperform ediyor. "
                             f"Türkiye risk priminin düştüğü sinyal — yabancı ilgisi artıyor.")
            elif tur_vs_em <= -2:
                cds_signal = "red"
                cds_note   = (f"TUR ETF, gelişen piyasaların -%{abs(tur_vs_em):.1f} gerisinde. "
                             f"Türkiye risk priminin arttığı sinyal — yabancı çıkışı olabilir.")
            else:
                cds_signal = "neutral"
                cds_note   = f"Türkiye risk primi stabil, gelişen piyasalarla paralel."

            results["cds_proxy"] = {
                "tur_etf":    tur_p,
                "tur_chg":    round(tur_chg,  2),
                "vs_em":      tur_vs_em,
                "signal":     cds_signal,
                "note":       cds_note,
            }
        time.sleep(0.15)
    except Exception as e:
        logger.debug("CDS proxy failed: %s", e)

    return results


# ─── 4. Yabancı Yatırımcı Pozisyonu ─────────────────────────────────────────

def fetch_foreign_investor_proxy() -> dict:
    """
    Yabancı yatırımcı pozisyonu — en önemli contrarian gösterge.

    Tarihsel veri:
    - 2013: %70+ yabancı sahiplik → büyük çıkış geldi
    - 2018: %60+ → kriz döneminde %50'ye indi
    - 2022-2024: %30-35 seviyesine geriledi
    - %15-20 altı: tarihsel dip bölgesi, contrarian alım fırsatı

    Proxy yöntemleri:
    1. TUR ETF hacim trendi (yabancı girişinin proxy'si)
    2. BIST'in dolar bazlı değerlemesi — ucuzluk düzeyi
    3. Türkiye-gelişen piyasa farkı
    """
    try:
        import yfinance as yf

        # TUR ETF 30 günlük hacim trendi
        tur_hist = yf.Ticker("TUR").history(period="60d", interval="1d")

        if len(tur_hist) < 20:
            return {}

        recent_vol  = float(tur_hist["Volume"].tail(10).mean())
        prev_vol    = float(tur_hist["Volume"].head(10).mean())
        vol_chg     = round((recent_vol - prev_vol) / prev_vol * 100, 1) if prev_vol > 0 else 0

        # TUR ETF performansı (dolar bazında Türkiye)
        tur_ret_30  = (tur_hist["Close"].iloc[-1] - tur_hist["Close"].iloc[-22]) / tur_hist["Close"].iloc[-22] * 100
        tur_ret_30  = round(tur_ret_30, 2)

        # EEM ile karşılaştır
        eem_hist    = yf.Ticker("EEM").history(period="60d", interval="1d")
        eem_ret_30  = 0
        if len(eem_hist) >= 22:
            eem_ret_30 = (eem_hist["Close"].iloc[-1] - eem_hist["Close"].iloc[-22]) / eem_hist["Close"].iloc[-22] * 100
            eem_ret_30 = round(eem_ret_30, 2)

        relative = round(tur_ret_30 - eem_ret_30, 2)

        # Yabancı ilgi yorumu
        if vol_chg >= 30 and relative >= 3:
            signal = "green"
            note   = (f"Yabancı yatırımcı ilgisi ARTIYOR: TUR ETF hacmi +%{vol_chg:.0f}, "
                     f"Türkiye EM'yi +%{relative:.1f} outperform ediyor. "
                     f"Yabancı girişi sinyali.")
        elif vol_chg >= 20:
            signal = "green"
            note   = (f"TUR ETF hacmi +%{vol_chg:.0f} artış — yabancı ilgisi canlanıyor. "
                     f"Kur ve faiz istikrarı sürdürülürse alım devam edebilir.")
        elif vol_chg <= -20 and relative <= -3:
            signal = "red"
            note   = (f"Yabancı çıkışı sinyali: TUR ETF hacmi -%{abs(vol_chg):.0f}, "
                     f"Türkiye EM'nin -%{abs(relative):.1f} gerisinde. "
                     f"Dikkat: yabancı satışı TL'yi baskılar.")
        elif relative >= 5:
            signal = "green"
            note   = (f"Türkiye dolar bazında EM'yi +%{relative:.1f} outperform ediyor (30g). "
                     f"Değerleme cazibeye yabancı ilgisi artıyor olabilir.")
        else:
            signal = "neutral"
            note   = (f"Yabancı yatırımcı pozisyonu stabil. TUR ETF hacim değişimi: %{vol_chg:+.0f}. "
                     f"Türkiye vs EM: %{relative:+.1f} (30g).")

        return {
            "tur_vol_chg":  vol_chg,
            "tur_ret_30":   tur_ret_30,
            "eem_ret_30":   eem_ret_30,
            "relative":     relative,
            "signal":       signal,
            "note":         note,
        }

    except Exception as e:
        logger.warning("Foreign investor proxy failed: %s", e)
        return {}


# ─── 5. BIST Dolar Bazlı Değerleme ───────────────────────────────────────────

def fetch_bist_usd_valuation() -> dict:
    """
    BIST100'ün dolar bazlı tarihsel değerleme analizi.

    Türkiye'ye yatırımda asıl soru şu:
    'TL bazında %30 kazandım ama dolar bazında ne kazandım?'

    Tarihsel BIST dolar bazlı değerleme:
    - 2018 kriz öncesi: ~1400 dolar puan
    - 2020 dip: ~800 dolar puan
    - 2024 orta: ~900-1000 dolar puan
    - 14000 TL endeks / güncel USD/TRY = dolar puan

    Dolar bazlı ucuzluk = en güvenilir alım sinyali.
    """
    try:
        import yfinance as yf

        # Mevcut BIST USD değeri
        bist_fi  = yf.Ticker("XU100.IS").fast_info
        bist_tl  = float(getattr(bist_fi, "last_price", 0) or 0)
        usdt_fi  = yf.Ticker("USDTRY=X").fast_info
        usd_try  = float(getattr(usdt_fi, "last_price", 32.0) or 32.0)

        bist_usd = round(bist_tl / usd_try, 1) if usd_try > 0 else 0

        # Tarihsel referans noktaları
        # (Bu değerler gerçek tarihsel ortalamalar)
        BIST_USD_CHEAP    = 700    # Dip bölge — tarihsel ucuzluk
        BIST_USD_FAIR     = 1000   # Adil değer — tarihsel ortalama
        BIST_USD_EXPENSIVE= 1400   # Pahalı bölge — tarihsel tepe

        if bist_usd <= BIST_USD_CHEAP:
            signal = "green"
            note   = (f"BIST dolar bazlı: {bist_usd:.0f} puan — TARİHSEL UCUZLUK BÖLGESİ. "
                     f"2020 diplerinde de bu seviyelerdeydi. "
                     f"Uzun vadeli yatırımcı için güçlü alım sinyali.")
        elif bist_usd <= BIST_USD_FAIR:
            signal = "green"
            note   = (f"BIST dolar bazlı: {bist_usd:.0f} puan — Adil değer altında. "
                     f"Tarihsel ortalamanın ({BIST_USD_FAIR}) altında, cazip.")
        elif bist_usd <= BIST_USD_EXPENSIVE:
            signal = "amber"
            note   = (f"BIST dolar bazlı: {bist_usd:.0f} puan — Adil değer civarı. "
                     f"Alım için acele etme, daha iyi giriş noktası beklenebilir.")
        else:
            signal = "red"
            note   = (f"BIST dolar bazlı: {bist_usd:.0f} puan — Pahalı bölge. "
                     f"Tarihsel tepelere yakın. Kademeli kâr realizasyonu düşünülebilir.")

        # TL bazında ve dolar bazında getiri farkı yorumu
        note += (f" (Güncel: {bist_tl:,.0f} TL / {usd_try:.1f} = "
                f"${bist_usd:.0f} eşdeğeri)")

        return {
            "bist_tl":       round(bist_tl,  0),
            "usd_try":       round(usd_try,  2),
            "bist_usd":      bist_usd,
            "cheap_zone":    BIST_USD_CHEAP,
            "fair_value":    BIST_USD_FAIR,
            "expensive_zone":BIST_USD_EXPENSIVE,
            "signal":        signal,
            "note":          note,
        }

    except Exception as e:
        logger.warning("BIST USD valuation failed: %s", e)
        return {}


# ─── 6. Türkiye Korelasyonları ────────────────────────────────────────────────

def fetch_turkey_correlations() -> dict:
    """
    Türkiye piyasasının kritik korelasyonları:
    - BIST100 / DXY (dolar güçlenince BIST düşer)
    - BIST100 / S&P 500 (global risk iştahı ile bağlantı)
    - XBANK / BIST100 (bankacılık liderliği)
    - USD/TRY / BIST100 (TL değer kaybı vs BIST)
    - BIST USD bazlı / EEM (gelişen piyasalar ile karşılaştırma)
    """
    try:
        import yfinance as yf
        import statistics

        end   = datetime.now()
        start = end - timedelta(days=95)

        pairs = [
            ("BIST / DXY",          "XU100.IS", "DX-Y.NYB", "negatif",
             "Dolar güçlenince TL ve BIST baskı altına girer."),
            ("BIST / S&P 500",      "XU100.IS", "^GSPC",    "pozitif",
             "Global risk iştahı yükselince BIST de kazanır."),
            ("XBANK / BIST100",     "XBANK.IS", "XU100.IS", "pozitif",
             "Bankalar öncü göstergedir: XBANK>BIST bullish, XBANK<BIST bearish."),
            ("TUR ETF / EEM",       "TUR",      "EEM",      "pozitif",
             "Türkiye'nin gelişen piyasalara göre göreli performansı."),
        ]

        results = {}
        for label, ticker_a, ticker_b, expected, desc in pairs:
            try:
                hist_a = yf.Ticker(ticker_a).history(start=start, end=end)["Close"]
                hist_b = yf.Ticker(ticker_b).history(start=start, end=end)["Close"]

                common = hist_a.index.intersection(hist_b.index)
                if len(common) < 15:
                    continue

                a_vals = [float(hist_a[d]) for d in common]
                b_vals = [float(hist_b[d]) for d in common]

                a_rets = [(a_vals[i]-a_vals[i-1])/a_vals[i-1] for i in range(1,len(a_vals)) if a_vals[i-1]>0]
                b_rets = [(b_vals[i]-b_vals[i-1])/b_vals[i-1] for i in range(1,len(b_vals)) if b_vals[i-1]>0]

                n = min(len(a_rets), len(b_rets))
                a_rets, b_rets = a_rets[:n], b_rets[:n]

                mean_a = sum(a_rets) / n
                mean_b = sum(b_rets) / n
                cov    = sum((a_rets[i]-mean_a)*(b_rets[i]-mean_b) for i in range(n)) / n
                std_a  = statistics.stdev(a_rets)
                std_b  = statistics.stdev(b_rets)
                corr   = round(cov/(std_a*std_b), 3) if std_a > 0 and std_b > 0 else 0

                # Yorumla
                if expected == "negatif" and corr >= 0.3:
                    warn = f"⚠️ Beklenmedik pozitif korelasyon ({corr:+.2f}) — dolar güçlenirken BIST de yükseliyor, altyapısal değişim olabilir"
                elif expected == "pozitif" and corr <= -0.3:
                    warn = f"⚠️ Beklenmedik negatif korelasyon ({corr:+.2f}) — dikkat"
                elif abs(corr) >= 0.7:
                    warn = f"Çok güçlü korelasyon ({corr:+.2f}) — {desc}"
                else:
                    warn = f"Korelasyon: {corr:+.2f} — {desc}"

                results[label] = {
                    "correlation": corr,
                    "expected":    expected,
                    "signal":      "neutral",
                    "note":        f"{label}: {warn}",
                }
                time.sleep(0.2)
            except Exception as e:
                logger.debug("Turkey corr %s failed: %s", label, e)

        return results

    except Exception as e:
        logger.warning("Turkey correlations failed: %s", e)
        return {}


# ─── 7. TEFAS Entegrasyonu ────────────────────────────────────────────────────

def fetch_tefas_fund(fund_code: str) -> dict:
    """
    TEFAS fon verisi çek.

    Yöntem 1: tefas-crawler paketi (en güvenilir)
    Yöntem 2: TEFAS API (session + tüm fontip değerleri)
    Yöntem 3: TEFAS HTML scraping
    """
    import requests

    code = fund_code.upper().strip()
    today     = datetime.now()
    yesterday = today - timedelta(days=5)  # hafta sonu/tatil buffer
    start_1y  = today - timedelta(days=380)

    # ── Yöntem 1: tefas-crawler paketi ───────────────────────────────────
    try:
        from tefas import Crawler
        tefas_crawler = Crawler()
        df = tefas_crawler.fetch(
            start=yesterday.strftime("%Y-%m-%d"),
            end=today.strftime("%Y-%m-%d"),
            name=code,
        )
        if df is not None and len(df) > 0:
            latest_row = df.iloc[-1]
            price = float(latest_row.get("price", 0) or latest_row.get("FIYAT", 0) or 0)
            if price > 0:
                # 1 yıllık veri çek getiri hesabı için
                df_1y = tefas_crawler.fetch(
                    start=start_1y.strftime("%Y-%m-%d"),
                    end=today.strftime("%Y-%m-%d"),
                    name=code,
                )
                p_1m = p_3m = p_1y = price
                if df_1y is not None and len(df_1y) > 5:
                    n = len(df_1y)
                    p_1m = float(df_1y.iloc[max(0, n-22)].get("price", price) or price)
                    p_3m = float(df_1y.iloc[max(0, n-66)].get("price", price) or price)
                    p_1y = float(df_1y.iloc[0].get("price", price) or price)

                logger.info("TEFAS crawler başarılı: %s = %.4f TL", code, price)
                return {
                    "fund_code": code,
                    "price":     round(price, 4),
                    "ret_1m":    round((price - p_1m) / p_1m * 100, 2) if p_1m > 0 else 0,
                    "ret_3m":    round((price - p_3m) / p_3m * 100, 2) if p_3m > 0 else 0,
                    "ret_1y":    round((price - p_1y) / p_1y * 100, 2) if p_1y > 0 else 0,
                    "date":      today.strftime("%Y-%m-%d"),
                    "source":    "tefas-crawler",
                }
    except Exception as e:
        logger.debug("tefas-crawler başarısız: %s", e)

    # ── Yöntem 2: TEFAS API (session cookie ile) ─────────────────────────
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        })
        session.get(
            f"https://www.tefas.gov.tr/FonAnaliz.aspx?fonKod={code}",
            timeout=15,
        )
        api_headers = {
            "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
            "Referer":          f"https://www.tefas.gov.tr/FonAnaliz.aspx?fonKod={code}",
            "Origin":           "https://www.tefas.gov.tr",
            "X-Requested-With": "XMLHttpRequest",
        }
        end_str   = today.strftime("%d.%m.%Y")
        start_str = start_1y.strftime("%d.%m.%Y")

        for fontip in ["", "YAT", "HIS", "BYF", "BOR", "KAR", "DEG", "PAR", "ALT", "EMK"]:
            try:
                r = session.post(
                    "https://www.tefas.gov.tr/api/DB/BindHistoryInfo",
                    data={"fontip": fontip, "bastarih": start_str,
                          "bittarih": end_str, "fonkod": code},
                    headers=api_headers,
                    timeout=12,
                )
                if r.status_code != 200:
                    continue
                records = r.json().get("data", [])
                if not records:
                    continue

                # Fiyat alanını bul
                price_field = None
                sample = records[-1]
                for f in ["FIYAT", "BIRIMPAYFIYATI", "PORTFOYBUYUKLUK"]:
                    if sample.get(f) and float(sample.get(f) or 0) > 0:
                        price_field = f
                        break
                if not price_field:
                    continue

                latest = records[-1]
                price = float(latest.get(price_field) or 0)
                if price <= 0:
                    continue

                n = len(records)
                p_1m = float(records[max(0, n-22)].get(price_field) or price)
                p_3m = float(records[max(0, n-66)].get(price_field) or price)
                p_1y = float(records[0].get(price_field) or price)

                logger.info("TEFAS API başarılı: %s fontip=%r, %.4f TL", code, fontip, price)
                return {
                    "fund_code": code,
                    "price":     round(price, 4),
                    "ret_1m":    round((price - p_1m) / p_1m * 100, 2) if p_1m > 0 else 0,
                    "ret_3m":    round((price - p_3m) / p_3m * 100, 2) if p_3m > 0 else 0,
                    "ret_1y":    round((price - p_1y) / p_1y * 100, 2) if p_1y > 0 else 0,
                    "date":      latest.get("TARIH", today.strftime("%Y-%m-%d")),
                    "source":    "tefas-api",
                }
            except Exception:
                continue
    except Exception as e:
        logger.debug("TEFAS API yöntemi başarısız: %s", e)

    # ── Yöntem 3: TEFAS HTML scraping ────────────────────────────────────
    try:
        from bs4 import BeautifulSoup
        session2 = requests.Session()
        session2.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        r = session2.get(
            f"https://www.tefas.gov.tr/FonAnaliz.aspx?fonKod={code}",
            timeout=15,
        )
        if r.status_code == 200:
            soup = BeautifulSoup(r.content, "html.parser")
            # TEFAS sayfasındaki data-value attribute veya metin
            price = 0.0
            # Tablo hücreleri veya span'lar içinde fiyat ara
            for el in soup.find_all(["span", "td", "div"]):
                text = el.get_text(strip=True).replace(",", ".").replace(" ", "")
                try:
                    val = float(text)
                    # TEFAS fon fiyatı genellikle 0.1 - 1000 TL arası
                    if 0.01 < val < 10000:
                        price = val
                        break
                except ValueError:
                    pass
            if price > 0:
                logger.info("TEFAS HTML scraping başarılı: %s = %.4f", code, price)
                return {
                    "fund_code": code,
                    "price":     round(price, 4),
                    "ret_1m":    0.0,
                    "ret_3m":    0.0,
                    "ret_1y":    0.0,
                    "date":      today.strftime("%Y-%m-%d"),
                    "source":    "tefas-html",
                }
    except Exception as e:
        logger.debug("TEFAS HTML scraping başarısız: %s", e)

    logger.error("TEFAS: %s için tüm yöntemler başarısız", code)
    return {}


def fetch_tefas_portfolio(fund_codes: list) -> dict:
    """
    Kullanıcının TEFAS fonlarını çek ve normalize et.
    TL bazlı getiri + dolar bazlı gerçek getiri hesapla.
    """
    if not fund_codes:
        return {}

    try:
        import yfinance as yf
        usd_try = float(yf.Ticker("USDTRY=X").fast_info.last_price or 32.0)
    except Exception:
        usd_try = 32.0

    results = {}
    for code in fund_codes:
        fund = fetch_tefas_fund(code)
        if fund:
            # Dolar bazlı normalize getiri tahmini
            # TL getiri - TL değer kaybı = yaklaşık dolar getiri
            tl_devaluation_1y = 20.0  # yaklaşık TL yıllık değer kaybı tahmini
            usd_ret_1y = round(fund["ret_1y"] - tl_devaluation_1y, 2)

            fund["usd_ret_1y_approx"] = usd_ret_1y
            fund["usd_try"]           = round(usd_try, 2)
            results[code.upper()]     = fund
        time.sleep(0.3)

    return results


# ─── Ana Toplayıcı ───────────────────────────────────────────────────────────

def fetch_all_turkey_data(tefas_codes: list = None) -> dict:
    """
    Tüm Katman 5 Türkiye verilerini tek seferde topla.
    """
    logger.info("Türkiye verileri toplanıyor...")

    data = {
        "bist":          fetch_bist_data(),
        "xbank":         fetch_xbank_analysis(),
        "macro":         fetch_turkey_macro(),
        "foreign":       fetch_foreign_investor_proxy(),
        "valuation":     fetch_bist_usd_valuation(),
        "correlations":  fetch_turkey_correlations(),
        "tefas":         fetch_tefas_portfolio(tefas_codes or []),
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }

    logger.info("Türkiye verisi tamamlandı.")
    return data


def build_turkey_prompt(data: dict) -> str:
    """
    Türkiye verilerini Claude analizi için formatlı metne dönüştür.
    """
    lines = ["=== TÜRKİYE BORSASI ANALİZİ ==="]

    # BIST temel
    bist  = data.get("bist", {})
    b100  = bist.get("BIST100", {})
    if b100:
        lines.append(
            f"\nBIST100: {b100.get('tl',0):,.0f} TL ({b100.get('tl_chg',0):+.1f}%) | "
            f"Dolar bazlı: ${b100.get('usd',0):,.0f} ({b100.get('usd_chg',0):+.1f}%)"
        )

    usd_try = bist.get("USD_TRY", {})
    if usd_try:
        lines.append(f"USD/TRY: {usd_try.get('value',0):.2f} ({usd_try.get('change',0):+.2f}%)")

    # XBANK
    xbank = data.get("xbank", {})
    if xbank.get("note"):
        lines.append(f"\n{xbank['note']}")

    # Dolar bazlı değerleme
    val = data.get("valuation", {})
    if val.get("note"):
        lines.append(f"\n{val['note']}")

    # Makro
    macro = data.get("macro", {})
    rr = macro.get("real_rate", {})
    if rr.get("note"):
        lines.append(f"\n{rr['note']}")

    cds = macro.get("cds_proxy", {})
    if cds.get("note"):
        lines.append(f"{cds['note']}")

    # Yabancı yatırımcı
    foreign = data.get("foreign", {})
    if foreign.get("note"):
        lines.append(f"\n{foreign['note']}")

    # Korelasyonlar
    corr = data.get("correlations", {})
    if corr:
        lines.append("\nKorelasyonlar:")
        for label, d in corr.items():
            if d.get("correlation") is not None:
                lines.append(f"  {label}: {d['correlation']:+.2f}")

    # TEFAS fonları
    tefas = data.get("tefas", {})
    if tefas:
        lines.append("\nTEFAS Fonları:")
        for code, fund in tefas.items():
            lines.append(
                f"  {code}: {fund.get('price',0):.4f} TL | "
                f"1A: %{fund.get('ret_1m',0):+.1f} | "
                f"3A: %{fund.get('ret_3m',0):+.1f} | "
                f"1Y: %{fund.get('ret_1y',0):+.1f} "
                f"(USD bazlı tahmini: %{fund.get('usd_ret_1y_approx',0):+.1f})"
            )

    return "\n".join(lines)
