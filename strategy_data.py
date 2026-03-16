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


# ─── 1. MAKRO VERİ ───────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict:
    """
    CNN Fear & Greed Index'i çek.
    0-25: Aşırı Korku, 25-45: Korku, 45-55: Nötr, 55-75: Açgözlülük, 75-100: Aşırı Açgözlülük
    Ücretsiz, API key gerektirmez.
    """
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data  = resp.json()
        score = float(data["fear_and_greed"]["score"])
        rating = data["fear_and_greed"]["rating"]  # "Fear", "Greed" vs.

        # Türkçe açıklama
        if score <= 25:
            tr_rating, signal = "Aşırı Korku", "GÜÇLÜ ALIM FIRSATI"
        elif score <= 45:
            tr_rating, signal = "Korku", "DİKKATLİ AMA OLUMLU"
        elif score <= 55:
            tr_rating, signal = "Nötr", "BEKLİYOR"
        elif score <= 75:
            tr_rating, signal = "Açgözlülük", "TEMKİNLİ OL"
        else:
            tr_rating, signal = "Aşırı Açgözlülük", "DİKKAT - BALON RİSKİ"

        return {
            "score":     round(score, 1),
            "rating":    rating,
            "tr_rating": tr_rating,
            "signal":    signal,
            "note": f"F&G Endeksi {score:.0f}/100 — {tr_rating}. Buffett kuralı: aşırı korkuda al, aşırı açgözlülükte sat.",
        }
    except Exception as e:
        logger.warning("Fear&Greed fetch failed: %s", e)
        return {"score": 50, "rating": "Neutral", "tr_rating": "Nötr",
                "signal": "VERİ ALINAMADI", "note": "Fear&Greed verisi alınamadı."}


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
    existing_scores: dict = None,   # {ticker: score} — hafızadan
    existing_targets: dict = None,  # {ticker: {mean, upside}} — hedeflerden
    macro_data: dict = None,        # Zaten çekilmişse tekrar çekme
) -> dict:
    """
    Strateji analizine girecek TÜM veriyi tek seferde topla.
    Bu fonksiyonun çıktısı Claude'a gidecek.

    Döndürür: Tam veri paketi dict
    """
    logger.info("Strateji verisi toplanıyor...")
    tickers = [p.get("ticker", "") for p in positions if p.get("ticker")]
    all_tickers = list(dict.fromkeys(tickers + (watchlist_tickers or [])))

    data = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "user_profile": get_user_profile(),
        "portfolio":    {},
        "macro":        {},
        "sentiment":    {},
        "fed":          {},
        "market":       {},
        "earnings_calendar": [],
        "short_interest":    {},
        "hisse_skorlari":    existing_scores or {},
        "analist_hedefleri": existing_targets or {},
    }

    # Portföy özeti
    data["portfolio"] = {
        "positions":   positions,
        "cash":        round(cash, 2),
        "analytics":   fetch_portfolio_analytics(positions),
    }

    # Makro — zaten varsa tekrar çekme (performans)
    if macro_data:
        data["macro"] = macro_data
    else:
        try:
            from macro_dashboard import fetch_macro_data, compute_market_regime
            _macro = fetch_macro_data()
            _regime = compute_market_regime(_macro)
            data["macro"] = {
                "indicators": {k: {"value": v.value, "signal": v.signal, "note": v.note}
                               for k, v in _macro.items()},
                "regime":     _regime,
            }
        except Exception as e:
            logger.warning("Macro data failed: %s", e)

    # Fear & Greed
    data["sentiment"] = fetch_fear_greed()

    # Fed takvimi
    data["fed"] = fetch_fed_calendar()

    # Piyasa göstergeleri (breadth, risk appetite)
    data["market"] = fetch_economic_indicators()

    # Put/Call proxy
    data["put_call"] = fetch_put_call_ratio()

    # Earnings takvimi
    data["earnings_calendar"] = fetch_earnings_calendar(tickers)

    # Short interest (sadece portföy hisseleri)
    data["short_interest"] = fetch_short_interest(tickers)

    logger.info("Strateji verisi tamamlandı.")
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

    # ── Earnings Takvimi ─────────────────────────────────────────────────
    lines.append("\n=== YAKLAŞAN EARNINGS (45 GÜN) ===")
    if ec:
        for e in ec[:8]:
            lines.append(f"  {e['ticker']}: {e['date']} ({e['days_until']} gün) — {e.get('note', '')}")
    else:
        lines.append("  Önümüzdeki 45 günde portföyde earnings yok.")

    # ── Hisse Skorları & Analist Hedefleri ───────────────────────────────
    lines.append("\n=== HİSSE ANALİZ SKORLARI ===")
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

    lines.append("\n=== GÖREV ===")
    lines.append(
        "Yukarıdaki tüm veriyi değerlendirerek bu yatırımcı için kapsamlı strateji üret. "
        "Çelişkileri tespit et ve açıkla. Kısa vade (1-3 ay), orta vade (3-12 ay) ve "
        "uzun vade (1-3 yıl) için ayrı ayrı öneri sun. Her öneride somut aksiyon belirt. "
        "Yanıtını Türkçe ver."
    )

    return "\n".join(lines)
