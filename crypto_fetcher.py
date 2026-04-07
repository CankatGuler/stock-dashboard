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
import os
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ─── Alphractal API Yardımcı ─────────────────────────────────────────────────

ALPHRACTAL_BASE = "https://api.alphractal.com"

def _alphractal_get(path: str, asset: str = "btc", days: int = 3) -> list:
    """
    Alphractal API'den veri çek.
    path: /{asset}/market/Mvrv_zscore gibi, {asset} otomatik replace edilir.
    """
    import requests
    api_key = os.getenv("ALPHRACTAL_API_KEY", "")
    if not api_key:
        logger.warning("ALPHRACTAL_API_KEY eksik — Alphractal verisi çekilemiyor")
        return []

    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT00:00:00Z"
    )
    url = f"{ALPHRACTAL_BASE}{path.replace('{asset}', asset)}"
    try:
        resp = requests.get(
            url,
            headers={"X-Api-Key": api_key},
            params={"startDate": start},
            timeout=12,
        )
        if resp.status_code == 200:
            data = resp.json() or []
            logger.info("Alphractal OK: %s → %d kayıt", path, len(data))
            return data
        logger.warning("Alphractal %s → HTTP %s: %s", path, resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Alphractal hata %s: %s", path, e)
    return []


def _alph_latest(path: str, field: str, asset: str = "btc") -> float | None:
    """Alphractal'dan en son günün değerini çek."""
    data = _alphractal_get(path, asset=asset, days=5)
    if data:
        last = data[-1]
        val  = last.get(field)
        if val is not None:
            return float(val)
    return None

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
            "index":      score,   # HTML fg.index olarak bekliyor
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

def fetch_bitcoin_dominance() -> dict:
    """
    BTC/ETH dominans + TOTAL2/TOTAL3.
    Kaynak sırası: CoinGecko → alternative.me → yfinance proxy
    """
    import requests

    def _build(btc_dom, eth_dom, total2_pct, total3_pct, total_mc, total_chg, proxy=False):
        tag = " (tahmini)" if proxy else ""
        if btc_dom >= 60:
            sig, note = "amber", f"BTC dominance %{btc_dom:.1f}{tag} — YÜKSEK. Para altcoinlerden kaçıyor."
        elif btc_dom >= 52:
            sig, note = "neutral", f"BTC dominance %{btc_dom:.1f}{tag} — Normal aralık."
        else:
            sig, note = "green", f"BTC dominance %{btc_dom:.1f}{tag} — DÜŞÜK. Altcoin sezonu sinyali."
        t3_note = "BTC + ETH hariç saf altcoin piyasası" if total3_pct > 0 else ""
        return {
            "btc_dominance": btc_dom, "eth_dominance": eth_dom,
            "total2_pct": total2_pct, "total3_pct": total3_pct,
            "total_market_cap": total_mc, "total_change_24h": total_chg,
            "total2_change_24h": 0, "total3_change_24h": 0,
            "total3_note": t3_note, "dom_signal": sig, "dom_note": note, "note": note,
        }

    # Kaynak 1: CoinGecko
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if r.status_code == 200:
            g = r.json().get("data", {})
            mc = g.get("market_cap_percentage", {})
            btc = round(mc.get("bitcoin",  0), 1)
            eth = round(mc.get("ethereum", 0), 1)
            total_mc  = g.get("total_market_cap", {}).get("usd", 0)
            total_chg = round(g.get("market_cap_change_percentage_24h_usd", 0), 2)
            if btc > 0:
                t2 = round(100 - btc, 1)
                t3 = round(100 - btc - eth, 1)
                return _build(btc, eth, t2, t3, total_mc, total_chg)
    except Exception as e:
        logger.debug("CoinGecko: %s", e)

    # Kaynak 2: alternative.me
    try:
        r = requests.get("https://api.alternative.me/v1/global/",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if r.status_code == 200:
            g = r.json()
            btc = round(float(g.get("bitcoin_percentage_of_market_cap", 0)), 1)
            total_mc = float(g.get("total_market_cap_usd", 0))
            if btc > 0:
                return _build(btc, 0, round(100-btc,1), 0, total_mc, 0)
    except Exception as e:
        logger.debug("alternative.me: %s", e)

    # Kaynak 3: yfinance BTC market cap proxy
    try:
        import yfinance as yf
        btc_h = yf.Ticker("BTC-USD").history(period="2d")
        eth_h = yf.Ticker("ETH-USD").history(period="2d")
        if not btc_h.empty:
            btc_p = float(btc_h["Close"].iloc[-1])
            eth_p = float(eth_h["Close"].iloc[-1]) if not eth_h.empty else 0
            btc_mc  = btc_p * 19_700_000
            eth_mc  = eth_p * 120_000_000
            total_mc = btc_mc * 2.2
            btc_dom  = round(btc_mc  / total_mc * 100, 1)
            eth_dom  = round(eth_mc  / total_mc * 100, 1)
            t2 = round(100 - btc_dom, 1)
            t3 = round(100 - btc_dom - eth_dom, 1)
            return _build(btc_dom, eth_dom, t2, t3, total_mc, 0, proxy=True)
    except Exception as e:
        logger.debug("yfinance proxy: %s", e)

    logger.warning("Tüm dominance kaynakları başarısız")
    return {}

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
    On-chain metrikler — Alphractal API (gerçek veri) + yfinance fallback.
    MVRV Z-Score, NUPL, STH/LTH MVRV, BTC RSI, Hacim Trendi.
    """
    results = {}

    # ── MVRV Z-Score (Alphractal) ─────────────────────────────────────────
    mvrv_z = _alph_latest("/{asset}/market/Mvrv_zscore", "mvrv_zscore")
    if mvrv_z is not None:
        if mvrv_z >= 7:
            sig, note = "red",    f"MVRV Z-Score: {mvrv_z:.2f} — AŞIRI ISITILMIŞ. Tarihsel zirve bölgesi. Kâr realizasyonu düşün."
        elif mvrv_z >= 4:
            sig, note = "amber",  f"MVRV Z-Score: {mvrv_z:.2f} — Yüksek bölge. Risk artıyor, yeni alım yapma."
        elif mvrv_z >= 1:
            sig, note = "neutral",f"MVRV Z-Score: {mvrv_z:.2f} — Normal boğa bölgesi."
        elif mvrv_z >= -0.5:
            sig, note = "green",  f"MVRV Z-Score: {mvrv_z:.2f} — Adil değer civarı. İyi alım bölgesi."
        else:
            sig, note = "green",  f"MVRV Z-Score: {mvrv_z:.2f} — DİP BÖLGESİ! Tarihsel kapitülasyon sinyali."
        results["mvrv_zscore"] = {"value": mvrv_z, "signal": sig, "note": note}

    # ── MVRV Ratio (Alphractal) ───────────────────────────────────────────
    mvrv_cur = _alph_latest("/{asset}/market/CapMVRVCur", "capMVRVCur")
    if mvrv_cur is not None:
        if mvrv_cur >= 3.5:
            sig, note = "red",    f"MVRV Ratio: {mvrv_cur:.2f} — YÜKSEK RİSK. Kâr al."
        elif mvrv_cur >= 2.5:
            sig, note = "amber",  f"MVRV Ratio: {mvrv_cur:.2f} — Dikkat bölgesi."
        elif mvrv_cur >= 1.0:
            sig, note = "green",  f"MVRV Ratio: {mvrv_cur:.2f} — Sağlıklı boğa bölgesi."
        else:
            sig, note = "green",  f"MVRV Ratio: {mvrv_cur:.2f} — Dip bölgesi, güçlü alım sinyali."
        results["mvrv_proxy"] = {"value": mvrv_cur, "signal": sig, "note": note}

    # ── NUPL (Alphractal) ─────────────────────────────────────────────────
    nupl = _alph_latest("/{asset}/market/Nupl", "nupl")
    if nupl is not None:
        if nupl >= 0.75:
            sig, note = "red",    f"NUPL: {nupl:.3f} — EUPHORIA. Zirve yakın olabilir."
        elif nupl >= 0.5:
            sig, note = "amber",  f"NUPL: {nupl:.3f} — Açgözlülük bölgesi. Dikkatli ol."
        elif nupl >= 0:
            sig, note = "neutral",f"NUPL: {nupl:.3f} — Umut/iyimserlik bölgesi."
        elif nupl >= -0.25:
            sig, note = "green",  f"NUPL: {nupl:.3f} — Korku bölgesi. Orta vadeli alım fırsatı."
        else:
            sig, note = "green",  f"NUPL: {nupl:.3f} — KAPİTÜLASYON. Güçlü alım sinyali."
        results["nupl"] = {"value": nupl, "signal": sig, "note": note}

    # ── LTH-MVRV (Alphractal) ─────────────────────────────────────────────
    lth_mvrv = _alph_latest("/{asset}/lifespan/Lth_mvrv", "lth_mvrv")
    if lth_mvrv is not None:
        sig = "red" if lth_mvrv >= 3.5 else "amber" if lth_mvrv >= 2 else "green" if lth_mvrv >= 0.9 else "green"
        results["lth_mvrv"] = {"value": lth_mvrv, "signal": sig,
                               "note": f"LTH-MVRV: {lth_mvrv:.2f} — Uzun vadeli tutucularin kar/zarar durumu"}

    # ── BTC RSI — yfinance (teknik, gunluk) ───────────────────────────────
    try:
        import yfinance as yf
        hist = yf.Ticker("BTC-USD").history(period="30d", interval="1d")
        if len(hist) >= 14:
            closes = hist["Close"].tail(14)
            gains  = closes.diff().clip(lower=0).mean()
            losses = (-closes.diff().clip(upper=0)).mean()
            rsi    = round(100 - (100 / (1 + gains / losses)), 1) if losses > 0 else 50
            if rsi >= 75:
                sig, note = "red",    f"BTC RSI: {rsi} — ASIRI ALIM. Duzeltme riski."
            elif rsi >= 55:
                sig, note = "amber",  f"BTC RSI: {rsi} — Yuksek momentum, dikkat."
            elif rsi <= 25:
                sig, note = "green",  f"BTC RSI: {rsi} — ASIRI SATIS. Alim firsati."
            elif rsi <= 45:
                sig, note = "green",  f"BTC RSI: {rsi} — Dusuk, alim firsati."
            else:
                sig, note = "neutral",f"BTC RSI: {rsi} — Notr bolge."
            results["btc_rsi"] = {"value": rsi, "signal": sig, "note": note}

            # Hacim trendi
            if len(hist) >= 14:
                vols    = hist["Volume"]
                r7      = float(vols.tail(7).mean())
                p7      = float(vols.tail(14).head(7).mean())
                vol_chg = round((r7 - p7) / p7 * 100, 1) if p7 > 0 else 0
                vsig    = "amber" if vol_chg >= 50 else "green" if vol_chg >= 20 else "amber" if vol_chg <= -30 else "neutral"
                results["volume_trend"] = {
                    "value":  vol_chg,
                    "signal": vsig,
                    "note":   f"Hacim {'+' if vol_chg>=0 else ''}{vol_chg:.0f}% degisim (7g)"
                }
    except Exception as e:
        logger.debug("RSI/hacim hesaplama: %s", e)

    return results


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
    """Long/Short oranı — Alphractal API (gercek turev verisi)."""
    val = _alph_latest("/{asset}/derivatives/Long_short_ratio", "long_short_ratio")
    if val is not None:
        if val > 2.0:
            sig  = "red"
            note = f"Long/Short: {val:.2f} — ASIRI LONG. Squeeze riski yuksek."
        elif val > 1.2:
            sig  = "amber"
            note = f"Long/Short: {val:.2f} — Long agirlikli, dikkat."
        elif val < 0.5:
            sig  = "green"
            note = f"Long/Short: {val:.2f} — Short agirlikli — bounce firsati olabilir."
        else:
            sig  = "neutral"
            note = f"Long/Short: {val:.2f} — Dengeli pozisyon dagilimi."
        # Dashboard uyumlu format (long_pct / short_pct)
        total    = val + 1
        long_pct = round(val / total * 100, 1)
        return {"long_pct": long_pct, "short_pct": round(100-long_pct,1),
                "signal": sig, "note": note}

    # Fallback: yfinance proxy
    try:
        import yfinance as yf
        h = yf.Ticker("BTC-USD").history(period="2d", interval="1h")["Close"]
        if len(h) >= 6:
            chg = (h.iloc[-1] - h.iloc[-6]) / h.iloc[-6] * 100
            if chg > 3:
                return {"long_pct": 62, "short_pct": 38, "signal": "red",
                        "note": f"BTC +%{chg:.1f} (6s) — long agirlikli tahmin (proxy)"}
            elif chg < -3:
                return {"long_pct": 38, "short_pct": 62, "signal": "green",
                        "note": f"BTC %{chg:.1f} (6s) — short agirlikli tahmin (proxy)"}
            else:
                return {"long_pct": 50, "short_pct": 50, "signal": "neutral",
                        "note": f"BTC yatay (%{chg:+.1f}) — dengeli tahmin (proxy)"}
    except Exception:
        pass
    return {"signal": "neutral", "note": "Long/Short verisi alinamadi"}


def fetch_exchange_net_flow() -> dict:
    """Exchange Net Flow — Alphractal API (gercek on-chain verisi)."""
    val = _alph_latest("/{asset}/exchange_flow/Netflow", "netflow")
    if val is not None:
        if val > 1000:
            sig  = "red"
            note = f"Exchange Netflow: +{val:,.0f} BTC — Borsalara giris YUKSEK. Satis baskisi artabilir."
        elif val > 0:
            sig  = "amber"
            note = f"Exchange Netflow: +{val:,.0f} BTC — Borsalara hafif giris."
        elif val > -1000:
            sig  = "green"
            note = f"Exchange Netflow: {val:,.0f} BTC — Borsalardan cikis. HODLing artıyor."
        else:
            sig  = "green"
            note = f"Exchange Netflow: {val:,.0f} BTC — GUCLU CIKIS. Kurumsal birikim sinyali."
        return {"value": val, "signal": sig, "note": note}

    # Fallback: IBIT proxy
    try:
        import yfinance as yf
        ibit = yf.Ticker("IBIT").history(period="5d")
        btc  = yf.Ticker("BTC-USD").history(period="5d")
        if len(ibit) >= 3 and len(btc) >= 3:
            ibit_chg = (ibit["Volume"].iloc[-1] - ibit["Volume"].iloc[-3]) / ibit["Volume"].iloc[-3] * 100
            if ibit_chg > 30:
                return {"signal": "green", "note": f"BTC ETF (IBIT) hacmi +%{ibit_chg:.0f} — kurumsal talep guclu (proxy)"}
            elif ibit_chg < -30:
                return {"signal": "amber", "note": f"BTC ETF (IBIT) hacmi -%{abs(ibit_chg):.0f} — kurumsal ilgi azaliyor (proxy)"}
            else:
                return {"signal": "neutral", "note": "Exchange akisi: normal seyir (proxy)"}
    except Exception:
        pass
    return {"signal": "neutral", "note": "Exchange net flow verisi alinamadi"}


def fetch_nvt_signal() -> dict:
    """NVT Signal — Alphractal API (gercek on-chain veri)."""
    # NVTAdj90: 90 gunluk adjusted NVT
    nvt = _alph_latest("/{asset}/market/NVTAdj90", "nVTAdj90")
    if nvt is None:
        nvt = _alph_latest("/{asset}/market/NVTAdj", "nVTAdj")

    if nvt is not None:
        if nvt >= 65:
            sig  = "red"
            note = f"NVT Signal: {nvt:.0f} — YUKSEK. Fiyat on-chain aktivitesinin cok uzerinde: spekulatif balon riski."
        elif nvt >= 45:
            sig  = "amber"
            note = f"NVT Signal: {nvt:.0f} — Orta-yuksek. Dikkatli izle."
        elif nvt <= 20:
            sig  = "green"
            note = f"NVT Signal: {nvt:.0f} — DUSUK. Ag yogun kullaniliyor, fiyat cazip."
        else:
            sig  = "neutral"
            note = f"NVT Signal: {nvt:.0f} — Normal aralikta."
        return {"nvt_current": nvt, "nvt_ratio": 1.0, "signal": sig, "note": note}

    # Fallback: yfinance proxy
    try:
        import yfinance as yf
        h = yf.Ticker("BTC-USD").history(period="90d")
        if len(h) >= 30:
            BTC_SUPPLY = 19_700_000
            prices, vols = h["Close"], h["Volume"]
            nvt_series = (prices * BTC_SUPPLY) / vols
            nvt_cur  = round(float(nvt_series.iloc[-1]), 1)
            nvt_avg  = round(float(nvt_series.tail(90).mean()), 1)
            ratio    = round(nvt_cur / nvt_avg, 2) if nvt_avg > 0 else 1.0
            sig      = "red" if ratio >= 1.5 else "amber" if ratio >= 1.2 else "green" if ratio <= 0.7 else "neutral"
            return {"nvt_current": nvt_cur, "nvt_ratio": ratio, "signal": sig,
                    "note": f"NVT: {nvt_cur:.0f} (ratio: {ratio:.2f}) — proxy veri"}
    except Exception:
        pass
    return {}


def fetch_active_addresses_proxy() -> dict:
    """Aktif adres sayisi — Alphractal API (gercek on-chain veri)."""
    val = _alph_latest("/{asset}/addresses/AdrActCnt", "adrActCnt")
    if val is not None:
        active_k = round(val / 1000, 0)
        if val >= 1_500_000:
            sig  = "green"
            note = f"Aktif Adres: ~{active_k:.0f}K/gun — YUKSEK katilim. Ag aktivitesi guclu."
        elif val >= 800_000:
            sig  = "neutral"
            note = f"Aktif Adres: ~{active_k:.0f}K/gun — Normal aktivite."
        elif val >= 400_000:
            sig  = "amber"
            note = f"Aktif Adres: ~{active_k:.0f}K/gun — Dusuk aktivite, ilgi azaliyor."
        else:
            sig  = "amber"
            note = f"Aktif Adres: ~{active_k:.0f}K/gun — Cok dusuk aktivite."
        return {"active_est": int(active_k), "n_tx": int(val), "signal": sig, "note": note}

    # Fallback: blockchain.info
    try:
        import requests
        r = requests.get("https://api.blockchain.info/stats",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            n_tx     = int(r.json().get("n_tx", 0))
            est      = round(n_tx * 1.7 / 1000)
            sig      = "green" if est >= 1500 else "neutral" if est >= 800 else "amber"
            return {"active_est": est, "n_tx": n_tx, "signal": sig,
                    "note": f"Aktif Adres Proxy: ~{est}K/gun (blockchain.info)"}
    except Exception:
        pass
    return {"signal": "neutral", "note": "Aktif adres verisi alinamadi"}


def fetch_sopr_proxy() -> dict:
    """SOPR — Alphractal API (gercek UTXO bazli veri)."""
    # STH-SOPR daha anlamlı (kisa vadeli tutucularin davranisi)
    sth_sopr = _alph_latest("/{asset}/lifespan/Sth_sopr", "sth_sopr")
    lth_sopr = _alph_latest("/{asset}/lifespan/Lth_sopr", "lth_sopr")
    sopr     = _alph_latest("/{asset}/lifespan/Sopr",     "sopr")

    main_val = sth_sopr or sopr
    if main_val is not None:
        if main_val < 0.95:
            sig  = "green"
            note = f"STH-SOPR: {main_val:.3f} — 1 ALTINDA. Kisa vadeli tutucularin zarar satisi = DIP sinyali."
        elif main_val < 1.0:
            sig  = "green"
            note = f"STH-SOPR: {main_val:.3f} — Hafif zarar bolgesi. Zayif eller temizleniyor."
        elif main_val < 1.05:
            sig  = "neutral"
            note = f"STH-SOPR: {main_val:.3f} — 1 civari. Kar ve zarar dengeli."
        elif main_val < 1.15:
            sig  = "amber"
            note = f"STH-SOPR: {main_val:.3f} — Kar realizasyonu var. Satis baskisi olabilir."
        else:
            sig  = "red"
            note = f"STH-SOPR: {main_val:.3f} — YUKSEK kar realizasyonu. Tepe yakın olabilir."
        return {"sopr_7d": main_val, "sopr_30d": lth_sopr or main_val,
                "signal": sig, "note": note}

    # Fallback: yfinance VWAP proxy
    try:
        import yfinance as yf
        h = yf.Ticker("BTC-USD").history(period="60d")
        if len(h) >= 30:
            cur   = float(h["Close"].iloc[-1])
            r7    = h.tail(7)
            vwap7 = float((r7["Close"]*r7["Volume"]).sum() / r7["Volume"].sum()) if r7["Volume"].sum() > 0 else cur
            s7    = round(cur / vwap7, 3)
            r30   = h.tail(30)
            vwap30= float((r30["Close"]*r30["Volume"]).sum() / r30["Volume"].sum()) if r30["Volume"].sum() > 0 else cur
            s30   = round(cur / vwap30, 3)
            sig   = "green" if s7 < 1 else "amber" if s7 > 1.1 else "neutral"
            return {"sopr_7d": s7, "sopr_30d": s30, "signal": sig,
                    "note": f"SOPR Proxy (7g): {s7:.3f} — proxy veri"}
    except Exception:
        pass
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
    "STRK":  "starknet",        "MANTA": "manta-network",
    "ZETA":  "zetachain",       "DYM":   "dymension",
    "PIXEL": "pixels",          "PORTAL":"portal-2",
    "SAGA":  "saga-2",          "REZ":   "renzo-protocol",
    "INJ":   "injective-protocol",
    "ARB":   "arbitrum",        "OP":    "optimism",
    "INJ":   "injective-protocol",
    "SEI":   "sei-network",     "TIA":   "celestia",
    "JUP":   "jupiter-ag",
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
        if resp.status_code == 404:
            # ID yanlış olabilir — search API ile tekrar dene
            try:
                search_resp = requests.get(
                    "https://api.coingecko.com/api/v3/search",
                    params={"query": symbol},
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                if search_resp.status_code == 200:
                    coins = search_resp.json().get("coins", [])
                    for coin in coins[:5]:
                        if coin.get("symbol", "").upper() == symbol.upper():
                            new_id = coin["id"]
                            # Doğru ID ile tekrar dene
                            retry = requests.get(
                                f"https://api.coingecko.com/api/v3/coins/{new_id}",
                                params={"localization": "false", "tickers": "false",
                                        "market_data": "true", "community_data": "false",
                                        "developer_data": "false"},
                                headers={"User-Agent": "Mozilla/5.0"},
                                timeout=15,
                            )
                            if retry.status_code == 200:
                                resp = retry
                                cg_id = new_id
                                break
            except Exception:
                pass
            if resp.status_code != 200:
                return {"found": False, "error": f"CoinGecko: {symbol} bulunamadı (ID: {cg_id})"}
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
    Evrensel kripto fiyat çekici — 3 katmanlı:
    1. yfinance: çoklu ticker formatı dene (SUI-USD, SUI1-USD, SUI4-USD...)
    2. CoinGecko /simple/price (hafif endpoint, rate limit yok)
    3. CoinGecko /coins/{id} (tam detay)
    """
    import yfinance as yf
    import requests

    symbol_clean = symbol.replace("-USD", "").upper()

    # Denenmesi gereken yfinance ticker formatları
    YF_FORMATS = {
        "SUI":   ["SUI-USD", "SUI1-USD", "SUI4-USD", "SUI11861-USD"],
        "APT":   ["APT-USD", "APT21814-USD", "APT1-USD"],
        "JUP":   ["JUP-USD", "JUP4-USD", "JUP1-USD"],
        "INJ":   ["INJ-USD", "INJ1-USD"],
        "SEI":   ["SEI-USD", "SEI1-USD"],
        "TIA":   ["TIA-USD", "TIA1-USD"],
        "PYTH":  ["PYTH-USD", "PYTH1-USD"],
        "WIF":   ["WIF-USD", "WIF1-USD", "DOGWIF-USD"],
        "BONK":  ["BONK-USD", "BONK1-USD"],
        "PEPE":  ["PEPE-USD", "PEPE24478-USD"],
        "FLOKI": ["FLOKI-USD", "FLOKI1-USD"],
        "NOT":   ["NOT1-USD"],
        "JTO":   ["JTO-USD", "JTO1-USD"],
        "RNDR":  ["RNDR-USD", "RENDER-USD"],
        "FET":   ["FET-USD", "FETCHAI-USD"],
        "STRK":  ["STRK-USD", "STRK1-USD"],
        "HMSTR": ["HMSTR-USD", "HMSTR1-USD"],
    }

    # ── 1. yfinance — tüm formatları dene ───────────────────────────────
    formats_to_try = YF_FORMATS.get(symbol_clean, [f"{symbol_clean}-USD"])
    for yf_ticker in formats_to_try:
        try:
            fi    = yf.Ticker(yf_ticker).fast_info
            price = float(getattr(fi, "last_price",     0) or 0)
            prev  = float(getattr(fi, "previous_close", price) or price)
            chg   = (price - prev) / prev * 100 if prev > 0 else 0

            if price > 0.000001:  # Sıfıra çok yakın değerleri reddet
                # Makul bir fiyat aralığı kontrolü
                # Örn: JUP $0.16, SUI $3, APT $6 civarında
                # 0.000001 - 100000 arası makul
                logger.debug("yfinance OK: %s via %s = $%.6f", symbol_clean, yf_ticker, price)
                return {
                    "found":      True,
                    "symbol":     symbol_clean,
                    "name":       symbol_clean,
                    "price":      round(price, 8),
                    "change_24h": round(chg, 2),
                    "source":     f"yfinance({yf_ticker})",
                }
        except Exception:
            continue

    # ── 2. CoinGecko /simple/price — hafif endpoint ──────────────────────
    cg_id = COINGECKO_ID_MAP.get(symbol_clean)
    if cg_id:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids":             cg_id,
                    "vs_currencies":   "usd",
                    "include_24hr_change": "true",
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get(cg_id, {})
                price = float(data.get("usd", 0) or 0)
                chg   = float(data.get("usd_24h_change", 0) or 0)
                if price > 0:
                    logger.debug("CoinGecko simple: %s = $%.6f", symbol_clean, price)
                    return {
                        "found":      True,
                        "symbol":     symbol_clean,
                        "name":       symbol_clean,
                        "price":      round(price, 8),
                        "change_24h": round(chg, 2),
                        "source":     "coingecko",
                    }
        except Exception as e:
            logger.debug("CoinGecko simple/price failed %s: %s", symbol_clean, e)

    # ── 3. CoinGecko tam endpoint veya arama ────────────────────────────
    time.sleep(0.2)
    cg_result = fetch_price_coingecko(symbol_clean)
    if cg_result.get("found") and cg_result.get("price", 0) > 0:
        return cg_result

    # ── 4. Bulunamadı ────────────────────────────────────────────────────
    logger.warning("fetch_crypto_price_universal: %s bulunamadı (yfinance formatları: %s)",
                   symbol_clean, formats_to_try)
    return {
        "found":  False,
        "symbol": symbol_clean,
        "price":  0,
        "error":  f"{symbol_clean} bulunamadı — ticker formatını kontrol et",
    }


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
