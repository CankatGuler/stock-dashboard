# stock_analyzer.py — Hisse Temel Analizi ve Haber Araması
#
# İki işlev:
#   1. get_fundamentals(ticker) — yfinance'ten P/E, ROIC, FCF vs. çeker
#   2. search_market_news(query) — Claude web_search tool ile haber arar
#   3. analyze_ticker(ticker) — ikisini birleştirip direktör yorumu ekler

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── 1. Temel Analiz (yfinance) ───────────────────────────────────────────────

def get_fundamentals(ticker: str) -> dict:
    """
    Hisse için temel finansal metrikleri çek.
    Döndürür: temiz bir dict, eksik alanlar None yerine "—" ile dolu.
    """
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker.upper())
        info = t.info
        hist = t.history(period="2d")

        # Anlık fiyat
        price     = float(hist["Close"].iloc[-1]) if not hist.empty else 0
        prev      = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        price_chg = (price - prev) / prev * 100 if prev > 0 else 0

        def fmt_num(val, suffix="", multiplier=1, decimals=1):
            """Sayıyı güzel formatla, None ise — döndür."""
            if val is None or val == 0:
                return "—"
            v = val * multiplier
            if abs(v) >= 1e9:
                return f"${v/1e9:.1f}B{suffix}"
            elif abs(v) >= 1e6:
                return f"${v/1e6:.1f}M{suffix}"
            return f"{v:.{decimals}f}{suffix}"

        def fmt_pct(val):
            if val is None:
                return "—"
            return f"%{val*100:.1f}"

        def fmt_ratio(val, decimals=1):
            if val is None or val == 0:
                return "—"
            return f"{val:.{decimals}f}x"

        # Piyasa değeri formatı
        mc = info.get("marketCap")
        if mc and mc >= 1e12:
            mc_str = f"${mc/1e12:.2f}T"
        elif mc and mc >= 1e9:
            mc_str = f"${mc/1e9:.1f}B"
        else:
            mc_str = "—"

        # FCF ve FCF Yield
        fcf       = info.get("freeCashflow")
        fcf_yield = (fcf / mc * 100) if fcf and mc else None

        # Net Debt / EBITDA hesapla
        net_debt_ebitda = None
        try:
            bs  = t.balance_sheet
            is_ = t.income_stmt
            cf  = t.cashflow
            if (bs is not None and not bs.empty and
                is_ is not None and not is_.empty):

                # Total Debt
                total_debt = 0.0
                for debt_key in ["Total Debt", "Long Term Debt", "Short Long Term Debt"]:
                    if debt_key in bs.index:
                        total_debt = float(bs.loc[debt_key].iloc[0] or 0)
                        break

                # Cash
                cash_val = 0.0
                for cash_key in ["Cash And Cash Equivalents", "Cash"]:
                    if cash_key in bs.index:
                        cash_val = float(bs.loc[cash_key].iloc[0] or 0)
                        break

                net_debt = total_debt - cash_val

                # EBITDA = Operating Income + D&A
                ebitda = info.get("ebitda")
                if not ebitda and "EBIT" in is_.index:
                    ebit = float(is_.loc["EBIT"].iloc[0] or 0)
                    da   = 0.0
                    if cf is not None and not cf.empty:
                        for da_key in ["Depreciation And Amortization", "Depreciation"]:
                            if da_key in cf.index:
                                da = float(cf.loc[da_key].iloc[0] or 0)
                                break
                    ebitda = ebit + abs(da)

                if ebitda and ebitda > 0:
                    net_debt_ebitda = net_debt / ebitda
        except Exception:
            pass

        # EV/Sales
        ev_sales = None
        ev = info.get("enterpriseValue")
        rev = info.get("totalRevenue")
        if ev and rev and rev > 0:
            ev_sales = ev / rev

        # Short Interest
        short_ratio   = info.get("shortRatio")
        short_pct_float = info.get("shortPercentOfFloat")

        # Insider Ownership
        insider_pct   = info.get("heldPercentInsiders")
        inst_pct      = info.get("heldPercentInstitutions")

        # Analist hedef fiyat
        target_price  = info.get("targetMeanPrice")
        analyst_count = info.get("numberOfAnalystOpinions")
        recom         = info.get("recommendationKey", "")

        # Upside/Downside
        upside = None
        if target_price and price > 0:
            upside = (target_price - price) / price * 100

        # ROIC yaklaşımı (yfinance'te direkt yok, hesapla)
        roic = None
        try:
            bs2  = t.balance_sheet
            is2_ = t.income_stmt
            if bs2 is not None and not bs2.empty and is2_ is not None and not is2_.empty:
                total_assets = float(bs2.loc["Total Assets"].iloc[0]) if "Total Assets" in bs2.index else None
                curr_liab    = float(bs2.loc["Current Liabilities"].iloc[0]) if "Current Liabilities" in bs2.index else None
                net_income   = float(is2_.loc["Net Income"].iloc[0]) if "Net Income" in is2_.index else None
                if total_assets and curr_liab and net_income:
                    invested_cap = total_assets - curr_liab
                    if invested_cap > 0:
                        roic = net_income / invested_cap * 100
        except Exception:
            pass

        # Temettü — yfinance bazen yanlış döndürüyor, doğrula
        raw_div = info.get("dividendYield")
        div_yield = None
        if raw_div is not None:
            if 0 < raw_div <= 0.20:
                div_yield = raw_div        # Zaten oran (örn: 0.02 = %2)
            elif 0.20 < raw_div <= 20:
                div_yield = raw_div / 100  # Yüzde gelmiş (örn: 2.0 = %2)
            # 20 üzeriyse anlamsız veri, None bırak

        return {
            # Kimlik
            "ticker":       ticker.upper(),
            "name":         info.get("longName", ticker.upper()),
            "sector":       info.get("sector", "—"),
            "industry":     info.get("industry", "—"),
            "country":      info.get("country", "—"),

            # Fiyat
            "price":        price,
            "price_chg":    price_chg,
            "52w_high":     info.get("fiftyTwoWeekHigh"),
            "52w_low":      info.get("fiftyTwoWeekLow"),
            "beta":         info.get("beta"),

            # Değerleme
            "pe_trailing":  info.get("trailingPE"),
            "pe_forward":   info.get("forwardPE"),
            "peg":          info.get("pegRatio"),
            "pb":           info.get("priceToBook"),
            "ev_ebitda":    info.get("enterpriseToEbitda"),
            "ev_sales":     ev_sales,

            # Karlılık
            "roe":          info.get("returnOnEquity"),
            "roa":          info.get("returnOnAssets"),
            "roic":         roic,
            "gross_margin": info.get("grossMargins"),
            "op_margin":    info.get("operatingMargins"),
            "net_margin":   info.get("profitMargins"),

            # Nakit Akışı
            "fcf":          fcf,
            "fcf_yield":    fcf_yield,
            "op_cashflow":  info.get("operatingCashflow"),

            # Bilanço
            "debt_equity":      info.get("debtToEquity"),
            "net_debt_ebitda":  net_debt_ebitda,
            "current_ratio":    info.get("currentRatio"),
            "quick_ratio":      info.get("quickRatio"),

            # Büyüme
            "revenue_growth":   info.get("revenueGrowth"),
            "earnings_growth":  info.get("earningsGrowth"),

            # Sahiplik & Kısa Pozisyon
            "short_ratio":        short_ratio,
            "short_pct_float":    short_pct_float,
            "insider_pct":        insider_pct,
            "inst_pct":           inst_pct,

            # Analist
            "target_price":   target_price,
            "analyst_count":  analyst_count,
            "recommendation": recom,
            "upside":         upside,

            # Büyüklük
            "market_cap":   mc_str,

            # Temettü
            "div_yield":    div_yield,
        }

    except Exception as e:
        logger.error("Fundamental veri alınamadı %s: %s", ticker, e)
        return {"ticker": ticker.upper(), "error": str(e)}


