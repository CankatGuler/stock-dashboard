import streamlit as st
# crypto_fetcher.py — Kripto Varlık Sınıfı Veri Modülü
#
# Katman 3 metrikleri:
#   - Kripto Fear & Greed (alternative.me)
#   - Bitcoin Dominance (CoinGecko)
#   - MVRV Z-Score proxy
#   - SOPR proxy
#   - Exchange Net Flow proxy
#   - Long/Short Ratio (Coinglass)
#   - Halving döngüsü pozisyonu
#   - Stablecoin dominance
#   - NVT Signal proxy
#   - Active Addresses proxy
#
# Tüm kaynaklar ücretsiz, API key gerektirmez.
# Her metrik için: değer + bölge tanımı + ne anlama geldiği

import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── Bitcoin Halving Tarihleri ───────────────────────────────────────────────
HALVING_DATES = [
    datetime(2009, 1, 3,  tzinfo=timezone.utc),   # Genesis
    datetime(2012, 11, 28, tzinfo=timezone.utc),   # 1. Halving
    datetime(2016, 7, 9,   tzinfo=timezone.utc),   # 2. Halving
    datetime(2020, 5, 11,  tzinfo=timezone.utc),   # 3. Halving
    datetime(2024, 4, 19,  tzinfo=timezone.utc),   # 4. Halving (son)
    datetime(2028, 3, 15,  tzinfo=timezone.utc),   # 5. Halving (tahmini)
]


