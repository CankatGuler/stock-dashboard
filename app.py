# app.py — AI-Powered Stock Analysis & Decision Dashboard
# Run with:  streamlit run app.py

import os
import time
import logging

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()

from utils import (
    SECTOR_TICKERS,
    categorise_stock,
    score_color,
    score_badge,
)
from data_fetcher import batch_enrich, get_quote
from news_fetcher import fetch_news_batch, format_news_for_prompt
from claude_analyzer import analyse_batch
from analysis_memory import get_ticker_history, get_all_history, get_history_summary, get_top_tickers
from radar_engine import run_radar


def determine_category(stock: dict) -> str:
    """Yeni kategori sistemi: Rocket / Balanced / Shield — mktCap + Beta bazlı."""
    from utils import categorise_stock as _cat
    return _cat(stock)
from portfolio_manager import (
    load_portfolio, add_position, remove_position, update_position,
    sell_position, enrich_portfolio_with_prices, portfolio_summary,
    import_from_csv, export_to_csv, generate_csv_template,
    get_cash, add_cash, deduct_cash, set_cash,
)

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Quant Dashboard | AI Stock Analysis",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL CSS — Wall-Street Terminal Aesthetic
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;800&display=swap');

    :root {
        --bg-deep:     #080c10;
        --bg-card:     #0d1117;
        --bg-elevated: #13181f;
        --border:      #1e2833;
        --accent:      #00c48c;
        --accent-dim:  #007a58;
        --amber:       #f5a623;
        --red:         #e74c3c;
        --text-primary: #e8edf3;
        --text-muted:   #5a6a7a;
        --text-dim:     #3a4a5a;
    }

    html, body, [class*="css"] {
        font-family: 'JetBrains Mono', monospace !important;
        background-color: var(--bg-deep) !important;
        color: var(--text-primary) !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: var(--bg-card) !important;
        border-right: 1px solid var(--border) !important;
    }
    section[data-testid="stSidebar"] * { color: var(--text-primary) !important; }

    /* Header */
    .dash-header {
        font-family: 'Syne', sans-serif;
        font-weight: 800;
        font-size: 2rem;
        letter-spacing: -0.03em;
        color: var(--text-primary);
        border-bottom: 1px solid var(--border);
        padding-bottom: 0.6rem;
        margin-bottom: 0.3rem;
    }
    .dash-sub {
        font-size: 0.72rem;
        color: var(--text-muted);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 1.8rem;
    }

    /* KPI Cards */
    .kpi-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1.1rem 1.3rem;
        position: relative;
        overflow: hidden;
    }
    .kpi-card::before {
        content: "";
        position: absolute;
        left: 0; top: 0; bottom: 0;
        width: 3px;
    }
    .kpi-card.green::before  { background: var(--accent); }
    .kpi-card.amber::before  { background: var(--amber);  }
    .kpi-card.red::before    { background: var(--red);    }
    .kpi-ticker {
        font-size: 1.3rem;
        font-weight: 700;
        color: var(--text-primary);
    }
    .kpi-name {
        font-size: 0.65rem;
        color: var(--text-muted);
        margin-bottom: 0.6rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .kpi-score-label { font-size: 0.6rem; color: var(--text-muted); }
    .kpi-meta {
        font-size: 0.62rem;
        color: var(--text-muted);
        margin-top: 0.5rem;
        line-height: 1.7;
    }
    .kpi-recommendation {
        display: inline-block;
        margin-top: 0.5rem;
        font-size: 0.6rem;
        padding: 2px 8px;
        border-radius: 3px;
        font-weight: 700;
        letter-spacing: 0.08em;
    }
    .rec-up   { background: #0a2e1f; color: var(--accent); border: 1px solid var(--accent-dim); }
    .rec-hold { background: #2a1f00; color: var(--amber);  border: 1px solid #7a5000; }
    .rec-down { background: #2e0a0a; color: var(--red);    border: 1px solid #7a2020; }

    /* Risk pill badges */
    .risk-label {
        display: inline-block;
        font-size: 0.6rem;
        padding: 2px 7px;
        border-radius: 3px;
        margin-bottom: 0.25rem;
        background: var(--bg-elevated);
        border: 1px solid var(--border);
        color: var(--text-muted);
    }

    /* Expander overrides */
    details summary {
        background: var(--bg-elevated) !important;
        border: 1px solid var(--border) !important;
        border-radius: 6px !important;
        padding: 0.75rem 1rem !important;
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        color: var(--text-primary) !important;
    }
    details[open] summary { border-radius: 6px 6px 0 0 !important; }

    /* Streamlit widgets */
    .stMultiSelect [data-baseweb="tag"] {
        background-color: var(--accent-dim) !important;
        border-color: var(--accent) !important;
    }
    .stButton > button {
        width: 100%;
        background: var(--accent) !important;
        color: #080c10 !important;
        border: none !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 700 !important;
        letter-spacing: 0.08em !important;
        border-radius: 5px !important;
        padding: 0.55rem 0 !important;
        transition: opacity 0.15s;
    }
    .stButton > button:hover { opacity: 0.85; }

    /* Divider */
    .section-divider {
        border: none;
        border-top: 1px solid var(--border);
        margin: 1.5rem 0;
    }

    /* Progress text */
    .progress-label {
        font-size: 0.65rem;
        color: var(--text-muted);
        margin-bottom: 0.3rem;
    }

    /* Gauge ring */
    .gauge-wrap { text-align: center; }

    /* Empty state */
    .empty-state {
        text-align: center;
        padding: 3rem;
        color: var(--text-dim);
        font-size: 0.8rem;
        border: 1px dashed var(--border);
        border-radius: 8px;
    }

    /* Scrollable news list */
    .news-item {
        padding: 0.5rem 0;
        border-bottom: 1px solid var(--border);
        font-size: 0.65rem;
        line-height: 1.6;
    }
    .news-source { color: var(--accent); font-weight: 600; }
    .news-title  { color: var(--text-primary); }
    .news-desc   { color: var(--text-muted); }

    /* Plotly transparent bg */
    .js-plotly-plot .plotly .bg { fill: transparent !important; }

    /* Hide Streamlit default chrome */
    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER COMPONENTS
# ─────────────────────────────────────────────────────────────────────────────


def tradingview_chart(ticker: str, height: int = 420) -> None:
    """TradingView Advanced Chart widget'ını Streamlit'e göm."""
    # Exchange prefix otomatik tespit için NASDAQ/NYSE yazmadan sadece sembol kullan
    # TradingView kendi kendine tanır
    html = f"""
    <div class="tradingview-widget-container" style="border-radius:8px;overflow:hidden;">
      <div id="tv_chart_{ticker}"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "width": "100%",
        "height": {height},
        "symbol": "{ticker}",
        "interval": "D",
        "timezone": "Europe/Istanbul",
        "theme": "dark",
        "style": "1",
        "locale": "tr",
        "toolbar_bg": "#0a1929",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": false,
        "save_image": false,
        "container_id": "tv_chart_{ticker}",
        "studies": ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
        "show_popup_button": true,
        "popup_width": "1000",
        "popup_height": "650"
      }});
      </script>
    </div>
    """
    components.html(html, height=height + 20, scrolling=False)

def gauge_chart(score: int, size: int = 200) -> go.Figure:
    """Render a donut-style gauge for the confidence score."""
    color = score_color(score)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        gauge=dict(
            axis=dict(
                range=[0, 100],
                tickwidth=1,
                tickcolor="#1e2833",
                tickfont=dict(color="#3a4a5a", size=9),
            ),
            bar=dict(color=color, thickness=0.22),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            steps=[
                dict(range=[0,  45],  color="#13181f"),
                dict(range=[45, 70],  color="#1a1e14"),
                dict(range=[70, 100], color="#0a1e16"),
            ],
            threshold=dict(
                line=dict(color=color, width=2),
                thickness=0.7,
                value=score,
            ),
        ),
        number=dict(font=dict(color=color, size=32, family="JetBrains Mono")),
        domain=dict(x=[0, 1], y=[0, 1]),
    ))
    fig.update_layout(
        height=size,
        margin=dict(l=20, r=20, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#5a6a7a"),
    )
    return fig


def recommendation_badge(tavsiye: str) -> str:
    tavsiye_lower = tavsiye.lower()
    if "artır" in tavsiye_lower or "artirir" in tavsiye_lower:
        css_class = "rec-up"
        icon = "▲"
    elif "azalt" in tavsiye_lower:
        css_class = "rec-down"
        icon = "▼"
    else:
        css_class = "rec-hold"
        icon = "■"
    return f'<span class="kpi-recommendation {css_class}">{icon} {tavsiye.upper()}</span>'


def category_chip(kategori: str) -> str:
    if kategori == "Rocket 🚀":
        return '<span style="background:#1a3a1a;color:#00e676;border:1px solid #00e676;border-radius:4px;padding:1px 8px;font-size:0.65rem;font-weight:700;">Rocket 🚀</span>'
    if kategori == "Balanced ⚖️":
        return '<span style="background:#1a2a3a;color:#4fc3f7;border:1px solid #4fc3f7;border-radius:4px;padding:1px 8px;font-size:0.65rem;font-weight:700;">Balanced ⚖️</span>'
    if kategori == "Shield 🛡️":
        return '<span style="background:#2a2a1a;color:#ffb300;border:1px solid #ffb300;border-radius:4px;padding:1px 8px;font-size:0.65rem;font-weight:700;">Shield 🛡️</span>'
    if kategori == "A Tipi":
        return '<span style="font-size:0.6rem;background:#0a2040;color:#5599ff;border:1px solid #1a3060;padding:2px 7px;border-radius:3px;font-weight:700;">A TİPİ · KALKAN</span>'
    return '<span style="font-size:0.6rem;background:#2a0a20;color:#ff55aa;border:1px solid #601a40;padding:2px 7px;border-radius:3px;font-weight:700;">B TİPİ · ROKET</span>'


def _score_css_class(score: int) -> str:
    if score >= 70:  return "green"
    if score >= 45:  return "amber"
    return "red"


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

# Sidebar hidden — filters moved inline
selected_sectors = ["Sanayi"]
strategy         = "Hepsi"
max_tickers      = 8
news_days        = 7
run_button       = False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(
    '<div class="dash-header">AI DESTEKLI HİSSE ANALİZ DASHBOARD</div>'
    '<div class="dash-sub">Quantitative Signal Engine · Real-Time Fundamental Screener · Claude AI Risk Mapping</div>',
    unsafe_allow_html=True,
)

# ─── API Key check banner ───
missing_keys = []
if not os.getenv("FMP_API_KEY"):       missing_keys.append("FMP_API_KEY")
if not os.getenv("NEWS_API_KEY"):      missing_keys.append("NEWS_API_KEY")
if not os.getenv("ANTHROPIC_API_KEY"): missing_keys.append("ANTHROPIC_API_KEY")

if missing_keys:
    st.warning(
        f"⚠️  Eksik API anahtarları: `{', '.join(missing_keys)}` — "
        "`.env` dosyanızı kontrol edin. Demo modu için mock veriler kullanılabilir.",
        icon="🔑",
    )


# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_screener, tab_portfolio, tab_radar, tab_lookup, tab_memory, tab_watchlist = st.tabs(["📡  Sektör Tarayıcı", "💼  Portföyüm", "🔭  Fırsat Radarı", "🔍  Hisse Sorgula", "🧠  Hafıza", "👁  Takip"])

# ─────────────────────────────────────────────────────────────────────────────
# STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
if "analysis_results" not in st.session_state:
    st.session_state["analysis_results"] = []
if "enriched_stocks"   not in st.session_state:
    st.session_state["enriched_stocks"]   = []
if "news_map"          not in st.session_state:
    st.session_state["news_map"]          = {}
if "enriched_portfolio" not in st.session_state:
    st.session_state["enriched_portfolio"] = []
if "correlation_analysis" not in st.session_state:
    st.session_state["correlation_analysis"] = ""
if "scenario_analysis" not in st.session_state:
    st.session_state["scenario_analysis"] = ""
if "scenario_title" not in st.session_state:
    st.session_state["scenario_title"] = ""


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SCREENER
# ─────────────────────────────────────────────────────────────────────────────
with tab_screener:

    # ── INLINE FILTER PANEL ────────────────────────────────────────────────────
    with st.expander("⚙️  Filtreler ve Ayarlar", expanded=True):
        fc1, fc2 = st.columns([2, 1])
        with fc1:
            selected_sectors = st.multiselect(
                "🏭 SEKTÖR FİLTRESİ",
                options=list(SECTOR_TICKERS.keys()),
                default=["Sanayi"],
                help="Analiz edilecek sektörleri seçin.",
            )
        with fc2:
            strategy = st.radio(
                "🎯 STRATEJİ",
                options=["Rocket 🚀", "Balanced ⚖️", "Shield 🛡️", "Hepsi"],
                index=3,
                horizontal=True,
                help="Rocket: mktCap<10B | Balanced: 10-50B | Shield: >50B | Hepsi: tümü",
            )

        sc1, sc2, sc3 = st.columns([1, 1, 1])
        with sc1:
            max_tickers = st.slider("🔢 Maks. Hisse Sayısı", 3, 20, 8)
        with sc2:
            news_days = st.slider("📰 Haber Penceresi (Gün)", 3, 14, 7)
        with sc3:
            st.markdown('<div style="margin-top:1.6rem;"></div>', unsafe_allow_html=True)
            run_button = st.button("⚡  ANALİZİ BAŞLAT", use_container_width=True)

    st.markdown(
        '<div style="font-size:0.55rem;color:#3a4a5a;text-align:right;margin-top:-0.5rem;">'
        'UYARI: Bu araç yatırım tavsiyesi değildir. © 2025 Quant Dashboard'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── RUN ANALYSIS PIPELINE ──────────────────────────────────────────────────

    if run_button:
        if not selected_sectors:
            st.error("Lütfen en az bir sektör seçin.")

        # ── Build ticker universe ──
        all_tickers: list[str] = []
        for sec in selected_sectors:
            all_tickers.extend(SECTOR_TICKERS.get(sec, []))
        # Deduplicate, respect max_tickers
        all_tickers = list(dict.fromkeys(all_tickers))[:max_tickers]

        with st.status("🔄 Pipeline çalışıyor...", expanded=True) as status:

            # 1. FMP enrichment
            st.write(f"📊 **Adım 1/3:** {len(all_tickers)} hisse için FMP'den temel veriler çekiliyor...")
            enriched = batch_enrich(all_tickers)

            # Attach kategori
            for stock in enriched:
                stock["kategori"] = determine_category(stock)

            # Strategy filter
            if strategy != "Hepsi":
                enriched = [s for s in enriched if s["kategori"] == strategy]

            if not enriched:
                st.warning("Seçilen kriterlere uyan hisse bulunamadı.")
                status.update(label="⚠️ Hisse bulunamadı", state="error")

            st.write(f"✅ {len(enriched)} hisse seçildi ({strategy}).")

            # 2. News fetch
            st.write(f"📰 **Adım 2/3:** Son {news_days} günün haberleri çekiliyor ve filtreleniyor...")
            news_map = fetch_news_batch(enriched, days_back=news_days)
            total_news = sum(len(v) for v in news_map.values())
            st.write(f"✅ Toplam {total_news} filtreli haber bulundu.")

            # 3. Claude analysis
            st.write(f"🤖 **Adım 3/3:** Claude ile {len(enriched)} hisse analiz ediliyor...")

            # Progress placeholder
            progress_bar  = st.progress(0)
            progress_text = st.empty()

            def on_progress(ticker, idx, total):
                pct = idx / total
                progress_bar.progress(pct)
                progress_text.markdown(
                    f'<div class="progress-label">Analiz ediliyor: '
                    f'<span style="color:#00c48c;">{ticker}</span> '
                    f'({idx}/{total})</div>',
                    unsafe_allow_html=True,
                )

            results = analyse_batch(
                enriched,
                news_map,
                progress_callback=on_progress,
            )

            # Claude'un kategori değerini bizim hesapladığımızla override et
            for res in results:
                meta = res.get("_stock_meta", {})
                if meta:
                    res["kategori"] = determine_category(meta)

            progress_bar.progress(1.0)
            progress_text.empty()

            # Persist to session state
            st.session_state["analysis_results"] = results
            st.session_state["enriched_stocks"]  = enriched
            st.session_state["news_map"]         = news_map

            status.update(
                label=f"✅ Analiz tamamlandı — {len(results)} hisse değerlendirildi.",
                state="complete",
                expanded=False,
            )


    # ─────────────────────────────────────────────────────────────────────────────
    # DISPLAY RESULTS
    # ─────────────────────────────────────────────────────────────────────────────

    results: list[dict] = st.session_state.get("analysis_results", [])
    news_map: dict       = st.session_state.get("news_map", {})

    if not results:
        st.markdown(
            '<div class="empty-state">'
            '📡 Analiz başlatılmadı.<br><br>'
            'Sol menüden sektör ve strateji seçin, ardından<br>'
            '<strong>⚡ ANALİZİ BAŞLAT</strong> butonuna tıklayın.'
            '</div>',
            unsafe_allow_html=True,
        )

    # ─── TOP KPI CARDS ───────────────────────────────────────────────────────────
    TOP_N   = 5
    top_hits = [r for r in results if r.get("nihai_guven_skoru", 0) >= 70][:TOP_N]
    if not top_hits:
        top_hits = results[:TOP_N]

    st.markdown(
        f'<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        f'letter-spacing:0.12em;margin-bottom:0.8rem;">'
        f'▶ EN YÜKSEK SKORLU HİSSELER  ·  Güven Eşiği ≥ 70</div>',
        unsafe_allow_html=True,
    )

    if not top_hits:
        st.info("Henüz analiz yapılmadı. Sol menüden sektör seçip ⚡ ANALİZİ BAŞLAT butonuna tıklayın.")
    else:
        kpi_cols = st.columns(len(top_hits))

    for col, result in zip(kpi_cols if top_hits else [], top_hits):
        meta  = result.get("_stock_meta", {})
        score = result.get("nihai_guven_skoru", 0)
        css   = _score_css_class(score)
        tavsiye = result.get("tavsiye", "Tut")

        with col:
            st.markdown(
                f'<div class="kpi-card {css}">'
                f'  <div class="kpi-ticker">{result["hisse_sembolu"]}</div>'
                f'  <div class="kpi-name">{meta.get("companyName", "")}</div>'
                f'  <div class="kpi-score-label">Güven Skoru</div>'
                f'  {score_badge(score)}'
                f'  <div class="kpi-meta">'
                f'    Kategori: {result.get("kategori","N/A")}<br>'
                f'    Fiyat:    ${meta.get("price", 0):.2f} '
                f'    ({meta.get("change_pct", 0):+.1f}%)<br>'
                f'    Mkt Cap:  ${meta.get("mktCap",0)/1e9:.1f}B<br>'
                f'    Beta:     {meta.get("beta",0):.2f}'
                f'  </div>'
                f'  {recommendation_badge(tavsiye)}'
                f'</div>',
                unsafe_allow_html=True,
            )


    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ─── DETAILED EXPANDER CARDS ─────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.12em;margin-bottom:0.8rem;">'
        '▶ TÜM ANALİZLER — DETAYLI RAPOR</div>',
        unsafe_allow_html=True,
    )

    for result in results:
        score     = result.get("nihai_guven_skoru", 0)
        ticker    = result.get("hisse_sembolu", "?")
        kategori  = result.get("kategori", "")
        tavsiye   = result.get("tavsiye", "Tut")
        ozet      = result.get("analiz_ozeti", "")
        riskler   = result.get("kritik_riskler", {})
        meta      = result.get("_stock_meta", {})
        css_class = _score_css_class(score)
        color     = score_color(score)

        expander_label = (
            f"{ticker}  ·  {meta.get('companyName', '')}  ·  "
            f"Skor: {score}/100  ·  {kategori}  ·  {tavsiye}"
        )

        with st.expander(expander_label, expanded=(score >= 75)):

            col_left, col_mid, col_right = st.columns([1.4, 2.2, 1.8])

            # ── Left: Gauge + meta ──────────────────────────────────────────────
            with col_left:
                st.plotly_chart(gauge_chart(score, size=190), use_container_width=True, key=f"gauge_{ticker}")

                st.markdown(
                    f'{category_chip(kategori)}'
                    f'<br>{recommendation_badge(tavsiye)}',
                    unsafe_allow_html=True,
                )

                # ── Metrikler (yfinance) ───────────────────────────────────
                _price  = meta.get("price") or 0
                _chg    = meta.get("change_pct") or 0
                _mc     = meta.get("mktCap") or 0
                _beta   = meta.get("beta") or 0
                _pe     = meta.get("peRatio") or 0
                _fpe    = meta.get("forwardPE") or 0
                _eps    = meta.get("eps") or 0
                _de     = meta.get("debtToEquity") or 0
                _roe    = meta.get("roic") or 0
                _gm     = meta.get("grossMargin") or 0
                _revgr  = meta.get("revenueGrowth") or 0
                _fcf    = meta.get("freeCashFlow") or 0
                _div    = meta.get("dividendYield") or 0
                _52h    = meta.get("52wHigh") or 0
                _52l    = meta.get("52wLow") or 0
                _tgt    = meta.get("analystTarget") or 0
                _tgt_h  = meta.get("analystHigh") or 0
                _tgt_l  = meta.get("analystLow") or 0
                _rec    = meta.get("recommendation") or ""
                _acnt   = meta.get("analystCount") or 0
                _sector = meta.get("sector", "N/A")

                def _fmt(val, fmt, fallback="—"):
                    try:
                        return fmt.format(val) if val else fallback
                    except Exception:
                        return fallback

                _mc_str  = f"${_mc/1e9:.1f}B" if _mc > 0 else "—"
                _pe_str  = f"{_pe:.1f}x" if _pe > 0 else "—"
                _fpe_str = f"{_fpe:.1f}x" if _fpe > 0 else "—"
                _eps_str = f"${_eps:.2f}" if _eps != 0 else "—"
                _de_str  = f"{_de:.2f}" if _de > 0 else "—"
                _roe_str = f"{_roe:.1%}" if _roe != 0 else "—"
                _gm_str  = f"{_gm:.1%}" if _gm > 0 else "—"
                _rg_str  = f"{_revgr:+.1%}" if _revgr != 0 else "—"
                _div_str = f"{_div:.1%}" if _div > 0 else "—"
                _fcf_str = (f"${_fcf/1e9:.1f}B" if abs(_fcf) >= 1e9
                            else f"${_fcf/1e6:.0f}M" if _fcf != 0 else "—")

                _range_str = "—"
                if _52h > 0 and _52l > 0 and _price > 0 and (_52h - _52l) > 0:
                    _pct = (_price - _52l) / (_52h - _52l) * 100
                    _range_str = f"{_pct:.0f}%  ({_52l:.0f} / {_52h:.0f})"

                _tgt_str = "—"
                if _tgt > 0 and _price > 0:
                    _up = (_tgt - _price) / _price * 100
                    _tgt_str = f"${_tgt:.0f} ({_up:+.1f}%)"
                    if _tgt_h > 0 and _tgt_l > 0:
                        _tgt_str += f" · {_tgt_l:.0f}–{_tgt_h:.0f}"

                _rec_str = _rec.replace("-", " ").title() if _rec else "—"
                if _acnt > 0:
                    _rec_str += f" · {_acnt} uzman"

                st.markdown(
                    f'<div class="kpi-meta" style="margin-top:0.6rem;line-height:1.95;">'
                    f'  Sektör     : {_sector}<br>'
                    f'  Fiyat      : ${_price:.2f} ({_chg:+.1f}%)<br>'
                    f'  Mkt Cap    : {_mc_str}<br>'
                    f'  Beta       : {_beta:.2f}<br>'
                    f'  P/E (TTM)  : {_pe_str}<br>'
                    f'  P/E (Fwd)  : {_fpe_str}<br>'
                    f'  EPS        : {_eps_str}<br>'
                    f'  D/E        : {_de_str}<br>'
                    f'  ROE        : {_roe_str}<br>'
                    f'  Brüt Marj  : {_gm_str}<br>'
                    f'  Gelir Büy. : {_rg_str}<br>'
                    f'  FCF        : {_fcf_str}<br>'
                    f'  52H Pos.   : {_range_str}<br>'
                    f'  Analist    : {_tgt_str}<br>'
                    f'  Tavsiye    : {_rec_str}<br>'
                    f'  Temettü    : {_div_str}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # ── Middle: Analiz özeti + risk haritası ────────────────────────────
            with col_mid:
                st.markdown(
                    f'<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                    f'letter-spacing:0.1em;margin-bottom:0.4rem;">📋 ANALİZ ÖZETİ</div>'
                    f'<div style="background:#13181f;border:1px solid #1e2833;border-radius:6px;'
                    f'padding:0.9rem;font-size:0.75rem;line-height:1.7;color:#c0c8d0;">'
                    f'{ozet}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                st.markdown(
                    '<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                    'letter-spacing:0.1em;margin:1rem 0 0.4rem;">⚠️ İKİLİ RİSK HARİTASI</div>',
                    unsafe_allow_html=True,
                )

                macro_risk = riskler.get("global_makro", "Belirtilmemiş")
                firm_risk  = riskler.get("finansal_sirket_ozel", "Belirtilmemiş")

                st.markdown(
                    f'<div style="background:#13181f;border:1px solid #1e2833;'
                    f'border-radius:6px;padding:0.9rem;">'
                    f'<div style="margin-bottom:0.6rem;">'
                    f'  <span class="risk-label">🌍 GLOBAL MAKRO</span><br>'
                    f'  <span style="font-size:0.72rem;color:#c0c8d0;line-height:1.6;">{macro_risk}</span>'
                    f'</div>'
                    f'<div>'
                    f'  <span class="risk-label">🏢 ŞİRKET / FİNANSAL</span><br>'
                    f'  <span style="font-size:0.72rem;color:#c0c8d0;line-height:1.6;">{firm_risk}</span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # ── Right: Filtered news ─────────────────────────────────────────────
            with col_right:
                st.markdown(
                    '<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                    'letter-spacing:0.1em;margin-bottom:0.4rem;">📰 FİLTRELENMİŞ HABERLER</div>',
                    unsafe_allow_html=True,
                )

                articles = news_map.get(ticker, [])
                if articles:
                    for art in articles[:6]:
                        title   = art.get("title", "")[:90]
                        source  = art.get("source", "")
                        if isinstance(source, dict): source = source.get("name", "")
                        pub     = art.get("published", "")[:10]
                        url     = art.get("url", "#")
                        st.markdown(
                            f'<div class="news-item">'
                            f'  <span class="news-source">[{source}]</span>'
                            f'  <span style="color:#3a4a5a;"> {pub}</span><br>'
                            f'  <a href="{url}" target="_blank" style="color:#c0c8d0;'
                            f'  text-decoration:none;" class="news-title">{title}</a>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#3a4a5a;">'
                        'Bu hisse için filtreden geçen haber bulunamadı.'
                        '</div>',
                        unsafe_allow_html=True,
                    )


            # ── TradingView Grafik (tam genişlik) ───────────────────────────────
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:1rem 0 0.3rem;">📈 FİYAT GRAFİĞİ</div>',
                unsafe_allow_html=True,
            )
            tradingview_chart(ticker, height=400)


    # ─── SUMMARY TABLE ───────────────────────────────────────────────────────────
    if results:
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.8rem;">'
            '▶ ÖZET SKOR TABLOSU</div>',
            unsafe_allow_html=True,
        )

        table_data = []
        for r in results:
            meta = r.get("_stock_meta", {})
            table_data.append({
                "Ticker":    r.get("hisse_sembolu", ""),
                "Şirket":    meta.get("companyName", "")[:30],
                "Kategori":  r.get("kategori", ""),
                "Skor":      r.get("nihai_guven_skoru", 0),
                "Tavsiye":   r.get("tavsiye", ""),
                "Fiyat":     f"${meta.get('price', 0):.2f}",
                "MktCap(B)": f"${meta.get('mktCap', 0)/1e9:.1f}",
                "Beta":      f"{meta.get('beta', 0):.2f}",
            })

        df = pd.DataFrame(table_data)

        def color_score(val):
            try:
                v = int(val)
            except (ValueError, TypeError):
                return ""
            if v >= 70:   return "color: #00c48c; font-weight: 700"
            if v >= 45:   return "color: #f5a623; font-weight: 700"
            return "color: #e74c3c; font-weight: 700"

        if not df.empty and "Skor" in df.columns:
            st.dataframe(
                df.style.map(color_score, subset=["Skor"]),
                use_container_width=True,
                hide_index=True,
            )

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇  CSV Olarak İndir",
                data=csv,
                file_name="quant_analysis.csv",
                mime="text/csv",
            )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — PORTFOLIO
# ─────────────────────────────────────────────────────────────────────────────
with tab_portfolio:

    st.markdown(
        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.12em;margin-bottom:1rem;">'
        '▶ PORTFÖY YÖNETİMİ — Pozisyon Ekle / Düzenle / Analiz Et</div>',
        unsafe_allow_html=True,
    )

    # ── Top action buttons ─────────────────────────────────────────────────
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        st.download_button(
            label="📥  CSV Şablonunu İndir",
            data=generate_csv_template(),
            file_name="portfoy_sablonu.csv",
            mime="text/csv",
            key="dl_template",
            use_container_width=True,
        )
    with btn_col2:
        current_pos = load_portfolio()
        if current_pos:
            st.download_button(
                label="⬇  Mevcut Portföyü İndir",
                data=export_to_csv(current_pos),
                file_name="portfoy.csv",
                mime="text/csv",
                key="dl_current",
                use_container_width=True,
            )
    with btn_col3:
        st.markdown("")   # spacer

    st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

    # ── CSV Bulk Import ─────────────────────────────────────────────────────
    with st.expander("📤  CSV ile Toplu Yükle / Güncelle", expanded=False):
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;line-height:1.9;margin-bottom:0.8rem;">'
            '1. Yukarıdaki <b>CSV Şablonunu İndir</b> butonuyla şablonu al.<br>'
            '2. Excel veya Google Sheets\'te açıp portföyünü doldur.<br>'
            '3. CSV olarak kaydet ve aşağıdan yükle.<br>'
            '<b>Sütunlar:</b> ticker · shares (adet) · avg_cost (ort. maliyet $) · sector · notes'
            '</div>',
            unsafe_allow_html=True,
        )
        csv_mode = st.radio(
            "Yükleme Modu",
            options=["Birleştir (mevcut portföye ekle)", "Sıfırla (portföyü tamamen değiştir)"],
            key="csv_mode",
            horizontal=True,
        )
        uploaded_csv = st.file_uploader(
            "CSV Dosyasını Seç",
            type=["csv"],
            key="csv_uploader",
        )
        if uploaded_csv is not None:
            if st.button("🚀  Yükle ve Kaydet", key="btn_csv_import"):
                mode = "replace" if "Sıfırla" in csv_mode else "merge"
                positions_new, errs = import_from_csv(uploaded_csv.read(), mode=mode)
                if errs:
                    for e in errs:
                        st.warning(e)
                st.success(f"✅ {len(positions_new)} pozisyon yüklendi!")
                st.rerun()

    # ── Add Single Position Form ────────────────────────────────────────────
    with st.expander("➕  Tek Pozisyon Ekle / Yeni Alış", expanded=False):
        col_f1, col_f2, col_f3, col_f4 = st.columns([1.2, 1, 1.2, 1.5])
        with col_f1:
            p_ticker = st.text_input("Ticker", placeholder="AAPL", key="p_ticker").upper().strip()
        with col_f2:
            p_shares = st.number_input("Hisse Adedi", min_value=0.0, step=1.0, key="p_shares")
        with col_f3:
            p_cost   = st.number_input("Ortalama Maliyet ($)", min_value=0.0, step=0.01, key="p_cost")
        with col_f4:
            p_notes  = st.text_input("Not", placeholder="İsteğe bağlı", key="p_notes")

        st.caption("💡 Sektör bilgisi otomatik olarak piyasadan çekilir.")

        # Nakit önizlemesi
        _buy_cash = get_cash()
        if p_shares > 0 and p_cost > 0:
            _buy_total = p_shares * p_cost
            _remaining = _buy_cash - _buy_total
            _clr = "#00c48c" if _remaining >= 0 else "#e74c3c"
            _emoji = "✅" if _remaining >= 0 else "⚠️"
            st.markdown(
                f'<div style="background:#0d1117;border:1px solid #1e2833;border-radius:6px;'
                f'padding:0.45rem 0.8rem;font-size:0.75rem;margin-bottom:0.3rem;">'
                f'Mevcut nakit: <b style="color:#4fc3f7;">${_buy_cash:,.2f}</b>'
                f' &nbsp;→&nbsp; Alım tutarı: <b>${_buy_total:,.2f}</b>'
                f' &nbsp;→&nbsp; Kalan: <b style="color:{_clr};">{_emoji} ${_remaining:,.2f}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="font-size:0.72rem;color:#5a6a7a;margin-bottom:0.3rem;">'
                f'Mevcut nakit: <b style="color:#4fc3f7;">${_buy_cash:,.2f}</b> — '
                f'Alım onaylandığında otomatik düşülür.</div>',
                unsafe_allow_html=True,
            )

        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("💾  Kaydet", key="btn_add_pos"):
                if p_ticker and p_shares > 0 and p_cost > 0:
                    add_position(p_ticker, p_shares, p_cost, "Diğer", p_notes)
                    st.success(f"✅ {p_ticker} portföye eklendi! Sektör otomatik yüklenecek.")
                    st.rerun()
                else:
                    st.error("Ticker, hisse adedi ve maliyet zorunludur.")

    # ── Cash Management ────────────────────────────────────────────────────
    with st.expander("💵  Nakit Ekle / Çıkar", expanded=False):
        _cur_cash = get_cash()
        st.markdown(
            f'<div style="background:#0d1117;border:1px solid #1e6a9e;border-radius:8px;'
            f'padding:0.6rem 1rem;margin-bottom:0.8rem;display:flex;align-items:center;gap:12px;">'
            f'<span style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;letter-spacing:0.08em;">Mevcut Nakit</span>'
            f'<span style="font-size:1.4rem;font-weight:700;color:#4fc3f7;">${_cur_cash:,.2f}</span>'
            f'<span style="font-size:0.65rem;color:#5a6a7a;margin-left:auto;">Hisse alımında otomatik düşülür · Satışta otomatik eklenir</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        cash_col1, cash_col2, cash_col3 = st.columns([1.5, 1, 2])
        with cash_col1:
            cash_op = st.radio(
                "İşlem:", ["➕ Nakit Ekle", "➖ Nakit Çıkar", "🔄 Bakiyeyi Ayarla"],
                key="cash_op", horizontal=False,
            )
        with cash_col2:
            cash_amount = st.number_input(
                "Miktar ($)", min_value=0.0, step=100.0, key="cash_amount"
            )
        with cash_col3:
            cash_note = st.text_input(
                "Not (isteğe bağlı)", placeholder="örn: Maaş, Temettü, Para yatırma...",
                key="cash_note"
            )
            if cash_op == "🔄 Bakiyeyi Ayarla":
                st.caption("Nakiti doğrudan girdiğin değere ayarlar (mevcut bakiyeyi ezer).")
            st.markdown('<div style="margin-top:0.4rem;"></div>', unsafe_allow_html=True)
            if st.button("✅ Uygula", key="btn_cash", use_container_width=True):
                if cash_amount > 0:
                    if cash_op == "➕ Nakit Ekle":
                        new_bal, msg = add_cash(cash_amount, cash_note or "Nakit ekleme")
                    elif cash_op == "➖ Nakit Çıkar":
                        new_bal, msg = deduct_cash(cash_amount, cash_note or "Nakit çıkarma")
                    else:
                        set_cash(cash_amount)
                        new_bal = cash_amount
                        msg = f"Bakiye ${cash_amount:,.2f} olarak ayarlandı."
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.error("Miktar 0'dan büyük olmalı.")

    # ── Sell Position Form ──────────────────────────────────────────────────
    with st.expander("📉  Satış Yap (Pozisyon Azalt / Kapat)", expanded=False):
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.8rem;">'
            'Kısmi satış: Adet gir → pozisyon azalır. '
            'Tam satış: Tüm adedi gir → pozisyon kapanır.'
            '</div>',
            unsafe_allow_html=True,
        )
        sell_col1, sell_col2, sell_col3 = st.columns([1.2, 1, 1.2])
        with sell_col1:
            s_ticker = st.text_input("Ticker", placeholder="AAPL", key="s_ticker").upper().strip()
        with sell_col2:
            s_shares = st.number_input("Satılan Adet", min_value=0.0, step=1.0, key="s_shares")
        with sell_col3:
            s_price = st.number_input("Satış Fiyatı ($)", min_value=0.0, step=0.01, key="s_price")

        # Anlık K/Z önizlemesi
        if s_ticker and s_shares > 0 and s_price > 0:
            _port_now  = load_portfolio()
            _pos_match = next((p for p in _port_now if p["ticker"] == s_ticker), None)
            if _pos_match:
                _avg_cost = _pos_match.get("avg_cost", 0)
                if _avg_cost > 0:
                    _pnl_per = s_price - _avg_cost
                    _pnl_tot = _pnl_per * s_shares
                    _pnl_pct = (_pnl_per / _avg_cost) * 100
                    _sign    = "+" if _pnl_tot >= 0 else ""
                    _clr     = "#00c48c" if _pnl_tot >= 0 else "#e74c3c"
                    _emoji   = "✅" if _pnl_tot >= 0 else "🔴"
                    st.markdown(
                        f'<div style="background:#0d1117;border:1px solid #1e2833;'
                        f'border-radius:6px;padding:0.5rem 0.8rem;font-size:0.78rem;margin-top:0.3rem;">'
                        f'<b style="color:#8a9ab0;">Önizleme:</b> '
                        f'<span style="color:{_clr};font-weight:600;">{_emoji} {_sign}${_pnl_tot:,.2f}</span>'
                        f' &nbsp;|&nbsp; '
                        f'<span style="color:{_clr};">{_sign}{_pnl_pct:.2f}%</span>'
                        f' &nbsp;|&nbsp; '
                        f'Maliyet: ${_avg_cost:.2f} → Satış: ${s_price:.2f}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        if st.button("📉  Satışı Onayla", key="btn_sell"):
            if s_ticker and s_shares > 0:
                _, msg = sell_position(s_ticker, s_shares, sell_price=s_price if s_price > 0 else 0.0)
                st.success(f"✅ {msg}")
                st.rerun()
            else:
                st.error("Ticker ve satılan adet girilmeli.")

    # ── Load & enrich portfolio ─────────────────────────────────────────────
    positions = load_portfolio()

    if not positions:
        st.markdown(
            '<div class="empty-state">'
            '💼 Henüz portföy pozisyonu yok.<br><br>'
            'Yukarıdaki formu kullanarak ilk pozisyonunu ekle.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        # Fetch live prices + yfinance sector for all portfolio tickers
        import yfinance as _yf_port
        failed_tickers = []
        with st.spinner("📊 Canlı fiyatlar ve sektör verileri çekiliyor..."):
            price_map:  dict[str, float] = {}
            change_map: dict[str, float] = {}
            sector_map: dict[str, str]   = {}
            w52h_map:   dict[str, float] = {}
            w52l_map:   dict[str, float] = {}
            for pos in positions:
                ticker_sym = pos["ticker"]
                try:
                    info  = _yf_port.Ticker(ticker_sym).info
                    price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
                    prev  = float(info.get("previousClose") or price or 1)
                    chg   = ((price - prev) / prev * 100) if prev else 0
                    sec   = info.get("sector") or info.get("industry") or pos.get("sector", "Diğer")
                    w52h  = float(info.get("fiftyTwoWeekHigh") or 0)
                    w52l  = float(info.get("fiftyTwoWeekLow") or 0)
                    if price > 0:
                        price_map[ticker_sym]  = price
                        change_map[ticker_sym] = round(chg, 2)
                    else:
                        failed_tickers.append(ticker_sym)
                    sector_map[ticker_sym] = sec
                    w52h_map[ticker_sym]   = w52h
                    w52l_map[ticker_sym]   = w52l
                except Exception:
                    # fast_info fallback
                    try:
                        fi    = _yf_port.Ticker(ticker_sym).fast_info
                        price = float(getattr(fi, "last_price", 0) or 0)
                        w52h  = float(getattr(fi, "year_high", 0) or 0)
                        w52l  = float(getattr(fi, "year_low", 0) or 0)
                        if price > 0:
                            price_map[ticker_sym] = price
                        else:
                            failed_tickers.append(ticker_sym)
                        w52h_map[ticker_sym] = w52h
                        w52l_map[ticker_sym] = w52l
                    except Exception:
                        failed_tickers.append(ticker_sym)
                    sector_map[ticker_sym] = pos.get("sector", "Diğer")

        if failed_tickers:
            st.warning(
                f"⚠️ Şu hisseler için fiyat çekilemedi: **{', '.join(failed_tickers)}**  \n"
                "Olası nedenler: ETF/yabancı hisse veya yanlış ticker sembolü. "
                "Bu hisseler $0 olarak gösterilir.",
                icon="📡",
            )

        enriched_pos = enrich_portfolio_with_prices(positions, price_map)
        # yfinance'ten gelen sektör + 52H verilerini yaz
        for p in enriched_pos:
            tk = p["ticker"]
            p["sector"] = sector_map.get(tk, p.get("sector", "Diğer"))
            p["w52h"]   = w52h_map.get(tk, 0)
            p["w52l"]   = w52l_map.get(tk, 0)
            # 52H pozisyon yüzdesi ve alarm durumu
            price = p.get("current_price", 0)
            w52h  = p["w52h"]
            w52l  = p["w52l"]
            if w52h > 0 and w52l > 0 and (w52h - w52l) > 0:
                p["w52h_pos_pct"] = round((price - w52l) / (w52h - w52l) * 100, 1)
            else:
                p["w52h_pos_pct"] = 0
            if w52h > 0 and price > 0:
                if price >= w52h:
                    p["breakout_status"] = "🔥"
                elif price >= w52h * 0.995:
                    p["breakout_status"] = "⚡"
                else:
                    p["breakout_status"] = ""
            else:
                p["breakout_status"] = ""
        summary      = portfolio_summary(enriched_pos)
        st.session_state["enriched_portfolio"] = enriched_pos  # korelasyon analizi için

        # ── Summary KPI Bar ─────────────────────────────────────────────────
        _cash_now = get_cash()
        k1, k2, k3, k4, k5, k6 = st.columns(6)

        total_pnl_color = "#00c48c" if summary["total_pnl"] >= 0 else "#e74c3c"
        pnl_sign        = "+" if summary["total_pnl"] >= 0 else ""

        with k1:
            st.markdown(
                f'<div class="kpi-card green">'
                f'<div class="kpi-score-label">TOPLAM DEĞER</div>'
                f'<div style="font-size:1.3rem;font-weight:700;color:#e8edf3;">'
                f'${summary["total_value"]:,.0f}</div>'
                f'</div>', unsafe_allow_html=True,
            )
        with k2:
            st.markdown(
                f'<div class="kpi-card {"green" if summary["total_pnl"]>=0 else "red"}">'
                f'<div class="kpi-score-label">TOPLAM K/Z</div>'
                f'<div style="font-size:1.3rem;font-weight:700;color:{total_pnl_color};">'
                f'{pnl_sign}${summary["total_pnl"]:,.0f}</div>'
                f'</div>', unsafe_allow_html=True,
            )
        with k3:
            st.markdown(
                f'<div class="kpi-card {"green" if summary["total_pnl_pct"]>=0 else "red"}">'
                f'<div class="kpi-score-label">K/Z %</div>'
                f'<div style="font-size:1.3rem;font-weight:700;color:{total_pnl_color};">'
                f'{pnl_sign}{summary["total_pnl_pct"]:.2f}%</div>'
                f'</div>', unsafe_allow_html=True,
            )
        with k4:
            best = summary.get("best")
            if best:
                b_color = "#00c48c" if best["pnl_pct"] >= 0 else "#e74c3c"
                st.markdown(
                    f'<div class="kpi-card green">'
                    f'<div class="kpi-score-label">EN İYİ POZİSYON</div>'
                    f'<div style="font-size:1.1rem;font-weight:700;color:#e8edf3;">{best["ticker"]}</div>'
                    f'<div style="color:{b_color};font-size:0.8rem;">+{best["pnl_pct"]:.1f}%</div>'
                    f'</div>', unsafe_allow_html=True,
                )
        with k5:
            worst = summary.get("worst")
            if worst:
                w_color = "#e74c3c" if worst["pnl_pct"] < 0 else "#00c48c"
                st.markdown(
                    f'<div class="kpi-card red">'
                    f'<div class="kpi-score-label">EN KÖTÜ POZİSYON</div>'
                    f'<div style="font-size:1.1rem;font-weight:700;color:#e8edf3;">{worst["ticker"]}</div>'
                    f'<div style="color:{w_color};font-size:0.8rem;">{worst["pnl_pct"]:.1f}%</div>'
                    f'</div>', unsafe_allow_html=True,
                )
        with k6:
            _total_with_cash = summary["total_value"] + _cash_now
            st.markdown(
                f'<div class="kpi-card" style="border-color:#1e6a9e;">'
                f'<div class="kpi-score-label">NAKİT</div>'
                f'<div style="font-size:1.3rem;font-weight:700;color:#4fc3f7;">${_cash_now:,.0f}</div>'
                f'<div style="font-size:0.7rem;color:#5a6a7a;">Toplam: ${_total_with_cash:,.0f}</div>'
                f'</div>', unsafe_allow_html=True,
            )

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        # ── Portfolio Table ─────────────────────────────────────────────────
        col_tbl, col_pie = st.columns([2.2, 1])

        with col_tbl:
            st.markdown(
                '<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin-bottom:0.5rem;">📋 POZİSYONLAR</div>',
                unsafe_allow_html=True,
            )

            rows = []
            for p in enriched_pos:
                sign = "+" if p["pnl_dollar"] >= 0 else ""
                w52h_pos = p.get("w52h_pos_pct", 0)
                alarm    = p.get("breakout_status", "")
                rows.append({
                    "Ticker":        p["ticker"],
                    "Şirket":        p.get("notes", "")[:20] or p["ticker"],
                    "Sektör":        p.get("sector", "Diğer"),
                    "Adet":          f'{p["shares"]:.2f}',
                    "Maliyet ($)":   f'${p["avg_cost"]:.2f}',
                    "Fiyat ($)":     f'${p["current_price"]:.2f}',
                    "Değer ($)":     f'${p["current_value"]:,.0f}',
                    "K/Z ($)":       f'{sign}${abs(p["pnl_dollar"]):,.0f}',
                    "K/Z (%)":       f'{sign}{p["pnl_pct"]:.2f}%',
                    "Ağırlık (%)":   f'{p["weight_pct"]:.1f}%',
                    "52H Pos.":      f'%{w52h_pos:.0f}',
                    "🔔":            alarm,
                })

            df_port = pd.DataFrame(rows)

            def color_pnl(val):
                if isinstance(val, str) and val.startswith("+"):
                    return "color: #00c48c; font-weight: 600"
                if isinstance(val, str) and val.startswith("-"):
                    return "color: #e74c3c; font-weight: 600"
                return ""

            def color_52h(val):
                if isinstance(val, str):
                    pct = val.replace("%", "").strip()
                    try:
                        v = float(pct)
                        if v >= 99:   return "color: #e74c3c; font-weight: 600"
                        if v >= 90:   return "color: #ffb300; font-weight: 600"
                        if v >= 75:   return "color: #00c48c"
                    except Exception:
                        pass
                return ""

            st.dataframe(
                df_port.style
                    .map(color_pnl, subset=["K/Z ($)", "K/Z (%)"])
                    .map(color_52h, subset=["52H Pos."]),
                use_container_width=True,
                hide_index=True,
            )

            # Delete position
            st.markdown('<div style="margin-top:0.8rem;"></div>', unsafe_allow_html=True)
            del_col1, del_col2 = st.columns([1.5, 3])
            with del_col1:
                del_ticker = st.text_input("Pozisyon Sil (Ticker)", key="del_ticker", placeholder="AAPL")
            with del_col2:
                st.markdown('<div style="margin-top:1.65rem;"></div>', unsafe_allow_html=True)
                if st.button("🗑  Sil", key="btn_del"):
                    if del_ticker:
                        remove_position(del_ticker.upper())
                        st.success(f"✅ {del_ticker.upper()} silindi.")
                        st.rerun()

        with col_pie:
            st.markdown(
                '<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin-bottom:0.5rem;">🥧 AĞIRLIK DAĞILIMI</div>',
                unsafe_allow_html=True,
            )
            labels  = [p["ticker"] for p in enriched_pos]
            values  = [p["current_value"] for p in enriched_pos]
            colors  = ["#00c48c", "#0099ff", "#f5a623", "#e74c3c",
                       "#aa55ff", "#ff6688", "#55ddff", "#ffdd55",
                       "#88ff88", "#ff8855", "#aabbcc"]

            fig_pie = go.Figure(go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                marker=dict(colors=colors[:len(labels)], line=dict(color="#080c10", width=2)),
                textfont=dict(family="JetBrains Mono", size=10, color="#e8edf3"),
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<br>%{percent}<extra></extra>",
            ))
            fig_pie.update_layout(
                height=280,
                margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                legend=dict(
                    font=dict(family="JetBrains Mono", size=9, color="#5a6a7a"),
                    bgcolor="rgba(0,0,0,0)",
                ),
            )
            st.plotly_chart(fig_pie, use_container_width=True, key="portfolio_pie")

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        # ── Claude Analysis for Portfolio ───────────────────────────────────
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.8rem;">'
            '▶ PORTFÖY HİSSELERİ İÇİN CLAUDE ANALİZİ</div>',
            unsafe_allow_html=True,
        )

        if st.button("🤖  Portföyü Analiz Et (Claude)", key="btn_port_analyze"):
            port_tickers = [p["ticker"] for p in positions]

            with st.status("🔄 Portföy analizi yapılıyor...", expanded=True) as port_status:
                st.write(f"📊 {len(port_tickers)} hisse için FMP verisi çekiliyor...")
                port_enriched = batch_enrich(port_tickers)

                for stock in port_enriched:
                    stock["kategori"] = categorise_stock(
                        stock.get("_profile", {}),
                        stock.get("_financials", {}),
                    )

                st.write("📰 Haberler çekiliyor ve filtreleniyor...")
                port_news = fetch_news_batch(port_enriched, days_back=7)

                st.write("🤖 Claude analiz yapıyor...")
                p_bar  = st.progress(0)
                p_text = st.empty()

                def port_progress(ticker, idx, total):
                    p_bar.progress(idx / total)
                    p_text.markdown(
                        f'<div class="progress-label">Analiz: '
                        f'<span style="color:#00c48c;">{ticker}</span> ({idx}/{total})</div>',
                        unsafe_allow_html=True,
                    )

                port_results = analyse_batch(port_enriched, port_news, progress_callback=port_progress)
                for res in port_results:
                    meta = res.get("_stock_meta", {})
                    if meta:
                        res["kategori"] = determine_category(meta)
                p_bar.progress(1.0)
                p_text.empty()

                st.session_state["portfolio_analysis"] = port_results
                port_status.update(label="✅ Portföy analizi tamamlandı!", state="complete", expanded=False)

        # Show portfolio analysis results if available
        port_results = st.session_state.get("portfolio_analysis", [])
        if port_results:
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.12em;margin:1rem 0 0.8rem;">▶ ANALİZ SONUÇLARI</div>',
                unsafe_allow_html=True,
            )
            for result in port_results:
                score   = result.get("nihai_guven_skoru", 0)
                ticker  = result.get("hisse_sembolu", "?")
                meta    = result.get("_stock_meta", {})
                tavsiye = result.get("tavsiye", "Tut")
                ozet    = result.get("analiz_ozeti", "")
                riskler = result.get("kritik_riskler", {})

                with st.expander(
                    f"{ticker}  ·  Skor: {score}/100  ·  {result.get('kategori','')}  ·  {tavsiye}",
                    expanded=(score >= 70),
                ):
                    c1, c2 = st.columns([1, 2])
                    with c1:
                        st.plotly_chart(gauge_chart(score, size=190), use_container_width=True, key=f"port_gauge_{ticker}")
                        st.markdown(recommendation_badge(tavsiye), unsafe_allow_html=True)
                    with c2:
                        st.markdown(
                            f'<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                            f'letter-spacing:0.1em;margin-bottom:0.4rem;">📋 ANALİZ ÖZETİ</div>'
                            f'<div style="background:#13181f;border:1px solid #1e2833;border-radius:6px;'
                            f'padding:0.9rem;font-size:0.75rem;line-height:1.7;color:#c0c8d0;">{ozet}</div>'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
                            f'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">⚠️ RİSK HARİTASI</div>'
                            f'<div style="background:#13181f;border:1px solid #1e2833;border-radius:6px;padding:0.9rem;">'
                            f'<span class="risk-label">🌍 GLOBAL MAKRO</span><br>'
                            f'<span style="font-size:0.72rem;color:#c0c8d0;">{riskler.get("global_makro","N/A")}</span><br><br>'
                            f'<span class="risk-label">🏢 ŞİRKET / FİNANSAL</span><br>'
                            f'<span style="font-size:0.72rem;color:#c0c8d0;">{riskler.get("finansal_sirket_ozel","N/A")}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    # ── TradingView Grafik ───────────────────────────────
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                        'letter-spacing:0.1em;margin:1rem 0 0.3rem;">📈 FİYAT GRAFİĞİ</div>',
                        unsafe_allow_html=True,
                    )
                    tradingview_chart(ticker, height=380)

        # CSV Export
        if enriched_pos:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            csv_port = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇  Portföyü CSV Olarak İndir",
                data=csv_port,
                file_name="portfolio.csv",
                mime="text/csv",
                key="dl_portfolio",
            )