def format_fundamentals(data: dict) -> str:
    """Fundamental veriyi Telegram'a uygun HTML formatına çevir."""
    if "error" in data:
        return f"❌ {data['ticker']} verisi alınamadı: {data['error']}"

    def f(val, suffix="", pct=False, mult=1, dec=1):
        if val is None:
            return "—"
        v = val * mult
        if pct:
            return f"%{v*100:.{dec}f}"
        return f"{v:.{dec}f}{suffix}"

    def fmoney(val):
        if val is None:
            return "—"
        if abs(val) >= 1e9:
            return f"${val/1e9:.1f}B"
        if abs(val) >= 1e6:
            return f"${val/1e6:.1f}M"
        return f"${val:,.0f}"

    price     = data.get("price", 0)
    price_chg = data.get("price_chg", 0)
    chg_e     = "🟢" if price_chg >= 0 else "🔴"

    # 52 haftalık konum
    h52 = data.get("52w_high")
    l52 = data.get("52w_low")
    if h52 and l52 and h52 > l52:
        pos_pct = (price - l52) / (h52 - l52) * 100
        pos_str = f"%{pos_pct:.0f} (52h aralığında)"
    else:
        pos_str = "—"

    lines = [
        f"📊 <b>{data['ticker']} — {data['name']}</b>",
        f"<i>{data.get('sector','—')} | {data.get('industry','—')}</i>",
        "━" * 28,

        f"\n💰 <b>Fiyat</b>",
        f"  Anlık: <b>${price:,.2f}</b> {chg_e} ({price_chg:+.2f}%)",
        f"  52h: ${l52:,.2f} — ${h52:,.2f}  |  Pozisyon: {pos_str}" if l52 and h52 else "  52h: —",
        f"  Beta: {f(data.get('beta'), dec=2)}  |  Piyasa Değeri: {data.get('market_cap','—')}",

        f"\n📈 <b>Değerleme</b>",
        f"  P/E (TTM): {f(data.get('pe_trailing'))}  |  Forward P/E: {f(data.get('pe_forward'))}",
        f"  PEG: {f(data.get('peg'), dec=2)}  |  P/B: {f(data.get('pb'), dec=2)}",
        f"  EV/EBITDA: {f(data.get('ev_ebitda'))}  |  EV/Sales: {f(data.get('ev_sales'), dec=2)}",

        f"\n💵 <b>Karlılık</b>",
        f"  ROE: {f(data.get('roe'), pct=True)}  |  ROA: {f(data.get('roa'), pct=True)}",
        f"  ROIC: {'%{:.1f}'.format(data['roic']) if data.get('roic') else '—'}",
        f"  Brüt Marj: {f(data.get('gross_margin'), pct=True)}  |  Net Marj: {f(data.get('net_margin'), pct=True)}",

        f"\n🏦 <b>Nakit Akışı & Bilanço</b>",
        f"  FCF: {fmoney(data.get('fcf'))}  |  FCF Yield: {'%{:.1f}'.format(data['fcf_yield']) if data.get('fcf_yield') else '—'}",
        f"  Borç/ÖK: {f(data.get('debt_equity'), dec=2)}  |  Net Borç/EBITDA: {f(data.get('net_debt_ebitda'), dec=2)}",
        f"  Current Ratio: {f(data.get('current_ratio'), dec=2)}  |  Quick Ratio: {f(data.get('quick_ratio'), dec=2)}",

        f"\n📊 <b>Büyüme</b>",
        f"  Gelir: {f(data.get('revenue_growth'), pct=True)}  |  Kazanç: {f(data.get('earnings_growth'), pct=True)}",

        f"\n👥 <b>Sahiplik & Short</b>",
        f"  Insider: {f(data.get('insider_pct'), pct=True)}  |  Kurumsal: {f(data.get('inst_pct'), pct=True)}",
        f"  Short/Float: {f(data.get('short_pct_float'), pct=True)}  |  Short Ratio: {f(data.get('short_ratio'), dec=1)} gün",
    ]

    # Analist görüşü
    target = data.get("target_price")
    upside = data.get("upside")
    recom  = data.get("recommendation", "").replace("_", " ").upper()
    n      = data.get("analyst_count")
    if target:
        upside_str = f" ({upside:+.1f}%)" if upside else ""
        lines.append(
            f"\n🎯 <b>Analist Görüşü</b> ({n} analist)"
            if n else f"\n🎯 <b>Analist Görüşü</b>"
        )
        lines.append(f"  Hedef: ${target:,.2f}{upside_str}  |  Tavsiye: {recom or '—'}")

    # Temettü
    div = data.get("div_yield")
    if div:
        lines.append(f"\n💸 <b>Temettü</b>: %{div*100:.2f}")

    return "\n".join(lines)


