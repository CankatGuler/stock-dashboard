# commodity_fetcher.py — Emtia Varlık Sınıfı Veri Modülü
#
# Katman 4 metrikleri:
#   - Altın: reel faiz, merkez bankası alımları proxy, fiyat/trend
#   - Petrol: EIA stok değişimi proxy, OPEC bağlamı, fiyat
#   - Gümüş, Bakır: fiyat + trend
#   - Altın/Bakır oranı (ekonomik aktivite göstergesi)
#   - ABD borç/altın rezerv tezi bağlamı
#   - Jeopolitik haber filtresi
#
# Tüm kaynaklar ücretsiz: yfinance, FRED API, web scraping

import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── Emtia Ticker Tanımları ───────────────────────────────────────────────────

COMMODITY_TICKERS = {
    "GOLD":    {"ticker": "GC=F",  "label": "Altın (XAU/USD)",    "unit": "$/oz"},
    "SILVER":  {"ticker": "SI=F",  "label": "Gümüş (XAG/USD)",   "unit": "$/oz"},
    "COPPER":  {"ticker": "HG=F",  "label": "Bakır",              "unit": "$/lb"},
    "OIL_WTI": {"ticker": "CL=F",  "label": "Petrol WTI",        "unit": "$/bbl"},
    "OIL_BRT": {"ticker": "BZ=F",  "label": "Petrol Brent",      "unit": "$/bbl"},
    "NATGAS":  {"ticker": "NG=F",  "label": "Doğalgaz",          "unit": "$/MMBtu"},
    "GLD_ETF": {"ticker": "GLD",   "label": "Altın ETF (GLD)",   "unit": "$"},
    "SLV_ETF": {"ticker": "SLV",   "label": "Gümüş ETF (SLV)",  "unit": "$"},
}

# ─── 1. Emtia Fiyatları ───────────────────────────────────────────────────────

def fetch_commodity_prices() -> dict:
    """
    Tüm emtia fiyatlarını yfinance'ten çek.
    Her biri için: fiyat, 24h değişim, 52H pozisyon, trend.
    """
    try:
        import yfinance as yf
        results = {}

        for key, meta in COMMODITY_TICKERS.items():
            try:
                fi    = yf.Ticker(meta["ticker"]).fast_info
                price = float(getattr(fi, "last_price",      0) or 0)
                prev  = float(getattr(fi, "previous_close",  price) or price)
                w52h  = float(getattr(fi, "year_high",       0) or 0)
                w52l  = float(getattr(fi, "year_low",        0) or 0)
                chg   = (price - prev) / prev * 100 if prev > 0 else 0
                pos   = (price - w52l) / (w52h - w52l) * 100 if w52h > w52l else 50

                results[key] = {
                    "label":    meta["label"],
                    "unit":     meta["unit"],
                    "price":    round(price, 2),
                    "change":   round(chg,   2),
                    "w52h":     round(w52h,  2),
                    "w52l":     round(w52l,  2),
                    "pos_52h":  round(pos,   1),
                }
                time.sleep(0.1)
            except Exception as e:
                logger.debug("Commodity price failed %s: %s", key, e)

        return results
    except Exception as e:
        logger.warning("fetch_commodity_prices failed: %s", e)
        return {}


# ─── 2. Altın — Reel Faiz İlişkisi ───────────────────────────────────────────