# ─────────────────────────────────────────────────────────────────────────────
# PORTFÖY — KORELASYON & SENARYO & HAFIZA
# ─────────────────────────────────────────────────────────────────────────────

with tab_portfolio:
    # ── Portföy Korelasyon + Senaryo Analizi ─────────────────────────────────
    st.markdown('<hr style="border-color:#1e2833;margin:1.5rem 0;">', unsafe_allow_html=True)

    adv_col1, adv_col2 = st.columns(2)

    # ── Korelasyon Analizi ──────────────────────────────────────────────────
    with adv_col1:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.5rem;">🔗 PORTFÖY KORİLASYON & SİSTEMATİK RİSK</div>',
            unsafe_allow_html=True,
        )
        st.caption("Tüm portföyünü bir bütün olarak değerlendir — sektörel yoğunlaşma, sistematik riskler")

        if st.button("🧠 Portföy Riski Analiz Et", key="btn_correlation", use_container_width=True):
            positions = load_portfolio()
            if not positions:
                st.warning("Portföyünüzde hisse yok.")
            else:
                with st.spinner("Claude tüm portföyü analiz ediyor..."):
                    api_key = os.getenv("ANTHROPIC_API_KEY", "")
                    if not api_key:
                        st.error("ANTHROPIC_API_KEY eksik.")
                    else:
                        import anthropic as _anthropic
                        _client = _anthropic.Anthropic(api_key=api_key)

                        # ── Güncel fiyatlı enriched portföyü kullan ──────────
                        enriched_pos = st.session_state.get("enriched_portfolio", [])

                        if not enriched_pos:
                            st.warning("Önce portföy tablosunu yükleyin (sayfa açılırken otomatik yüklenir). Sayfayı yenileyin.")
                            st.stop()

                        # Sektör zaten enriched_pos içinde yfinance'ten geliyor
                        sector_cache = {p["ticker"]: p.get("sector", "Bilinmiyor") for p in enriched_pos}

                        # ── Portföy satırları: GÜNCEL fiyat + gerçek P&L ─────
                        portfolio_lines = []
                        sector_counts   = {}
                        total_value     = sum(p["current_value"] for p in enriched_pos)

                        for p in enriched_pos:
                            tk      = p["ticker"]
                            shares  = p.get("shares", 0)
                            avg_cost = p.get("avg_cost", 0)
                            cur_price = p.get("current_price", 0)
                            cur_val  = p.get("current_value", 0)
                            cost_basis = p.get("cost_basis", 0)
                            pnl_pct  = p.get("pnl_pct", 0)
                            pnl_usd  = p.get("pnl_dollar", 0)
                            weight   = p.get("weight_pct", 0)
                            sec      = sector_cache.get(tk, "Bilinmiyor")

                            sector_counts[sec] = sector_counts.get(sec, 0) + cur_val

                            pnl_str = f"+${pnl_usd:,.0f} ({pnl_pct:+.1f}%)" if pnl_usd >= 0 else f"-${abs(pnl_usd):,.0f} ({pnl_pct:.1f}%)"
                            status  = "✅ KARDA" if pnl_pct >= 0 else "🔴 ZARARDA"

                            portfolio_lines.append(
                                f"  {tk:6s} | {shares:.0f} adet | "
                                f"Maliyet: ${avg_cost:.2f} → Güncel: ${cur_price:.2f} | "
                                f"Değer: ${cur_val:,.0f} (%{weight:.1f}) | "
                                f"P&L: {pnl_str} {status} | Sektör: {sec}"
                            )

                        # Sektör ağırlıkları
                        sector_weights = {
                            s: (v / total_value * 100) if total_value > 0 else 0
                            for s, v in sorted(sector_counts.items(), key=lambda x: -x[1])
                        }
                        sector_summary = " | ".join(
                            f"{s}: %{w:.0f}" for s, w in sector_weights.items()
                        )
                        portfolio_text = "\n".join(portfolio_lines)

                        prompt = f"""Sen deneyimli bir portföy yöneticisisin. Aşağıdaki portföyü kurumsal düzeyde analiz et ve SOMUT aksiyon önerileri sun.

ÖNEMLI: Analizde hisselerin GÜNCEL PİYASA DEĞERİNİ ve P&L durumunu dikkate al.
Zararda olan hisseler için "zararda satmak" vs "ortalama düşürmek" kararını değerlendir.
Karda olan hisseler için "kârı realize etmek" vs "tutmak" kararını değerlendir.

═══════════════════════════════════════
PORTFÖY ({len(enriched_pos)} pozisyon | Toplam Güncel Değer: ${total_value:,.0f})
═══════════════════════════════════════
{portfolio_text}

SEKTÖR AĞIRLIKLARI (güncel değer bazlı): {sector_summary}
═══════════════════════════════════════

Raporun şu yapıda olsun:

## 🔴 RİSK DEĞERLENDİRMESİ

Her risk kategorisini 1-10 arası puanla (10 = kritik risk):

| Risk Kategorisi | Puan | Açıklama |
|---|---|---|
| Sektörel Yoğunlaşma | X/10 | ... |
| Korelasyon Riski | X/10 | ... |
| Sistematik/Makro Risk | X/10 | ... |
| Likidite Riski | X/10 | ... |
| Döviz/Jeopolitik Risk | X/10 | ... |

**Genel Risk Skoru: X/10** — [Düşük / Orta / Yüksek / Kritik]

---

## 📊 SEKTÖREL ANALİZ

Hangi sektörde aşırı yoğunlaşma var ve neden tehlikeli? Hangi hisseler aynı anda düşer?

---

## ⚡ ACİL AKSİYON ÖNERİLERİ (Öncelik Sırasına Göre)

Zararda olan hisseler için özellikle net karar ver: sat mı, ortalama düşür mü, tut mu?
Karda olan hisseler için: kârı realize et mi, devam et mi?

Her öneri için şu formatta yaz:

**[1. Öncelik]** 🔴 [Aksiyon]: [TICKER] → [SAT / AZALT / ARTIR / TUT / ORTALAMA DÜŞÜR]
- **Durum**: [Karda/Zararda, %X, $Y P&L]
- **Neden**: [tek cümle, spesifik gerekçe]
- **Hedef**: [%X azalt / tamamen sat / X adede çıkar]
- **Yerine**: [varsa alternatif hisse önerisi ve neden o]

**[2. Öncelik]** 🟡 ...
**[3. Öncelik]** 🟢 ...

(En az 3, en fazla 6 öneri)

---

## 🎯 PORTFÖY HEDEFİ

Bu değişiklikler sonrasında portföy nasıl görünmeli? İdeal sektör dağılımı nedir?

---

Türkçe yaz. Her öneri somut, ölçülebilir ve uygulanabilir olsun.
Genel laflar etme — "azaltabilirsin" değil "X'i sat, yerine Y al" de."""

                        try:
                            resp = _client.messages.create(
                                model="claude-opus-4-5",
                                max_tokens=2500,
                                messages=[{"role": "user", "content": prompt}]
                            )
                            analysis_text = resp.content[0].text if resp.content else ""
                            st.session_state["correlation_analysis"] = analysis_text
                        except Exception as exc:
                            st.error(f"Claude bağlantı hatası: {exc}")

        if st.session_state.get("correlation_analysis"):
            with st.container():
                st.markdown(
                    '<div style="background:#0d1117;border:1px solid #1e2833;border-radius:8px;padding:1rem;margin-top:0.5rem;">',
                    unsafe_allow_html=True,
                )
                st.markdown(st.session_state["correlation_analysis"])
                st.markdown('</div>', unsafe_allow_html=True)

    # ── Senaryo Analizi ────────────────────────────────────────────────────
    with adv_col2:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.5rem;">🎯 MAKRO SENARYO ANALİZİ</div>',
            unsafe_allow_html=True,
        )
        st.caption("Bir makro senaryo gir — Claude her hissenin nasıl etkileneceğini söylesin")

        scenario_examples = [
            "Faiz oranları %1 artar",
            "ABD-Çin ticaret savaşı tırmanır",
            "Resesyon başlar, büyüme -%2",
            "Petrol fiyatı $120'ye çıkar",
            "Fed faiz indirir, para politikası gevşer",
            "Savunma bütçesi %15 kısılır",
        ]

        # Hızlı seçim butonları — tıklayınca input'a yazar
        if "scenario_preset" not in st.session_state:
            st.session_state["scenario_preset"] = ""

        st.markdown('<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.3rem;">Hızlı seçim:</div>', unsafe_allow_html=True)
        preset_cols = st.columns(3)
        for i, ex in enumerate(scenario_examples):
            col = preset_cols[i % 3]
            short = ex[:28] + "…" if len(ex) > 28 else ex
            if col.button(short, key=f"preset_{i}", use_container_width=True):
                st.session_state["scenario_preset"] = ex

        # Input — preset seçiliyse onu göster
        default_val = st.session_state.get("scenario_preset", "")
        scenario_input = st.text_input(
            "Veya kendin yaz:",
            value=default_val,
            placeholder="örn: Faiz oranları %1 artar",
            key="scenario_input",
        )

        if st.button("⚡ Senaryo Analizi Başlat", key="btn_scenario", use_container_width=True):
            positions = load_portfolio()
            if not scenario_input.strip():
                st.warning("Lütfen bir senaryo girin.")
            elif not positions:
                st.warning("Portföyünüzde hisse yok.")
            else:
                with st.spinner(f"Claude senaryoyu analiz ediyor: {scenario_input}"):
                    api_key = os.getenv("ANTHROPIC_API_KEY", "")
                    if not api_key:
                        st.error("ANTHROPIC_API_KEY eksik.")
                    else:
                        import anthropic as _anthropic
                        _client = _anthropic.Anthropic(api_key=api_key)

                        tickers_list = ", ".join(p["ticker"] for p in positions)
                        sectors_list = ", ".join(
                            f"{p['ticker']} ({p.get('sector','?')})" for p in positions
                        )

                        prompt = f"""MAKRO SENARYO: "{scenario_input}"

Bu senaryo gerçekleşirse aşağıdaki portföy hisseleri nasıl etkilenir?

POZİSYONLAR: {sectors_list}

Her hisse için şunu ver:
- **Etki**: Çok Olumsuz / Olumsuz / Nötr / Olumlu / Çok Olumlu
- **Neden**: 1-2 cümle açıklama (spesifik, o hisseye özgü)

Format:
**[TICKER]** — [Etki Seviyesi]
[Açıklama]

Sonunda portföyün genel etkisini özetle: hangi hisseler korunma sağlar, hangileri en çok zarar görür?
Türkçe yaz, kısa ve net ol."""

                        try:
                            resp = _client.messages.create(
                                model="claude-opus-4-5",
                                max_tokens=1500,
                                messages=[{"role": "user", "content": prompt}]
                            )
                            scenario_text = resp.content[0].text if resp.content else ""
                            st.session_state["scenario_analysis"] = scenario_text
                            st.session_state["scenario_title"] = scenario_input
                        except Exception as exc:
                            st.error(f"Claude bağlantı hatası: {exc}")

        if st.session_state.get("scenario_analysis"):
            st.markdown(
                f'<div style="font-size:0.65rem;color:#ffb300;margin:0.5rem 0 0.3rem;">'
                f'📌 Senaryo: {st.session_state.get("scenario_title","")}</div>',
                unsafe_allow_html=True,
            )
            with st.container():
                st.markdown(
                    '<div style="background:#0d1117;border:1px solid #1e2833;border-radius:8px;padding:1rem;">',
                    unsafe_allow_html=True,
                )
                st.markdown(st.session_state["scenario_analysis"])
                st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — HAFIZA