# ─── 1. Kripto Fear & Greed ──────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_crypto_fear_greed() -> dict:
    """
    alternative.me'den kripto spesifik Fear & Greed endeksi.
    CNN'in genel piyasa F&G'sinden bağımsız, sadece kripto.
    """
    try:
        import requests
        resp = requests.get(
            "https://api.alternative.me/fng/?limit=2&format=json",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return {}

        current  = data[0]
        previous = data[1] if len(data) > 1 else data[0]

        score     = int(current.get("value", 50))
        label     = current.get("value_classification", "Neutral")
        prev_score= int(previous.get("value", 50))
        change    = score - prev_score

        # Türkçe etiket ve sinyal
        if score <= 20:
            tr_label = "Aşırı Korku"
            signal   = "green"   # Buffett kuralı: korkuda al
            note     = (f"Kripto F&G: {score}/100 — AŞIRI KORKU. "
                       f"Tarihsel olarak güçlü alım fırsatı. "
                       f"2022 diplerinde 6-10 arasındaydı.")
        elif score <= 40:
            tr_label = "Korku"
            signal   = "green"
            note     = (f"Kripto F&G: {score}/100 — KORKU bölgesi. "
                       f"Orta vadeli alım için uygun zemin.")
        elif score <= 60:
            tr_label = "Nötr"
            signal   = "neutral"
            note     = f"Kripto F&G: {score}/100 — Nötr, bekle ve izle."
        elif score <= 80:
            tr_label = "Açgözlülük"
            signal   = "amber"
            note     = (f"Kripto F&G: {score}/100 — AÇGÖZLÜLÜK. "
                       f"Yeni pozisyon açmak için dikkatli ol.")
        else:
            tr_label = "Aşırı Açgözlülük"
            signal   = "red"
            note     = (f"Kripto F&G: {score}/100 — AŞIRI AÇGÖZLÜLÜK. "
                       f"Tarihsel tepeler bu bölgede oluştu. Kâr al!")

        return {
            "score":      score,
            "prev_score": prev_score,
            "change":     change,
            "label":      label,
            "tr_label":   tr_label,
            "signal":     signal,
            "note":       note,
        }
    except Exception as e:
        logger.warning("Crypto F&G failed: %s", e)
        return {"score": 50, "tr_label": "Nötr", "signal": "neutral",
                "note": "Veri alınamadı"}


# ─── 2. Bitcoin Dominance & Market Data ─────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bitcoin_dominance() -> dict:
    """
    CoinGecko'dan Bitcoin dominance ve top coin verileri.
    Bitcoin dominance > %60 = altcoin sezonu değil
    Bitcoin dominance < %40 = altcoin sezonu
    """
    try:
        import requests
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        gdata = resp.json().get("data", {})

        btc_dom  = round(gdata.get("market_cap_percentage", {}).get("bitcoin", 0), 1)
        eth_dom  = round(gdata.get("market_cap_percentage", {}).get("ethereum", 0), 1)
        total_mc = gdata.get("total_market_cap", {}).get("usd", 0)
        total_chg= round(gdata.get("market_cap_change_percentage_24h_usd", 0), 2)

        # Dominance yorumu
        if btc_dom >= 60:
            dom_signal = "amber"
            dom_note   = (f"BTC dominance %{btc_dom:.0f} — YÜKSEK. "
                         f"Altcoinler zayıf, BTC liderliği var. "
                         f"Altcoin pozisyonlarını küçük tut.")
        elif btc_dom >= 50:
            dom_signal = "neutral"
            dom_note   = (f"BTC dominance %{btc_dom:.0f} — Normal aralık. "
                         f"Karma portföy mantıklı.")
        else:
            dom_signal = "green"
            dom_note   = (f"BTC dominance %{btc_dom:.0f} — DÜŞÜK. "
                         f"Altcoin sezonu sinyali! "
                         f"ETH ve quality altcoinler BTC'yi outperform edebilir.")

        return {
            "btc_dominance":   btc_dom,
            "eth_dominance":   eth_dom,
            "total_market_cap": total_mc,
            "total_change_24h": total_chg,
            "dom_signal":      dom_signal,
            "dom_note":        dom_note,
        }
    except Exception as e:
        logger.warning("Bitcoin dominance failed: %s", e)
        return {}


# ─── 3. Fiyat Verileri (yfinance) ───────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def fetch_crypto_prices() -> dict:
    """
    BTC, ETH ve diğer major kripto fiyatları yfinance'ten.
    """
    try:
        import yfinance as yf
        tickers = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
        prices  = {}

        for symbol, yticker in tickers.items():
            try:
                fi    = yf.Ticker(yticker).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                prev  = float(getattr(fi, "previous_close", price) or price)
                chg   = (price - prev) / prev * 100 if prev > 0 else 0
                w52h  = float(getattr(fi, "year_high", 0) or 0)
                w52l  = float(getattr(fi, "year_low", 0) or 0)

                # 52H pozisyon
                pos_52h = 0
                if w52h > w52l and w52h > 0:
                    pos_52h = (price - w52l) / (w52h - w52l) * 100

                prices[symbol] = {
                    "price":    round(price, 2),
                    "change_24h": round(chg, 2),
                    "52h_pos":  round(pos_52h, 1),
                    "52h_high": round(w52h, 2),
                    "52h_low":  round(w52l, 2),
                }
                time.sleep(0.1)
            except Exception:
                pass

        return prices
    except Exception as e:
        logger.warning("Crypto prices failed: %s", e)
        return {}


# ─── 4. Halving Döngüsü ─────────────────────────────────────────────────────

def get_halving_cycle() -> dict:
    """
    Şu an hangi halving döngüsündeyiz?
    Son halving'den kaç gün geçti?
    Tarihsel döngülerde neredeyiz?
    """
    now = datetime.now(timezone.utc)

    # Son geçmiş halving
    past_halvings  = [d for d in HALVING_DATES if d <= now]
    future_halvings= [d for d in HALVING_DATES if d > now]

    last_halving = past_halvings[-1] if past_halvings else HALVING_DATES[0]
    next_halving = future_halvings[0] if future_halvings else None

    days_since  = (now - last_halving).days
    days_until  = (next_halving - now).days if next_halving else 9999
    cycle_total = (next_halving - last_halving).days if next_halving else 1460
    cycle_pct   = round(days_since / cycle_total * 100, 1)

    # Döngü fazı yorumu
    # Tarihsel: 0-12 ay = birikim, 12-24 ay = boğa başlangıç, 24-36 ay = boğa tepe/son
    if days_since <= 180:
        phase  = "Erken Birikim"
        signal = "green"
        note   = (f"Halving'den {days_since} gün geçti — erken döngü. "
                 f"Tarihsel olarak en iyi alım dönemlerinden biri.")
    elif days_since <= 365:
        phase  = "Boğa Başlangıcı"
        signal = "green"
        note   = (f"Halving'den {days_since} gün geçti — büyüme fazı başlıyor. "
                 f"Geçmiş döngülerde bu fazda güçlü yükselişler oldu.")
    elif days_since <= 548:
        phase  = "Boğa Orta Fazı"
        signal = "amber"
        note   = (f"Halving'den {days_since} gün geçti — boğa olgunlaşıyor. "
                 f"Temkinli ol, risk/ödül oranı değişiyor.")
    elif days_since <= 730:
        phase  = "Boğa Geç Fazı"
        signal = "amber"
        note   = (f"Halving'den {days_since} gün geçti — geç boğa. "
                 f"Tarihsel tepeler bu bölgede oluştu. Stop loss gir!")
    else:
        phase  = "Ayı / Birikim"
        signal = "neutral"
        note   = (f"Halving'den {days_since} gün geçti — döngü uzadı. "
                 f"Kademeli birikim dönemi, sabırlı ol.")

    return {
        "last_halving":   last_halving.strftime("%Y-%m-%d"),
        "next_halving":   next_halving.strftime("%Y-%m-%d") if next_halving else "—",
        "days_since":     days_since,
        "days_until":     days_until,
        "cycle_pct":      cycle_pct,
        "phase":          phase,
        "signal":         signal,
        "note":           note,
    }


# ─── 5. On-Chain Proxy Metrikler ─────────────────────────────────────────────

def fetch_onchain_proxies() -> dict:
    """
    Glassnode'un ücretsiz verisi çok kısıtlı.
    Bunun yerine yfinance'ten çekilebilen proxy değerleri kullan:

    MVRV Proxy: BTC Piyasa Değeri / Realized Value tahmini
    NVT Proxy: Piyasa değeri / Zincir hacmi tahmini
    Exchange Flow Proxy: BTC Spot hacim değişimi
    """
    results = {}

    try:
        import yfinance as yf

        # BTC tarihsel veri
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="2y", interval="1d")

        if len(hist) < 200:
            return results

        current_price = float(hist["Close"].iloc[-1])
        volumes       = hist["Volume"]

        # ── MVRV Proxy ───────────────────────────────────────────────────
        # Realized price ≈ 365 günlük VWAP (Volume Weighted Average Price)
        # Bu gerçek realized price değil ama iyi bir proxy
        recent_365 = hist.tail(365)
        if len(recent_365) > 0:
            vwap_365 = (recent_365["Close"] * recent_365["Volume"]).sum() / recent_365["Volume"].sum()
            mvrv_proxy = round(current_price / vwap_365, 2) if vwap_365 > 0 else 1.0

            if mvrv_proxy >= 3.5:
                mvrv_signal = "red"
                mvrv_note   = (f"MVRV Proxy: {mvrv_proxy:.2f} — YÜKSEK RİSK. "
                              f"Tarihsel tepeler 3.5-5.0 arasında oluştu. Kâr al!")
            elif mvrv_proxy >= 2.5:
                mvrv_signal = "amber"
                mvrv_note   = (f"MVRV Proxy: {mvrv_proxy:.2f} — Dikkat bölgesi. "
                              f"Hâlâ potansiyel var ama risk artıyor.")
            elif mvrv_proxy >= 1.5:
                mvrv_signal = "green"
                mvrv_note   = (f"MVRV Proxy: {mvrv_proxy:.2f} — Sağlıklı bölge. "
                              f"Çoğu yatırımcı kârda, panik satış riski düşük.")
            elif mvrv_proxy >= 1.0:
                mvrv_signal = "green"
                mvrv_note   = (f"MVRV Proxy: {mvrv_proxy:.2f} — Adil değer civarı. "
                              f"İyi alım bölgesi, uzun vadeli fırsat.")
            else:
                mvrv_signal = "green"
                mvrv_note   = (f"MVRV Proxy: {mvrv_proxy:.2f} — DİP BÖLGESİ! "
                              f"Tarihsel diplerle örtüşüyor. Güçlü alım sinyali.")

            results["mvrv_proxy"] = {
                "value":  mvrv_proxy,
                "signal": mvrv_signal,
                "note":   mvrv_note,
            }

        # ── Hacim Trendi (Exchange Flow Proxy) ────────────────────────────
        # Son 7 günlük hacim vs önceki 7 gün
        if len(hist) >= 14:
            recent_7  = float(volumes.tail(7).mean())
            prev_7    = float(volumes.tail(14).head(7).mean())
            vol_change= round((recent_7 - prev_7) / prev_7 * 100, 1) if prev_7 > 0 else 0

            if vol_change >= 50:
                vol_signal = "amber"
                vol_note   = (f"Hacim +%{vol_change:.0f} artış — yüksek aktivite. "
                             f"Borsalara büyük giriş/çıkış var, volatilite artabilir.")
            elif vol_change >= 20:
                vol_signal = "green"
                vol_note   = f"Hacim +%{vol_change:.0f} artış — sağlıklı katılım."
            elif vol_change <= -30:
                vol_signal = "amber"
                vol_note   = (f"Hacim -%{abs(vol_change):.0f} düşüş — ilgi azalıyor. "
                             f"Consolidasyon veya dip sinyali olabilir.")
            else:
                vol_signal = "neutral"
                vol_note   = f"Hacim stabil — normal seyir."

            results["volume_trend"] = {
                "value":  vol_change,
                "signal": vol_signal,
                "note":   vol_note,
            }

        # ── Momentum (RSI Proxy) ──────────────────────────────────────────
        if len(hist) >= 14:
            closes  = hist["Close"].tail(14)
            gains   = closes.diff().clip(lower=0).mean()
            losses  = (-closes.diff().clip(upper=0)).mean()
            rsi     = round(100 - (100 / (1 + gains / losses)), 1) if losses > 0 else 50

            if rsi >= 75:
                rsi_signal = "red"
                rsi_note   = f"BTC RSI: {rsi} — AŞIRI ALIM. Kısa vadeli düzeltme riski."
            elif rsi >= 55:
                rsi_signal = "amber"
                rsi_note   = f"BTC RSI: {rsi} — Yüksek momentum, dikkatli ol."
            elif rsi <= 25:
                rsi_signal = "green"
                rsi_note   = f"BTC RSI: {rsi} — AŞIRI SATIŞ. Güçlü alım sinyali."
            elif rsi <= 45:
                rsi_signal = "green"
                rsi_note   = f"BTC RSI: {rsi} — Düşük, alım fırsatı."
            else:
                rsi_signal = "neutral"
                rsi_note   = f"BTC RSI: {rsi} — Nötr bölge."

            results["btc_rsi"] = {
                "value":  rsi,
                "signal": rsi_signal,
                "note":   rsi_note,
            }

    except Exception as e:
        logger.warning("On-chain proxies failed: %s", e)

    return results


