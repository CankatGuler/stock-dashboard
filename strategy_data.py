# strategy_data.py — Strateji Sekmesi Veri Toplayıcı
#
# Bu modül strateji analizine girecek TÜM veriyi toplar:
#   1. Makro ortam (VIX, faiz, yield curve, DXY, Fear&Greed, Fed takvimi)
#   2. Portföy durumu (değer, nakit, konsantrasyon, korelasyon özeti)
#   3. Bireysel hisse verileri (skor, analist, insider, short interest, teknik)
#   4. Haber akışı (earnings takvimi, kritik haberler)
#   5. Kullanıcı profili (risk toleransı, zaman ufku, nakit döngüsü)
#
# Çıktı: Tek bir dict — Claude bu dict'i alır ve strateji üretir.

import os
import logging
import time
from datetime import datetime, timezone, timedelta

import yfinance as yf
import requests

logger = logging.getLogger(__name__)

# ─── USD/TRY Kur Çekici — Anlık, Çok Kaynaklı ────────────────────────────────

def fetch_usd_try_rate() -> float:
    """
    USD/TRY kurunu anlık çeker. Birden fazla yöntem dener.
    Hepsi başarısız → RuntimeError fırlatır.
    Hardcoded fallback YOKTUR — hata durumunu çağıran kod yönetmeli.
    """
    import yfinance as _yf
    errors = []

    # Yöntem 1: 5 dakikalık geçmiş — en güncel değer
    try:
        _hist = _yf.Ticker("USDTRY=X").history(period="1d", interval="5m")
        if not _hist.empty:
            _rate = float(_hist["Close"].iloc[-1])
            if _rate > 30:
                return round(_rate, 4)
            errors.append(f"history şüpheli: {_rate}")
    except Exception as e:
        errors.append(f"history: {e}")

    # Yöntem 2: fast_info
    try:
        _rate = float(_yf.Ticker("USDTRY=X").fast_info.last_price or 0)
        if _rate > 30:
            return round(_rate, 4)
        errors.append(f"fast_info şüpheli: {_rate}")
    except Exception as e:
        errors.append(f"fast_info: {e}")

    # Yöntem 3: info dict — regularMarketPrice
    try:
        _info = _yf.Ticker("USDTRY=X").info
        for _field in ("regularMarketPrice", "bid", "ask"):
            _v = _info.get(_field)
            if _v and float(_v) > 30:
                return round(float(_v), 4)
        errors.append(f"info tüm alanlar şüpheli")
    except Exception as e:
        errors.append(f"info: {e}")

    # Yöntem 4: yfinance download
    try:
        _df = _yf.download("USDTRY=X", period="1d", interval="1h",
                           progress=False, show_errors=False)
        if not _df.empty:
            _rate = float(_df["Close"].iloc[-1])
            if _rate > 30:
                return round(_rate, 4)
        errors.append("download boş/şüpheli")
    except Exception as e:
        errors.append(f"download: {e}")

    raise RuntimeError(
        f"USD/TRY kuru çekilemedi. Yöntemler: {' | '.join(errors)}"
    )



# ─── 1. MAKRO VERİ ───────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict:
    """
    CNN Fear & Greed Index — ABD hisse piyasası duygu endeksi.
    Kaynak 1: CNN dataviz API
    Kaynak 2: alternative.me (kripto F&G, genellikle erişilebilir)
    Fallback: VIX bazlı hesaplama
    """
    def _parse_score(score):
        score = float(score)
        if score <= 25:   tr, sig = "Aşırı Korku",       "GÜÇLÜ ALIM FIRSATI"
        elif score <= 45: tr, sig = "Korku",              "DİKKATLİ AMA OLUMLU"
        elif score <= 55: tr, sig = "Nötr",               "BEKLİYOR"
        elif score <= 75: tr, sig = "Açgözlülük",         "TEMKİNLİ OL"
        else:             tr, sig = "Aşırı Açgözlülük",   "DİKKAT - BALON RİSKİ"
        return round(score, 1), tr, sig

    # Yöntem 1: CNN API
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=8,
        )
        if resp.status_code == 200:
            data   = resp.json()
            score  = float(data["fear_and_greed"]["score"])
            rating = data["fear_and_greed"]["rating"]
            sc, tr, sig = _parse_score(score)
            return {"score": sc, "rating": rating, "tr_rating": tr, "signal": sig,
                    "source": "CNN",
                    "note": f"CNN F&G: {sc:.0f}/100 — {tr} (ABD hisse piyasası)"}
    except Exception as e:
        logger.debug("CNN F&G failed: %s", e)

    # Yöntem 2: VIX bazlı proxy (her zaman çalışır)
    try:
        import yfinance as yf
        vix_fi = yf.Ticker("^VIX").fast_info
        vix    = float(getattr(vix_fi, "last_price", 20) or 20)
        # VIX → F&G dönüşüm: VIX 40+ = 0-10 (Aşırı Korku), VIX 12- = 80-90 (Aşırı Açgözlülük)
        # Lineer: score = max(0, min(100, 110 - vix * 2.5))
        score = max(0, min(100, 110 - vix * 2.5))
        sc, tr, sig = _parse_score(score)
        return {"score": sc, "rating": tr, "tr_rating": tr, "signal": sig,
                "source": f"VIX proxy ({vix:.0f})",
                "note": f"F&G proxy: {sc:.0f}/100 — {tr} (VIX {vix:.0f} bazlı, CNN API erişilemedi)"}
    except Exception as e:
        logger.warning("VIX F&G proxy failed: %s", e)

    return {"score": 50, "rating": "Neutral", "tr_rating": "Nötr",
            "signal": "VERİ ALINAMADI", "source": "—",
            "note": "Fear&Greed verisi alınamadı."}