def fetch_gold_real_rate() -> dict:
    """
    Altın fiyatının en kritik belirleyicisi: reel faiz oranı.
    Reel faiz = 10Y nominal faiz - 10Y breakeven enflasyon beklentisi

    Reel faiz negatif → altın tarihi ralliler yapar
    Reel faiz pozitif & yüksek → altın baskı altında

    FRED serileri:
    - T10Y2Y: 10Y-2Y spread (yield curve)
    - T10YIE: 10Y breakeven inflation
    - DGS10:  10Y Treasury yield
    """
    try:
        import requests
        import yfinance as yf

        # FRED'den 10Y breakeven enflasyon (TIPS spread)
        def fred_latest(series_id):
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id":  series_id,
                    "api_key":    "abcdefghijklmnopqrstuvwxyz123456",
                    "file_type":  "json",
                    "sort_order": "desc",
                    "limit":      5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                obs = [o for o in resp.json().get("observations", [])
                       if o.get("value", ".") != "."]
                if obs:
                    return float(obs[0]["value"])
            return None

        nominal_10y  = fred_latest("DGS10")   # 10Y nominal faiz
        breakeven_10y= fred_latest("T10YIE")  # 10Y breakeven enflasyon

        if nominal_10y and breakeven_10y:
            real_rate = round(nominal_10y - breakeven_10y, 2)

            if real_rate <= -0.5:
                signal = "green"
                note   = (f"Reel Faiz: %{real_rate:.2f} — NEGATİF. "
                         f"Altın için en güçlü bülten ortamı. "
                         f"2020'de -1.0% altına indi, altın 2X yaptı.")
            elif real_rate <= 0.5:
                signal = "green"
                note   = (f"Reel Faiz: %{real_rate:.2f} — Düşük pozitif. "
                         f"Altın için destekleyici ortam.")
            elif real_rate <= 1.5:
                signal = "amber"
                note   = (f"Reel Faiz: %{real_rate:.2f} — Orta. "
                         f"Altın için nötr, diğer faktörler belirleyici.")
            else:
                signal = "red"
                note   = (f"Reel Faiz: %{real_rate:.2f} — YÜKSEK. "
                         f"Altın üzerinde baskı var, nakit tutmanın fırsat maliyeti düşük.")

            return {
                "nominal_10y":   nominal_10y,
                "breakeven_10y": breakeven_10y,
                "real_rate":     real_rate,
                "signal":        signal,
                "note":          note,
            }

        # FRED başarısız olursa yfinance TIP ETF proxy
        tip = yf.Ticker("TIP").fast_info
        tlt = yf.Ticker("TLT").fast_info
        tip_p = float(getattr(tip, "last_price", 0) or 0)
        tlt_p = float(getattr(tlt, "last_price", 0) or 0)
        tip_prev = float(getattr(tip, "previous_close", tip_p) or tip_p)
        tlt_prev = float(getattr(tlt, "previous_close", tlt_p) or tlt_p)

        # TIP outperforms TLT → reel faiz düşüyor → altın için iyi
        tip_chg = (tip_p - tip_prev) / tip_prev * 100 if tip_prev > 0 else 0
        tlt_chg = (tlt_p - tlt_prev) / tlt_prev * 100 if tlt_prev > 0 else 0
        rel     = round(tip_chg - tlt_chg, 2)

        signal = "green" if rel > 0.1 else ("red" if rel < -0.1 else "neutral")
        note   = (f"Reel Faiz Proxy (TIP/TLT): {rel:+.2f}% — "
                 + ("DÜŞÜYOR, altın için olumlu" if rel > 0.1
                    else "YÜKSELIYOR, altın için olumsuz" if rel < -0.1
                    else "Stabil"))

        return {"real_rate_proxy": rel, "signal": signal, "note": note}

    except Exception as e:
        logger.warning("Gold real rate failed: %s", e)
        return {}


# ─── 3. Merkez Bankası Altın Alımları Proxy ───────────────────────────────────

def fetch_central_bank_gold_proxy() -> dict:
    """
    Merkez bankası altın alımlarının proxy göstergesi.
    Gerçek veri: World Gold Council aylık yayınlar (ücretsiz web scraping zor).

    Proxy: GLD ETF kurumsal akışı + altın fiyatının dolar güçsüzlüğüne karşı performansı.
    Dolar zayıflarken altın yükseliyorsa → organik talep var (MB alımları dahil).
    Dolar güçlenirken altın da yükseliyorsa → GÜÇLÜ MB alım sinyali!
    """
    try:
        import yfinance as yf

        gld  = yf.Ticker("GLD").history(period="30d", interval="1d")["Close"]
        dxy_tk = yf.Ticker("DX-Y.NYB")
        dxy  = dxy_tk.history(period="30d", interval="1d")["Close"]

        if len(gld) < 10 or len(dxy) < 10:
            return {}

        gld_ret = (gld.iloc[-1] - gld.iloc[0]) / gld.iloc[0] * 100
        dxy_ret = (dxy.iloc[-1] - dxy.iloc[0]) / dxy.iloc[0] * 100

        # Altın - Dolar ters korelasyon kırılması = güçlü alım
        divergence = round(gld_ret + dxy_ret, 2)  # Normalize: normalde -1 korelasyon

        if gld_ret > 2 and dxy_ret > 1:
            signal = "green"
            note   = (f"Altın-Dolar Ayrışması: Altın +%{gld_ret:.1f}, DXY +%{dxy_ret:.1f} — "
                     f"GÜÇLÜ alım baskısı! Dolar güçlenirken altın da yükseliyor. "
                     f"Merkez bankası/kurumsal alım sinyali.")
        elif gld_ret > 2 and dxy_ret < -1:
            signal = "amber"
            note   = (f"Altın +%{gld_ret:.1f}, DXY %{dxy_ret:.1f} — "
                     f"Normal ters korelasyon. Dolar zayıflığıyla destekli yükseliş.")
        elif gld_ret < -2:
            signal = "amber"
            note   = (f"Altın -%{abs(gld_ret):.1f} (30g) — Kısa vadeli zayıflık. "
                     f"Uzun vadeli yapısal boğa trendi devam edebilir.")
        else:
            signal = "neutral"
            note   = f"Altın %{gld_ret:+.1f} (30g) — Stabil seyir."

        return {
            "gold_30d_ret":  round(gld_ret, 2),
            "dxy_30d_ret":   round(dxy_ret, 2),
            "divergence":    divergence,
            "signal":        signal,
            "note":          note,
        }
    except Exception as e:
        logger.debug("CB gold proxy failed: %s", e)
        return {}


