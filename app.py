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

# Streamlit Cloud secrets → os.environ'a taşı
# (analysis_memory, portfolio_manager vs. os.getenv() kullandığı için)
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
    # GH_TOKEN → GH_PAT alias
    if "GH_TOKEN" in os.environ and "GH_PAT" not in os.environ:
        os.environ["GH_PAT"] = os.environ["GH_TOKEN"]
except Exception:
    pass

from utils import (
    SECTOR_TICKERS,
    categorise_stock,
    score_color,
    score_badge,
)
from data_fetcher import batch_enrich, get_quote
from news_fetcher import fetch_news_batch, format_news_for_prompt
from claude_analyzer import analyse_batch
from analysis_memory import (
    get_ticker_history, get_all_history, get_history_summary, get_top_tickers,
    save_macro_snapshot, get_macro_history, get_macro_snapshot_by_date,
    save_portfolio_analysis, get_portfolio_analysis_history,
    find_comparison_record, build_comparison_context,
)
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
tab_screener, tab_portfolio, tab_radar, tab_lookup, tab_memory, tab_watchlist, tab_macro, tab_library, tab_targets, tab_strategy = st.tabs(["📡  Sektör Tarayıcı", "💼  Portföyüm", "🔭  Fırsat Radarı", "🔍  Hisse Sorgula", "🧠  Hafıza", "👁  Takip", "🌍  Makro", "📚  Kütüphane", "🎯  Hedefler", "🧭  Strateji"])

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
if "macro_data" not in st.session_state:
    st.session_state["macro_data"] = {}
if "macro_regime" not in st.session_state:
    st.session_state["macro_regime"] = {}
if "macro_claude_analysis" not in st.session_state:
    st.session_state["macro_claude_analysis"] = ""
if "comparison_result" not in st.session_state:
    st.session_state["comparison_result"] = ""
if "comparison_title" not in st.session_state:
    st.session_state["comparison_title"] = ""
if "insider_results" not in st.session_state:
    st.session_state["insider_results"] = None
if "wl_full_result" not in st.session_state:
    st.session_state["wl_full_result"] = None
if "wl_phase1_result" not in st.session_state:
    st.session_state["wl_phase1_result"] = None
if "tgt_data" not in st.session_state:
    st.session_state["tgt_data"] = None
if "wr_cache" not in st.session_state:
    st.session_state["wr_cache"] = None


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

                        # Makro bağlamı ekle
                        _macro_ctx_str = ""
                        _macro_regime_label = ""
                        _m = st.session_state.get("macro_data", {})
                        _mr = st.session_state.get("macro_regime", {})
                        if _m and _mr:
                            from macro_dashboard import build_claude_macro_context
                            _macro_ctx_str = build_claude_macro_context(_m, _mr)
                            _macro_regime_label = _mr.get("label", "")

                        prompt = f"""Sen deneyimli bir portföy yöneticisisin. Aşağıdaki portföyü kurumsal düzeyde analiz et ve SOMUT aksiyon önerileri sun.

ÖNEMLI: Analizde hisselerin GÜNCEL PİYASA DEĞERİNİ ve P&L durumunu dikkate al.
Zararda olan hisseler için "zararda satmak" vs "ortalama düşürmek" kararını değerlendir.
Karda olan hisseler için "kârı realize etmek" vs "tutmak" kararını değerlendir.

{_macro_ctx_str}

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
                            # Hafızaya kaydet
                            try:
                                save_portfolio_analysis(
                                    analysis_type="risk",
                                    analysis_text=analysis_text,
                                    portfolio_snapshot=enriched_pos,
                                    macro_regime=_macro_regime_label,
                                )
                            except Exception:
                                pass
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

                        # Makro bağlamı
                        _sc_macro_str = ""
                        _sc_macro_regime = ""
                        _sm = st.session_state.get("macro_data", {})
                        _smr = st.session_state.get("macro_regime", {})
                        if _sm and _smr:
                            from macro_dashboard import build_claude_macro_context
                            _sc_macro_str = build_claude_macro_context(_sm, _smr)
                            _sc_macro_regime = _smr.get("label", "")

                        prompt = f"""MAKRO SENARYO: "{scenario_input}"

Bu senaryo gerçekleşirse aşağıdaki portföy hisseleri nasıl etkilenir?