def fetch_fed_calendar() -> dict:
    """
    Yaklaşan FOMC toplantı tarihlerini ve son Fed açıklamasını çek.
    yfinance calendar + hardcoded 2026 FOMC takvimi.
    """
    # 2026 FOMC toplantı tarihleri (resmi Fed takvimi)
    fomc_dates_2026 = [
        "2026-01-28", "2026-03-18", "2026-05-06",
        "2026-06-17", "2026-07-29", "2026-09-16",
        "2026-10-28", "2026-12-09",
    ]

    today = datetime.now(timezone.utc).date()
    today_str = today.strftime("%Y-%m-%d")

    # Gelecekteki toplantıları bul
    upcoming = [d for d in fomc_dates_2026 if d >= today_str]
    past     = [d for d in fomc_dates_2026 if d < today_str]

    next_meeting = upcoming[0] if upcoming else "Takvim dışı"
    last_meeting = past[-1] if past else "—"

    # Kaç gün kaldı?
    days_until = None
    if upcoming:
        next_dt    = datetime.strptime(next_meeting, "%Y-%m-%d").date()
        days_until = (next_dt - today).days

    return {
        "next_meeting":   next_meeting,
        "days_until":     days_until,
        "last_meeting":   last_meeting,
        "all_2026":       fomc_dates_2026,
        "note": (
            f"Sonraki FOMC: {next_meeting}"
            + (f" ({days_until} gün kaldı)" if days_until is not None else "")
            + ". Toplantı öncesi hafta genellikle volatildir."
        ),
    }


def fetch_economic_indicators() -> dict:
    """
    Temel ekonomik göstergeler: enflasyon proxy, işsizlik proxy.
    yfinance üzerinden ETF ve tahvil verileriyle yaklaşık değerler.
    """
    indicators = {}
    try:
        # 10Y Breakeven Enflasyon (TIPS spread proxy)
        # T10YIE = 10-Year Breakeven Inflation Rate (FRED)
        tips = yf.Ticker("TIP").fast_info   # iShares TIPS ETF
        tips_price = float(getattr(tips, "last_price", 0) or 0)
        indicators["tips_etf"] = tips_price

        # İşsizlik proxy: XLY/XLP oranı (tüketici döngüsel vs. savunmacı)
        # XLY/XLP > 1 ve yükseliyorsa ekonomi güçlü
        xly = float(yf.Ticker("XLY").fast_info.last_price or 0)
        xlp = float(yf.Ticker("XLP").fast_info.last_price or 0)
        risk_appetite = round(xly / xlp, 3) if xlp > 0 else 0
        indicators["risk_appetite_ratio"] = risk_appetite
        indicators["risk_appetite_note"] = (
            "Tüketici risk iştahı güçlü" if risk_appetite > 2.5
            else "Tüketici savunmacıya yöneliyor"
        )

        # Piyasa genişliği: RSP (Equal Weight S&P) vs SPY (Market Cap)
        # RSP > SPY büyümesi = sağlıklı geniş katılım
        rsp = float(yf.Ticker("RSP").fast_info.last_price or 0)
        spy = float(yf.Ticker("SPY").fast_info.last_price or 0)
        rsp_prev = float(getattr(yf.Ticker("RSP").fast_info, "previous_close", rsp) or rsp)
        spy_prev = float(getattr(yf.Ticker("SPY").fast_info, "previous_close", spy) or spy)

        rsp_chg = (rsp - rsp_prev) / rsp_prev * 100 if rsp_prev > 0 else 0
        spy_chg = (spy - spy_prev) / spy_prev * 100 if spy_prev > 0 else 0
        breadth_diff = rsp_chg - spy_chg

        indicators["market_breadth"] = {
            "rsp_change":   round(rsp_chg, 2),
            "spy_change":   round(spy_chg, 2),
            "breadth_diff": round(breadth_diff, 2),
            "note": (
                "Piyasa genişliği SAĞLIKLI — geniş katılımlı yükseliş" if breadth_diff > 0
                else "Piyasa genişliği ZAYIF — sadece büyük hisseler taşıyor"
            ),
        }

    except Exception as e:
        logger.warning("Economic indicators failed: %s", e)

    return indicators