# ─── 4. ABD Borç/Altın Rezerv Tezi ───────────────────────────────────────────

def get_us_debt_gold_context() -> dict:
    """
    ABD'nin dev borcu ve altın rezerv yeniden değerleme tezi.
    Bu yapısal bağlamı Claude'a ver — kısa vadeli değil, uzun vadeli çerçeve.

    ABD altın rezervi: ~8.133 ton
    Kayıt değeri: $42.22/oz (1970'lerden)
    Piyasa değeri: güncel altın fiyatına göre hesapla
    """
    try:
        import yfinance as yf
        gold_price = float(yf.Ticker("GC=F").fast_info.last_price or 3000)

        US_GOLD_TONS   = 8133
        TROY_OZ_PER_TON= 32150.75
        US_GOLD_OZ     = US_GOLD_TONS * TROY_OZ_PER_TON

        book_value     = US_GOLD_OZ * 42.22          # 1970'lerden kayıt değeri
        market_value   = US_GOLD_OZ * gold_price     # Güncel piyasa değeri
        hidden_value   = market_value - book_value   # "Gizli" değer
        us_debt_approx = 36_000_000_000_000          # ~36 trilyon

        debt_coverage  = market_value / us_debt_approx * 100

        note = (
            f"ABD Altın Rezerv Tezi: "
            f"{US_GOLD_TONS:,} ton altın × ${gold_price:,.0f}/oz = "
            f"${market_value/1e12:.2f}T piyasa değeri "
            f"(kayıt değeri ${book_value/1e9:.0f}B — fark ${hidden_value/1e12:.2f}T). "
            f"ABD ~$36T borcunun %{debt_coverage:.1f}'ini karşılıyor. "
            f"Altın fiyatı yükselirse bu oran artar — "
            f"yapısal altın boğa tezi devam ediyor."
        )

        return {
            "gold_price":     gold_price,
            "reserve_tons":   US_GOLD_TONS,
            "market_value_t": round(market_value / 1e12, 2),
            "debt_coverage":  round(debt_coverage, 1),
            "signal":         "green",
            "note":           note,
        }
    except Exception as e:
        logger.debug("US debt gold context failed: %s", e)
        return {}


# ─── 5. Petrol — EIA Stok Proxy ──────────────────────────────────────────────