# ─── 2. Haber Araması (Claude web_search) ────────────────────────────────────

def search_market_news(query: str, context: str = "") -> str:
    """
    Claude'un web_search tool'u ile piyasa haberi ara.
    529 overloaded hatası için 2 kez retry yapar.
    """
    import anthropic
    import time

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    prompt = f"""Şu piyasa sorusunu araştır ve 3-4 cümleyle özetle:

SORU: {query}
{f'BAĞLAM: {context}' if context else ''}

Sadece son 24-48 saatteki gelişmelere odaklan.
Türkçe yanıt ver.
Kaynak link verme, sadece özet bilgi yaz."""

    for attempt in range(3):  # Max 3 deneme
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )
            result = ""
            for block in response.content:
                if hasattr(block, "text"):
                    result += block.text
            return result.strip() if result else "Güncel haber bulunamadı."

        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                # Overloaded — kısa bekle ve tekrar dene
                time.sleep(3 * (attempt + 1))
                continue
            logger.warning("Haber araması başarısız (attempt %d): %s", attempt+1, e)
            return ""  # Hata mesajı gösterme, sessizce atla
        except Exception as e:
            logger.error("Haber araması hatası: %s", e)
            return ""

    return ""


# ─── 3. Tam Hisse Analizi ────────────────────────────────────────────────────