def fetch_put_call_ratio() -> dict:
    """
    Put/Call oranı proxy: VIX/VIX3M veya opsiyon ETF'lerinden.
    VIXY (kısa vade VIX ETF) vs VIX seviyesinden çıkar.
    """
    try:
        vix_now  = float(yf.Ticker("^VIX").fast_info.last_price or 20)
        vix_3m   = float(yf.Ticker("^VIX3M").fast_info.last_price or 20)

        # VIX/VIX3M < 1 = piyasa yakın vadeyi daha riskli görüyor (korku)
        ratio = round(vix_now / vix_3m, 3) if vix_3m > 0 else 1.0

        if ratio > 1.1:
            signal = "YÜKSEK KORKU — Kısa vadeli opsiyon talebi patladı"
        elif ratio > 0.95:
            signal = "NÖTR"
        else:
            signal = "DÜŞÜK KORKU — Piyasa sakin, complacency riski"

        return {
            "vix_now":     round(vix_now, 1),
            "vix_3m":      round(vix_3m, 1),
            "ratio":       ratio,
            "signal":      signal,
            "note": f"VIX/VIX3M = {ratio} — {signal}",
        }
    except Exception as e:
        logger.warning("Put/Call proxy failed: %s", e)
        return {"ratio": 1.0, "signal": "VERİ ALINAMADI", "note": ""}


# ─── 2. PORTFÖY ANALİZ VERİSİ ────────────────────────────────────────────────

def fetch_portfolio_analytics(positions: list) -> dict:
    """
    Portföy için konsantrasyon, korelasyon özeti, toplam değer ve pozisyon sağlığı.
    """
    if not positions:
        return {}

    analytics = {
        "total_value":    0,
        "total_cost":     0,
        "total_pnl":      0,
        "total_pnl_pct":  0,
        "sector_weights": {},
        "top_positions":  [],
        "concentration_risk": "",
        "positions_detail": [],
    }

    total_value = 0
    total_cost  = 0
    sector_values = {}

    for pos in positions:
        ticker    = pos.get("ticker", "")
        shares    = float(pos.get("shares", 0) or 0)
        avg_cost  = float(pos.get("avg_cost", 0) or 0)
        cur_price = float(pos.get("current_price", avg_cost) or avg_cost)
        sector    = pos.get("sector", "Diğer") or "Diğer"

        position_value = shares * cur_price
        position_cost  = shares * avg_cost
        pnl            = position_value - position_cost
        pnl_pct        = (pnl / position_cost * 100) if position_cost > 0 else 0

        total_value += position_value
        total_cost  += position_cost
        sector_values[sector] = sector_values.get(sector, 0) + position_value

        analytics["positions_detail"].append({
            "ticker":    ticker,
            "value":     round(position_value, 2),
            "cost":      round(position_cost, 2),
            "pnl":       round(pnl, 2),
            "pnl_pct":   round(pnl_pct, 1),
            "sector":    sector,
            "weight":    0,  # Sonra hesaplanacak
        })

    analytics["total_value"]   = round(total_value, 2)
    analytics["total_cost"]    = round(total_cost, 2)
    analytics["total_pnl"]     = round(total_value - total_cost, 2)
    analytics["total_pnl_pct"] = round((total_value - total_cost) / total_cost * 100, 1) if total_cost > 0 else 0

    # Ağırlıkları hesapla
    for pos in analytics["positions_detail"]:
        pos["weight"] = round(pos["value"] / total_value * 100, 1) if total_value > 0 else 0

    # Sektör ağırlıkları
    for sector, val in sector_values.items():
        analytics["sector_weights"][sector] = round(val / total_value * 100, 1) if total_value > 0 else 0

    # Konsantrasyon riski
    max_sector      = max(analytics["sector_weights"].items(), key=lambda x: x[1]) if analytics["sector_weights"] else ("—", 0)
    max_single_pos  = max(analytics["positions_detail"], key=lambda x: x["weight"]) if analytics["positions_detail"] else {"ticker": "—", "weight": 0}

    if max_sector[1] > 50:
        concentration = f"KRİTİK: {max_sector[0]} sektörü %{max_sector[1]:.0f} ağırlıkla aşırı yoğun"
    elif max_sector[1] > 35:
        concentration = f"YÜKSEK: {max_sector[0]} sektörü %{max_sector[1]:.0f} — çeşitlendirme önerilir"
    elif max_single_pos["weight"] > 20:
        concentration = f"ORTA: {max_single_pos['ticker']} tek pozisyon %{max_single_pos['weight']:.0f} ağırlıkta"
    else:
        concentration = "İYİ: Portföy dengeli dağılmış"

    analytics["concentration_risk"] = concentration

    # Top 5 pozisyon
    analytics["top_positions"] = sorted(
        analytics["positions_detail"], key=lambda x: x["weight"], reverse=True
    )[:5]

    return analytics


def fetch_short_interest(tickers: list) -> dict:
    """
    Short interest verisi — yfinance shortPercentOfFloat.
    Yüksek short interest (>%20) hem risk hem squeeze fırsatı olabilir.
    """
    result = {}
    for ticker in tickers[:15]:  # Rate limit için max 15
        try:
            info  = yf.Ticker(ticker).info
            short = float(info.get("shortPercentOfFloat") or 0) * 100
            short_ratio = float(info.get("shortRatio") or 0)  # Days to cover

            if short > 20:
                signal = f"YÜKSEK SHORT (%{short:.0f}) — Squeeze potansiyeli var"
            elif short > 10:
                signal = f"ORTA SHORT (%{short:.0f}) — Dikkatli izle"
            else:
                signal = f"DÜŞÜK SHORT (%{short:.0f}) — Normal"

            result[ticker] = {
                "short_pct":   round(short, 1),
                "short_ratio": round(short_ratio, 1),
                "signal":      signal,
            }
            time.sleep(0.2)
        except Exception:
            result[ticker] = {"short_pct": 0, "short_ratio": 0, "signal": "Veri yok"}

    return result