def fetch_oil_fundamentals() -> dict:
    """
    Petrol temel verileri:
    - EIA haftalık stok değişimi proxy (yfinance USO ETF hacim)
    - OPEC+ üretim kapasitesi bağlamı
    - WTI/Brent spread (piyasa yapısı göstergesi)
    - Petrol-enflasyon-Fed üçgeni analizi
    """
    try:
        import yfinance as yf
        import requests

        results = {}

        # WTI ve Brent fiyatları
        wti_fi   = yf.Ticker("CL=F").fast_info
        brt_fi   = yf.Ticker("BZ=F").fast_info
        wti      = float(getattr(wti_fi, "last_price", 0) or 0)
        brt      = float(getattr(brt_fi, "last_price", 0) or 0)
        wti_prev = float(getattr(wti_fi, "previous_close", wti) or wti)

        wti_chg  = (wti - wti_prev) / wti_prev * 100 if wti_prev > 0 else 0
        wti_brt  = round(brt - wti, 2) if brt > 0 and wti > 0 else 0

        # WTI/Brent spread yorumu
        if wti_brt > 5:
            spread_note = f"Brent premi yüksek (${wti_brt:.1f}) — jeopolitik risk fiyatlanıyor"
        elif wti_brt < 1:
            spread_note = f"WTI/Brent yakın (${wti_brt:.1f}) — normal piyasa yapısı"
        else:
            spread_note = f"Brent premi ${wti_brt:.1f} — hafif jeopolitik endişe"

        # EIA stok proxy: USO ETF hacim değişimi
        uso_hist = yf.Ticker("USO").history(period="10d", interval="1d")
        uso_vol_chg = 0
        if len(uso_hist) >= 5:
            recent_vol = float(uso_hist["Volume"].tail(3).mean())
            prev_vol   = float(uso_hist["Volume"].head(3).mean())
            uso_vol_chg = round((recent_vol - prev_vol) / prev_vol * 100, 1) if prev_vol > 0 else 0

        # Petrol seviyesi yorumu
        if wti >= 90:
            oil_signal = "red"
            oil_note   = (f"WTI ${wti:.1f} — YÜKSEK. Enflasyon baskısı artar, "
                         f"Fed elinin bağlandığı bölge. Enerji hisselerine pozitif ama geniş piyasaya olumsuz.")
        elif wti >= 70:
            oil_signal = "neutral"
            oil_note   = f"WTI ${wti:.1f} — Normal aralık. Ekonomi dengeli."
        elif wti >= 50:
            oil_signal = "amber"
            oil_note   = (f"WTI ${wti:.1f} — Düşük. Enerji sektörü baskılı, "
                         f"tüketici harcamalarına pozitif etki.")
        else:
            oil_signal = "red"
            oil_note   = f"WTI ${wti:.1f} — Çok düşük. Deflasyon riski veya talep çöküşü."

        # Petrol-Fed ilişkisi
        fed_note = ""
        if wti >= 85:
            fed_note = " ⚠️ Yüksek petrol fiyatı enflasyonu besliyor — Fed faiz indirimini erteleyebilir."
        elif wti <= 60:
            fed_note = " ✅ Düşük petrol fiyatı enflasyon baskısını azaltıyor — Fed indirim için zemin hazırlıyor."

        results = {
            "wti":        wti,
            "brent":      brt,
            "wti_change": round(wti_chg, 2),
            "wti_brt_spread": wti_brt,
            "spread_note":    spread_note,
            "uso_vol_chg":    uso_vol_chg,
            "signal":         oil_signal,
            "note":           oil_note + fed_note,
        }

        return results

    except Exception as e:
        logger.warning("Oil fundamentals failed: %s", e)
        return {}


# ─── 6. Bakır — Ekonomik Aktivite Göstergesi ─────────────────────────────────