{_sc_macro_str}

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
                            try:
                                save_portfolio_analysis(
                                    analysis_type="scenario",
                                    analysis_text=scenario_text,
                                    portfolio_snapshot=positions,
                                    macro_regime=_sc_macro_regime,
                                    scenario=scenario_input,
                                )
                            except Exception:
                                pass
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

        # ── Hisse Karşılaştırma Motoru ────────────────────────────────────────
        st.markdown('<hr style="border-color:#1e2833;margin:1.5rem 0 0.8rem;">', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.6rem;">📊 Geçmişle Karşılaştır</div>',
            unsafe_allow_html=True,
        )
        cmp_c1, cmp_c2, cmp_c3 = st.columns([1.5, 1, 1.5])
        with cmp_c1:
            cmp_ticker = st.text_input(
                "Hisse:", placeholder="örn: NVDA", key="cmp_ticker"
            ).upper().strip()
        with cmp_c2:
            cmp_weeks = st.selectbox(
                "Ne kadar önce?",
                [1, 2, 4, 8, 12],
                format_func=lambda x: f"{x} hafta önce",
                key="cmp_weeks",
            )
        with cmp_c3:
            st.markdown('<div style="margin-top:1.7rem;"></div>', unsafe_allow_html=True)
            cmp_btn = st.button("🔍 Karşılaştır", key="btn_compare", use_container_width=True)

        if cmp_btn and cmp_ticker:
            _cur_recs = get_ticker_history(cmp_ticker, limit=1)
            _past_rec = find_comparison_record(cmp_ticker, weeks_ago=cmp_weeks)

            if not _cur_recs:
                st.warning(f"{cmp_ticker} için henüz analiz kaydı yok.")
            elif not _past_rec:
                st.info(f"{cmp_weeks} hafta öncesine ait kayıt bulunamadı — daha az seç veya daha fazla analiz bekle.")
            else:
                _cur_rec   = _cur_recs[0]
                _cur_macro = get_macro_history(limit=1)
                _cur_macro = _cur_macro[0] if _cur_macro else None
                _past_macro = get_macro_snapshot_by_date(_past_rec["date"])

                _cmp_ctx = build_comparison_context(
                    cmp_ticker, _cur_rec, _past_rec,
                    past_macro=_past_macro,
                    current_macro=_cur_macro,
                )

                _api_key = os.getenv("ANTHROPIC_API_KEY", "")
                if not _api_key:
                    st.error("ANTHROPIC_API_KEY eksik.")
                else:
                    with st.spinner(f"{cmp_ticker} karşılaştırılıyor..."):
                        import anthropic as _ant_cmp
                        _cmp_client = _ant_cmp.Anthropic(api_key=_api_key)
                        _cmp_prompt = f"""{_cmp_ctx}

Bu iki analizi karşılaştır ve şunları yorumla:

1. **Skor Değişimi**: {_past_rec.get('score')} → {_cur_rec.get('score')} — Bu değişim neden oldu?
   - Şirket içi mi (earnings, ürün, yönetim)?
   - Makro kaynaklı mı (faiz, VIX, dolar)?
   - Sektörel baskı mı?

2. **Fiyat vs Skor Uyumu**: Fiyat değişimi skor değişimiyle tutarlı mı? Ayrışma varsa ne anlama geliyor?

3. **Makro Etki**: Geçen dönemle bugün arasındaki makro değişim bu hisseyi nasıl etkiledi?

4. **Öneri**: Geçmiş analize göre şimdi pozisyon değişmeli mi? Tut / Artır / Azalt / Sat?

Türkçe, net ve somut yaz. Spesifik rakamlara dayan."""

                        try:
                            _cmp_resp = _cmp_client.messages.create(
                                model="claude-opus-4-5",
                                max_tokens=1200,
                                messages=[{"role": "user", "content": _cmp_prompt}]
                            )
                            _cmp_text = _cmp_resp.content[0].text if _cmp_resp.content else ""
                            st.session_state["comparison_result"] = _cmp_text
                            st.session_state["comparison_title"]  = f"{cmp_ticker} — {cmp_weeks} hafta karşılaştırması"
                        except Exception as _e:
                            st.error(f"Claude hatası: {_e}")

        if st.session_state.get("comparison_result"):
            st.markdown(
                f'<div style="font-size:0.65rem;color:#ffb300;margin:0.5rem 0 0.3rem;">'
                f'📌 {st.session_state.get("comparison_title","")}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(st.session_state["comparison_result"])

        # ── Portföy Analiz Arşivi ─────────────────────────────────────────────
        st.markdown('<hr style="border-color:#1e2833;margin:1.5rem 0 0.8rem;">', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.6rem;">🗂 Portföy Analiz Arşivi</div>',
            unsafe_allow_html=True,
        )

        _arch_type = st.radio(
            "Analiz türü:",
            ["risk", "scenario", "correlation"],
            format_func=lambda x: {"risk": "🔴 Risk Analizi", "scenario": "🎯 Senaryo", "correlation": "🔗 Korelasyon"}.get(x, x),
            horizontal=True,
            key="arch_type",
        )

        _arch_records = get_portfolio_analysis_history(analysis_type=_arch_type, limit=15)

        if not _arch_records:
            st.info(f"Henüz '{_arch_type}' türünde analiz kaydı yok.")
        else:
            for _ar in _arch_records:
                _ar_label = (
                    f"{_ar['date']} — {_ar.get('scenario', '') or _ar.get('macro_regime', '')} "
                    f"| {_ar.get('position_count', 0)} hisse | ${_ar.get('total_value', 0):,.0f}"
                ).strip(" —")
                with st.expander(_ar_label, expanded=False):
                    if _ar.get("macro_regime"):
                        st.markdown(
                            f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.4rem;">'
                            f'Makro Rejim: {_ar["macro_regime"]}</div>',
                            unsafe_allow_html=True,
                        )
                    if _ar.get("scenario"):
                        st.markdown(
                            f'<div style="font-size:0.65rem;color:#ffb300;margin-bottom:0.4rem;">'
                            f'Senaryo: {_ar["scenario"]}</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(_ar.get("analysis", "")[:2000])
                    if _ar.get("tickers"):
                        st.caption("Pozisyonlar: " + ", ".join(_ar["tickers"]))

    # ── HAFTALIK RAPOR ARŞİVİ ────────────────────────────────────────────
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1.5rem 0;">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:0.8rem;">📋 HAFTALIK RAPOR ARŞİVİ</div>',
        unsafe_allow_html=True,
    )

    from analysis_memory import get_weekly_reports, get_weekly_report_by_id, save_weekly_report
    from weekly_report_html import generate_weekly_html

    # ── Manuel Rapor Oluştur ──────────────────────────────────────────────
    wr_btn_c1, wr_btn_c2, wr_btn_c3 = st.columns([1.5, 1.5, 1])
    with wr_btn_c1:
        wr_run_port = st.button("💼 Portföy Raporunu Arşivle", key="wr_run_portfolio", use_container_width=True)
    with wr_btn_c2:
        wr_run_surp = st.button("🔭 Sürpriz Raporunu Arşivle", key="wr_run_surprise", use_container_width=True)
    with wr_btn_c3:
        wr_type = st.selectbox(
            "Filtre:",
            ["Tümü", "Portföy", "Sürpriz", "Makro"],
            key="wr_type_filter",
            label_visibility="collapsed",
        )

    # Portföy raporu oluştur ve arşivle
    if wr_run_port:
        _port_tickers = [p["ticker"] for p in load_portfolio() if p.get("ticker")]
        if not _port_tickers:
            st.warning("Portföyde hisse yok.")
        else:
            with st.spinner(f"{len(_port_tickers)} hisse analiz ediliyor ve arşivleniyor..."):
                try:
                    from weekly_scanner import run_portfolio_scan
                    _port_results = run_portfolio_scan(_port_tickers)
                    if _port_results:
                        _top = sorted(_port_results, key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True)
                        _summary = f"{len(_port_results)} portföy hissesi analiz edildi. En yüksek: {_top[0].get('hisse_sembolu','')} ({_top[0].get('nihai_guven_skoru',0)})"
                        save_weekly_report("portfolio", _port_results, summary_text=_summary)
                        st.success(f"✅ {len(_port_results)} hisse arşivlendi!")
                        st.session_state["wr_cache"] = None  # Cache sıfırla
                        st.rerun()
                    else:
                        st.error("Analiz sonucu boş geldi.")
                except Exception as _e:
                    st.error(f"Hata: {_e}")

    # Sürpriz raporu oluştur ve arşivle
    if wr_run_surp:
        with st.spinner("Sürpriz taraması çalışıyor ve arşivleniyor..."):
            try:
                from weekly_scanner import run_surprise_scan
                _surp_results = run_surprise_scan(top_n_stage1=50, top_n_final=20)
                if _surp_results:
                    _top_s = sorted(_surp_results, key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True)
                    _summary_s = f"{len(_surp_results)} sürpriz hisse bulundu. En iyi: {_top_s[0].get('hisse_sembolu','')} ({_top_s[0].get('nihai_guven_skoru',0)})"
                    save_weekly_report("surprise", _surp_results, summary_text=_summary_s)
                    st.success(f"✅ {len(_surp_results)} hisse arşivlendi!")
                    st.session_state["wr_cache"] = None
                    st.rerun()
                else:
                    st.error("Tarama sonucu boş geldi.")
            except Exception as _e:
                st.error(f"Hata: {_e}")

    st.caption("Manuel arşiv: istediğin zaman çalıştır · PDF için raporu aç → Yazdır → PDF kaydet")

    _type_map = {"Tümü": None, "Portföy": "portfolio", "Sürpriz": "surprise", "Makro": "macro"}

    # Cache ile yükle
    if st.session_state.get("wr_cache") is None:
        st.session_state["wr_cache"] = get_weekly_reports(limit=20)
    _wr_list = [r for r in st.session_state.get("wr_cache", [])
                if _type_map[wr_type] is None or r.get("type") == _type_map[wr_type]]

    if not _wr_list:
        st.info("Henüz arşivlenmiş rapor yok. Yukarıdaki butonlarla oluşturabilirsin.")
    else:
        _type_emoji = {"portfolio": "💼", "surprise": "🔭", "macro": "🌍"}
        _type_label = {"portfolio": "Portföy", "surprise": "Sürpriz", "macro": "Makro"}

        for _wr in _wr_list:
            _wr_id     = _wr.get("id", "")
            _wr_date   = _wr.get("date", "")
            _wr_type   = _wr.get("type", "")
            _wr_week   = _wr.get("week", "")
            _wr_cnt    = _wr.get("result_count", 0)
            _wr_summ   = _wr.get("summary", "")
            _wr_emoji  = _type_emoji.get(_wr_type, "📊")
            _wr_tlabel = _type_label.get(_wr_type, "Rapor")

            with st.expander(
                f"{_wr_emoji}  {_wr_tlabel}  ·  {_wr_date}  ·  {_wr_week}  ·  {_wr_cnt} hisse",
                expanded=False,
            ):
                if _wr_summ:
                    st.markdown(
                        f'<div style="font-size:0.78rem;color:var(--color-text-secondary);'
                        f'line-height:1.6;margin-bottom:0.8rem;">{_wr_summ}</div>',
                        unsafe_allow_html=True,
                    )

                _wr_results = _wr.get("results", [])
                if _wr_results:
                    # Hisse kartları — mini grid
                    import math
                    _cols_per_row = 3
                    for _ri in range(0, len(_wr_results), _cols_per_row):
                        _chunk = _wr_results[_ri:_ri + _cols_per_row]
                        _rcols = st.columns(len(_chunk))
                        for _col, _r in zip(_rcols, _chunk):
                            _tk  = _r.get("hisse_sembolu") or _r.get("ticker", "—")
                            _sc  = int(_r.get("nihai_guven_skoru", 0))
                            _tav = _r.get("tavsiye", "Tut")
                            _oz  = _r.get("analiz_ozeti", "")[:80]
                            _kat = _r.get("kategori", "")
                            _sc_color = "#00c48c" if _sc >= 75 else ("#ffb300" if _sc >= 55 else "#e74c3c")
                            _tav_color = {"Ağırlık Artır": "#00c48c", "Tut": "#ffb300", "Azalt": "#e74c3c"}.get(_tav, "#8a9ab0")
                            _col.markdown(
                                f'<div style="background:var(--color-background-secondary);'
                                f'border:0.5px solid var(--color-border-tertiary);'
                                f'border-top:3px solid {_sc_color};'
                                f'border-radius:var(--border-radius-md);padding:0.7rem;">'
                                f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                                f'<div>'
                                f'<div style="font-size:14px;font-weight:600;">{_tk}</div>'
                                f'<div style="font-size:10px;color:var(--color-text-tertiary);">{_kat}</div>'
                                f'</div>'
                                f'<div style="text-align:right;">'
                                f'<div style="font-size:20px;font-weight:700;color:{_sc_color};">{_sc}</div>'
                                f'<div style="font-size:10px;padding:1px 6px;background:{_tav_color}22;'
                                f'color:{_tav_color};border-radius:10px;">{_tav}</div>'
                                f'</div>'
                                f'</div>'
                                f'<div style="font-size:11px;color:var(--color-text-secondary);'
                                f'margin-top:6px;line-height:1.5;">{_oz}{"..." if len(_r.get("analiz_ozeti","")) > 80 else ""}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                    # Skor grafiği (Plotly sparkline)
                    try:
                        import plotly.graph_objects as go
                        _sorted_r = sorted(_wr_results, key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True)[:15]
                        _tickers_g = [r.get("hisse_sembolu") or r.get("ticker","") for r in _sorted_r]
                        _scores_g  = [r.get("nihai_guven_skoru", 0) for r in _sorted_r]
                        _colors_g  = ["#00c48c" if s >= 75 else "#ffb300" if s >= 55 else "#e74c3c" for s in _scores_g]

                        fig = go.Figure(go.Bar(
                            x=_tickers_g,
                            y=_scores_g,
                            marker_color=_colors_g,
                            text=[str(s) for s in _scores_g],
                            textposition="outside",
                        ))
                        fig.update_layout(
                            height=280,
                            margin=dict(l=0, r=0, t=20, b=0),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            yaxis=dict(range=[0, 110], showgrid=False, visible=False),
                            xaxis=dict(tickfont=dict(size=10)),
                            showlegend=False,
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"wr_chart_{_wr_id}")
                    except Exception:
                        pass

                # ── PDF Download butonu ───────────────────────────────────
                st.markdown('<div style="margin-top:0.8rem;"></div>', unsafe_allow_html=True)
                _html_content = generate_weekly_html(_wr)
                st.download_button(
                    label="📄 HTML Raporu İndir (PDF için tarayıcıdan Yazdır)",
                    data=_html_content.encode("utf-8"),
                    file_name=f"rapor_{_wr_id}.html",
                    mime="text/html",
                    key=f"dl_{_wr_id}",
                    use_container_width=True,
                )

# ─────────────────────────────────────────────────────────────────────────────



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
        '<div style="background:var(--color-background-secondary);'
        'border:0.5px solid var(--color-border-tertiary);'
        'border-radius:var(--border-radius-lg);padding:1.2rem 1.4rem;margin-bottom:1rem;">'

        '<div style="font-size:0.7rem;font-weight:500;color:var(--color-text-tertiary);'
        'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.8rem;">'
        '🔭 Radar v3 — 6 Katmanlı Puanlama Sistemi</div>'

        '<div style="font-size:0.72rem;color:var(--color-text-secondary);'
        'font-family:monospace;background:var(--color-background-primary);'
        'border-radius:var(--border-radius-md);padding:0.5rem 0.8rem;margin-bottom:1rem;">'
        '(Temel×0.25 + Haber×0.30 + Sürpriz×0.20 + Momentum×0.15) × Makro_Çarpanı + Insider + Hafıza'
        '</div>'

        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #378ADD;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#378ADD;margin-bottom:3px;">Temel Skor ×0.25</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        'Gelir büyümesi, FCF, ROE, brüt marj, P/E, analist konsensüsü, beta, piyasa değeri, hedef upside</div></div>'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #E8593C;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#E8593C;margin-bottom:3px;">Haber Etkisi ×0.30</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        'Gürültü filtrelenmiş kaynaklardan Claude analizi. Seeking Alpha ve ZeroHedge engellendi</div></div>'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #7F77DD;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#7F77DD;margin-bottom:3px;">Sürpriz Faktörü ×0.20</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        'Claude tahmini ×0.6 + gerçek EPS/analist konsensüs sapması ×0.4</div></div>'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #BA7517;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#BA7517;margin-bottom:3px;">Momentum ×0.15</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        '52H pozisyon (%40–80 ideal), hacim patlaması, günlük değişim. Fiyatlanmış haberi filtreler</div></div>'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #1D9E75;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#1D9E75;margin-bottom:3px;">Makro Çarpanı ×0.60–1.35</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        'VIX×0.30 · 10Y Faiz×0.25 · Yield Curve×0.20 · DXY×0.15 · S&P Trend×0.10</div></div>'

        '<div style="background:var(--color-background-primary);border-radius:var(--border-radius-md);padding:0.7rem 0.8rem;border-left:3px solid #639922;">'
        '<div style="font-size:0.68rem;font-weight:500;color:#639922;margin-bottom:3px;">Insider & Hafıza +0–18</div>'
        '<div style="font-size:0.7rem;color:var(--color-text-secondary);line-height:1.55;">'
        'CEO/küme alımı max +10 · Skor trendi bonusu max ±8</div></div>'

        '</div></div>',
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

            # ── Makro Özet Bandı ─────────────────────────────────────────────
            if radar_results:
                _md = radar_results[0].get("macro_detail", {})
                _mc = radar_results[0].get("macro_multiplier", 1.0)
                _ms = _md.get("macro_score", 0)
                _mc_color = "#00c48c" if _mc >= 1.1 else ("#ffb300" if _mc >= 0.9 else "#e74c3c")
                st.markdown(
                    f'<div style="background:var(--color-background-secondary);'
                    f'border:0.5px solid var(--color-border-tertiary);'
                    f'border-left:3px solid {_mc_color};'
                    f'border-radius:0 8px 8px 0;padding:0.6rem 1rem;'
                    f'margin-bottom:1rem;font-size:0.75rem;">'
                    f'<b style="color:{_mc_color};">Makro Çarpanı: ×{_mc}</b>'
                    f' &nbsp;|&nbsp; Makro Skor: {_ms:.0f}/100'
                    + (f' &nbsp;|&nbsp; VIX {_md.get("vix",0):.0f}'
                       f' &nbsp;|&nbsp; 10Y %{_md.get("tnx",0):.1f}'
                       f' &nbsp;|&nbsp; Spread {_md.get("spread",0):+.2f}%'
                       f' &nbsp;|&nbsp; DXY {_md.get("dxy",0):.0f}'
                       if _md else "")
                    + '</div>',
                    unsafe_allow_html=True,
                )

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
                pos_rec       = res.get("position_rec", {})
                memory_desc   = res.get("memory_desc", "")
                eps_desc      = res.get("eps_desc", "")
                insider_bonus = res.get("insider_bonus", 0)
                memory_bonus  = res.get("memory_bonus", 0)
                macro_mult    = res.get("macro_multiplier", 1.0)

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

                # Pozisyon aksiyonu rengi
                _action = pos_rec.get("action", "İzle")
                _act_color = {
                    "Güçlü Al": "#00e676", "Al": "#4fc3f7",
                    "Küçük Pozisyon": "#ffb300", "İzle": "#5a6a7a", "Kaçın": "#e74c3c"
                }.get(_action, "#5a6a7a")

                with st.expander(
                    f"🎯 {ticker}  —  Radar: {radar_score}  |  "
                    f"{_action}  |  {haber_sayisi} haber  |  "
                    f"{'${:,.2f}'.format(price) if price else 'N/A'}",
                    expanded=(radar_score >= 75),
                ):
                    # ── Üst KPI satırı (6 metrik) ────────────────────────────
                    c1, c2, c3, c4, c5, c6 = st.columns(6)
                    for _col, _label, _val, _clr in [
                        (c1, "RADAR", radar_score, badge_color),
                        (c2, "TEMEL", fund_score, "#4fc3f7"),
                        (c3, "HABER", haber_etkisi, "#ff6b35"),
                        (c4, "SÜRPRİZ", surpriz, "#ce93d8"),
                        (c5, "MOMENTUM", res.get("momentum_score", 0), "#ffb300"),
                        (c6, "MAKRO ×", macro_mult, "#00e676" if macro_mult >= 1.0 else "#e74c3c"),
                    ]:
                        _col.markdown(
                            f'<div style="background:#0a1929;border:1px solid #1e3a4a;'
                            f'border-radius:8px;padding:0.6rem;text-align:center;">'
                            f'<div style="font-size:0.55rem;color:#5a6a7a;">{_label}</div>'
                            f'<div style="font-size:1.5rem;font-weight:800;color:{_clr};">{_val}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    # ── Pozisyon Önerisi ─────────────────────────────────────
                    st.markdown('<div style="margin-top:0.8rem;"></div>', unsafe_allow_html=True)
                    if pos_rec:
                        _pos_pct = pos_rec.get("position_pct", 0)
                        _stop    = pos_rec.get("stop_loss_pct", 0)
                        _upside  = pos_rec.get("upside_pct", 0)
                        _rr      = pos_rec.get("rr_ratio", 0)
                        _risk    = pos_rec.get("risk_level", "")
                        _rat     = pos_rec.get("rationale", "")
                        st.markdown(
                            f'<div style="background:#0a1929;border:1px solid {_act_color}33;'
                            f'border-left:3px solid {_act_color};border-radius:0 8px 8px 0;'
                            f'padding:0.7rem 1rem;margin-bottom:0.5rem;">'
                            f'<span style="color:{_act_color};font-weight:700;font-size:0.85rem;">{_action}</span>'
                            + (f' &nbsp;·&nbsp; <span style="font-size:0.75rem;">Portföy: %{_pos_pct:.1f}</span>' if _pos_pct > 0 else "")
                            + (f' &nbsp;·&nbsp; <span style="font-size:0.75rem;">Stop: -%{_stop}</span>' if _stop > 0 else "")
                            + (f' &nbsp;·&nbsp; <span style="font-size:0.75rem;">Upside: +%{_upside:.0f}</span>' if _upside > 0 else "")
                            + (f' &nbsp;·&nbsp; <span style="font-size:0.75rem;">R/R: {_rr:.1f}x</span>' if _rr > 0 else "")
                            + (f' &nbsp;·&nbsp; <span style="font-size:0.7rem;color:#5a6a7a;">Risk: {_risk}</span>' if _risk else "")
                            + f'<br><span style="font-size:0.72rem;color:#8a9ab0;">{_rat}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    # ── Neden & Tavsiye ──────────────────────────────────────
                    _extras = []
                    if insider_bonus > 0:
                        _extras.append(f"👔 Insider bonus: +{insider_bonus:.1f}")
                    if memory_bonus != 0:
                        _extras.append(f"🧠 Hafıza trend: {memory_bonus:+.1f}")
                    if eps_desc and eps_desc != "Veri yetersiz":
                        _extras.append(f"📊 {eps_desc[:60]}")
                    if memory_desc:
                        _extras.append(f"📈 {memory_desc[:60]}")

                    extras_html = (
                        '<br><span style="font-size:0.7rem;color:#4fc3f7;">'
                        + " &nbsp;|&nbsp; ".join(_extras) + '</span>'
                    ) if _extras else ""

                    st.markdown(
                        f'<div style="margin-top:0.3rem;padding:0.8rem;background:#0d1f2d;'
                        f'border-radius:6px;border-left:3px solid {tavsiye_color};">'
                        f'<span style="color:#7a9ab5;font-size:0.75rem;">📌 </span>'
                        f'<span style="color:#c8d8e8;font-size:0.82rem;">{neden}</span>'
                        f'<span style="margin-left:1rem;background:{tavsiye_color}22;'
                        f'color:{tavsiye_color};border-radius:4px;padding:2px 8px;'
                        f'font-size:0.7rem;font-weight:700;">{tavsiye}</span>'
                        f'{extras_html}'
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

with tab_watchlist:
    import yfinance as _yf_wlt
    import pandas as _pd_wlt
    from breakout_scanner import load_watchlist, add_to_watchlist, remove_from_watchlist

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► TAKİP LİSTESİ — Canlı Veri & Analiz</div>',
        unsafe_allow_html=True,
    )

    # ── Hisse ekle / çıkar ───────────────────────────────────────────────
    wl_top1, wl_top2, wl_top3 = st.columns([2.5, 1, 1])
    with wl_top1:
        wl_new = st.text_input("Takibe al:", placeholder="örn: AAPL",
                               key="wl_add_input", label_visibility="collapsed").upper().strip()
    with wl_top2:
        if st.button("➕ Ekle", key="wl_add_btn", use_container_width=True):
            if wl_new:
                add_to_watchlist(wl_new)
                st.success(f"{wl_new} eklendi.")
                st.rerun()
    with wl_top3:
        wl_refresh = st.button("🔄 Yenile", key="wl_refresh_btn", use_container_width=True)

    watchlist = load_watchlist()

    if not watchlist:
        st.info("Takip listesi boş. Yukarıdan hisse ekleyebilirsin.")
    else:
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.8rem;">'
            f'{len(watchlist)} hisse takip ediliyor</div>',
            unsafe_allow_html=True,
        )

        # ── Canlı veri çek ───────────────────────────────────────────────
        if "wl_table_data" not in st.session_state or wl_refresh:
            with st.spinner("Canlı veriler yükleniyor..."):
                wl_rows = []
                for _tk in watchlist:
                    try:
                        _info = _yf_wlt.Ticker(_tk).info
                        _fi   = _yf_wlt.Ticker(_tk).fast_info

                        _price   = float(_info.get("currentPrice") or _info.get("regularMarketPrice") or
                                         getattr(_fi, "last_price", 0) or 0)
                        _prev    = float(_info.get("previousClose") or _price or 1)
                        _chg     = round((_price - _prev) / _prev * 100, 2) if _prev else 0
                        _w52h    = float(_info.get("fiftyTwoWeekHigh") or getattr(_fi, "year_high", 0) or 0)
                        _w52l    = float(_info.get("fiftyTwoWeekLow")  or getattr(_fi, "year_low",  0) or 0)
                        _mktcap  = float(_info.get("marketCap") or getattr(_fi, "market_cap", 0) or 0)
                        _pe      = float(_info.get("trailingPE") or 0)
                        _fpe     = float(_info.get("forwardPE") or 0)
                        _tgt     = float(_info.get("targetMeanPrice") or 0)
                        _rec     = (_info.get("recommendationKey") or "").replace("-", " ").title()
                        _ancount = int(_info.get("numberOfAnalystOpinions") or 0)
                        _volume  = int(_info.get("regularMarketVolume") or getattr(_fi, "last_volume", 0) or 0)
                        _avgvol  = int(_info.get("averageVolume") or 0)
                        _sector  = _info.get("sector") or _info.get("industry") or "—"
                        _beta    = float(_info.get("beta") or 0)
                        _div     = float(_info.get("dividendYield") or 0)

                        # 52H pozisyon
                        _pos = round((_price - _w52l) / (_w52h - _w52l) * 100, 1) if (_w52h - _w52l) > 0 else 0

                        # Alarm
                        if _w52h > 0 and _price >= _w52h:
                            _alarm = "🔥"
                        elif _w52h > 0 and _price >= _w52h * 0.995:
                            _alarm = "⚡"
                        else:
                            _alarm = ""

                        # Analist upside
                        _upside = round((_tgt - _price) / _price * 100, 1) if (_tgt > 0 and _price > 0) else 0

                        # Hacim oranı
                        _volr = round(_volume / _avgvol, 1) if _avgvol > 0 else 0

                        wl_rows.append({
                            "ticker":   _tk,
                            "price":    _price,
                            "chg":      _chg,
                            "mktcap":   _mktcap,
                            "pe":       _pe,
                            "fpe":      _fpe,
                            "beta":     _beta,
                            "w52h_pos": _pos,
                            "alarm":    _alarm,
                            "tgt":      _tgt,
                            "upside":   _upside,
                            "rec":      _rec,
                            "ancount":  _ancount,
                            "div":      _div,
                            "volr":     _volr,
                            "sector":   _sector,
                        })
                    except Exception:
                        wl_rows.append({"ticker": _tk, "price": 0, "chg": 0, "mktcap": 0,
                                        "pe": 0, "fpe": 0, "beta": 0, "w52h_pos": 0,
                                        "alarm": "?", "tgt": 0, "upside": 0, "rec": "—",
                                        "ancount": 0, "div": 0, "volr": 0, "sector": "—"})
                st.session_state["wl_table_data"] = wl_rows

        wl_rows = st.session_state.get("wl_table_data", [])

        if wl_rows:
            # ── Tablo oluştur ──────────────────────────────────────────────
            def _mc(v):
                if v >= 1e12: return f"${v/1e12:.1f}T"
                if v >= 1e9:  return f"${v/1e9:.1f}B"
                if v >= 1e6:  return f"${v/1e6:.0f}M"
                return "—" if v == 0 else f"${v:.0f}"

            df_wl = _pd_wlt.DataFrame([{
                "🔔":          r["alarm"],
                "Ticker":      r["ticker"],
                "Sektör":      r["sector"],
                "Fiyat":       f"${r['price']:.2f}" if r["price"] else "—",
                "Günlük %":    f"{r['chg']:+.2f}%" if r["price"] else "—",
                "Mkt Cap":     _mc(r["mktcap"]),
                "Beta":        f"{r['beta']:.2f}" if r["beta"] else "—",
                "P/E":         f"{r['pe']:.1f}x" if r["pe"] else "—",
                "Fwd P/E":     f"{r['fpe']:.1f}x" if r["fpe"] else "—",
                "52H Pos.":    f"%{r['w52h_pos']:.0f}" if r["price"] else "—",
                "Analist Hdf": f"${r['tgt']:.0f} ({r['upside']:+.1f}%)" if r["tgt"] else "—",
                "Tavsiye":     r["rec"] or "—",
                "# Analist":   str(r["ancount"]) if r["ancount"] else "—",
                "Temettü":     f"{r['div']:.1%}" if r["div"] else "—",
                "Hacim":       f"{r['volr']:.1f}x" if r["volr"] else "—",
            } for r in wl_rows])

            # Renk fonksiyonları
            def _color_chg(val):
                if isinstance(val, str) and "+" in val: return "color:#00c48c;font-weight:600"
                if isinstance(val, str) and val.startswith("-"): return "color:#e74c3c;font-weight:600"
                return ""

            def _color_alarm(val):
                if val == "🔥": return "background-color:#1a0a00;font-size:1rem;"
                if val == "⚡": return "background-color:#1a1500;font-size:1rem;"
                return ""

            def _color_rec(val):
                if isinstance(val, str):
                    v = val.lower()
                    if "strong buy" in v or "buy" in v: return "color:#00c48c;font-weight:600"
                    if "sell" in v: return "color:#e74c3c;font-weight:600"
                    if "hold" in v: return "color:#ffb300"
                return ""

            def _color_upside(val):
                if isinstance(val, str) and "+" in val: return "color:#00c48c"
                if isinstance(val, str) and "-" in val: return "color:#e74c3c"
                return ""

            st.dataframe(
                df_wl.style
                    .map(_color_alarm, subset=["🔔"])
                    .map(_color_chg,   subset=["Günlük %"])
                    .map(_color_rec,   subset=["Tavsiye"])
                    .map(_color_upside, subset=["Analist Hdf"]),
                use_container_width=True,
                hide_index=True,
                height=min(len(wl_rows) * 38 + 40, 700),
            )

            # ── Hisse çıkarma ──────────────────────────────────────────────
            st.markdown('<hr style="border-color:#1e2833;margin:0.8rem 0;">', unsafe_allow_html=True)
            rm_col1, rm_col2 = st.columns([2, 1])
            with rm_col1:
                wl_rm = st.selectbox(
                    "Listeden çıkar:",
                    options=["— seç —"] + watchlist,
                    key="wl_rm_select",
                    label_visibility="collapsed",
                )
            with rm_col2:
                if st.button("🗑 Çıkar", key="wl_rm_btn", use_container_width=True):
                    if wl_rm != "— seç —":
                        remove_from_watchlist(wl_rm)
                        if "wl_table_data" in st.session_state:
                            del st.session_state["wl_table_data"]
                        st.success(f"{wl_rm} listeden çıkarıldı.")
                        st.rerun()

        # ── Manuel tarama butonları ───────────────────────────────────────
        st.markdown('<hr style="border-color:#1e2833;margin:1rem 0;">', unsafe_allow_html=True)
        scan_c1, scan_c2, scan_c3 = st.columns(3)
        with scan_c1:
            wl_scan_trigger = st.button("🔍 52H Kontrol Et", key="wl_scan_btn", use_container_width=True)
        with scan_c2:
            wl_phase1_btn = st.button("📡 Faz 1 — Erken Uyarı", key="wl_phase1_btn", use_container_width=True)
            st.caption("T1+T4 · Claude yok · hızlı radar")
        with scan_c3:
            wl_phase2_btn = st.button("🧠 Faz 2 — Tam Analiz", key="wl_phase2_btn", use_container_width=True)
            st.caption("6 tetikleyici · Claude aktif · al/sat önerisi")

    # ── Faz 1: Erken Uyarı ───────────────────────────────────────────────
    if wl_phase1_btn:
        if not watchlist:
            st.warning("Takip listesi boş.")
        else:
            from watchlist_analyzer import run_phase1_scan
            with st.spinner(f"Pre-market erken uyarı taraması: {len(watchlist)} hisse..."):
                _p1_result = run_phase1_scan()
                st.session_state["wl_phase1_result"] = _p1_result

    if st.session_state.get("wl_phase1_result"):
        _p1 = st.session_state["wl_phase1_result"]
        _alerts = _p1["alerts"]
        if not _alerts:
            st.success("✅ Pre-market sakin — dikkat çeken hareket yok.")
        else:
            st.markdown(
                f'<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                f'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">📡 {len(_alerts)} erken uyarı</div>',
                unsafe_allow_html=True,
            )
            for _a in _alerts:
                _chg = _a["chg"]
                _clr = "#00c48c" if _chg > 0 else "#e74c3c"
                _ar  = "▲" if _chg > 0 else "▼"
                st.markdown(
                    f'<div style="background:var(--color-background-secondary);'
                    f'border-left:3px solid {_clr};padding:0.5rem 0.8rem;'
                    f'margin-bottom:0.4rem;border-radius:0 6px 6px 0;font-size:0.78rem;">'
                    f'<b>{_a["ticker"]}</b> &nbsp; '
                    f'<span style="color:{_clr};">{_ar} %{abs(_chg):.1f}</span> &nbsp; '
                    f'${_a["price"]:.2f} &nbsp;|&nbsp; '
                    + " &nbsp;+&nbsp; ".join(_a["triggers"])
                    + "<br>" + "<br>".join(f'<span style="color:var(--color-text-secondary);">{v}</span>'
                                           for v in _a["details"].values())
                    + f'<br><span style="color:var(--color-text-tertiary);font-size:0.7rem;">⏳ {_a["note"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Faz 2: Tam Analiz ────────────────────────────────────────────────
    wl_full_scan = wl_phase2_btn

    if wl_full_scan:
        if not watchlist:
            st.warning("Takip listesi boş.")
        else:
            from watchlist_analyzer import run_phase2_analysis
            with st.spinner(f"{len(watchlist)} hisse için 6 tetikleyici + Claude analizi..."):
                _wl_result = run_phase2_analysis()
                st.session_state["wl_full_result"] = _wl_result

    if st.session_state.get("wl_full_result"):
        _wlr = st.session_state["wl_full_result"]
        _triggered = _wlr["triggered"]
        _screened  = _wlr["screened"]

        # Özet metrik
        m1, m2, m3 = st.columns(3)
        m1.metric("Taranan", _wlr["total"])
        m2.metric("Tetiklenen", _wlr["analyzed"])
        m3.metric("Sakin", _wlr["total"] - _wlr["analyzed"])

        if not _triggered:
            st.success("✅ Bugün tetikleyici yok — tüm hisseler sakin.")
        else:
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">Tetiklenen Hisseler</div>',
                unsafe_allow_html=True,
            )
            for _r in _triggered:
                _tk     = _r.get("hisse_sembolu", "")
                _score  = _r.get("nihai_guven_skoru", 0)
                _tav    = _r.get("tavsiye", "Tut")
                _ozet   = _r.get("analiz_ozeti", "")[:120]
                _trigs  = _r.get("_triggers", [])
                _tdet   = _r.get("_trigger_details", {})
                _tdata  = _r.get("_trigger_data", {})
                _sc     = "#00c48c" if _score >= 70 else ("#ffb300" if _score >= 50 else "#e74c3c")

                with st.expander(
                    f"{'🟢' if _score>=70 else '🟡' if _score>=50 else '🔴'}  "
                    f"{_tk}  ·  {_score}/100  ·  {_tav}  ·  "
                    f"Tetikleyiciler: {', '.join(_trigs)}",
                    expanded=(_score >= 70)
                ):
                    # Tetikleyici detayları
                    for _t in _trigs:
                        _d = _tdet.get(_t, "")
                        _t_emoji = {
                            "T1": "📈", "T2": "🚀", "T3": "👔",
                            "T4": "📰", "T5": "📊", "T6": "🔻"
                        }.get(_t, "•")
                        st.markdown(
                            f'<div style="font-size:0.75rem;padding:2px 0;">'
                            f'{_t_emoji} <b>{_t}</b>: {_d}</div>',
                            unsafe_allow_html=True,
                        )

                    st.markdown(
                        f'<div style="margin-top:0.5rem;font-size:0.78rem;'
                        f'border-left:3px solid {_sc};padding-left:0.6rem;">'
                        f'{_ozet}</div>',
                        unsafe_allow_html=True,
                    )

                    # Metrik özeti
                    _d = _tdata
                    st.caption(
                        f"Fiyat: ${_d.get('price',0):.2f} ({_d.get('change_pct',0):+.1f}%) · "
                        f"52H: %{_d.get('w52h_pos',0):.0f} · "
                        f"RSI: {_d.get('rsi',50):.0f} · "
                        f"Hacim: {_d.get('vol_ratio',1):.1f}x"
                    )

        # Yakın kaçanlar
        _near = [s for s in _screened if s["trigger_count"] == 1][:5]
        if _near:
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">Yakın Kaçanlar (1 tetikleyici)</div>',
                unsafe_allow_html=True,
            )
            import pandas as _pd_near
            st.dataframe(
                _pd_near.DataFrame([{
                    "Ticker": s["ticker"],
                    "Fiyat":  f"${s['price']:.2f}",
                    "Değişim": f"{s['chg']:+.1f}%",
                    "52H Pos.": f"%{s['w52h_pos']:.0f}",
                    "Tetikleyici": ", ".join(s["triggers"]) if s["triggers"] else "—",
                } for s in _near]),
                use_container_width=True, hide_index=True,
            )

    if wl_scan_trigger:
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

    # ── İçeriden Alım/Satım (Insider) ────────────────────────────────────
    st.markdown('<hr style="border-color:#1e2833;margin:1.5rem 0;">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:0.5rem;">🔎 İÇERİDEN ALIM/SATIM (SEC Form 4)</div>',
        unsafe_allow_html=True,
    )
    st.caption("Portföy + takip listesindeki hisselerde yönetici alım/satım işlemlerini tara.")

    ins_col1, ins_col2 = st.columns([1, 2])
    with ins_col1:
        ins_days = st.selectbox("Tarama süresi:", [7, 14, 30], format_func=lambda x: f"Son {x} gün", key="ins_days")
    with ins_col2:
        st.markdown('<div style="margin-top:1.7rem;"></div>', unsafe_allow_html=True)
        ins_btn = st.button("🔍 Insider Tara", key="btn_insider", use_container_width=True)

    if ins_btn:
        from insider_tracker import run_insider_scan
        # Portföy + watchlist
        _ins_tickers = [p["ticker"] for p in load_portfolio()]
        _ins_tickers += load_watchlist()
        _ins_tickers  = list(dict.fromkeys(_ins_tickers))[:25]

        if not _ins_tickers:
            st.warning("Portföy ve takip listesi boş.")
        else:
            with st.spinner(f"{len(_ins_tickers)} hisse için SEC Form 4 taranıyor..."):
                _ins_results = run_insider_scan(_ins_tickers, days=ins_days)
                st.session_state["insider_results"] = _ins_results

    if st.session_state.get("insider_results") is not None:
        _ins_results = st.session_state["insider_results"]
        if not _ins_results:
            st.success("✅ Seçilen dönemde anlamlı içeriden işlem sinyali bulunamadı.")
        else:
            for _ir in _ins_results:
                _sig   = _ir["signal"]
                _score = _ir["score"]
                _sig_c = "#00c48c" if _score >= 2 else ("#e74c3c" if _score <= -2 else "#ffb300")
                _sig_e = "📈" if _score >= 2 else ("📉" if _score <= -2 else "➡️")

                with st.expander(
                    f"{_sig_e}  {_ir['ticker']}  ·  {_sig}  ·  Skor: {_score:+.1f}  ·  {_ir['summary']}",
                    expanded=(_score >= 4 or _score <= -4)
                ):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(
                            f'<div style="font-size:0.78rem;line-height:1.8;">'
                            f'Alım: <b style="color:#00c48c;">{_ir["buy_count"]} işlem · ${_ir["buy_value"]/1000:.0f}K</b><br>'
                            f'Satış: <b style="color:#e74c3c;">{_ir["sell_count"]} işlem · ${_ir["sell_value"]/1000:.0f}K</b><br>'
                            f'CEO/CFO: {"✅ Dahil" if _ir["ceo_involved"] else "—"}<br>'
                            f'Küme: {"⚡ Var" if _ir["cluster"] else "—"}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    with c2:
                        if _ir.get("transactions"):
                            import pandas as _pd_ins
                            _tx_rows = [{
                                "Tarih":    t.get("trade_date", t.get("filing_date", ""))[:10],
                                "Kişi":     t.get("insider_name", "")[:20],
                                "Unvan":    t.get("title", "")[:15],
                                "İşlem":    "AL" if "P" in t.get("trade_type","").upper() else "SAT",
                                "Fiyat":    f"${t.get('price',0):.2f}" if t.get('price') else "—",
                                "Değer":    f"${t.get('value',0)/1000:.0f}K" if t.get('value') else "—",
                            } for t in _ir["transactions"][:8]]
                            if _tx_rows:
                                st.dataframe(_pd_ins.DataFrame(_tx_rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 7 — MAKRO GÖSTERGE PANELİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_macro:
    from macro_dashboard import (
        fetch_macro_data, compute_market_regime, build_claude_macro_context
    )

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► MAKRO GÖSTERGE PANELİ — Piyasa Rejimi & Bağlam</div>',
        unsafe_allow_html=True,
    )

    # ── Veri Çek ─────────────────────────────────────────────────────────────
    if st.button("🔄 Makro Verileri Güncelle", key="btn_macro_refresh"):
        st.session_state.pop("macro_data", None)
        st.session_state.pop("macro_regime", None)

    if "macro_data" not in st.session_state:
        with st.spinner("Makro veriler çekiliyor..."):
            try:
                _macro_data   = fetch_macro_data()
                _macro_regime = compute_market_regime(_macro_data)
                st.session_state["macro_data"]   = _macro_data
                st.session_state["macro_regime"]  = _macro_regime
                # Hafızaya kaydet
                try:
                    save_macro_snapshot(_macro_data, _macro_regime)
                except Exception:
                    pass
            except Exception as _e:
                st.error(f"Makro veri çekme hatası: {_e}")
                _macro_data   = {}
                _macro_regime = {"regime": "CAUTION", "label": "Veri Yok",
                                 "color": "#5a6a7a", "bg": "#1e2833",
                                 "description": "Veriler yüklenemedi."}

    _macro_data   = st.session_state.get("macro_data", {})
    _macro_regime = st.session_state.get("macro_regime", {})

    if not _macro_data:
        st.info("Verileri yüklemek için 'Makro Verileri Güncelle' butonuna bas.")
    else:
        # ── Rejim Kutusu ─────────────────────────────────────────────────────
        _rc = _macro_regime.get("color", "#5a6a7a")
        _rb = _macro_regime.get("bg", "#1e2833")
        st.markdown(
            f'<div style="border:1.5px solid {_rc};border-radius:10px;'
            f'padding:1rem 1.2rem;margin-bottom:1.2rem;display:flex;'
            f'align-items:flex-start;gap:1rem;">'
            f'<div style="min-width:140px;">'
            f'<div style="font-size:0.6rem;color:#5a6a7a;text-transform:uppercase;'
            f'letter-spacing:0.08em;margin-bottom:4px;">Piyasa Rejimi</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{_rc};">'
            f'{_macro_regime.get("label","")}</div>'
            f'</div>'
            f'<div style="font-size:0.78rem;color:#8a9ab0;line-height:1.7;padding-top:4px;">'
            f'{_macro_regime.get("description","")}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # ── Gösterge Grupları ─────────────────────────────────────────────────
        _groups = [
            ("fear",      "Korku & Volatilite", ["VIX", "YIELD_CURVE"]),
            ("rates",     "Faiz Ortamı",        ["TNX", "IRX", "TLT"]),
            ("fx_comm",   "Dolar & Emtia",      ["DXY", "GOLD", "OIL", "COPPER"]),
            ("market",    "Piyasa",             ["SPX", "NDX"]),
        ]

        _signal_colors = {
            "green":   ("#00c48c", "#0d2b1a", "✅"),
            "amber":   ("#ffb300", "#2b1f00", "⚡"),
            "red":     ("#e74c3c", "#2b0a0a", "⚠"),
            "neutral": ("#5a6a7a", "#1a1f26", "—"),
        }

        for _gkey, _glabel, _keys in _groups:
            _items = [_macro_data[k] for k in _keys if k in _macro_data]
            if not _items:
                continue

            st.markdown(
                f'<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                f'letter-spacing:0.08em;margin:1rem 0 0.4rem;">{_glabel}</div>',
                unsafe_allow_html=True,
            )

            _cols = st.columns(len(_items))
            for _col, _item in zip(_cols, _items):
                _sc, _bg, _emoji = _signal_colors.get(_item.signal, _signal_colors["neutral"])
                _prefix = "$" if _item.unit == "$" else ""
                _suffix = _item.unit if _item.unit != "$" else ""
                _chg_c  = "#00c48c" if _item.change_pct >= 0 else "#e74c3c"
                _chg_s  = f"{_item.change_pct:+.2f}%"

                _col.markdown(
                    f'<div style="background:#0d1117;border:1px solid {_sc}33;'
                    f'border-left:3px solid {_sc};border-radius:0 8px 8px 0;'
                    f'padding:0.7rem 0.8rem;">'
                    f'<div style="font-size:0.6rem;color:#5a6a7a;margin-bottom:3px;">{_item.label}</div>'
                    f'<div style="font-size:1.1rem;font-weight:700;color:{_sc};">'
                    f'{_prefix}{_item.value:.2f}{_suffix}</div>'
                    f'<div style="font-size:0.65rem;color:{_chg_c};margin-top:1px;">{_chg_s}</div>'
                    f'<div style="font-size:0.6rem;color:#5a6a7a;margin-top:4px;line-height:1.5;">'
                    f'{_item.note}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # ── Sinyal Özet Tablosu ───────────────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.08em;margin:1.2rem 0 0.4rem;">Sinyal Özeti</div>',
            unsafe_allow_html=True,
        )

        _all_items = list(_macro_data.values())
        _all_items.sort(key=lambda x: {"red": 0, "amber": 1, "green": 2, "neutral": 3}.get(x.signal, 3))

        for _item in _all_items:
            _sc, _, _emoji = _signal_colors.get(_item.signal, _signal_colors["neutral"])
            _prefix = "$" if _item.unit == "$" else ""
            _suffix = _item.unit if _item.unit != "$" else ""
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:0.5px solid #1e2833;">'
                f'<span style="font-size:11px;color:{_sc};min-width:16px;">{_emoji}</span>'
                f'<span style="font-size:12px;color:#8a9ab0;min-width:180px;">{_item.label}</span>'
                f'<span style="font-size:12px;font-weight:600;color:#e0e6ed;min-width:80px;">'
                f'{_prefix}{_item.value:.2f}{_suffix}</span>'
                f'<span style="font-size:11px;color:#5a6a7a;">{_item.note}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # ── Claude Makro Analizi ──────────────────────────────────────────────
        st.markdown('<hr style="border-color:#1e2833;margin:1.2rem 0;">', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.08em;margin-bottom:0.5rem;">Claude Makro Yorumu</div>',
            unsafe_allow_html=True,
        )

        if st.button("🧠 Claude ile Makroyu Yorumla", key="btn_macro_claude"):
            _macro_ctx = build_claude_macro_context(_macro_data, _macro_regime)
            _api_key   = os.getenv("ANTHROPIC_API_KEY", "")
            if not _api_key:
                st.error("ANTHROPIC_API_KEY eksik.")
            else:
                with st.spinner("Claude makro ortamı analiz ediyor..."):
                    import anthropic as _ant
                    _client = _ant.Anthropic(api_key=_api_key)
                    _prompt = f"""{_macro_ctx}

Yukarıdaki makro verilere bakarak şunları değerlendir:

1. **Genel Piyasa Ortamı**: Şu an hangi aşamadayız? (genişleme, yavaşlama, daralma, toparlanma)
2. **En Kritik Risk**: Şu an portföy için en tehlikeli gösterge hangisi ve neden?
3. **En Önemli Fırsat**: Mevcut ortamda hangi sektör veya varlık tipi öne çıkıyor?
4. **Portföy Tavsiyesi**: Bu makro ortamda ideal portföy dağılımı nasıl olmalı? (savunmacı/saldırgan/dengeli)
5. **Önümüzdeki 4-8 Hafta**: Dikkat edilmesi gereken kritik gelişmeler neler?

Türkçe, net ve somut yaz. Genel laflar değil, bu spesifik rakamlara dayalı yorum yap."""

                    try:
                        _resp = _client.messages.create(
                            model="claude-opus-4-5",
                            max_tokens=1500,
                            messages=[{"role": "user", "content": _prompt}]
                        )
                        st.session_state["macro_claude_analysis"] = _resp.content[0].text
                    except Exception as _e:
                        st.error(f"Claude bağlantı hatası: {_e}")

        if st.session_state.get("macro_claude_analysis"):
            st.markdown(st.session_state["macro_claude_analysis"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 8 — FİNANSAL TERİMLER KÜTÜPHANESİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_library:
    from knowledge_library import (
        get_all_terms, get_terms_by_category, search_terms,
        get_term_by_id, CATEGORIES
    )

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► FİNANSAL TERİMLER KÜTÜPHANESİ — Öğren, Anla, Uygula</div>',
        unsafe_allow_html=True,
    )

    # ── Arama + Filtre ────────────────────────────────────────────────────
    lib_s1, lib_s2 = st.columns([2, 3])
    with lib_s1:
        lib_search = st.text_input(
            "Terim ara:", placeholder="örn: P/E, VIX, RSI, beta...",
            key="lib_search", label_visibility="collapsed"
        ).strip()
    with lib_s2:
        cat_options = {"hepsi": "Tümü"} | {k: f"{v['emoji']} {v['label']}" for k, v in CATEGORIES.items()}
        lib_cat = st.selectbox(
            "Kategori:", options=list(cat_options.keys()),
            format_func=lambda x: cat_options[x],
            key="lib_cat", label_visibility="collapsed"
        )

    # Seviye filtresi
    lib_level = st.radio(
        "Seviye:", ["hepsi", "başlangıç", "orta", "ileri"],
        format_func=lambda x: {"hepsi": "Tüm seviyeler", "başlangıç": "🟢 Başlangıç",
                                "orta": "🟡 Orta", "ileri": "🔴 İleri"}.get(x, x),
        horizontal=True, key="lib_level",
    )

    # Filtreleme
    if lib_search:
        terms = search_terms(lib_search)
    elif lib_cat != "hepsi":
        terms = get_terms_by_category(lib_cat)
    else:
        terms = get_all_terms()

    if lib_level != "hepsi":
        terms = [t for t in terms if t.get("level") == lib_level]

    # Özet sayaç
    st.markdown(
        f'<div style="font-size:0.65rem;color:#5a6a7a;margin:0.4rem 0 0.8rem;">'
        f'{len(terms)} terim gösteriliyor · Toplam {len(get_all_terms())} terim</div>',
        unsafe_allow_html=True,
    )

    # Seviye renk/etiket
    _level_badge = {
        "başlangıç": ('<span style="background:#EAF3DE;color:#3B6D11;font-size:10px;'
                      'padding:1px 6px;border-radius:4px;">Başlangıç</span>'),
        "orta":      ('<span style="background:#FAEEDA;color:#854F0B;font-size:10px;'
                      'padding:1px 6px;border-radius:4px;">Orta</span>'),
        "ileri":     ('<span style="background:#FCEBEB;color:#A32D2D;font-size:10px;'
                      'padding:1px 6px;border-radius:4px;">İleri</span>'),
    }
    _cat_emoji = {k: v["emoji"] for k, v in CATEGORIES.items()}

    # ── Kart listesi ──────────────────────────────────────────────────────
    if not terms:
        st.info("Arama sonucu bulunamadı. Farklı bir terim dene.")
    else:
        for term in terms:
            _lvl_badge = _level_badge.get(term.get("level", ""), "")
            _cat_em    = _cat_emoji.get(term["category"], "")
            _cat_label = CATEGORIES.get(term["category"], {}).get("label", "")
            _header = (
                f'{term["emoji"]} **{term["term"]}** '
                f'<span style="color:#5a6a7a;font-size:0.75rem;">— {term["eng"]}</span>'
            )

            with st.expander(
                f'{term["emoji"]}  {term["term"]}  ·  {term["eng"]}',
                expanded=False
            ):
                # Üst etiketler
                st.markdown(
                    f'{_lvl_badge} &nbsp;'
                    f'<span style="font-size:10px;color:#5a6a7a;">{_cat_em} {_cat_label}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown("")

                # İçerik — 2 kolon
                col_left, col_right = st.columns([1.1, 1])

                with col_left:
                    st.markdown("**Ne anlama gelir?**")
                    st.markdown(
                        f'<div style="font-size:0.8rem;line-height:1.7;">'
                        f'{term["definition"]}</div>',
                        unsafe_allow_html=True,
                    )

                    if term.get("formula"):
                        st.markdown('<div style="margin-top:0.6rem;"></div>', unsafe_allow_html=True)
                        st.markdown("**Formül:**")
                        st.markdown(
                            f'<div style="background:#0d1117;border-left:3px solid #1e6a9e;'
                            f'padding:0.4rem 0.7rem;border-radius:0 4px 4px 0;'
                            f'font-size:0.75rem;color:#4fc3f7;font-family:monospace;">'
                            f'{term["formula"]}</div>',
                            unsafe_allow_html=True,
                        )

                with col_right:
                    st.markdown("**Nasıl okunur?**")
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:1.75;">'
                        f'{term["how_to_read"].replace(chr(10), "<br>")}</div>',
                        unsafe_allow_html=True,
                    )

                # Portföy + örnek
                st.markdown('<hr style="border-color:#1e2833;margin:0.7rem 0;">', unsafe_allow_html=True)
                port_col, ex_col = st.columns(2)

                with port_col:
                    st.markdown("**💼 Portföy kararında kullanımı:**")
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:1.7;">'
                        f'{term["portfolio"]}</div>',
                        unsafe_allow_html=True,
                    )

                with ex_col:
                    st.markdown("**📌 Gerçek örnek:**")
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:1.7;">'
                        f'{term["example"].replace(chr(10), "<br>")}</div>',
                        unsafe_allow_html=True,
                    )

                # İlişkili terimler
                if term.get("related"):
                    st.markdown('<div style="margin-top:0.6rem;"></div>', unsafe_allow_html=True)
                    rel_labels = []
                    for rid in term["related"]:
                        rt = get_term_by_id(rid)
                        if rt:
                            rel_labels.append(f'{rt["emoji"]} {rt["term"]}')
                    if rel_labels:
                        st.markdown(
                            '<span style="font-size:0.65rem;color:#5a6a7a;">İlgili terimler: </span>' +
                            " &nbsp;·&nbsp; ".join(
                                f'<span style="font-size:0.72rem;color:#4fc3f7;">{r}</span>'
                                for r in rel_labels
                            ),
                            unsafe_allow_html=True,
                        )

                # ── Claude'a Sor ──────────────────────────────────────────
                st.markdown('<div style="margin-top:0.7rem;"></div>', unsafe_allow_html=True)
                ask_col1, ask_col2 = st.columns([2, 1])
                with ask_col1:
                    ask_input = st.text_input(
                        "Claude'a sor:",
                        placeholder=f"örn: Portföyümdeki NVDA için {term['term']}'i yorumla",
                        key=f"ask_{term['id']}",
                        label_visibility="collapsed",
                    )
                with ask_col2:
                    ask_btn = st.button(
                        "🧠 Sor", key=f"btn_ask_{term['id']}", use_container_width=True
                    )

                if ask_btn and ask_input.strip():
                    _api_key = os.getenv("ANTHROPIC_API_KEY", "")
                    if not _api_key:
                        st.error("ANTHROPIC_API_KEY eksik.")
                    else:
                        with st.spinner("Claude yanıtlıyor..."):
                            import anthropic as _ant_lib
                            _lib_client = _ant_lib.Anthropic(api_key=_api_key)

                            # Portföy bağlamı ekle
                            _port = load_portfolio()
                            _port_str = ""
                            if _port:
                                _port_str = (
                                    "\nMevcut portföy: " +
                                    ", ".join(p["ticker"] for p in _port[:10])
                                )

                            _lib_prompt = f"""Finans terimleri kütüphanesi sorusu.

Terim: {term['term']} ({term['eng']})
Tanım: {term['definition'][:200]}

Kullanıcı sorusu: {ask_input}
{_port_str}

Lütfen bu soruya:
1. Terimi sade Türkçe ile açıklayarak yanıtla
2. Eğer portföy hissesi belirtildiyse o hisseyle bağlantı kur
3. Pratik, uygulanabilir tavsiye ver
4. 3–5 cümleyle kısa tut — uzun anlatım yapma

Türkçe yaz."""

                            try:
                                _lib_resp = _lib_client.messages.create(
                                    model="claude-opus-4-5",
                                    max_tokens=600,
                                    messages=[{"role": "user", "content": _lib_prompt}]
                                )
                                _lib_answer = _lib_resp.content[0].text if _lib_resp.content else ""
                                st.session_state[f"lib_answer_{term['id']}"] = _lib_answer
                            except Exception as _e:
                                st.error(f"Claude hatası: {_e}")

                if st.session_state.get(f"lib_answer_{term['id']}"):
                    st.markdown(
                        '<div style="background:#0d1117;border:1px solid #1e2833;'
                        'border-left:3px solid #00c48c;border-radius:0 8px 8px 0;'
                        'padding:0.7rem 0.9rem;margin-top:0.4rem;font-size:0.78rem;'
                        'color:#dde3ea;line-height:1.7;">'
                        + st.session_state[f"lib_answer_{term['id']}"]
                        + '</div>',
                        unsafe_allow_html=True,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 9 — FİYAT HEDEFİ TAKİPÇİSİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_targets:
    from price_target_tracker import (
        get_all_targets_summary, update_price_targets,
        get_revision_trend, get_upside_category,
    )
    import pandas as _pd_tgt

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► ANALİST FİYAT HEDEFİ TAKİPÇİSİ</div>',
        unsafe_allow_html=True,
    )

    # Tüm ticker listesi: portföy + watchlist
    from breakout_scanner import load_watchlist as _load_wl_tgt
    _tgt_tickers = [p["ticker"] for p in load_portfolio()]
    _tgt_tickers += _load_wl_tgt()
    _tgt_tickers  = list(dict.fromkeys(_tgt_tickers))

    tgt_c1, tgt_c2, tgt_c3 = st.columns([1, 1, 2])
    with tgt_c1:
        tgt_refresh = st.button("🔄 Verileri Güncelle", key="tgt_refresh", use_container_width=True)
    with tgt_c2:
        tgt_filter  = st.selectbox(
            "Filtrele:",
            ["Tümü", "Portföy", "Watchlist", "Yüksek Potansiyel (>%15)", "Hedefin Üzerinde"],
            key="tgt_filter", label_visibility="collapsed",
        )
    with tgt_c3:
        st.caption(f"📊 {len(_tgt_tickers)} hisse takip ediliyor · Portföy + Watchlist")

    if tgt_refresh:
        with st.spinner("Analist hedefleri yükleniyor..."):
            update_price_targets(_tgt_tickers)
            st.session_state["tgt_data"] = None  # Cache temizle

    # Veri yükle
    if st.session_state.get("tgt_data") is None:
        with st.spinner("Hedef veriler yükleniyor..."):
            _tgt_data = get_all_targets_summary(_tgt_tickers)
            st.session_state["tgt_data"] = _tgt_data

    _tgt_data = st.session_state.get("tgt_data") or []

    # Filtrele
    _port_tickers = {p["ticker"] for p in load_portfolio()}
    _wl_tickers   = set(_load_wl_tgt())
    if tgt_filter == "Portföy":
        _tgt_data = [r for r in _tgt_data if r["ticker"] in _port_tickers]
    elif tgt_filter == "Watchlist":
        _tgt_data = [r for r in _tgt_data if r["ticker"] in _wl_tickers]
    elif tgt_filter == "Yüksek Potansiyel (>%15)":
        _tgt_data = [r for r in _tgt_data if r["upside"] >= 15]
    elif tgt_filter == "Hedefin Üzerinde":
        _tgt_data = [r for r in _tgt_data if r["upside"] < 0]

    if not _tgt_data:
        st.info("Veri bulunamadı. 'Verileri Güncelle' butonuna tıkla.")
    else:
        # ── Özet metrik bar ───────────────────────────────────────────────
        _avg_upside   = sum(r["upside"] for r in _tgt_data) / len(_tgt_data)
        _high_pot     = sum(1 for r in _tgt_data if r["upside"] >= 15)
        _above_target = sum(1 for r in _tgt_data if r["upside"] < 0)
        _revising_up  = sum(1 for r in _tgt_data if r["trend"]["direction"] in ("yukarı","güçlü_yukarı"))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ort. Upside", f"%{_avg_upside:.1f}")
        m2.metric("Yüksek Potansiyel", f"{_high_pot} hisse")
        m3.metric("Hedef Revize ↑", f"{_revising_up} hisse")
        m4.metric("Hedefin Üzerinde", f"{_above_target} hisse")

        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.8rem 0;">', unsafe_allow_html=True)

        # ── Ana Tablo ─────────────────────────────────────────────────────
        tbl_rows = []
        for r in _tgt_data:
            _trend_ch  = r["trend"].get("change_pct", 0)
            _trend_str = f"{r['trend_arrow']} {_trend_ch:+.1f}%" if _trend_ch != 0 else "➡ Stabil"
            tbl_rows.append({
                "Ticker":       r["ticker"],
                "Fiyat":        f"${r['price']:.2f}",
                "Ort. Hedef":   f"${r['mean']:.2f}",
                "En Yüksek":    f"${r['high']:.2f}",
                "En Düşük":     f"${r['low']:.2f}",
                "Upside":       f"{r['upside']:+.1f}%",
                "Potansiyel":   r["upside_cat"],
                "Revizyon(30g)":_trend_str,
                "Konsensüs":    r["consensus"],
                "Son Güncelleme": r["date"],
            })

        _df_tgt = _pd_tgt.DataFrame(tbl_rows)

        def _color_upside(val):
            if isinstance(val, str):
                try:
                    v = float(val.replace("%","").replace("+",""))
                    if v >= 20: return "color:#00c48c;font-weight:600"
                    if v >= 10: return "color:#4fc3f7"
                    if v >= 0:  return "color:#ffb300"
                    return "color:#e74c3c"
                except Exception:
                    pass
            return ""

        def _color_rev(val):
            if isinstance(val, str):
                if "⬆" in val: return "color:#00c48c"
                if "⬇" in val: return "color:#e74c3c"
            return ""

        st.dataframe(
            _df_tgt.style
                .map(_color_upside, subset=["Upside"])
                .map(_color_rev,    subset=["Revizyon(30g)"]),
            use_container_width=True,
            hide_index=True,
            height=min(len(tbl_rows) * 38 + 40, 650),
        )

        # ── Detay Kartları ────────────────────────────────────────────────
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin:1rem 0 0.5rem;">Detaylı Görünüm</div>',
            unsafe_allow_html=True,
        )

        for r in _tgt_data[:10]:  # İlk 10 detaylı göster
            _u = r["upside"]
            _uc = r["upside_color"]
            _tc = r["trend_color"]
            _trend = r["trend"]

            with st.expander(
                f"{r['trend_arrow']}  {r['ticker']}  ·  "
                f"Upside: {_u:+.1f}%  ·  {r['upside_cat']}  ·  {r['consensus']}",
                expanded=(_u >= 20 or _trend["direction"] in ("güçlü_yukarı","güçlü_aşağı")),
            ):
                dc1, dc2, dc3 = st.columns(3)

                with dc1:
                    st.markdown("**Hedef Fiyatlar**")
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:2;">'
                        f'Ort. Hedef: <b style="color:{_uc};">${r["mean"]:.2f}</b><br>'
                        f'En Yüksek: <b>${r["high"]:.2f}</b><br>'
                        f'En Düşük: <b>${r["low"]:.2f}</b><br>'
                        f'Mevcut: <b>${r["price"]:.2f}</b><br>'
                        f'<b style="color:{_uc};">Upside: {_u:+.1f}%</b>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with dc2:
                    st.markdown("**Konsensüs**")
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:2;">'
                        f'{r["consensus"]}<br>'
                        f'Analist: {r["n_analysts"]}<br>'
                        f'Öneri: {r["rec"]}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                with dc3:
                    st.markdown("**30 Günlük Revizyon**")
                    _td = r["trend"]
                    st.markdown(
                        f'<div style="font-size:0.78rem;line-height:2;color:{_tc};">'
                        f'{_td.get("description","—")}<br>'
                        + (f'Eski hedef: ${_td.get("old_mean",0):.2f}<br>'
                           f'Yeni hedef: ${_td.get("new_mean",0):.2f}'
                           if _td.get("old_mean",0) != _td.get("new_mean",0) else "Yeterli geçmiş yok")
                        + f'</div>',
                        unsafe_allow_html=True,
                    )

                # Fiyat/Hedef görsel bandı
                if r["price"] > 0 and r["low"] > 0 and r["high"] > 0:
                    _rng   = r["high"] - r["low"]
                    _pos   = max(0, min(100, (r["price"] - r["low"]) / _rng * 100)) if _rng > 0 else 50
                    _mean_pos = max(0, min(100, (r["mean"] - r["low"]) / _rng * 100)) if _rng > 0 else 50
                    st.markdown(
                        f'<div style="margin-top:0.5rem;">'
                        f'<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:4px;">'
                        f'Analist Aralığı: ${r["low"]:.0f} → ${r["high"]:.0f}</div>'
                        f'<div style="position:relative;height:10px;background:var(--color-background-secondary);'
                        f'border-radius:5px;overflow:visible;">'
                        f'<div style="position:absolute;left:{_mean_pos:.0f}%;top:-3px;'
                        f'width:3px;height:16px;background:#ffb300;border-radius:2px;" title="Ort. Hedef"></div>'
                        f'<div style="position:absolute;left:{_pos:.0f}%;top:-4px;'
                        f'width:4px;height:18px;background:{_uc};border-radius:2px;" title="Mevcut Fiyat"></div>'
                        f'</div>'
                        f'<div style="display:flex;justify-content:space-between;'
                        f'font-size:0.6rem;color:#5a6a7a;margin-top:4px;">'
                        f'<span>📍 Mevcut: ${r["price"]:.2f}</span>'
                        f'<span>🎯 Ort. Hedef: ${r["mean"]:.2f}</span>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 10 — STRATEJİ MERKEZİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_strategy:
    from strategy_data   import collect_all_strategy_data
    from strategy_engine import generate_strategy, save_strategy

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► STRATEJİ MERKEZİ — Kısa / Orta / Uzun Vade Aksiyon Planı</div>',
        unsafe_allow_html=True,
    )

    # ── Katman 1: Anlık Durum Panosu ─────────────────────────────────────
    _port_now     = load_portfolio()
    _cash_now     = get_cash()
    _port_val_now = sum(
        p.get("shares", 0) * p.get("current_price", p.get("avg_cost", 0))
        for p in _port_now
    )
    _total_now    = _port_val_now + _cash_now
    _cash_ratio   = (_cash_now / _total_now * 100) if _total_now > 0 else 0

    # Makro hızlı özet
    try:
        from macro_dashboard import fetch_macro_data, compute_market_regime
        _macro_quick  = fetch_macro_data()
        _regime_quick = compute_market_regime(_macro_quick)
        _vix_val      = getattr(_macro_quick.get("VIX"), "value", 0) if _macro_quick.get("VIX") else 0
        _regime_label = _regime_quick.get("label", "—")
        _regime_color = _regime_quick.get("color", "#8a9ab0")
    except Exception:
        _vix_val, _regime_label, _regime_color = 0, "—", "#8a9ab0"

    # Fear & Greed hızlı
    try:
        from strategy_data import fetch_fear_greed, fetch_fed_calendar
        _fg_quick  = fetch_fear_greed()
        _fed_quick = fetch_fed_calendar()
        _fg_score  = _fg_quick.get("score", 50)
        _fg_rating = _fg_quick.get("tr_rating", "—")
        _fg_color  = "#00c48c" if _fg_score <= 30 else ("#e74c3c" if _fg_score >= 70 else "#ffb300")
        _fomc_days = _fed_quick.get("days_until", "—")
    except Exception:
        _fg_score, _fg_rating, _fg_color, _fomc_days = 50, "—", "#ffb300", "—"

    # KPI bar
    _kpi_cols = st.columns(5)
    for _col, _label, _val, _clr, _sub in [
        (_kpi_cols[0], "Portföy Değeri",  f"${_port_val_now:,.0f}", "#4fc3f7", "hisse"),
        (_kpi_cols[1], "Nakit",           f"${_cash_now:,.0f}",     "#00c48c", f"%{_cash_ratio:.0f} oran"),
        (_kpi_cols[2], "Makro Rejim",     _regime_label,            _regime_color, f"VIX {_vix_val:.0f}"),
        (_kpi_cols[3], "Fear & Greed",    f"{_fg_score:.0f}/100",   _fg_color, _fg_rating),
        (_kpi_cols[4], "FOMC'a Kalan",    f"{_fomc_days} gün",      "#ce93d8", "Fed toplantısı"),
    ]:
        _col.markdown(
            f'<div style="background:var(--color-background-secondary);'
            f'border:0.5px solid var(--color-border-tertiary);'
            f'border-top:3px solid {_clr};'
            f'border-radius:var(--border-radius-md);padding:0.8rem;text-align:center;">'
            f'<div style="font-size:0.6rem;color:var(--color-text-tertiary);'
            f'text-transform:uppercase;letter-spacing:0.05em;">{_label}</div>'
            f'<div style="font-size:1.3rem;font-weight:600;color:{_clr};margin:4px 0;">{_val}</div>'
            f'<div style="font-size:0.65rem;color:var(--color-text-tertiary);">{_sub}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)

    # ── Katman 2: Profil Ayarları ─────────────────────────────────────────
    with st.expander("⚙️ Yatırımcı Profili — Strateji Parametreleri", expanded=False):
        _pr_c1, _pr_c2, _pr_c3 = st.columns(3)
        with _pr_c1:
            _time_horizon = st.selectbox(
                "Zaman Ufku:",
                ["1-3 yıl (Uzun Vade)", "3-12 ay (Orta Vade)", "1-3 ay (Kısa Vade)"],
                index=0, key="st_time_horizon",
            )
            _risk_tol = st.selectbox(
                "Risk Toleransı:",
                ["Orta-Yüksek (%20 düşüş tolere edilir)",
                 "Orta (%10 düşüş tolere edilir)",
                 "Düşük (koruma öncelikli)"],
                index=0, key="st_risk_tol",
            )
        with _pr_c2:
            _cash_cycle = st.selectbox(
                "Nakit Döngüsü:",
                ["3 ayda bir", "Aylık düzenli", "Düzensiz / fırsata göre"],
                index=0, key="st_cash_cycle",
            )
            _deploy_cash = st.number_input(
                "Bu dönem dağıtılacak ek nakit ($):",
                min_value=0.0, value=0.0, step=100.0,
                key="st_deploy_cash",
            )
        with _pr_c3:
            _goal = st.text_area(
                "Yatırım Hedefi:",
                value="Uzun vadeli büyüme odaklı, volatiliteyi minimize ederek "
                      "portföyü sistematik şekilde büyütmek.",
                height=80, key="st_goal",
            )

    # ── Katman 3: Strateji Üret ───────────────────────────────────────────
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">', unsafe_allow_html=True)

    _strat_c1, _strat_c2 = st.columns([2, 1])
    with _strat_c1:
        st.markdown(
            '<div style="font-size:0.75rem;color:var(--color-text-secondary);line-height:1.7;">'
            'Aşağıdaki butona basıldığında sistem tüm verileri toplar: portföy durumu, '
            'makro göstergeler, haftalık raporlar, fırsat radarı, takip listesi, '
            'analist hedefleri, Fear&Greed, FOMC takvimi, short interest, earnings takvimi. '
            'Claude bunların hepsini senin profilinle birleştirerek somut bir aksiyon planı üretir.'
            '</div>',
            unsafe_allow_html=True,
        )
    with _strat_c2:
        _run_strategy = st.button(
            "🧭 Strateji Üret",
            key="btn_strategy", use_container_width=True, type="primary",
        )

    # Strateji çalıştır
    if _run_strategy:
        with st.spinner("Tüm veriler toplanıyor ve analiz ediliyor... (30-60 saniye)"):
            try:
                # Tüm veri kaynaklarını topla
                from breakout_scanner    import load_watchlist
                from price_target_tracker import get_all_targets_summary
                from analysis_memory     import get_weekly_reports, get_top_tickers

                _watchlist_tickers = load_watchlist()
                _port_enriched = [
                    {**p, "current_price": p.get("current_price", p.get("avg_cost", 0))}
                    for p in _port_now
                ]

                # Hisse skorları (hafızadan)
                _top_tickers = get_top_tickers(limit=30)
                _scores = {t["ticker"]: t.get("avg_score", 0) for t in _top_tickers}

                # Analist hedefleri
                _all_targets = get_all_targets_summary(_watchlist_tickers + [p["ticker"] for p in _port_now])
                _targets_dict = {t["ticker"]: {"mean": t["mean"], "upside": t["upside"],
                                               "n_analysts": t["n_analysts"], "rec": t["rec"]}
                                 for t in _all_targets}

                # Kullanıcı profili override
                from strategy_data import get_user_profile
                _user_profile = get_user_profile()
                _user_profile["time_horizon_years"] = _time_horizon
                _user_profile["risk_tolerance"]     = _risk_tol
                _user_profile["cash_cycle"]         = _cash_cycle
                _user_profile["goal"]               = _goal

                # Strateji verisi topla
                _strat_data = collect_all_strategy_data(
                    positions=_port_enriched,
                    watchlist_tickers=_watchlist_tickers,
                    cash=_cash_now,
                    existing_scores=_scores,
                    existing_targets=_targets_dict,
                )
                _strat_data["user_profile"] = _user_profile

                # Haftalık raporlar
                _weekly = get_weekly_reports(limit=4)

                # Radar sonuçları (session state'den)
                _radar  = st.session_state.get("radar_results", [])

                # Watchlist hedef verileri
                _wl_data = _all_targets

                # Strateji üret
                _result = generate_strategy(
                    strategy_data=_strat_data,
                    weekly_reports=_weekly,
                    radar_results=_radar,
                    watchlist_data=_wl_data,
                    user_cash_to_deploy=float(_deploy_cash),
                )

                st.session_state["strategy_result"] = _result
                st.session_state["strategy_data"]   = _strat_data

                if _result["success"]:
                    # Kaydet
                    save_strategy(_result, _port_val_now, _cash_now)
                    st.success("✅ Strateji üretildi ve kaydedildi!")
                else:
                    st.error(f"Strateji üretilemedi: {_result.get('error', '?')}")

            except Exception as _e:
                st.error(f"Hata: {_e}")
                import traceback
                st.code(traceback.format_exc())

    # ── Katman 4: Strateji Görüntüleme ────────────────────────────────────
    _sr = st.session_state.get("strategy_result", {})
    if _sr and _sr.get("success") and _sr.get("strategy"):
        _s = _sr["strategy"]

        # Genel Özet
        if _s.get("ozet"):
            st.markdown(
                f'<div style="background:var(--color-background-secondary);'
                f'border-left:4px solid #4fc3f7;border-radius:0 var(--border-radius-lg) '
                f'var(--border-radius-lg) 0;padding:1rem 1.2rem;margin:1rem 0;'
                f'font-size:0.82rem;line-height:1.7;">'
                f'<b style="font-size:0.7rem;color:var(--color-text-tertiary);'
                f'text-transform:uppercase;letter-spacing:0.08em;">Genel Değerlendirme</b><br>'
                f'{_s["ozet"]}</div>',
                unsafe_allow_html=True,
            )

        # Çelişkiler
        if _s.get("celiskiler"):
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:1rem 0 0.5rem;">⚡ TESPİT EDİLEN ÇELİŞKİLER</div>',
                unsafe_allow_html=True,
            )
            for _c in _s["celiskiler"]:
                st.markdown(
                    f'<div style="background:var(--color-background-secondary);'
                    f'border-left:3px solid #ffb300;border-radius:0 8px 8px 0;'
                    f'padding:0.7rem 1rem;margin-bottom:0.5rem;font-size:0.78rem;">'
                    f'<b>{_c.get("hisse","")}</b> — {_c.get("celisik_sinyaller","")}<br>'
                    f'<span style="color:#00c48c;">→ {_c.get("cozum","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Aksiyon Planı
        _aks = _s.get("aksiyonlar", {})
        if _aks:
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:1rem 0 0.5rem;">🎯 AKSİYON PLANI</div>',
                unsafe_allow_html=True,
            )

            _ak_c1, _ak_c2, _ak_c3 = st.columns(3)

            # Sat / Azalt
            with _ak_c1:
                st.markdown(
                    '<div style="font-size:0.65rem;font-weight:500;color:#e74c3c;'
                    'text-transform:uppercase;margin-bottom:0.5rem;">📉 Sat / Azalt</div>',
                    unsafe_allow_html=True,
                )
                for _item in _aks.get("sat_azalt", []):
                    st.markdown(
                        f'<div style="background:var(--color-background-secondary);'
                        f'border:0.5px solid #e74c3c44;border-radius:var(--border-radius-md);'
                        f'padding:0.7rem;margin-bottom:0.5rem;">'
                        f'<b style="font-size:14px;">{_item.get("ticker","")}</b> '
                        f'<span style="color:#e74c3c;font-size:12px;">%{_item.get("miktar_pct",0)} azalt</span><br>'
                        f'<span style="font-size:11px;color:var(--color-text-tertiary);">'
                        f'{_item.get("gercekle","Hemen")} · {_item.get("neden","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Al / Artır
            with _ak_c2:
                st.markdown(
                    '<div style="font-size:0.65rem;font-weight:500;color:#00c48c;'
                    'text-transform:uppercase;margin-bottom:0.5rem;">📈 Al / Artır</div>',
                    unsafe_allow_html=True,
                )
                for _item in _aks.get("al_arttir", []):
                    _src_emoji = {"watchlist": "👁", "radar": "🔭", "sürpriz": "⚡"}.get(
                        _item.get("kaynak","").lower(), "📊")
                    st.markdown(
                        f'<div style="background:var(--color-background-secondary);'
                        f'border:0.5px solid #00c48c44;border-radius:var(--border-radius-md);'
                        f'padding:0.7rem;margin-bottom:0.5rem;">'
                        f'<b style="font-size:14px;">{_item.get("ticker","")}</b> '
                        f'<span style="color:#00c48c;font-size:12px;">Nakit %{_item.get("nakit_pct",0)}</span> '
                        f'{_src_emoji}<br>'
                        + (f'<span style="font-size:11px;">Hedef: ${_item.get("hedef_fiyat",0):.0f} · '
                           f'Stop: ${_item.get("stop_loss",0):.0f}</span><br>'
                           if _item.get("hedef_fiyat") else "")
                        + f'<span style="font-size:11px;color:var(--color-text-tertiary);">'
                        f'{_item.get("neden","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Bekle / İzle (Koşullu)
            with _ak_c3:
                st.markdown(
                    '<div style="font-size:0.65rem;font-weight:500;color:#ffb300;'
                    'text-transform:uppercase;margin-bottom:0.5rem;">⏳ Koşullu / Bekle</div>',
                    unsafe_allow_html=True,
                )
                for _item in _aks.get("bekle_izle", []):
                    st.markdown(
                        f'<div style="background:var(--color-background-secondary);'
                        f'border:0.5px solid #ffb30044;border-radius:var(--border-radius-md);'
                        f'padding:0.7rem;margin-bottom:0.5rem;">'
                        f'<b style="font-size:14px;">{_item.get("ticker","")}</b> '
                        f'<span style="color:#ffb300;font-size:12px;">{_item.get("islem","")}</span><br>'
                        f'<span style="font-size:11px;color:#ffb300;">📌 {_item.get("kosul","")}</span><br>'
                        f'<span style="font-size:11px;color:var(--color-text-tertiary);">'
                        f'{_item.get("neden","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Nakit rezerv
            _nakit_res = _aks.get("nakit_rezerv_pct", 0)
            if _nakit_res > 0:
                st.markdown(
                    f'<div style="background:var(--color-background-secondary);'
                    f'border:0.5px solid var(--color-border-secondary);'
                    f'border-radius:var(--border-radius-md);padding:0.6rem 1rem;'
                    f'font-size:0.75rem;margin-top:0.3rem;">'
                    f'💵 <b>Nakit Rezerv: %{_nakit_res}</b> — '
                    f'{_aks.get("nakit_rezerv_neden","")}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Vade Planları
        for _vade_key, _vade_label, _vade_color in [
            ("kisa_vade",  "📅 Kısa Vade (1-3 Ay)",    "#4fc3f7"),
            ("orta_vade",  "📆 Orta Vade (3-12 Ay)",   "#ce93d8"),
            ("uzun_vade",  "🗓️ Uzun Vade (1-3 Yıl)",   "#ffb300"),
        ]:
            _vade = _s.get(_vade_key, {})
            if not _vade:
                continue

            with st.expander(
                f"{_vade_label} — {_vade.get('senaryo_baz', _vade.get('hedef_portfoy',''))[:60]}",
                expanded=(_vade_key == "kisa_vade"),
            ):
                _v1, _v2 = st.columns(2)
                with _v1:
                    if _vade.get("senaryo_baz"):
                        st.markdown(
                            f'<div style="font-size:0.7rem;color:{_vade_color};'
                            f'font-weight:500;margin-bottom:4px;">Ana Senaryo</div>'
                            f'<div style="font-size:0.78rem;">{_vade["senaryo_baz"]}</div>',
                            unsafe_allow_html=True,
                        )
                    elif _vade.get("hedef_portfoy"):
                        st.markdown(
                            f'<div style="font-size:0.7rem;color:{_vade_color};'
                            f'font-weight:500;margin-bottom:4px;">Hedef Portföy</div>'
                            f'<div style="font-size:0.78rem;">{_vade["hedef_portfoy"]}</div>',
                            unsafe_allow_html=True,
                        )
                with _v2:
                    if _vade.get("senaryo_risk"):
                        st.markdown(
                            f'<div style="font-size:0.7rem;color:#e74c3c;'
                            f'font-weight:500;margin-bottom:4px;">Risk Senaryosu</div>'
                            f'<div style="font-size:0.78rem;">{_vade["senaryo_risk"]}</div>',
                            unsafe_allow_html=True,
                        )

                # Aksiyonlar
                for _act in _vade.get("aksiyonlar", []):
                    st.markdown(
                        f'<div style="font-size:0.75rem;padding:3px 0;'
                        f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                        f'• {_act}</div>',
                        unsafe_allow_html=True,
                    )

        # Risk Uyarıları & Güç Sinyalleri
        _risk_col, _guc_col = st.columns(2)
        with _risk_col:
            _risks = _s.get("risk_uyarilari", [])
            if _risks:
                st.markdown(
                    '<div style="font-size:0.65rem;color:#e74c3c;text-transform:uppercase;'
                    'letter-spacing:0.08em;margin:0.8rem 0 0.4rem;">⚠️ Risk Uyarıları</div>',
                    unsafe_allow_html=True,
                )
                for _r in _risks:
                    st.markdown(
                        f'<div style="font-size:0.75rem;color:var(--color-text-secondary);'
                        f'padding:2px 0;">• {_r}</div>',
                        unsafe_allow_html=True,
                    )

        with _guc_col:
            _gucs = _s.get("guc_sinyalleri", [])
            if _gucs:
                st.markdown(
                    '<div style="font-size:0.65rem;color:#00c48c;text-transform:uppercase;'
                    'letter-spacing:0.08em;margin:0.8rem 0 0.4rem;">💪 Güç Sinyalleri</div>',
                    unsafe_allow_html=True,
                )
                for _g in _gucs:
                    st.markdown(
                        f'<div style="font-size:0.75rem;color:var(--color-text-secondary);'
                        f'padding:2px 0;">• {_g}</div>',
                        unsafe_allow_html=True,
                    )

        # Oluşturulma zamanı
        st.markdown(
            f'<div style="font-size:0.65rem;color:var(--color-text-tertiary);'
            f'margin-top:1rem;text-align:right;">'
            f'Oluşturulma: {_sr.get("generated_at","")[:16]}</div>',
            unsafe_allow_html=True,
        )