def analyze_ticker(ticker: str, portfolio_context: str = "") -> str:
    """
    /hisse komutu için tam analiz:
      1. Temel metrikler (yfinance)
      2. Son haberler (Claude web_search)
      3. Direktör yorumu
    """
    import anthropic

    ticker = ticker.upper()

    # Adım 1: Temel metrikler
    data       = get_fundamentals(ticker)
    fund_text  = format_fundamentals(data)

    if "error" in data:
        return fund_text

    # Adım 2: Son haberler
    news = search_market_news(
        f"{ticker} hisse son gelişmeler analiz",
        context=f"Yatırımcı bu hisseyi portföyünde tutuyor."
    )

    # Adım 3: Direktör yorumu
    director_comment = ""
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

        metrics_summary = (
            f"Ticker: {ticker}\n"
            f"P/E: {data.get('pe_trailing')}, Forward P/E: {data.get('pe_forward')}\n"
            f"PEG: {data.get('peg')}, FCF Yield: {data.get('fcf_yield')}\n"
            f"ROE: {data.get('roe')}, ROIC: {data.get('roic')}\n"
            f"Borç/ÖK: {data.get('debt_equity')}, Current Ratio: {data.get('current_ratio')}\n"
            f"Büyüme: Gelir {data.get('revenue_growth')}, Kazanç {data.get('earnings_growth')}\n"
            f"Son haberler: {news[:200]}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=(
                "Sen deneyimli bir portföy direktörüsün. "
                "Verilen metriklere bakarak 2-3 cümlelik somut bir yorum yap. "
                "Türkçe, net, eyleme dönüştürülebilir ol."
                + (f"\nYatırımcının mevcut durumu: {portfolio_context}" if portfolio_context else "")
            ),
            messages=[{
                "role": "user",
                "content": f"Bu hisse için kısa yorum yap:\n{metrics_summary}"
            }],
        )
        director_comment = response.content[0].text.strip()
    except Exception as e:
        logger.error("Direktör yorum hatası: %s", e)

    # Birleştir
    parts = [fund_text]
    if news and news != "Haber bulunamadı.":
        parts.append(f"\n📰 <b>Son Gelişmeler</b>\n{news}")
    if director_comment:
        parts.append(f"\n🧠 <b>Direktör</b>\n<i>{director_comment}</i>")

    return "\n".join(parts)