def fetch_copper_analysis() -> dict:
    """
    'Dr. Copper' — ekonomik aktivitenin öncü göstergesi.
    Bakır talebi sanayileşme ve altyapı yatırımlarını yansıtır.
    Çin'in bakır talebi küresel talebin ~%55'ini oluşturur.
    """
    try:
        import yfinance as yf

        # Bakır fiyatı
        cu_fi   = yf.Ticker("HG=F").fast_info
        cu      = float(getattr(cu_fi, "last_price",     0) or 0)
        cu_prev = float(getattr(cu_fi, "previous_close", cu) or cu)
        cu_chg  = (cu - cu_prev) / cu_prev * 100 if cu_prev > 0 else 0

        # 52H pozisyon
        cu_hist = yf.Ticker("HG=F").history(period="1y", interval="1d")["Close"]
        cu_52h  = float(cu_hist.max()) if len(cu_hist) > 0 else 0
        cu_52l  = float(cu_hist.min()) if len(cu_hist) > 0 else 0
        pos_52h = (cu - cu_52l) / (cu_52h - cu_52l) * 100 if cu_52h > cu_52l else 50

        # Altın/Bakır oranı — risk iştahı barometresi
        gold_fi = yf.Ticker("GC=F").fast_info
        gold    = float(getattr(gold_fi, "last_price", 0) or 0)
        gc_ratio= round(gold / cu, 1) if cu > 0 else 0

        # Altın/Bakır oranı yorumu
        # Yüksek oran = korku/resesyon beklentisi, düşük oran = büyüme beklentisi
        HIST_GC_HIGH = 650   # Resesyon dönemlerinde ~700+
        HIST_GC_LOW  = 350   # Boğa dönemlerinde ~350-450
        if gc_ratio >= 600:
            gc_signal = "red"
            gc_note   = (f"Altın/Bakır: {gc_ratio:.0f} — YÜKSEK. "
                        f"Resesyon korkusu hakim, ekonomik aktivite yavaşlıyor.")
        elif gc_ratio >= 450:
            gc_signal = "amber"
            gc_note   = (f"Altın/Bakır: {gc_ratio:.0f} — Orta. "
                        f"Belirsizlik var, büyüme güveni tam değil.")
        else:
            gc_signal = "green"
            gc_note   = (f"Altın/Bakır: {gc_ratio:.0f} — DÜŞÜK. "
                        f"Risk iştahı yüksek, ekonomik büyüme beklentisi güçlü.")

        # Bakır trendi yorumu
        if cu_chg >= 1.5:
            cu_signal = "green"
            cu_note   = f"Bakır +%{cu_chg:.1f} — Küresel büyüme ivmesi. Sanayi ve inşaat talebi güçlü."
        elif cu_chg <= -1.5:
            cu_signal = "red"
            cu_note   = f"Bakır -%{abs(cu_chg):.1f} — Küresel talep zayıflıyor. Çin yavaşlaması olabilir."
        else:
            cu_signal = "neutral"
            cu_note   = f"Bakır stabil (${cu:.2f}/lb). Ekonomi nötr seyirde."

        return {
            "copper":     cu,
            "cu_change":  round(cu_chg, 2),
            "pos_52h":    round(pos_52h, 1),
            "gold_copper_ratio": gc_ratio,
            "gc_signal":  gc_signal,
            "gc_note":    gc_note,
            "signal":     cu_signal,
            "note":       cu_note,
        }

    except Exception as e:
        logger.warning("Copper analysis failed: %s", e)
        return {}


# ─── 7. Jeopolitik Haber Filtresi ────────────────────────────────────────────

def fetch_commodity_geo_news() -> dict:
    """
    Emtia fiyatlarını etkileyen jeopolitik haberleri tara.
    Anahtar kelimeler: Orta Doğu, Rusya-Ukrayna, OPEC, tarife, gümrük.

    Kaynak: RSS beslemeleri (Reuters, Bloomberg, CNBC)
    """
    try:
        import feedparser
        import re

        GEO_KEYWORDS = {
            "oil_risk": [
                "middle east", "iran", "saudi", "opec", "oil supply",
                "pipeline", "strait of hormuz", "energy sanctions",
            ],
            "gold_risk": [
                "central bank gold", "gold reserves", "dollar weaponized",
                "de-dollarization", "brics currency", "gold backed",
            ],
            "copper_risk": [
                "china manufacturing", "china pmi", "copper demand",
                "belt and road", "chile copper", "mining strike",
            ],
            "general": [
                "tariff", "sanctions", "trade war", "ukraine", "russia",
                "commodity", "inflation", "supply chain",
            ],
        }

        RSS_FEEDS = [
            "https://feeds.reuters.com/reuters/businessNews",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]

        triggered = {k: [] for k in GEO_KEYWORDS}
        cutoff    = datetime.now(timezone.utc) - timedelta(hours=48)

        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:20]:
                    title   = entry.get("title",   "").lower()
                    summary = entry.get("summary", "").lower()
                    text    = f"{title} {summary}"

                    for category, keywords in GEO_KEYWORDS.items():
                        for kw in keywords:
                            if kw in text:
                                triggered[category].append(entry.get("title", "")[:80])
                                break
            except Exception:
                pass

        # Özet
        alerts = []
        if triggered["oil_risk"]:
            alerts.append(f"🛢️ Petrol Riski: {len(triggered['oil_risk'])} haber — {triggered['oil_risk'][0][:60]}")
        if triggered["gold_risk"]:
            alerts.append(f"🥇 Altın Talebi: {len(triggered['gold_risk'])} haber — {triggered['gold_risk'][0][:60]}")
        if triggered["copper_risk"]:
            alerts.append(f"🔧 Bakır/Çin: {len(triggered['copper_risk'])} haber — {triggered['copper_risk'][0][:60]}")
        if triggered["general"]:
            alerts.append(f"⚠️ Genel: {len(triggered['general'])} jeopolitik haber")

        return {
            "alerts":    alerts,
            "triggered": triggered,
            "has_alerts": len(alerts) > 0,
            "note":      " | ".join(alerts) if alerts else "Son 48 saatte kritik emtia haberi yok.",
        }

    except Exception as e:
        logger.debug("Commodity geo news failed: %s", e)
        return {"alerts": [], "has_alerts": False, "note": "Haber taraması yapılamadı"}