# ─── 3. EARNINGS TAKVİMİ ────────────────────────────────────────────────────

def fetch_earnings_calendar(tickers: list) -> list:
    """
    Portföy ve watchlist hisselerinin yaklaşan earnings tarihlerini çek.
    Earnings öncesi ve sonrası dönem çok volatil olabilir.
    """
    calendar = []
    today    = datetime.now(timezone.utc).date()
    window   = today + timedelta(days=45)  # 45 günlük pencere

    for ticker in tickers[:20]:
        try:
            info = yf.Ticker(ticker).info
            # Earnings tarihini al
            earnings_ts = info.get("earningsTimestamp") or info.get("earningsDate")

            if earnings_ts:
                if isinstance(earnings_ts, (int, float)):
                    earnings_date = datetime.fromtimestamp(earnings_ts, tz=timezone.utc).date()
                else:
                    earnings_date = earnings_ts

                if today <= earnings_date <= window:
                    days_until = (earnings_date - today).days
                    calendar.append({
                        "ticker":      ticker,
                        "date":        earnings_date.strftime("%Y-%m-%d"),
                        "days_until":  days_until,
                        "eps_est":     info.get("forwardEps", 0),
                        "note": (
                            f"⚠️ {ticker} earnings {days_until} gün sonra ({earnings_date}) — "
                            f"Pozisyon boyutuna dikkat et"
                        ),
                    })
            time.sleep(0.15)
        except Exception:
            pass

    calendar.sort(key=lambda x: x["days_until"])
    return calendar


# ─── 4. KULLANICI PROFİLİ ────────────────────────────────────────────────────

def get_user_profile() -> dict:
    """
    Sabah not ettiğimiz yatırımcı profili.
    İleride kullanıcı arayüzünden edit edilebilir yapılacak.
    """
    return {
        "time_horizon":         "uzun_vade",        # kısa / orta / uzun
        "time_horizon_years":   "1-3 yıl",
        "cash_cycle":           "3_aylik",           # düzenli / 3_aylik / düzensiz
        "risk_tolerance":       "orta_yuksek",       # düşük / orta / orta_yuksek / yüksek
        "drawdown_tolerance":   "%20",               # kayıpda paniklemez
        "portfolio_purpose":    "büyüme",            # gelir / büyüme / karma
        "us_allocation":        "kısmi",             # tek / kısmi / çeşitli
        "trading_style":        "yatırımcı",         # trader / yatırımcı
        "goal": (
            "Uzun vadeli büyüme odaklı, volatiliteyi minimize ederek portföyü "
            "sistematik şekilde büyütmek. 3 ayda bir nakit ekleyerek dip fırsatlarını "
            "değerlendirmek. ABD borsası tek yatırım aracı değil."
        ),
    }


# ─── 5. ANA TOPLAYICI ────────────────────────────────────────────────────────