# ─── 6. Stablecoin Dominance ─────────────────────────────────────────────────

def fetch_stablecoin_dominance() -> dict:
    """
    Stablecoin dominance — piyasadaki nakit oranı.
    Yüksek → herkes nakit tutuyor, alım gücü birikmiş
    Düşük  → herkes yatırımda, nakit azaldı
    """
    try:
        import requests
        resp = requests.get(
            "https://api.coingecko.com/api/v3/global",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        gdata = resp.json().get("data", {})
        mc_pct = gdata.get("market_cap_percentage", {})

        usdt_dom = round(mc_pct.get("tether", 0), 1)
        usdc_dom = round(mc_pct.get("usd-coin", 0), 1)
        total_stable = round(usdt_dom + usdc_dom, 1)

        if total_stable >= 12:
            signal = "green"
            note   = (f"Stablecoin dominance %{total_stable:.1f} — YÜKSEK. "
                     f"Piyasada bol nakit birikmiş, potansiyel alım gücü var.")
        elif total_stable >= 8:
            signal = "neutral"
            note   = f"Stablecoin dominance %{total_stable:.1f} — Normal aralık."
        else:
            signal = "amber"
            note   = (f"Stablecoin dominance %{total_stable:.1f} — DÜŞÜK. "
                     f"Herkes yatırımda, yeni alım gücü sınırlı.")

        return {
            "usdt_dom":     usdt_dom,
            "usdc_dom":     usdc_dom,
            "total_stable": total_stable,
            "signal":       signal,
            "note":         note,
        }
    except Exception as e:
        logger.warning("Stablecoin dominance failed: %s", e)
        return {}


# ─── 7. Portföy Kripto Verisi ────────────────────────────────────────────────

def fetch_crypto_portfolio_data(crypto_positions: list) -> dict:
    """
    Kullanıcının kripto pozisyonları için detaylı veri.
    crypto_positions: [{"ticker": "BTC-USD", "shares": 0.5, "avg_cost": 50000}]
    """
    if not crypto_positions:
        return {}

    try:
        import yfinance as yf
        results = {}

        for pos in crypto_positions:
            ticker = pos.get("ticker", "")
            if not ticker:
                continue
            try:
                fi    = yf.Ticker(ticker).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                prev  = float(getattr(fi, "previous_close", price) or price)
                chg   = (price - prev) / prev * 100 if prev > 0 else 0

                shares   = float(pos.get("shares", 0) or 0)
                avg_cost = float(pos.get("avg_cost", 0) or 0)
                value    = shares * price
                cost     = shares * avg_cost
                pnl_pct  = (price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

                results[ticker] = {
                    "price":    round(price, 2),
                    "change":   round(chg, 2),
                    "value":    round(value, 2),
                    "pnl_pct":  round(pnl_pct, 1),
                }
                time.sleep(0.1)
            except Exception:
                pass

        return results
    except Exception as e:
        logger.warning("Crypto portfolio failed: %s", e)
        return {}


# ─── Ana Toplayıcı ───────────────────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def fetch_all_crypto_data(crypto_positions: tuple = None) -> dict:
    """
    Tüm Katman 3 verilerini tek seferde topla.
    Her metrik: değer + sinyal + not
    """
    logger.info("Kripto verileri toplanıyor...")
    data = {
        "fear_greed":        fetch_crypto_fear_greed(),
        "dominance":         fetch_bitcoin_dominance(),
        "prices":            fetch_crypto_prices(),
        "halving":           get_halving_cycle(),
        "onchain":           fetch_onchain_proxies(),
        "stablecoin":        fetch_stablecoin_dominance(),
        "long_short":        fetch_long_short_ratio(),
        "exchange_flow":     fetch_exchange_net_flow(),
        "nvt":               fetch_nvt_signal(),
        "active_addresses":  fetch_active_addresses_proxy(),
        "sopr":              fetch_sopr_proxy(),
        "portfolio":         fetch_crypto_portfolio_data(crypto_positions or []),
        "fetched_at":        datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Kripto verisi tamamlandı.")
    return data


def build_crypto_prompt(data: dict) -> str:
    """
    Kripto verilerini Claude analizi için formatlı metne dönüştür.
    """
    lines = ["=== KRİPTO PİYASASI ANALİZİ ==="]

    fg  = data.get("fear_greed", {})
    dom = data.get("dominance", {})
    hal = data.get("halving", {})
    onc = data.get("onchain", {})
    stb = data.get("stablecoin", {})
    prc = data.get("prices", {})

    # Fear & Greed
    if fg:
        lines.append(f"Fear & Greed: {fg.get('score','—')}/100 — {fg.get('tr_label','—')}")
        lines.append(f"  → {fg.get('note','')}")

    # BTC fiyatı
    btc = prc.get("BTC", {})
    if btc:
        lines.append(f"\nBTC: ${btc.get('price',0):,.0f} ({btc.get('change_24h',0):+.1f}%)")
        lines.append(f"  52H Pozisyon: %{btc.get('52h_pos',0):.0f}")

    # Dominance
    if dom:
        lines.append(f"\nBTC Dominance: %{dom.get('btc_dominance',0):.1f}")
        lines.append(f"  → {dom.get('dom_note','')}")

    # Halving döngüsü
    if hal:
        lines.append(f"\nHalving Döngüsü: {hal.get('phase','—')} ({hal.get('days_since',0)} gün)")
        lines.append(f"  → {hal.get('note','')}")

    # On-chain proxies
    mvrv = onc.get("mvrv_proxy", {})
    if mvrv:
        lines.append(f"\n{mvrv.get('note','')}")

    rsi = onc.get("btc_rsi", {})
    if rsi:
        lines.append(f"{rsi.get('note','')}")

    vol = onc.get("volume_trend", {})
    if vol:
        lines.append(f"{vol.get('note','')}")

    # Stablecoin
    if stb:
        lines.append(f"\n{stb.get('note','')}")

    # Long/Short Ratio
    ls = data.get("long_short", {})
    if ls:
        lines.append(f"\n{ls.get('note','')}")

    # Exchange Net Flow
    ef = data.get("exchange_flow", {})
    if ef:
        lines.append(f"{ef.get('note','')}")

    # NVT Signal
    nvt = data.get("nvt", {})
    if nvt:
        lines.append(f"{nvt.get('note','')}")

    # Active Addresses
    aa = data.get("active_addresses", {})
    if aa:
        lines.append(f"{aa.get('note','')}")

    # SOPR
    sopr = data.get("sopr", {})
    if sopr:
        lines.append(f"{sopr.get('note','')}")

    return "\n".join(lines)


def get_crypto_signal_summary(data: dict) -> dict:
    """
    Tüm kripto sinyallerini özetle.
    Returns: {overall: green/amber/red, score: 0-100, summary: str}
    """
    signals = []

    fg_score = data.get("fear_greed", {}).get("score", 50)
    hal_sig  = data.get("halving", {}).get("signal", "neutral")
    mvrv_sig = data.get("onchain", {}).get("mvrv_proxy", {}).get("signal", "neutral")
    rsi_sig  = data.get("onchain", {}).get("btc_rsi", {}).get("signal", "neutral")
    stb_sig  = data.get("stablecoin", {}).get("signal", "neutral")
    dom_sig  = data.get("dominance", {}).get("dom_signal", "neutral")

    # Puanlama: green=2, amber=1, neutral=0, red=-1
    score_map = {"green": 2, "amber": 1, "neutral": 0, "red": -1}
    # F&G ters mantık: düşük F&G = iyi alım
    fg_signal = "green" if fg_score <= 30 else ("red" if fg_score >= 75 else "neutral")

    total = sum(score_map.get(s, 0) for s in [
        fg_signal, hal_sig, mvrv_sig, rsi_sig, stb_sig
    ])
    max_score = 10
    pct_score = round((total + max_score) / (2 * max_score) * 100)

    if pct_score >= 65:
        overall = "green"
        summary = "Kripto ortamı OLUMLU — alım fırsatı var"
    elif pct_score >= 40:
        overall = "neutral"
        summary = "Kripto ortamı KARMA — seçici ol"
    else:
        overall = "red"
        summary = "Kripto ortamı OLUMSUZ — risk yüksek"

    return {
        "overall":  overall,
        "score":    pct_score,
        "summary":  summary,
    }


# ─── 8. Long/Short Ratio (Coinglass) ────────────────────────────────────────

def fetch_long_short_ratio() -> dict:
    """
    Coinglass'tan BTC Long/Short oranı.
    Yüksek long → long squeeze riski
    Yüksek short → short squeeze fırsatı
    """
    try:
        import requests
        # Coinglass ücretsiz endpoint
        resp = requests.get(
            "https://open-api.coinglass.com/public/v2/indicator/long_short_account_ratio",
            params={"symbol": "BTC", "interval": "1h", "limit": 2},
            headers={
                "User-Agent":   "Mozilla/5.0",
                "coinglassSecret": "",  # Ücretsiz — key olmadan da temel veri gelir
            },
            timeout=10,
        )

        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data and len(data) > 0:
                latest   = data[0]
                ls_ratio = float(latest.get("longAccount", 0))
                ss_ratio = float(latest.get("shortAccount", 0))

                if ls_ratio > 0.65:
                    signal = "red"
                    note   = (f"Long/Short: %{ls_ratio*100:.0f} long — AŞIRI LONG. "
                             f"Long squeeze riski yüksek! Fiyat düşerse uzun pozisyonlar tasfiye edilir.")
                elif ls_ratio < 0.40:
                    signal = "green"
                    note   = (f"Long/Short: %{(1-ls_ratio)*100:.0f} short ağırlıklı — SHORT SQUEEZE potansiyeli. "
                             f"Fiyat yükselirse shortlar kapanmak zorunda kalır.")
                else:
                    signal = "neutral"
                    note   = (f"Long/Short: %{ls_ratio*100:.0f} long / %{ss_ratio*100:.0f} short — "
                             f"Dengeli pozisyon dağılımı.")

                return {
                    "long_pct":  round(ls_ratio * 100, 1),
                    "short_pct": round(ss_ratio * 100, 1),
                    "signal":    signal,
                    "note":      note,
                }

        # Fallback: alternatif yöntem - BTC perpetual funding rate proxy
        raise Exception("Coinglass API yanıt vermedi, fallback kullanılıyor")

    except Exception:
        # Funding Rate proxy: yfinance'ten BTC volatilitesinden L/S tahmini
        try:
            import yfinance as yf
            btc_hist = yf.Ticker("BTC-USD").history(period="3d", interval="1h")["Close"]
            if len(btc_hist) >= 6:
                recent_chg = (btc_hist.iloc[-1] - btc_hist.iloc[-6]) / btc_hist.iloc[-6] * 100
                if recent_chg > 3:
                    return {"long_pct": 65, "short_pct": 35, "signal": "red",
                            "note": "Fiyat hızlı yükseldi — muhtemelen yüksek long oranı, squeeze riski var"}
                elif recent_chg < -3:
                    return {"long_pct": 35, "short_pct": 65, "signal": "green",
                            "note": "Fiyat hızlı düştü — short ağırlıklı olabilir, short squeeze fırsatı"}
                else:
                    return {"long_pct": 50, "short_pct": 50, "signal": "neutral",
                            "note": "Long/Short oranı: Dengeli görünüm (API verisi mevcut değil)"}
        except Exception as e:
            logger.debug("Long/Short fallback failed: %s", e)

    return {"signal": "neutral", "note": "Long/Short verisi alınamadı"}


# ─── 9. Exchange Net Flow (Gerçek) ───────────────────────────────────────────

def fetch_exchange_net_flow() -> dict:
    """
    Borsalara giren/çıkan BTC miktarı.
    Glassnode ücretsiz katmanı çok kısıtlı.
    CryptoQuant'ın halka açık verilerinden proxy.
    Fallback: yfinance BTC spot hacim vs futures hacim farkı.
    """
    try:
        import requests
        # CryptoQuant'ın halka açık özet verisi
        resp = requests.get(
            "https://api.cryptoquant.com/live/v2/charts/bitcoin/mpi",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            # MPI (Miner Position Index) — madencilerin satış baskısı
            value = float(data.get("value", 0))
            if value > 2:
                return {"value": value, "signal": "red",
                        "note": f"Madenci Satış Baskısı (MPI: {value:.1f}) — madenciler agresif satıyor, arz baskısı yüksek"}
            elif value < 0:
                return {"value": value, "signal": "green",
                        "note": f"Madenci Birikimi (MPI: {value:.1f}) — madenciler tutuyor, arz baskısı düşük"}
            else:
                return {"value": value, "signal": "neutral",
                        "note": f"Madenci Akışı Normal (MPI: {value:.1f})"}
    except Exception:
        pass

    # Gelişmiş proxy: BTC Spot vs ETF hacim farkı
    try:
        import yfinance as yf
        # IBIT (BlackRock BTC ETF) hacmi = kurumsal talep göstergesi
        ibit_hist = yf.Ticker("IBIT").history(period="5d", interval="1d")
        btc_hist  = yf.Ticker("BTC-USD").history(period="5d", interval="1d")

        if len(ibit_hist) >= 3 and len(btc_hist) >= 3:
            ibit_vol_chg = (ibit_hist["Volume"].iloc[-1] - ibit_hist["Volume"].iloc[-3]) / ibit_hist["Volume"].iloc[-3] * 100
            btc_vol_chg  = (btc_hist["Volume"].iloc[-1]  - btc_hist["Volume"].iloc[-3])  / btc_hist["Volume"].iloc[-3]  * 100

            if ibit_vol_chg > 30:
                return {
                    "signal": "green",
                    "note": f"BTC ETF (IBIT) hacmi +%{ibit_vol_chg:.0f} artış — kurumsal talep güçleniyor, alım akışı var"
                }
            elif ibit_vol_chg < -30:
                return {
                    "signal": "amber",
                    "note": f"BTC ETF (IBIT) hacmi -%{abs(ibit_vol_chg):.0f} düşüş — kurumsal ilgi azalıyor"
                }
            else:
                return {
                    "signal": "neutral",
                    "note": f"BTC ETF (IBIT) hacmi stabil — kurumsal talep normal seyrediyor"
                }
    except Exception as e:
        logger.debug("Exchange flow proxy failed: %s", e)

    return {"signal": "neutral", "note": "Exchange Net Flow verisi alınamadı"}


# ─── 10. NVT Signal ──────────────────────────────────────────────────────────

def fetch_nvt_signal() -> dict:
    """
    NVT (Network Value to Transactions) proxy.
    Piyasa değeri / Zincir üzeri işlem hacmi.
    Yüksek NVT = fiyat fundamentallerden kopmuş, spekülatif.
    Düşük NVT  = ağ yoğun kullanılıyor, fiyat ucuz kalabilir.

    Proxy hesabı:
    - BTC Piyasa Değeri: yfinance'ten market cap
    - İşlem Hacmi proxy: BTC-USD günlük işlem hacmi
    """
    try:
        import yfinance as yf
        btc_hist = yf.Ticker("BTC-USD").history(period="90d", interval="1d")

        if len(btc_hist) < 30:
            return {}

        # Piyasa değeri proxy: fiyat × 19.7M (yaklaşık dolaşımdaki BTC)
        BTC_SUPPLY = 19_700_000
        prices     = btc_hist["Close"]
        volumes    = btc_hist["Volume"]  # USD cinsinden işlem hacmi

        # NVT = Market Cap / Daily Transaction Volume
        market_cap      = prices.iloc[-1] * BTC_SUPPLY
        recent_vol_avg  = float(volumes.tail(14).mean())  # 14 günlük ort. hacim

        if recent_vol_avg <= 0:
            return {}

        nvt = round(market_cap / recent_vol_avg, 1)

        # NVT Signal = NVT'nin 90 günlük hareketli ortalaması
        nvt_series = (prices * BTC_SUPPLY) / volumes
        nvt_signal_val = round(float(nvt_series.tail(90).mean()), 1)
        nvt_current    = round(float(nvt_series.iloc[-1]), 1)

        # Normalize: mevcut / 90 gün ortalaması
        nvt_ratio = round(nvt_current / nvt_signal_val, 2) if nvt_signal_val > 0 else 1.0

        if nvt_ratio >= 1.5:
            signal = "red"
            note   = (f"NVT Signal: {nvt_current:.0f} (90g ort. {nvt_signal_val:.0f}, ratio: {nvt_ratio:.2f}) — "
                     f"YÜKSEK. Piyasa değeri işlem hacminin çok üzerinde: spekülatif balonun işareti olabilir.")
        elif nvt_ratio >= 1.2:
            signal = "amber"
            note   = (f"NVT Signal: {nvt_current:.0f} (ratio: {nvt_ratio:.2f}) — "
                     f"Orta-yüksek. Dikkatli izle.")
        elif nvt_ratio <= 0.7:
            signal = "green"
            note   = (f"NVT Signal: {nvt_current:.0f} (ratio: {nvt_ratio:.2f}) — "
                     f"DÜŞÜK. Ağ yoğun kullanılıyor, fiyat fundamentallere göre cazip.")
        else:
            signal = "neutral"
            note   = (f"NVT Signal: {nvt_current:.0f} (ratio: {nvt_ratio:.2f}) — "
                     f"Normal aralıkta.")

        return {
            "nvt_current": nvt_current,
            "nvt_signal":  nvt_signal_val,
            "nvt_ratio":   nvt_ratio,
            "signal":      signal,
            "note":        note,
        }

    except Exception as e:
        logger.debug("NVT failed: %s", e)
        return {}


# ─── 11. Active Addresses Proxy ──────────────────────────────────────────────

def fetch_active_addresses_proxy() -> dict:
    """
    Günlük aktif Bitcoin cüzdan sayısı proxy.
    Glassnode ücretsiz API çok kısıtlı.
    Proxy: BTC işlem sayısı ve unique address count tahmin.

    blockchain.info'nun halka açık istatistikleri kullanılır.
    """
    try:
        import requests
        # blockchain.info halka açık API — ücretsiz
        resp = requests.get(
            "https://api.blockchain.info/stats",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code == 200:
            stats = resp.json()

            n_tx         = int(stats.get("n_tx", 0))
            # 24h active addresses tahmin: tx sayısı × ortalama address per tx (≈1.7)
            active_est   = round(n_tx * 1.7 / 1000)  # Binler cinsinden

            # Tarihsel referans: ~800K-1.2M aktif adres normal, 1.5M+ boğa
            if active_est >= 1500:
                signal = "green"
                note   = (f"Aktif Adres Proxy: ~{active_est}K/gün — YÜKSEK katılım. "
                         f"Ağ aktivitesi güçlü, yeni kullanıcı girişi devam ediyor.")
            elif active_est >= 800:
                signal = "neutral"
                note   = (f"Aktif Adres Proxy: ~{active_est}K/gün — Normal aktivite.")
            elif active_est >= 400:
                signal = "amber"
                note   = (f"Aktif Adres Proxy: ~{active_est}K/gün — Düşük aktivite. "
                         f"Katılım azalıyor, dikkat.")
            else:
                signal = "amber"
                note   = (f"Aktif Adres Proxy: ~{active_est}K/gün — Çok düşük aktivite. "
                         f"Konsolidasyon dönemi veya ilgi kaybı.")

            return {
                "n_tx":       n_tx,
                "active_est": active_est,
                "signal":     signal,
                "note":       note,
            }
    except Exception as e:
        logger.debug("Active addresses failed: %s", e)

    return {"signal": "neutral", "note": "Aktif adres verisi alınamadı"}


# ─── 12. SOPR Proxy ──────────────────────────────────────────────────────────

def fetch_sopr_proxy() -> dict:
    """
    SOPR (Spent Output Profit Ratio) proxy.
    Gerçek SOPR Glassnode premium endpoint gerektirir.
    Proxy: Kısa vadeli tutulan BTC'nin kâr/zarar durumu.

    Yöntem: 1-30 gün önce alınan BTC'nin ortalama maliyeti vs mevcut fiyat.
    30 günlük VWAP < mevcut fiyat → SOPR > 1 (kâr realizasyonu)
    30 günlük VWAP > mevcut fiyat → SOPR < 1 (zarar realizasyonu = dip)
    """
    try:
        import yfinance as yf
        btc_hist = yf.Ticker("BTC-USD").history(period="60d", interval="1d")

        if len(btc_hist) < 30:
            return {}

        current_price = float(btc_hist["Close"].iloc[-1])

        # 7 günlük VWAP (kısa vadeli tutuculara proxy)
        recent_7   = btc_hist.tail(7)
        vwap_7     = float((recent_7["Close"] * recent_7["Volume"]).sum() / recent_7["Volume"].sum()) if recent_7["Volume"].sum() > 0 else current_price

        # 30 günlük VWAP (orta vadeli tutuculara proxy)
        recent_30  = btc_hist.tail(30)
        vwap_30    = float((recent_30["Close"] * recent_30["Volume"]).sum() / recent_30["Volume"].sum()) if recent_30["Volume"].sum() > 0 else current_price

        sopr_proxy_7  = round(current_price / vwap_7,  3)
        sopr_proxy_30 = round(current_price / vwap_30, 3)

        # Yorumla — SOPR 1'in altı en kritik sinyal
        if sopr_proxy_7 < 0.95:
            signal = "green"
            note   = (f"SOPR Proxy (7g): {sopr_proxy_7:.3f} — 1'İN ALTI. "
                     f"Kısa vadeli tutuculAR ZARAR REALIZE EDİYOR. "
                     f"Tarihsel olarak dip bölgeleriyle örtüşür. Güçlü alım sinyali.")
        elif sopr_proxy_7 < 1.0:
            signal = "green"
            note   = (f"SOPR Proxy (7g): {sopr_proxy_7:.3f} — Hafif zarar bölgesi. "
                     f"Zayıf eller temizleniyor, dip arayışı devam ediyor.")
        elif sopr_proxy_7 < 1.05:
            signal = "neutral"
            note   = (f"SOPR Proxy (7g): {sopr_proxy_7:.3f} — 1 civarı. "
                     f"Kâr ve zarar dengeli, piyasa kararsız.")
        elif sopr_proxy_7 < 1.15:
            signal = "amber"
            note   = (f"SOPR Proxy (7g): {sopr_proxy_7:.3f} — Kâr realizasyonu var. "
                     f"Kısa vadeli satış baskısı devam edebilir.")
        else:
            signal = "red"
            note   = (f"SOPR Proxy (7g): {sopr_proxy_7:.3f} — YÜKSEK kâr realizasyonu. "
                     f"Büyük kâr satışları dönemindeyiz, tepe yakın olabilir.")

        return {
            "sopr_7d":  sopr_proxy_7,
            "sopr_30d": sopr_proxy_30,
            "signal":   signal,
            "note":     note,
        }

    except Exception as e:
        logger.debug("SOPR proxy failed: %s", e)
        return {}


# ─── CoinGecko Fiyat Çekici (yfinance fallback) ──────────────────────────────

# Bilinen sembol → CoinGecko ID eşlemesi
# CoinGecko sembol bazlı arama bazen birden fazla coin döndürür
# Bu map en yaygın coinler için doğru ID'yi garantiler
COINGECKO_ID_MAP = {
    "BTC":   "bitcoin",         "ETH":   "ethereum",
    "BNB":   "binancecoin",     "SOL":   "solana",
    "XRP":   "ripple",          "ADA":   "cardano",
    "AVAX":  "avalanche-2",     "DOT":   "polkadot",
    "MATIC": "matic-network",   "POL":   "matic-network",
    "LINK":  "chainlink",       "UNI":   "uniswap",
    "ATOM":  "cosmos",          "LTC":   "litecoin",
    "BCH":   "bitcoin-cash",    "ALGO":  "algorand",
    "XLM":   "stellar",         "VET":   "vechain",
    "FIL":   "filecoin",        "ICP":   "internet-computer",
    "HBAR":  "hedera-hashgraph","SAND":  "the-sandbox",
    "MANA":  "decentraland",    "AXS":   "axie-infinity",
    "THETA": "theta-token",     "ETC":   "ethereum-classic",
    "XMR":   "monero",          "AAVE":  "aave",
    "GRT":   "the-graph",       "MKR":   "maker",
    "SNX":   "havven",          "COMP":  "compound-governance-token",
    "YFI":   "yearn-finance",   "SUSHI": "sushi",
    "CRV":   "curve-dao-token", "1INCH": "1inch",
    "ENJ":   "enjincoin",       "CHZ":   "chiliz",
    "BAT":   "basic-attention-token",
    "ZIL":   "zilliqa",         "IOTA":  "iota",
    "NEO":   "neo",             "WAVES": "waves",
    "DASH":  "dash",            "ZEC":   "zcash",
    "DOGE":  "dogecoin",        "SHIB":  "shiba-inu",
    "PEPE":  "pepe",            "WIF":   "dogwifcoin",
    "BONK":  "bonk",            "FLOKI": "floki",
    "TRX":   "tron",            "TON":   "the-open-network",
    "SUI":   "sui",             "APT":   "aptos",
    "ARB":   "arbitrum",        "OP":    "optimism",
    "INJ":   "injective-protocol",
    "SEI":   "sei-network",     "TIA":   "celestia",
    "JUP":   "jupiter-exchange-solana",
    "PYTH":  "pyth-network",    "WEN":   "wen-4",
    "RNDR":  "render-token",    "FET":   "fetch-ai",
    "AGIX":  "singularitynet",  "OCEAN": "ocean-protocol",
    "NOT":   "notcoin",         "HMSTR": "hamster-kombat",
}


def get_coingecko_id(symbol: str) -> str | None:
    """
    Sembolden CoinGecko ID'yi bul.
    Önce bilinen map'te ara, sonra API'den ara.
    """
    symbol_clean = symbol.replace("-USD", "").upper()

    # Bilinen map'te ara
    if symbol_clean in COINGECKO_ID_MAP:
        return COINGECKO_ID_MAP[symbol_clean]

    # CoinGecko search API'den ara
    try:
        import requests
        resp = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol_clean},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if resp.status_code == 200:
            coins = resp.json().get("coins", [])
            # İlk sonuç — sembol tam eşleşmesi öncelikli
            for coin in coins[:5]:
                if coin.get("symbol", "").upper() == symbol_clean:
                    return coin["id"]
            # Tam eşleşme yoksa ilk sonuç
            if coins:
                return coins[0]["id"]
    except Exception as e:
        logger.debug("CoinGecko search failed %s: %s", symbol_clean, e)
    return None


def fetch_price_coingecko(symbol: str) -> dict:
    """
    CoinGecko'dan coin fiyatı çek.
    yfinance'ta olmayan altcoinler için fallback.
    Returns: {price, change_24h, market_cap, volume_24h, found}
    """
    try:
        import requests

        cg_id = get_coingecko_id(symbol)
        if not cg_id:
            return {"found": False, "error": f"{symbol} CoinGecko'da bulunamadı"}

        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{cg_id}",
            params={
                "localization":   "false",
                "tickers":        "false",
                "market_data":    "true",
                "community_data": "false",
                "developer_data": "false",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )

        if resp.status_code == 429:
            return {"found": False, "error": "CoinGecko rate limit — biraz bekle"}
        if resp.status_code != 200:
            return {"found": False, "error": f"CoinGecko HTTP {resp.status_code}"}

        data = resp.json()
        md   = data.get("market_data", {})

        price      = float(md.get("current_price",        {}).get("usd", 0) or 0)
        change_24h = float(md.get("price_change_percentage_24h", 0) or 0)
        market_cap = float(md.get("market_cap",           {}).get("usd", 0) or 0)
        volume_24h = float(md.get("total_volume",         {}).get("usd", 0) or 0)
        high_24h   = float(md.get("high_24h",             {}).get("usd", 0) or 0)
        low_24h    = float(md.get("low_24h",              {}).get("usd", 0) or 0)
        ath        = float(md.get("ath",                  {}).get("usd", 0) or 0)
        ath_chg    = float(md.get("ath_change_percentage",{}).get("usd", 0) or 0)

        return {
            "found":      True,
            "symbol":     symbol,
            "cg_id":      cg_id,
            "name":       data.get("name", symbol),
            "price":      round(price,      8),
            "change_24h": round(change_24h, 2),
            "market_cap": market_cap,
            "volume_24h": volume_24h,
            "high_24h":   round(high_24h,   8),
            "low_24h":    round(low_24h,    8),
            "ath":        round(ath,        8),
            "ath_chg":    round(ath_chg,    2),
            "source":     "coingecko",
        }

    except Exception as e:
        logger.warning("CoinGecko price failed %s: %s", symbol, e)
        return {"found": False, "error": str(e)}


def fetch_crypto_price_universal(symbol: str) -> dict:
    """
    Evrensel kripto fiyat çekici.
    1. yfinance dene — fiyatı CoinGecko ile çapraz doğrula
    2. Şüpheli/yanlış fiyat varsa CoinGecko'yu tercih et
    3. Hata döndür
    """
    symbol_clean = symbol.replace("-USD", "").upper()
    yf_ticker    = f"{symbol_clean}-USD"

    # yfinance'te sorunlu bilinen coinler — direkt CoinGecko
    CG_PREFERRED = {
        "JUP", "WIF", "BONK", "PEPE", "FLOKI", "NOT", "HMSTR",
        "PYTH", "TIA", "SEI", "WEN", "RNDR", "FET", "AGIX",
        "JTO", "BOME", "POPCAT", "MEW", "SLERF", "PONKE",
    }

    yf_price = 0.0
    yf_chg   = 0.0

    # ── 1. yfinance ──────────────────────────────────────────────────────
    if symbol_clean not in CG_PREFERRED:
        try:
            import yfinance as yf
            fi       = yf.Ticker(yf_ticker).fast_info
            yf_price = float(getattr(fi, "last_price",     0) or 0)
            yf_prev  = float(getattr(fi, "previous_close", yf_price) or yf_price)
            yf_chg   = (yf_price - yf_prev) / yf_prev * 100 if yf_prev > 0 else 0
        except Exception:
            yf_price = 0.0

    # ── 2. CoinGecko ile doğrula / fallback ──────────────────────────────
    need_cg = (yf_price <= 0 or symbol_clean in CG_PREFERRED
               or symbol_clean in COINGECKO_ID_MAP)

    if need_cg:
        time.sleep(0.2)
        cg_result = fetch_price_coingecko(symbol_clean)
        if cg_result.get("found") and cg_result.get("price", 0) > 0:
            cg_price = float(cg_result["price"])
            if yf_price > 0 and cg_price > 0:
                ratio = yf_price / cg_price
                if 0.5 <= ratio <= 2.0:
                    # yfinance tutarlı — güvenilir
                    return {"found": True, "symbol": symbol_clean, "name": symbol_clean,
                            "price": round(yf_price, 8), "change_24h": round(yf_chg, 2),
                            "source": "yfinance"}
                else:
                    # yfinance sapıyor — CoinGecko kullan
                    logger.debug("%s yfinance %.8f vs CG %.8f — CoinGecko tercih edildi",
                                 symbol_clean, yf_price, cg_price)
            return cg_result

    if yf_price > 0:
        return {"found": True, "symbol": symbol_clean, "name": symbol_clean,
                "price": round(yf_price, 8), "change_24h": round(yf_chg, 2),
                "source": "yfinance"}

    return {"found": False, "symbol": symbol_clean, "price": 0,
            "error": f"{symbol_clean} bulunamadı"}


def fetch_crypto_portfolio_prices(positions: list) -> dict:
    """
    Kripto portföyü için tüm coin fiyatlarını çek.
    yfinance + CoinGecko kombinasyonu.
    positions: [{"ticker": "BTC-USD", "shares": 0.5, "avg_cost": 45000}, ...]
    """
    results = {}
    for pos in positions:
        ticker = pos.get("ticker", "")
        if not ticker:
            continue
        price_data = fetch_crypto_price_universal(ticker)
        results[ticker] = price_data
        time.sleep(0.2)  # Rate limit koruması
    return results