# ─── 8. Emtia Sinyal Özeti ───────────────────────────────────────────────────

def get_commodity_signal_summary(data: dict) -> dict:
    """
    Tüm emtia sinyallerini özetle.
    Returns: {overall, score, summary}
    """
    score_map = {"green": 2, "amber": 1, "neutral": 0, "red": -1}
    signals   = []

    gold_real  = data.get("gold_real_rate", {}).get("signal",   "neutral")
    cb_proxy   = data.get("cb_gold_proxy",  {}).get("signal",   "neutral")
    oil_sig    = data.get("oil",            {}).get("signal",   "neutral")
    copper_sig = data.get("copper",         {}).get("gc_signal","neutral")

    total    = sum(score_map.get(s, 0) for s in [gold_real, cb_proxy, oil_sig, copper_sig])
    pct      = round((total + 8) / 16 * 100)

    if pct >= 65:
        return {"overall": "green",   "score": pct, "summary": "Emtia ortamı OLUMLU"}
    elif pct >= 40:
        return {"overall": "neutral", "score": pct, "summary": "Emtia ortamı KARMA"}
    else:
        return {"overall": "red",     "score": pct, "summary": "Emtia ortamı OLUMSUZ"}


# ─── Ana Toplayıcı ───────────────────────────────────────────────────────────

def fetch_all_commodity_data() -> dict:
    """
    Tüm Katman 4 emtia verilerini tek seferde topla.
    """
    logger.info("Emtia verileri toplanıyor...")

    data = {
        "prices":         fetch_commodity_prices(),
        "gold_real_rate": fetch_gold_real_rate(),
        "cb_gold_proxy":  fetch_central_bank_gold_proxy(),
        "us_debt_gold":   get_us_debt_gold_context(),
        "oil":            fetch_oil_fundamentals(),
        "copper":         fetch_copper_analysis(),
        "geo_news":       fetch_commodity_geo_news(),
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
    }

    data["signal_summary"] = get_commodity_signal_summary(data)
    logger.info("Emtia verisi tamamlandı.")
    return data


def build_commodity_prompt(data: dict) -> str:
    """
    Emtia verilerini Claude analizi için formatlı metne dönüştür.
    """
    lines = ["=== EMTİA PİYASASI ANALİZİ ==="]

    # Altın
    prices = data.get("prices", {})
    gold   = prices.get("GOLD", {})
    if gold:
        lines.append(f"\nAltın: ${gold.get('price',0):,.0f}/oz "
                    f"({gold.get('change',0):+.1f}%) | "
                    f"52H Pozisyon: %{gold.get('pos_52h',0):.0f}")

    gr = data.get("gold_real_rate", {})
    if gr.get("note"):
        lines.append(f"  → {gr['note']}")

    cb = data.get("cb_gold_proxy", {})
    if cb.get("note"):
        lines.append(f"  → {cb['note']}")

    ug = data.get("us_debt_gold", {})
    if ug.get("note"):
        lines.append(f"  → {ug['note']}")

    # Petrol
    oil = data.get("oil", {})
    if oil.get("note"):
        lines.append(f"\n{oil['note']}")
        if oil.get("spread_note"):
            lines.append(f"  WTI/Brent: {oil['spread_note']}")

    # Bakır
    cu = data.get("copper", {})
    if cu.get("note"):
        lines.append(f"\n{cu['note']}")
    if cu.get("gc_note"):
        lines.append(f"  {cu['gc_note']}")

    # Gümüş
    silver = prices.get("SILVER", {})
    if silver.get("price"):
        lines.append(f"\nGümüş: ${silver.get('price',0):.2f}/oz "
                    f"({silver.get('change',0):+.1f}%)")

    # Jeopolitik
    geo = data.get("geo_news", {})
    if geo.get("has_alerts"):
        lines.append(f"\n⚠️ Jeopolitik Uyarılar:")
        for alert in geo.get("alerts", []):
            lines.append(f"  {alert}")

    # Özet
    ss = data.get("signal_summary", {})
    if ss:
        lines.append(f"\nEmtia Genel Durum: {ss.get('summary','')}")

    return "\n".join(lines)