def collect_all_strategy_data(
    positions: list,
    watchlist_tickers: list = None,
    cash: float = 0,
    existing_scores: dict = None,
    existing_targets: dict = None,
    macro_data: dict = None,
) -> dict:
    """
    Strateji analizine girecek TÜM veriyi topla.
    - Ağır katmanlar (2-6) ThreadPoolExecutor ile PARALEL çalışır → ~2.5 dk yerine ~45 sn
    - Her katmanın başarı/başarısızlık durumu data["veri_kalitesi"] ile raporlanır
    - Direktör boş veri geldiğinde bunu artık görüyor
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time as _time

    logger.info("Strateji verisi toplanıyor (paralel mod)...")
    t0 = _time.time()

    tickers     = [p.get("ticker", "") for p in positions if p.get("ticker")]
    all_tickers = list(dict.fromkeys(tickers + (watchlist_tickers or [])))
    tefas_codes = [p["ticker"] for p in positions
                   if p.get("asset_class") == "tefas" and float(p.get("shares", 0)) > 0]
    crypto_pos  = [p for p in positions if p.get("asset_class") == "crypto"]

    data = {
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "user_profile":      get_user_profile(),
        "portfolio":         {},
        "macro":             {},
        "sentiment":         {},
        "fed":               {},
        "market":            {},
        "economic":          {},
        "sp500_valuation":   {},
        "sector_rotation":   {},
        "economic_context":  "",
        "crypto":            {},
        "commodity":         {},
        "turkey":            {},
        "correlations":      {},
        "calendar":          [],
        "earnings_calendar": [],
        "short_interest":    {},
        "put_call":          {},
        "hisse_skorlari":    existing_scores or {},
        "analist_hedefleri": existing_targets or {},
        "veri_kalitesi":     {},   # ← YENİ: her katmanın sağlık durumu
    }

    # ── Portföy özeti (senkron — hızlı, veri gerektirmiyor) ──────────────
    # USD/TRY kuru çek — TRY varlık gösterimi için
    # USD/TRY — anlık, çok kaynaklı, hardcoded fallback yok
    try:
        _usd_try_curr = fetch_usd_try_rate()
        logger.info("USD/TRY kuru: %.4f", _usd_try_curr)
    except RuntimeError as _kur_err:
        logger.error("KUR HATASI: %s", _kur_err)
        raise RuntimeError(
            f"Strateji analizi başlatılamadı — USD/TRY kuru alınamadı. "
            f"Detay: {_kur_err}"
        )

    data["portfolio"] = {
        "positions": positions,
        "cash":      round(cash, 2),
        "analytics": fetch_portfolio_analytics(positions),
        "usd_try":   _usd_try_curr,
    }
    data["veri_kalitesi"]["portfoy_base"] = "ok"

    # ── Makro Katman 1 (senkron — zaten cache'li olabilir) ───────────────
    if macro_data:
        data["macro"] = macro_data
        data["veri_kalitesi"]["makro"] = "cache"
    else:
        try:
            from macro_dashboard import fetch_macro_data, compute_market_regime
            _macro  = fetch_macro_data()
            _regime = compute_market_regime(_macro)
            data["macro"] = {
                "indicators": {k: {"value": v.value, "change_pct": v.change_pct,
                                   "signal": v.signal, "note": v.note}
                               for k, v in _macro.items()},
                "regime": _regime,
            }
            data["veri_kalitesi"]["makro"] = f"ok ({len(_macro)} gösterge)"
        except Exception as e:
            logger.warning("Macro failed: %s", e)
            data["veri_kalitesi"]["makro"] = f"HATA: {str(e)[:60]}"

    # ── Hızlı senkron veriler ─────────────────────────────────────────────
    data["sentiment"] = fetch_fear_greed()
    data["fed"]       = fetch_fed_calendar()
    data["market"]    = fetch_economic_indicators()
    data["put_call"]  = fetch_put_call_ratio()

    # ── PARALEL katman çekişleri ──────────────────────────────────────────
    # Her katman bağımsız — birbirini beklemek zorunda değil
    def fetch_layer2():
        try:
            from economic_data import fetch_all_economic_data, build_economic_context
            r = fetch_all_economic_data()
            return ("layer2", {
                "economic":         r.get("macro_econ", {}),
                "sp500_valuation":  r.get("valuation", {}),
                "sector_rotation":  r.get("sectors", {}),
                "economic_context": build_economic_context(r),
            })
        except Exception as e:
            return ("layer2_err", str(e))

    def fetch_layer3():
        try:
            from crypto_fetcher import fetch_all_crypto_data
            r = fetch_all_crypto_data(crypto_positions=tuple(
                {k: v for k, v in p.items() if isinstance(v, (str, int, float, bool))}
                for p in crypto_pos
            ) if crypto_pos else None)
            return ("layer3", r)
        except Exception as e:
            return ("layer3_err", str(e))

    def fetch_layer4():
        try:
            from commodity_fetcher import fetch_all_commodity_data
            return ("layer4", fetch_all_commodity_data())
        except Exception as e:
            return ("layer4_err", str(e))

    def fetch_layer5():
        try:
            from turkey_fetcher import fetch_all_turkey_data
            return ("layer5", fetch_all_turkey_data(
                tefas_codes=tuple(tefas_codes) if tefas_codes else None
            ))
        except Exception as e:
            return ("layer5_err", str(e))

    def fetch_correlations():
        try:
            from correlation_engine import fetch_all_correlations
            return ("corr", fetch_all_correlations(portfolio_tickers=tickers))
        except Exception as e:
            return ("corr_err", str(e))

    def fetch_calendar():
        try:
            from financial_calendar import get_upcoming_events
            return ("cal", get_upcoming_events(tickers=tickers, days_ahead=30, min_stars=2))
        except Exception as e:
            return ("cal_err", str(e))

    def fetch_earnings():
        try:
            return ("earn", fetch_earnings_calendar(tickers))
        except Exception as e:
            return ("earn_err", str(e))

    def fetch_short():
        try:
            return ("short", fetch_short_interest(tickers))
        except Exception as e:
            return ("short_err", str(e))

    def fetch_portfolio_integrated():
        try:
            from portfolio_integrator import build_integrated_portfolio
            up = data.get("user_profile", {})
            return ("port_int", build_integrated_portfolio(
                positions=positions,
                cash_usd=cash,
                year_target_pct=float(up.get("year_target_pct", 40.0)),
                year_start_value=float(up.get("year_start_value", 0.0)),
            ))
        except Exception as e:
            return ("port_int_err", str(e))

    # Tüm görevleri paralel çalıştır
    tasks = [
        fetch_layer2, fetch_layer3, fetch_layer4, fetch_layer5,
        fetch_correlations, fetch_calendar, fetch_earnings,
        fetch_short, fetch_portfolio_integrated,
    ]

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in tasks}
        for future in as_completed(futures):
            try:
                result = future.result(timeout=45)
                key, val = result
                if key == "layer2":
                    # economic alt anahtarını ayrıca koru — analistler all_data["economic"] bekliyor
                    data["economic"]        = val.get("economic", {})
                    data["sp500_valuation"] = val.get("sp500_valuation", {})
                    data["sector_rotation"] = val.get("sector_rotation", {})
                    data["economic_context"]= val.get("economic_context", "")
                    # Geriye dönük uyumluluk için üst seviye de güncelle
                    data.update({k:v for k,v in val.items() if k != "economic"})
                    data["veri_kalitesi"]["ekonomik_k2"] = f"ok ({len(val.get('economic',{}))} gösterge)"
                elif key == "layer3":
                    data["crypto"] = val
                    data["veri_kalitesi"]["kripto_k3"] = f"ok ({len(val)} metrik)"
                elif key == "layer4":
                    data["commodity"] = val
                    data["veri_kalitesi"]["emtia_k4"] = f"ok ({len(val)} metrik)"
                elif key == "layer5":
                    data["turkey"] = val
                    data["veri_kalitesi"]["turkiye_k5"] = f"ok ({len(val)} metrik)"
                elif key == "corr":
                    data["correlations"] = val
                    data["veri_kalitesi"]["korelasyon"] = "ok"
                elif key == "cal":
                    data["calendar"] = val
                    data["veri_kalitesi"]["takvim"] = f"ok ({len(val)} olay)"
                elif key == "earn":
                    data["earnings_calendar"] = val
                elif key == "short":
                    data["short_interest"] = val
                elif key == "port_int":
                    data["portfolio"] = val
                    data["veri_kalitesi"]["portfoy_entegre"] = "ok"
                elif key.endswith("_err"):
                    layer = key.replace("_err", "")
                    data["veri_kalitesi"][layer] = f"⚠️ HATA: {str(val)[:80]}"
                    logger.warning("Paralel katman hatası [%s]: %s", layer, val)
                    # Kripto layer başarısız → yfinance'ten minimal fiyat verisi çek
                    if layer == "layer3":
                        try:
                            import yfinance as _yf_fb
                            _btc_t = _yf_fb.Ticker("BTC-USD")
                            _btc_p = float(_btc_t.fast_info.last_price or 0)
                            _eth_p = float(_yf_fb.Ticker("ETH-USD").fast_info.last_price or 0)
                            data["crypto"] = {
                                "prices": {
                                    "BTC": {"price": _btc_p, "change_24h": 0, "52h_pos": 50},
                                    "ETH": {"price": _eth_p, "change_24h": 0, "52h_pos": 50},
                                },
                                "fear_greed": {"note": "Veri çekilemedi — yfinance fallback"},
                                "_fallback": True,
                            }
                            data["veri_kalitesi"][layer] = f"⚠️ FALLBACK: yfinance BTC={_btc_p:,.0f}"
                        except Exception as _fb_e:
                            data["crypto"] = {"_fallback": True, "prices": {}}
                            logger.warning("Kripto fallback da başarısız: %s", _fb_e)
            except Exception as e:
                logger.warning("Future exception [%s]: %s", futures[future], e)

    # ── Tarihsel Kriz Karşılaştırması (senkron — hızlı hesaplama) ─────────
    try:
        from crisis_comparator import compare_to_historical_crises, get_crisis_context_for_claude
        _macro_ind = data.get("macro", {}).get("indicators", {})
        _econ      = data.get("macro_econ", {})
        _val       = data.get("valuation", {})

        # Mevcut gösterge değerlerini topla
        _current_ind = {}
        buffett = _val.get("buffett", {})
        if isinstance(buffett, dict):
            _current_ind["buffett_ratio"] = buffett.get("ratio", 0)

        for k, label in [("sp500_pe", "sp500_pe"), ("vix", "vix")]:
            ind = _macro_ind.get(k) or _econ.get(k.upper())
            if ind:
                _current_ind[label] = getattr(ind, "value", 0) if hasattr(ind, "value") else ind.get("value", 0)

        # VIX makro datadan
        vix_data = data.get("macro", {}).get("indicators", {}).get("vix")
        if vix_data:
            _current_ind["vix"] = getattr(vix_data, "value", 20)

        # Spekülatif aktivite
        spec = _econ.get("SPEC_ACTIVITY")
        if spec and hasattr(spec, "value"):
            _current_ind["spec_activity_pct"] = spec.value

        # Konut
        yeni_konut = _econ.get("yeni_konut") or data.get("housing", {}).get("yeni_konut")
        if yeni_konut and hasattr(yeni_konut, "value"):
            _current_ind["new_home_sales"] = yeni_konut.value

        _crisis_comps = compare_to_historical_crises(_current_ind)
        _crisis_ctx   = get_crisis_context_for_claude(_current_ind)
        data["crisis_comparisons"] = [
            {"label": c.label, "similarity_pct": c.similarity_pct,
             "risk_level": c.risk_level, "drawdown": c.drawdown,
             "trigger": c.trigger, "lesson": c.lesson,
             "matched_signals": c.matched_signals}
            for c in _crisis_comps
        ]
        data["crisis_context"] = _crisis_ctx
        data["veri_kalitesi"]["kriz_karsilastirma"] = f"ok ({len(_crisis_comps)} kriz)"
    except Exception as e:
        logger.warning("Kriz karşılaştırması alınamadı: %s", e)
        data["crisis_comparisons"] = []
        data["crisis_context"] = ""

    elapsed = _time.time() - t0
    data["veri_kalitesi"]["_sure_sn"] = round(elapsed, 1)
    logger.info("Strateji verisi tamamlandı — %.1f sn (paralel)", elapsed)
    return data


def build_strategy_prompt(data: dict) -> str:
    """
    Toplanan veriyi Claude'a gönderilecek formatlı prompt'a dönüştür.
    Her bölüm açıkça etiketlenmiş — Claude kolayca parse eder.
    """
    p   = data.get("portfolio", {})
    pa  = p.get("analytics", {})
    mac = data.get("macro", {})
    reg = mac.get("regime", {})
    fg  = data.get("sentiment", {})
    fed = data.get("fed", {})
    mkt = data.get("market", {})
    pc  = data.get("put_call", {})
    ec  = data.get("earnings_calendar", [])
    si  = data.get("short_interest", {})
    up  = data.get("user_profile", {})
    hs  = data.get("hisse_skorlari", {})
    ah  = data.get("analist_hedefleri", {})

    lines = []

    # ── Kullanıcı Profili ─────────────────────────────────────────────────
    lines.append("=== YATIRIMCI PROFİLİ ===")
    lines.append(f"Zaman Ufku: {up.get('time_horizon_years', '1-3 yıl')} (uzun vade)")
    lines.append(f"Risk Toleransı: {up.get('risk_tolerance', 'orta_yüksek')}")
    lines.append(f"Drawdown Toleransı: {up.get('drawdown_tolerance', '%20')} düşüşe dayanıklı")
    lines.append(f"Nakit Döngüsü: {up.get('cash_cycle', '3 ayda bir')}")
    lines.append(f"Hedef: {up.get('goal', '')}")

    # ── Portföy Durumu ────────────────────────────────────────────────────
    lines.append("\n=== PORTFÖY DURUMU ===")
    lines.append(f"Toplam Değer: ${pa.get('total_value', 0):,.2f}")
    lines.append(f"Toplam Maliyet: ${pa.get('total_cost', 0):,.2f}")
    lines.append(f"Toplam K/Z: ${pa.get('total_pnl', 0):,.2f} (%{pa.get('total_pnl_pct', 0):.1f})")
    lines.append(f"Nakit: ${p.get('cash', 0):,.2f}")
    total = pa.get('total_value', 0) + p.get('cash', 0)
    cash_ratio = p.get('cash', 0) / total * 100 if total > 0 else 0
    lines.append(f"Nakit Oranı: %{cash_ratio:.1f}")
    lines.append(f"Konsantrasyon Riski: {pa.get('concentration_risk', '—')}")

    # Sektör ağırlıkları
    sw = pa.get("sector_weights", {})
    if sw:
        lines.append("Sektör Dağılımı: " + " | ".join(
            f"{s}: %{w:.0f}" for s, w in sorted(sw.items(), key=lambda x: x[1], reverse=True)
        ))

    # Top pozisyonlar
    top = pa.get("top_positions", [])
    if top:
        lines.append("En Büyük Pozisyonlar: " + " | ".join(
            f"{pos['ticker']} %{pos['weight']:.0f} (K/Z: %{pos['pnl_pct']:.0f})"
            for pos in top
        ))

    # ── Makro Ortam ───────────────────────────────────────────────────────
    lines.append("\n=== MAKRO ORTAM ===")
    if reg:
        lines.append(f"Piyasa Rejimi: {reg.get('label', '—')} — {reg.get('description', '')}")

    inds = mac.get("indicators", {})
    for key, val in inds.items():
        if isinstance(val, dict):
            lines.append(f"{key}: {val.get('value', '—')} — {val.get('note', '')}")

    # ── Piyasa Duygusu ────────────────────────────────────────────────────
    lines.append("\n=== PİYASA DUYGUSU ===")
    lines.append(f"Fear & Greed Endeksi: {fg.get('score', '—')}/100 — {fg.get('tr_rating', '—')}")
    lines.append(f"Sinyal: {fg.get('signal', '—')}")
    lines.append(f"VIX/VIX3M Oranı: {pc.get('ratio', '—')} — {pc.get('signal', '—')}")

    # Piyasa genişliği
    breadth = mkt.get("market_breadth", {})
    if breadth:
        lines.append(f"Piyasa Genişliği: {breadth.get('note', '—')}")

    # Risk iştahı
    lines.append(f"Risk İştahı (XLY/XLP): {mkt.get('risk_appetite_note', '—')}")

    # ── Fed & Ekonomi ────────────────────────────────────────────────────
    lines.append("\n=== FED & EKONOMİ ===")
    lines.append(f"Sonraki FOMC: {fed.get('next_meeting', '—')} ({fed.get('days_until', '?')} gün)")
    lines.append(f"Son FOMC: {fed.get('last_meeting', '—')}")

    # ── Katman 1 Yeni Metrikler ───────────────────────────────────────────
    # Makro göstergeleri içinde yeni metrikler varsa ekle
    _ext_keys = {
        "CREDIT_SPREAD": "Credit Spread (HYG/LQD)",
        "OVX":           "Petrol Volatilitesi (OVX)",
        "USDJPY":        "USD/JPY Carry Trade",
        "LIQUIDITY":     "Küresel Likidite",
        "FED_WATCH":     "Fed Beklentisi",
        "MOVE_PROXY":    "Tahvil Volatilitesi (MOVE)",
    }

    _ext_found = []
    for _ek, _el in _ext_keys.items():
        _ind = inds.get(_ek)
        if _ind and isinstance(_ind, dict):
            _val  = _ind.get("value", "—")
            _note = _ind.get("note", "")
            _ext_found.append(f"{_el}: {_val} — {_note}")
        elif hasattr(_ind, "value"):
            _ext_found.append(f"{_el}: {_ind.value} — {_ind.note}")

    if _ext_found:
        lines.append("\n=== GENİŞLETİLMİŞ MAKRO SİNYALLER ===")
        for _ef in _ext_found:
            lines.append(f"  {_ef}")

    # ── Earnings Takvimi ─────────────────────────────────────────────────
    lines.append("\n=== YAKLAŞAN EARNINGS (45 GÜN) ===")
    if ec:
        for e in ec[:8]:
            lines.append(f"  {e['ticker']}: {e['date']} ({e['days_until']} gün) — {e.get('note', '')}")
    else:
        lines.append("  Önümüzdeki 45 günde portföyde earnings yok.")

    # ── Hisse Skorları & Analist Hedefleri ───────────────────────────────
    # Önce portföydeki aktif hisseleri açıkça listele
    active_positions = p.get("positions", [])
    if active_positions:
        lines.append("\n=== AKTİF PORTFÖY HİSSELERİ (BUNLAR PORTFÖYDE VAR) ===")
        lines.append("NOT: Aşağıdaki hisseler DIŞINDA hiçbir hisse bu kişinin portföyünde YOK.")
        for pos in active_positions:
            ticker = pos.get("ticker", "")
            shares = pos.get("shares", 0)
            avg_c  = pos.get("avg_cost", 0)
            cur_p  = pos.get("current_price", avg_c)
            pnl    = (cur_p - avg_c) / avg_c * 100 if avg_c > 0 else 0
            lines.append(
                f"  {ticker}: {shares:.2f} adet | Maliyet ${avg_c:.2f} | "
                f"Güncel ${cur_p:.2f} | K/Z %{pnl:.1f}"
            )

    lines.append("\n=== HİSSE ANALİZ SKORLARI (portföy + watchlist) ===")
    if hs:
        for ticker, score in sorted(hs.items(), key=lambda x: x[1], reverse=True):
            tgt_data = ah.get(ticker, {})
            upside   = tgt_data.get("upside", 0)
            analist  = tgt_data.get("n_analysts", 0)
            short    = si.get(ticker, {}).get("short_pct", 0)
            lines.append(
                f"  {ticker}: Skor {score} | Analist Upside %{upside:.0f} ({analist} analist)"
                + (f" | Short %{short:.0f}" if short > 5 else "")
            )
    else:
        lines.append("  Hafıza skoru bulunamadı — son taramayı çalıştır.")

    # ── Katman 2: Ekonomik Göstergeler ───────────────────────────────────
    econ = data.get("economic", {})
    if econ:
        lines.append("\n=== EKONOMİK GÖSTERGELER (FRED) ===")
        for sid, ed in econ.items():
            if isinstance(ed, dict) and ed.get("value") is not None:
                lines.append(
                    f"  {ed.get('name','')}: {ed.get('value','—')}{ed.get('unit','')} "
                    f"({ed.get('date','')}) — {ed.get('note','')}"
                )

    # ── S&P 500 Değerleme ─────────────────────────────────────────────────
    spv = data.get("sp500_valuation", {})
    if spv.get("forward_pe"):
        lines.append("\n=== S&P 500 DEĞERLEME ===")
        lines.append(f"  {spv.get('note','')}")
        lines.append(f"  Tarihsel Ort: {spv.get('hist_avg','16.5')}x | "
                     f"Prim/İskonto: %{spv.get('premium_pct',0):.0f}")

    # ── Sektör Rotasyonu ─────────────────────────────────────────────────
    sr = data.get("sector_rotation", {})
    sr_summary = sr.get("_summary", {})
    if sr_summary:
        lines.append("\n=== SEKTÖR ROTASYONU (Son 20 Gün) ===")
        lines.append(f"  {sr_summary.get('note','')}")
        lines.append("  Detay:")
        for etf, d in sorted(sr.items(), key=lambda x: x[1].get("perf_pct", 0) if isinstance(x[1], dict) else 0, reverse=True):
            if etf == "_summary" or not isinstance(d, dict):
                continue
            lines.append(f"    {d.get('name','')}: %{d.get('perf_pct',0):+.1f} {d.get('trend','')}")

    # Ekonomik göstergeler (FRED verisi)
    eco_ctx = data.get("economic_context", "")
    if eco_ctx:
        lines.append(f"\n{eco_ctx}")

    # ── Korelasyon Analizi ────────────────────────────────────────────────
    corr_data = data.get("correlations", {})
    corr_prompt = corr_data.get("prompt", "")
    if corr_prompt:
        lines.append(corr_prompt)

    lines.append("\n=== GÖREV ===")
    lines.append(
        "Yukarıdaki tüm veriyi değerlendirerek bu yatırımcı için kapsamlı strateji üret. "
        "KRİTİK KURAL: Sat/Azalt önerilerinde YALNIZCA 'AKTİF PORTFÖY HİSSELERİ' "
        "bölümünde listelenen hisseleri kullan — o listede olmayan hiçbir hisseyi "
        "portföyde varmış gibi işleme. "
        "Çelişkileri tespit et ve açıkla. Kısa vade (1-3 ay), orta vade (3-12 ay) ve "
        "uzun vade (1-3 yıl) için ayrı ayrı öneri sun. Her öneride somut aksiyon belirt. "
        "Yanıtını Türkçe ver."
    )

    return "\n".join(lines)
