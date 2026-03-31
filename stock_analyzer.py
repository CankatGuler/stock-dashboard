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

        # FCF Yield hesapla
        fcf        = info.get("freeCashflow")
        market_cap = info.get("marketCap")
        fcf_yield  = (fcf / market_cap * 100) if fcf and market_cap else None

        # ROIC yaklaşımı (yfinance'te direkt yok, hesapla)
        # ROIC = Net Income / (Total Assets - Current Liabilities)
        roic = None
        try:
            bs   = t.balance_sheet
            is_  = t.income_stmt
            if bs is not None and not bs.empty and is_ is not None and not is_.empty:
                total_assets = float(bs.loc["Total Assets"].iloc[0]) if "Total Assets" in bs.index else None
                curr_liab    = float(bs.loc["Current Liabilities"].iloc[0]) if "Current Liabilities" in bs.index else None
                net_income   = float(is_.loc["Net Income"].iloc[0]) if "Net Income" in is_.index else None
                if total_assets and curr_liab and net_income:
                    invested_cap = total_assets - curr_liab
                    if invested_cap > 0:
                        roic = net_income / invested_cap * 100
        except Exception:
            pass

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
            "debt_equity":  info.get("debtToEquity"),
            "current_ratio":info.get("currentRatio"),
            "quick_ratio":  info.get("quickRatio"),

            # Büyüme
            "revenue_growth":   info.get("revenueGrowth"),
            "earnings_growth":  info.get("earningsGrowth"),

            # Büyüklük
            "market_cap":   mc_str,

            # Temettü
            "div_yield":    info.get("dividendYield"),
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
        f"  52h Aralık: ${l52:,.2f} — ${h52:,.2f}" if l52 and h52 else "  52h: —",
        f"  Pozisyon: {pos_str}",
        f"  Beta: {f(data.get('beta'), dec=2)}  |  Piyasa Değeri: {data.get('market_cap','—')}",

        f"\n📈 <b>Değerleme</b>",
        f"  P/E (TTM): {f(data.get('pe_trailing'), dec=1)}  |  Forward P/E: {f(data.get('pe_forward'), dec=1)}",
        f"  PEG: {f(data.get('peg'), dec=2)}  |  P/B: {f(data.get('pb'), dec=2)}",
        f"  EV/EBITDA: {f(data.get('ev_ebitda'), dec=1)}",

        f"\n💵 <b>Karlılık</b>",
        f"  ROE: {f(data.get('roe'), pct=True)}  |  ROA: {f(data.get('roa'), pct=True)}",
        f"  ROIC: {'%{:.1f}'.format(data['roic']) if data.get('roic') else '—'}",
        f"  Brüt Marj: {f(data.get('gross_margin'), pct=True)}  |  Net Marj: {f(data.get('net_margin'), pct=True)}",

        f"\n🏦 <b>Nakit Akışı & Bilanço</b>",
        f"  FCF: {fmoney(data.get('fcf'))}  |  FCF Yield: {f(data.get('fcf_yield'), suffix='%', dec=1) if data.get('fcf_yield') else '—'}",
        f"  Borç/ÖK: {f(data.get('debt_equity'), dec=2)}  |  Current Ratio: {f(data.get('current_ratio'), dec=2)}",

        f"\n📊 <b>Büyüme</b>",
        f"  Gelir: {f(data.get('revenue_growth'), pct=True)}  |  Kazanç: {f(data.get('earnings_growth'), pct=True)}",
    ]

    div = data.get("div_yield")
    if div:
        lines.append(f"  Temettü: %{div*100:.2f}")

    return "\n".join(lines)


# ─── 2. Haber Araması (Claude web_search) ────────────────────────────────────

def search_market_news(query: str, context: str = "") -> str:
    """
    Claude'un web_search tool'u ile piyasa haberi ara.
    Perplexity yerine — ücretsiz, Claude API'ye dahil.

    query   : Aranacak konu (örn: "VIX spike sebebi bugün")
    context : Ek bağlam (örn: portföy özeti)
    Döndürür: 3-5 cümlelik haber özeti
    """
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

        prompt = f"""Şu piyasa sorusunu araştır ve 3-4 cümleyle özetle:

SORU: {query}
{f'BAĞLAM: {context}' if context else ''}

Sadece son 24 saatteki gelişmelere odaklan.
Türkçe yanıt ver.
Kaynak link verme, sadece özet bilgi yaz."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )

        # Yanıttan text bloklarını topla
        result = ""
        for block in response.content:
            if hasattr(block, "text"):
                result += block.text

        return result.strip() if result else "Haber bulunamadı."

    except Exception as e:
        logger.error("Haber araması hatası: %s", e)
        return f"Haber aranamadı: {e}"


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