# ─────────────────────────────────────────────────────────────────────────────

with tab_memory:
    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► ANALİZ HAFIZASI — Geçmiş Kayıtlar & Skor Trendleri</div>',
        unsafe_allow_html=True,
    )

    import plotly.graph_objects as _go
    import pandas as _pd

    summary = get_history_summary()

    # ── KPI bar ───────────────────────────────────────────────────────────
    hm1, hm2, hm3 = st.columns(3)
    hm1.metric("Toplam Analiz", summary["total"])
    hm2.metric("Benzersiz Hisse", summary["unique_tickers"])
    hm3.metric("Son Analiz", summary["last_date"])

    if summary["total"] == 0:
        st.info("Henüz analiz geçmişi yok. İlk analizden sonra burada görünecek.")
    else:
        # ── En çok analiz edilen 10 hisse ────────────────────────────────
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin:1rem 0 0.5rem;">En çok takip edilen hisseler</div>',
            unsafe_allow_html=True,
        )
        top_tickers = get_top_tickers(limit=10)
        if top_tickers:
            card_cols = st.columns(min(len(top_tickers), 5))
            for i, t in enumerate(top_tickers[:5]):
                col        = card_cols[i]
                score      = t["latest_score"]
                trend      = t["trend"]
                count      = t["count"]
                ticker     = t["ticker"]
                tavsiye    = t["latest_tavsiye"]
                trend_str  = f"↑ +{trend}" if trend > 0 else (f"↓ {trend}" if trend < 0 else "→")
                trend_color = "#00c48c" if trend > 0 else ("#e74c3c" if trend < 0 else "#5a6a7a")
                score_color = "#00c48c" if score >= 70 else ("#ffb300" if score >= 50 else "#e74c3c")
                col.markdown(
                    f'<div style="background:#0d1117;border:1px solid #1e2833;border-radius:8px;'
                    f'padding:0.7rem;text-align:center;">'
                    f'<div style="font-size:0.8rem;font-weight:600;color:#e0e6ed;">{ticker}</div>'
                    f'<div style="font-size:1.3rem;font-weight:700;color:{score_color};margin:2px 0;">{score}</div>'
                    f'<div style="font-size:0.65rem;color:{trend_color};">{trend_str}</div>'
                    f'<div style="font-size:0.6rem;color:#5a6a7a;">{count}x analiz</div>'
                    f'<div style="font-size:0.6rem;color:#5a6a7a;">{tavsiye}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            if len(top_tickers) > 5:
                card_cols2 = st.columns(min(len(top_tickers) - 5, 5))
                for i, t in enumerate(top_tickers[5:10]):
                    col        = card_cols2[i]
                    score      = t["latest_score"]
                    trend      = t["trend"]
                    count      = t["count"]
                    ticker     = t["ticker"]
                    tavsiye    = t["latest_tavsiye"]
                    trend_str  = f"↑ +{trend}" if trend > 0 else (f"↓ {trend}" if trend < 0 else "→")
                    trend_color = "#00c48c" if trend > 0 else ("#e74c3c" if trend < 0 else "#5a6a7a")
                    score_color = "#00c48c" if score >= 70 else ("#ffb300" if score >= 50 else "#e74c3c")
                    col.markdown(
                        f'<div style="background:#0d1117;border:1px solid #1e2833;border-radius:8px;'
                        f'padding:0.7rem;text-align:center;">'
                        f'<div style="font-size:0.8rem;font-weight:600;color:#e0e6ed;">{ticker}</div>'
                        f'<div style="font-size:1.3rem;font-weight:700;color:{score_color};margin:2px 0;">{score}</div>'
                        f'<div style="font-size:0.65rem;color:{trend_color};">{trend_str}</div>'
                        f'<div style="font-size:0.6rem;color:#5a6a7a;">{count}x analiz</div>'
                        f'<div style="font-size:0.6rem;color:#5a6a7a;">{tavsiye}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        # ── Hisse bazlı geçmiş arama ──────────────────────────────────────
        st.markdown('<hr style="border-color:#1e2833;margin:1rem 0 0.8rem;">', unsafe_allow_html=True)
        lookup_col, _ = st.columns([1, 2])
        with lookup_col:
            hist_ticker = st.text_input(
                "Hisse geçmişi ara:", placeholder="örn: NVDA",
                key="hist_ticker_input"
            ).upper().strip()

        if hist_ticker:
            history = get_ticker_history(hist_ticker, limit=10)
            if not history:
                st.info(f"{hist_ticker} için geçmiş analiz bulunamadı.")
            else:
                st.markdown(
                    f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.5rem;">'
                    f'{hist_ticker} — {len(history)} analiz kaydı</div>',
                    unsafe_allow_html=True,
                )
                dates  = [h["date"] for h in reversed(history)]
                scores = [h["score"] for h in reversed(history)]
                fig_hist = _go.Figure()
                fig_hist.add_trace(_go.Scatter(
                    x=dates, y=scores, mode="lines+markers+text",
                    text=scores, textposition="top center",
                    line=dict(color="#00e676", width=2),
                    marker=dict(size=8, color="#00e676"),
                ))
                fig_hist.update_layout(
                    height=220, paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(showgrid=False, color="#5a6a7a"),
                    yaxis=dict(showgrid=True, gridcolor="#1e2833", range=[0,100], color="#5a6a7a"),
                    margin=dict(l=10, r=10, t=10, b=10),
                    showlegend=False,
                )
                st.plotly_chart(fig_hist, use_container_width=True, key="history_chart")

                df_hist = _pd.DataFrame([{
                    "Tarih":   h["date"],
                    "Skor":    h["score"],
                    "Tavsiye": h["tavsiye"],
                    "Fiyat":   f"${h['price']:.2f}" if h.get("price") else "—",
                    "Özet":    (h.get("ozet","") or "")[:80] + "...",
                } for h in history])
                st.dataframe(df_hist, use_container_width=True, hide_index=True)

        else:
            recent = get_all_history(limit=20)
            if recent:
                df_recent = _pd.DataFrame([{
                    "Tarih":    r["date"],
                    "Hisse":    r["ticker"],
                    "Skor":     r["score"],
                    "Tavsiye":  r["tavsiye"],
                    "Kategori": r.get("kategori",""),
                    "Fiyat":    f"${r['price']:.2f}" if r.get("price") else "—",
                } for r in recent])
                st.dataframe(df_recent, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — FIRSAT RADARI
# ─────────────────────────────────────────────────────────────────────────────

with tab_radar:
    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► FIRSAT RADARI — Proaktif Hisse Tespiti</div>',
        unsafe_allow_html=True,
    )

    # ── Ayarlar ──────────────────────────────────────────────────────────────
    with st.expander("⚙️ Radar Ayarları", expanded=True):
        r1, r2, r3 = st.columns(3)
        with r1:
            radar_hours = st.slider("🕐 Haber Penceresi (Saat)", 6, 48, 24)
        with r2:
            radar_min_score = st.slider("🎯 Min Radar Puanı", 40, 90, 60)
        with r3:
            radar_max_tickers = st.slider("🔢 Maks Ticker", 5, 30, 15)

        radar_btn = st.button("🔭  RADARI ÇALIŞTIR", use_container_width=True, type="primary")

    # ── Bilgi Kutusu ─────────────────────────────────────────────────────────
    st.markdown(
        '<div style="background:#0d1f2d;border:1px solid #1e3a4a;border-radius:8px;'
        'padding:1rem;margin-bottom:1rem;font-size:0.78rem;color:#7a9ab5;">'
        '<b style="color:#4fc3f7;">📊 3 Katmanlı Puanlama Sistemi</b><br><br>'
        '• <b>Temel Skor × Çarpan (×0.30)</b> — Şirketin fundamentals kalitesi. '
        'Güçlü temel → haber daha değerli.<br>'
        '• <b>Haber Etkisi (×0.40)</b> — Bu haberin o hisse için önemi.<br>'
        '• <b>Sürpriz Faktörü (×0.30)</b> — Piyasa bunu biliyor mu? Sürpriz → daha yüksek puan.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Radar Çalıştır ───────────────────────────────────────────────────────
    if radar_btn:
        radar_results = []
        radar_progress = st.progress(0)
        radar_status   = st.empty()

        def radar_progress_cb(ticker, idx, total):
            radar_progress.progress(idx / total)
            radar_status.markdown(
                f'<div style="font-size:0.75rem;color:#5a6a7a;">🔍 Analiz ediliyor: '
                f'<b style="color:#4fc3f7;">{ticker}</b> ({idx}/{total})</div>',
                unsafe_allow_html=True,
            )

        with st.spinner("📡 Haberler taranıyor ve fırsatlar tespit ediliyor..."):
            radar_results = run_radar(
                max_age_hours=radar_hours,
                min_radar_score=radar_min_score,
                max_tickers=radar_max_tickers,
                progress_callback=radar_progress_cb,
            )

        radar_progress.empty()
        radar_status.empty()

        if not radar_results:
            st.info("📭 Belirlenen kriterlere uyan fırsat bulunamadı. Eşiği düşürmeyi veya haber penceresini genişletmeyi deneyin.")
        else:
            st.success(f"✅ {len(radar_results)} fırsat tespit edildi!")
            st.markdown("---")

            # ── Sonuç Kartları ───────────────────────────────────────────────
            for res in radar_results:
                ticker        = res["ticker"]
                radar_score   = res["radar_score"]
                fund_score    = res["fundamental_score"]
                haber_etkisi  = res["haber_etkisi"]
                surpriz       = res["surpriz_faktoru"]
                neden         = res["neden"]
                tavsiye       = res["tavsiye"]
                price         = res["price"]
                haber_sayisi  = res["haber_sayisi"]
                articles      = res["articles"]

                # Renk
                if radar_score >= 80:
                    border_color = "#00e676"
                    badge_color  = "#00e676"
                elif radar_score >= 65:
                    border_color = "#ffb300"
                    badge_color  = "#ffb300"
                else:
                    border_color = "#4fc3f7"
                    badge_color  = "#4fc3f7"

                # Tavsiye rengi
                if tavsiye == "İncele":
                    tavsiye_color = "#00e676"
                elif tavsiye == "Takibe Al":
                    tavsiye_color = "#ffb300"
                else:
                    tavsiye_color = "#5a6a7a"

                with st.expander(
                    f"🎯 {ticker}  —  Radar: {radar_score}  |  "
                    f"{tavsiye}  |  {haber_sayisi} haber  |  "
                    f"{'${:,.2f}'.format(price) if price else 'N/A'}",
                    expanded=(radar_score >= 75),
                ):
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid {border_color};'
                            f'border-radius:8px;padding:0.8rem;text-align:center;">'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;">RADAR PUANI</div>'
                            f'<div style="font-size:1.8rem;font-weight:800;color:{badge_color};">'
                            f'{radar_score}</div></div>',
                            unsafe_allow_html=True,
                        )
                    with c2:
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1e3a4a;'
                            f'border-radius:8px;padding:0.8rem;text-align:center;">'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;">TEMEL SKOR</div>'
                            f'<div style="font-size:1.8rem;font-weight:800;color:#4fc3f7;">'
                            f'{fund_score}</div></div>',
                            unsafe_allow_html=True,
                        )
                    with c3:
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1e3a4a;'
                            f'border-radius:8px;padding:0.8rem;text-align:center;">'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;">HABER ETKİSİ</div>'
                            f'<div style="font-size:1.8rem;font-weight:800;color:#ff6b35;">'
                            f'{haber_etkisi}</div></div>',
                            unsafe_allow_html=True,
                        )
                    with c4:
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1e3a4a;'
                            f'border-radius:8px;padding:0.8rem;text-align:center;">'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;">SÜRPRİZ</div>'
                            f'<div style="font-size:1.8rem;font-weight:800;color:#ce93d8;">'
                            f'{surpriz}</div></div>',
                            unsafe_allow_html=True,
                        )

                    # Neden ve tavsiye
                    st.markdown(
                        f'<div style="margin-top:0.8rem;padding:0.8rem;background:#0d1f2d;'
                        f'border-radius:6px;border-left:3px solid {tavsiye_color};">'
                        f'<span style="color:#7a9ab5;font-size:0.75rem;">📌 </span>'
                        f'<span style="color:#c8d8e8;font-size:0.82rem;">{neden}</span>'
                        f'<span style="margin-left:1rem;background:{tavsiye_color}22;'
                        f'color:{tavsiye_color};border-radius:4px;padding:2px 8px;'
                        f'font-size:0.7rem;font-weight:700;">{tavsiye}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Haberler
                    if articles:
                        st.markdown(
                            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                            'margin-top:0.8rem;margin-bottom:0.5rem;">📰 Kaynak Haberler</div>',
                            unsafe_allow_html=True,
                        )
                        for art in articles:
                            art_title    = art.get("title", "")
                            art_summary  = art.get("summary", "")
                            art_url      = art.get("url", "#")
                            art_source   = art.get("source", "")
                            if isinstance(art_source, dict): art_source = art_source.get("name", "")
                            art_pub      = art.get("published", "")

                            # Yayın tarihini kısalt
                            if art_pub and "T" in art_pub:
                                art_pub = art_pub.split("T")[0]

                            # Özet varsa göster
                            summary_html = ""
                            if art_summary and len(art_summary) > 20:
                                summary_html = (
                                    f'<div style="font-size:0.73rem;color:#8a9ab0;'
                                    f'margin:0.3rem 0 0.3rem 1rem;line-height:1.5;'
                                    f'border-left:2px solid #1e3a4a;padding-left:0.6rem;">'
                                    f'{art_summary[:300]}'
                                    f'{"..." if len(art_summary) > 300 else ""}'
                                    f'</div>'
                                )

                            st.markdown(
                                f'<div style="background:#0a1929;border:1px solid #1a2f42;'
                                f'border-radius:6px;padding:0.6rem 0.8rem;margin-bottom:0.5rem;">'
                                f'<div style="display:flex;justify-content:space-between;'
                                f'align-items:flex-start;">'
                                f'<a href="{art_url}" target="_blank" '
                                f'style="color:#4fc3f7;text-decoration:none;font-size:0.8rem;'
                                f'font-weight:600;line-height:1.4;flex:1;">'
                                f'{art_title}</a>'
                                f'</div>'
                                f'{summary_html}'
                                f'<div style="margin-top:0.3rem;font-size:0.65rem;color:#3a5a6a;">'
                                f'📡 {art_source}'
                                f'{" · " + art_pub if art_pub else ""}'
                                f'</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

            # ── Özet Tablo ───────────────────────────────────────────────────
            st.markdown("---")
            st.markdown(
                '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
                'margin-bottom:0.5rem;">📊 ÖZET TABLO</div>',
                unsafe_allow_html=True,
            )
            import pandas as pd
            df_radar = pd.DataFrame([{
                "Ticker":         r["ticker"],
                "Radar":          r["radar_score"],
                "Temel":          r["fundamental_score"],
                "Haber":          r["haber_etkisi"],
                "Sürpriz":        r["surpriz_faktoru"],
                "Tavsiye":        r["tavsiye"],
                "Fiyat ($)":      f"${r['price']:,.2f}" if r["price"] else "N/A",
                "Haber Sayısı":   r["haber_sayisi"],
            } for r in radar_results])

            st.dataframe(
                df_radar,
                hide_index=True,
                use_container_width=True,
            )

            # CSV indir + Telegram gönder
            col_dl, col_tg = st.columns([2, 1])
            with col_dl:
                csv_radar = df_radar.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Radar Sonuçlarını İndir (CSV)",
                    data=csv_radar,
                    file_name=f"radar_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    key="dl_radar",
                )
            with col_tg:
                if st.button("📱 Telegram'a Gönder", use_container_width=True, key="tg_radar"):
                    try:
                        from telegram_notifier import send_message, format_radar_summary
                        msg = format_radar_summary(radar_results, title="🔭 Manuel Radar Özeti")
                        ok  = send_message(msg)
                        if ok:
                            st.success("✅ Telegram'a gönderildi!")
                        else:
                            st.error("❌ Gönderilemedi. TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID secret'larını kontrol et.")
                    except Exception as e:
                        st.error(f"Hata: {e}")

    else:
        st.markdown(
            '<div style="text-align:center;padding:3rem;color:#3a4a5a;">'
            '<div style="font-size:3rem;">🔭</div>'
            '<div style="font-size:0.9rem;margin-top:0.5rem;">Radari çalıştırmak için yukarıdaki butona tıkla.</div>'
            '<div style="font-size:0.75rem;margin-top:0.3rem;color:#2a3a4a;">'
            'Haberler taranacak, tüm sektörler dışındaki fırsatlar da tespit edilecek.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — HİSSE SORGULA
# ─────────────────────────────────────────────────────────────────────────────

with tab_lookup:
    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► HİSSE SORGULA — Tekil Hisse Değerlendirme</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="background:#0d1f2d;border:1px solid #1e3a4a;border-radius:8px;'
        'padding:1rem;margin-bottom:1.2rem;font-size:0.78rem;color:#7a9ab5;">'
        'Sektör tarayıcısında olmayan veya anlık değerlendirmek istediğin herhangi bir '
        'hisseyi buraya yaz. Claude veri çekip puanlayacak.'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Arama Formu ───────────────────────────────────────────────────────
    lk_col1, lk_col2, lk_col3 = st.columns([2, 1, 1])
    with lk_col1:
        lookup_ticker = st.text_input(
            "Hisse Sembolü",
            placeholder="örn: AAPL, NVDA, TSLA",
            key="lookup_ticker_input",
        ).upper().strip()
    with lk_col2:
        lookup_days = st.slider("Haber Günü", 1, 14, 7, key="lookup_days")
    with lk_col3:
        st.markdown("<br>", unsafe_allow_html=True)
        lookup_btn = st.button("🔍  ANALİZ ET", use_container_width=True, type="primary", key="lookup_btn")

    # ── Analiz ───────────────────────────────────────────────────────────
    if lookup_btn:
        if not lookup_ticker:
            st.warning("Lütfen bir hisse sembolü girin.")
        else:
            with st.spinner(f"📊 {lookup_ticker} analiz ediliyor..."):
                from data_fetcher    import enrich_ticker
                from news_fetcher    import fetch_news_for_ticker, format_news_for_prompt
                from claude_analyzer import analyse_stock

                # 1. Veri çek
                lk_status = st.empty()
                lk_status.markdown(f'<div style="font-size:0.75rem;color:#5a6a7a;">📡 {lookup_ticker} verisi çekiliyor...</div>', unsafe_allow_html=True)
                stock_data = enrich_ticker(lookup_ticker)

                # 2. Kategori belirle
                stock_data["kategori"] = determine_category(stock_data)
                mkt_cap = stock_data.get("mktCap", 0) or 0

                # 3. Haberleri çek
                lk_status.markdown(f'<div style="font-size:0.75rem;color:#5a6a7a;">📰 Haberler çekiliyor...</div>', unsafe_allow_html=True)
                articles  = fetch_news_for_ticker(lookup_ticker, days_back=lookup_days)
                news_text = format_news_for_prompt(articles)

                # 4. Claude analizi
                lk_status.markdown(f'<div style="font-size:0.75rem;color:#5a6a7a;">🤖 Claude analiz yapıyor...</div>', unsafe_allow_html=True)
                result = analyse_stock(stock_data, news_text)
                lk_status.empty()

            if not result:
                st.error(f"❌ {lookup_ticker} analiz edilemedi. Sembolü kontrol edin.")
            else:
                score    = result.get("nihai_guven_skoru", 0)
                kategori = result.get("kategori", "")
                ozet     = result.get("analiz_ozeti", "")
                tavsiye  = result.get("tavsiye", "Tut")
                riskler  = result.get("kritik_riskler", {})
                price    = stock_data.get("price", 0)
                name     = stock_data.get("companyName", lookup_ticker)
                sector   = stock_data.get("sector", "N/A")
                mkt_b    = mkt_cap / 1e9

                # Renk
                if score >= 75:
                    score_color  = "#00e676"
                    border_color = "#00e676"
                elif score >= 55:
                    score_color  = "#ffb300"
                    border_color = "#ffb300"
                else:
                    score_color  = "#ef5350"
                    border_color = "#ef5350"

                tavsiye_color = {"Ağırlık Artır": "#00e676", "Tut": "#ffb300", "Azalt": "#ef5350"}.get(tavsiye, "#7a9ab5")

                # ── Başlık Kartı ─────────────────────────────────────────
                st.markdown(
                    f'<div style="background:#0a1929;border:2px solid {border_color};'
                    f'border-radius:10px;padding:1.2rem;margin-bottom:1rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<div>'
                    f'<div style="font-size:1.6rem;font-weight:800;color:#e8f0f8;">{lookup_ticker}</div>'
                    f'<div style="font-size:0.8rem;color:#7a9ab5;">{name}</div>'
                    f'<div style="font-size:0.72rem;color:#4a6a7a;margin-top:0.2rem;">{sector}</div>'
                    f'</div>'
                    f'<div style="text-align:right;">'
                    f'<div style="font-size:2.5rem;font-weight:900;color:{score_color};">{score}</div>'
                    f'<div style="font-size:0.65rem;color:#5a6a7a;">PUAN</div>'
                    f'<div style="background:{tavsiye_color}22;color:{tavsiye_color};'
                    f'border-radius:4px;padding:2px 10px;font-size:0.75rem;font-weight:700;'
                    f'margin-top:0.3rem;">{tavsiye}</div>'
                    f'</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── TradingView Grafik ───────────────────────────────────
                st.markdown(
                    '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                    'letter-spacing:0.1em;margin:0.8rem 0 0.3rem;">📈 FİYAT GRAFİĞİ</div>',
                    unsafe_allow_html=True,
                )
                tradingview_chart(lookup_ticker, height=440)

                # ── Metrik Kartları ──────────────────────────────────────
                m1, m2, m3, m4 = st.columns(4)
                metrics = [
                    (m1, "FİYAT",        f"${price:,.2f}" if price else "N/A",  "#4fc3f7"),
                    (m2, "PİYASA DEĞERİ",f"${mkt_b:.1f}B" if mkt_b else "N/A", "#4fc3f7"),
                    (m3, "KATEGORİ",     kategori,                               "#ce93d8"),
                    (m4, "HABER SAYISI", str(len(articles)),                     "#ffb300"),
                ]
                for col, label, val, color in metrics:
                    with col:
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1e3a4a;'
                            f'border-radius:8px;padding:0.8rem;text-align:center;">'
                            f'<div style="font-size:0.6rem;color:#5a6a7a;">{label}</div>'
                            f'<div style="font-size:1.2rem;font-weight:700;color:{color};">{val}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                # ── Analiz Özeti ─────────────────────────────────────────
                st.markdown(
                    f'<div style="background:#0d1f2d;border-left:3px solid {score_color};'
                    f'border-radius:6px;padding:0.9rem;margin:0.8rem 0;">'
                    f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.3rem;">ANALİZ ÖZETİ</div>'
                    f'<div style="font-size:0.85rem;color:#c8d8e8;">{ozet}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Riskler ──────────────────────────────────────────────
                r1, r2 = st.columns(2)
                with r1:
                    st.markdown(
                        f'<div style="background:#0a1929;border:1px solid #2a1a1a;'
                        f'border-radius:8px;padding:0.8rem;">'
                        f'<div style="font-size:0.65rem;color:#ef5350;margin-bottom:0.3rem;">🌍 GLOBAL MAKRO RİSK</div>'
                        f'<div style="font-size:0.78rem;color:#c8d8e8;">{riskler.get("global_makro","N/A")}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with r2:
                    st.markdown(
                        f'<div style="background:#0a1929;border:1px solid #2a1a1a;'
                        f'border-radius:8px;padding:0.8rem;">'
                        f'<div style="font-size:0.65rem;color:#ffb300;margin-bottom:0.3rem;">🏢 ŞİRKETE ÖZEL RİSK</div>'
                        f'<div style="font-size:0.78rem;color:#c8d8e8;">{riskler.get("finansal_sirket_ozel","N/A")}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # ── Haberler ─────────────────────────────────────────────
                if articles:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                        'margin:0.8rem 0 0.4rem 0;">📰 Kullanılan Haberler</div>',
                        unsafe_allow_html=True,
                    )
                    for art in articles[:5]:
                        art_title   = art.get("title", "")
                        art_url     = art.get("url", "#")
                        art_source  = art.get("source", {})
                        if isinstance(art_source, dict):
                            art_source = art_source.get("name", "")
                        art_desc    = art.get("description", "") or art.get("summary", "")

                        summary_html = ""
                        if art_desc and len(art_desc) > 20:
                            summary_html = (
                                f'<div style="font-size:0.73rem;color:#8a9ab0;'
                                f'margin:0.3rem 0 0 1rem;line-height:1.5;'
                                f'border-left:2px solid #1e3a4a;padding-left:0.6rem;">'
                                f'{art_desc[:300]}{"..." if len(art_desc)>300 else ""}'
                                f'</div>'
                            )

                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1a2f42;'
                            f'border-radius:6px;padding:0.6rem 0.8rem;margin-bottom:0.4rem;">'
                            f'<a href="{art_url}" target="_blank" '
                            f'style="color:#4fc3f7;text-decoration:none;font-size:0.8rem;font-weight:600;">'
                            f'{art_title}</a>'
                            f'{summary_html}'
                            f'<div style="margin-top:0.3rem;font-size:0.65rem;color:#3a5a6a;">'
                            f'📡 {art_source}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
    else:
        st.markdown(
            '<div style="text-align:center;padding:3rem;color:#3a4a5a;">'
            '<div style="font-size:3rem;">🔍</div>'
            '<div style="font-size:0.9rem;margin-top:0.5rem;">Analiz etmek istediğin hisse sembolünü gir.</div>'
            '<div style="font-size:0.75rem;margin-top:0.3rem;color:#2a3a4a;">'
            'NYSE ve NASDAQ\'taki tüm hisseler desteklenir.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
# ─────────────────────────────────────────────────────────────────────────────

with tab_watchlist:
    from breakout_scanner import (
        load_watchlist, add_to_watchlist, remove_from_watchlist,
        check_breakout,
    )

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► TAKİP LİSTESİ — 52H Kırılma Takibi</div>',
        unsafe_allow_html=True,
    )

    # ── Watchlist yönetimi ────────────────────────────────────────────────
    wl_col1, wl_col2 = st.columns([2, 1])

    with wl_col1:
        watchlist = load_watchlist()
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.5rem;">'
            f'{len(watchlist)} hisse takip ediliyor — sabah radarında otomatik 52H kontrolü yapılır</div>',
            unsafe_allow_html=True,
        )
        add_c, btn_c = st.columns([3, 1])
        with add_c:
            wl_new = st.text_input("Takibe al:", placeholder="örn: AAPL",
                                   key="wl_add_input", label_visibility="collapsed").upper().strip()
        with btn_c:
            if st.button("➕ Ekle", key="wl_add_btn", use_container_width=True):
                if wl_new:
                    add_to_watchlist(wl_new)
                    st.success(f"{wl_new} eklendi.")
                    st.rerun()

        if watchlist:
            for i in range(0, len(watchlist), 6):
                chunk = watchlist[i:i+6]
                cols  = st.columns(len(chunk))
                for col, tk in zip(cols, chunk):
                    if col.button(f"✕ {tk}", key=f"wl_rm_{tk}", use_container_width=True):
                        remove_from_watchlist(tk)
                        st.rerun()
        else:
            st.info("Takip listesi boş. Yukarıdan hisse ekleyebilirsin.")

    with wl_col2:
        st.markdown(
            '<div style="font-size:0.72rem;color:#8a9ab0;line-height:1.8;">'
            '• Sabah radarında otomatik taranır<br>'
            '• %0.5 yakın → ⚡ alarm<br>'
            '• 52H kırılınca → 🔥 alarm<br>'
            '• Portföy hisseleri zaten takip edilir<br>'
            '• Alarm Telegram\'a gönderilir'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── Manuel anlık tarama ───────────────────────────────────────────────
    st.markdown('<hr style="border-color:#1e2833;margin:1rem 0;">', unsafe_allow_html=True)

    if st.button("🔍 Şimdi 52H Kontrol Et", key="wl_scan_btn"):
        if not watchlist:
            st.warning("Takip listesi boş.")
        else:
            results = []
            prog = st.progress(0)
            for i, tk in enumerate(watchlist):
                r = check_breakout(tk)
                if r:
                    r["source"] = "watchlist"
                    results.append(r)
                prog.progress((i + 1) / len(watchlist))
            prog.empty()
            st.session_state["wl_scan_results"] = results
            st.session_state["wl_all_checked"]  = watchlist[:]

    if "wl_all_checked" in st.session_state:
        all_checked      = st.session_state.get("wl_all_checked", [])
        results          = st.session_state.get("wl_scan_results", [])
        breakout_tickers = {r["ticker"] for r in results}

        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;margin:0.5rem 0;">'
            f'{len(all_checked)} kontrol edildi — {len(results)} alarm</div>',
            unsafe_allow_html=True,
        )

        if results:
            for r in results:
                emoji  = "🔥" if r["confirmed"] else "⚡"
                status = "YENİ ZİRVE" if r["confirmed"] else "ZİRVEYE YAKLAŞIYOR"
                sc     = "#00c48c" if r["confirmed"] else "#ffb300"
                chg_c  = "#00c48c" if r["change_pct"] >= 0 else "#e74c3c"
                vol_str = f'Hacim {r["vol_ratio"]:.1f}x &nbsp;|&nbsp; ' if r["vol_ratio"] >= 1.5 else ""
                st.markdown(
                    f'<div style="background:#0d1117;border:1px solid {sc};border-radius:8px;'
                    f'padding:0.9rem 1.1rem;margin-bottom:0.5rem;">'
                    f'<div style="display:flex;justify-content:space-between;">'
                    f'<span style="font-size:1rem;font-weight:700;color:#e0e6ed;">{emoji} {r["ticker"]}</span>'
                    f'<span style="font-size:0.7rem;color:{sc};font-weight:600;">{status}</span>'
                    f'</div>'
                    f'<div style="font-size:0.78rem;color:#8a9ab0;margin-top:6px;line-height:1.9;">'
                    f'Fiyat: <b style="color:#e0e6ed;">${r["price"]:.2f}</b>'
                    f' &nbsp;|&nbsp; Günlük: <span style="color:{chg_c};">{r["change_pct"]:+.1f}%</span>'
                    f' &nbsp;|&nbsp; 52H: <b style="color:#e0e6ed;">${r["w52h"]:.2f}</b><br>'
                    f'{vol_str}52H Pozisyon: <b style="color:{sc};">%{r["range_pct"]:.0f}</b>'
                    f'{"&nbsp;— Kalan: %" + str(abs(r["upside"])) if not r["confirmed"] else " ✅ Zirve kırıldı"}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.success("✅ 52H yakınında hisse yok.")

        # Özet tablo
        import yfinance as _yf_wl
        import pandas as _pd_wl
        rows = []
        for tk in all_checked:
            try:
                fi    = _yf_wl.Ticker(tk).fast_info
                price = float(getattr(fi, "last_price", 0) or 0)
                w52h  = float(getattr(fi, "year_high", 0) or 0)
                w52l  = float(getattr(fi, "year_low", 0) or 0)
                pos   = round((price - w52l) / (w52h - w52l) * 100, 1) if (w52h - w52l) > 0 else 0
                alarm = "🔥" if (tk in breakout_tickers and any(r["confirmed"] for r in results if r["ticker"] == tk))                         else "⚡" if tk in breakout_tickers else "—"
                rows.append({"Ticker": tk, "Fiyat": f"${price:.2f}", "52H": f"${w52h:.2f}", "52H Pozisyon %": pos, "Alarm": alarm})
            except Exception:
                rows.append({"Ticker": tk, "Fiyat": "—", "52H": "—", "52H Pozisyon %": 0, "Alarm": "?"})
        if rows:
            df_wl = _pd_wl.DataFrame(rows).sort_values("52H Pozisyon %", ascending=False)
            st.dataframe(df_wl, use_container_width=True, hide_index=True)
