# app.py — AI-Powered Stock Analysis & Decision Dashboard
# Run with:  streamlit run app.py

import os
import json
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
    load_user_profile, save_user_profile,
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
    get_cash_accounts, set_cash_account, add_to_cash_account, get_total_cash_usd,
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
if "strat_archive_cache" not in st.session_state:
    st.session_state["strat_archive_cache"] = None


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


def _render_asset_summary(positions: list, label: str, usd_try: float = 32.0):
    """Varlık sınıfı KPI özet bar — tüm sekmeler için ortak."""
    if not positions:
        return
    rows = []
    for p in positions:
        shares   = float(p.get("shares", 0))
        avg      = float(p.get("avg_cost", 0))
        cur_usd  = float(p.get("current_price_usd", 0) or p.get("current_price", 0))
        currency = p.get("currency", "USD")
        avg_usd  = avg / usd_try if currency == "TRY" else avg
        if shares <= 0 or cur_usd <= 0:
            continue
        val_usd = shares * cur_usd
        pnl_usd = shares * (cur_usd - avg_usd)
        pnl_pct = (cur_usd - avg_usd) / avg_usd * 100 if avg_usd > 0 else 0
        rows.append({"ticker": p.get("ticker", "?"), "val_usd": val_usd,
                     "pnl_usd": pnl_usd, "pnl_pct": pnl_pct})
    if not rows:
        return
    total_val  = sum(r["val_usd"] for r in rows)
    total_pnl  = sum(r["pnl_usd"] for r in rows)
    total_cost = total_val - total_pnl
    total_pct  = total_pnl / total_cost * 100 if total_cost > 0 else 0
    best  = max(rows, key=lambda x: x["pnl_pct"])
    worst = min(rows, key=lambda x: x["pnl_pct"])
    pc = "#00c48c" if total_pnl >= 0 else "#e74c3c"
    ps = "+" if total_pnl >= 0 else ""
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.markdown(
            f'<div class="kpi-card green"><div class="kpi-score-label">{label} DEĞERİ</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:#e8edf3;">${total_val:,.0f}</div></div>',
            unsafe_allow_html=True)
    with k2:
        card_c = "green" if total_pnl >= 0 else "red"
        st.markdown(
            f'<div class="kpi-card {card_c}"><div class="kpi-score-label">TOPLAM K/Z</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{pc};">{ps}${total_pnl:,.0f}</div></div>',
            unsafe_allow_html=True)
    with k3:
        card_c2 = "green" if total_pct >= 0 else "red"
        st.markdown(
            f'<div class="kpi-card {card_c2}"><div class="kpi-score-label">K/Z %</div>'
            f'<div style="font-size:1.2rem;font-weight:700;color:{pc};">{ps}{total_pct:.1f}%</div></div>',
            unsafe_allow_html=True)
    with k4:
        bc = "#00c48c" if best["pnl_pct"] >= 0 else "#e74c3c"
        bs = "+" if best["pnl_pct"] >= 0 else ""
        st.markdown(
            f'<div class="kpi-card green"><div class="kpi-score-label">EN İYİ</div>'
            f'<div style="font-size:1rem;font-weight:700;color:#e8edf3;">{best["ticker"].replace("-USD","")}</div>'
            f'<div style="color:{bc};font-size:0.8rem;">{bs}{best["pnl_pct"]:.1f}%</div></div>',
            unsafe_allow_html=True)
    with k5:
        wc = "#e74c3c" if worst["pnl_pct"] < 0 else "#00c48c"
        ws = "" if worst["pnl_pct"] < 0 else "+"
        st.markdown(
            f'<div class="kpi-card red"><div class="kpi-score-label">EN KÖTÜ</div>'
            f'<div style="font-size:1rem;font-weight:700;color:#e8edf3;">{worst["ticker"].replace("-USD","")}</div>'
            f'<div style="color:{wc};font-size:0.8rem;">{ws}{worst["pnl_pct"]:.1f}%</div></div>',
            unsafe_allow_html=True)
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                unsafe_allow_html=True)



def _render_asset_summary(positions, label, usd_try=32.0):
    """Varlık sınıfı KPI özet bar — tüm sekmeler için ortak."""
    if not positions:
        return
    rows = []
    for p in positions:
        shares   = float(p.get("shares", 0))
        avg      = float(p.get("avg_cost", 0))
        cur_usd  = float(p.get("current_price_usd", 0) or p.get("current_price", 0))
        currency = p.get("currency", "USD")
        avg_usd  = avg / usd_try if currency == "TRY" else avg
        if shares <= 0 or cur_usd <= 0:
            continue
        val = shares * cur_usd
        pnl = shares * (cur_usd - avg_usd)
        pct = (cur_usd - avg_usd) / avg_usd * 100 if avg_usd > 0 else 0
        rows.append({"t": p.get("ticker","?"), "val": val, "pnl": pnl, "pct": pct})
    if not rows:
        return
    tv = sum(r["val"] for r in rows)
    tp = sum(r["pnl"] for r in rows)
    tc = tv - tp
    tpct = tp / tc * 100 if tc > 0 else 0
    best  = max(rows, key=lambda x: x["pct"])
    worst = min(rows, key=lambda x: x["pct"])
    pc = "#00c48c" if tp >= 0 else "#e74c3c"
    ps = "+" if tp >= 0 else ""
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f'''<div class="kpi-card green">
            <div class="kpi-score-label">{label} DEĞERİ</div>
            <div style="font-size:1.2rem;font-weight:700;color:#e8edf3;">${tv:,.0f}</div>
        </div>''', unsafe_allow_html=True)
    with c2:
        cc = "green" if tp >= 0 else "red"
        st.markdown(f'''<div class="kpi-card {cc}">
            <div class="kpi-score-label">TOPLAM K/Z</div>
            <div style="font-size:1.2rem;font-weight:700;color:{pc};">{ps}${tp:,.0f}</div>
        </div>''', unsafe_allow_html=True)
    with c3:
        cc2 = "green" if tpct >= 0 else "red"
        st.markdown(f'''<div class="kpi-card {cc2}">
            <div class="kpi-score-label">K/Z %</div>
            <div style="font-size:1.2rem;font-weight:700;color:{pc};">{ps}{tpct:.1f}%</div>
        </div>''', unsafe_allow_html=True)
    with c4:
        bc = "#00c48c" if best["pct"] >= 0 else "#e74c3c"
        bs = "+" if best["pct"] >= 0 else ""
        bt = best["t"].replace("-USD","")
        st.markdown(f'''<div class="kpi-card green">
            <div class="kpi-score-label">EN İYİ</div>
            <div style="font-size:1rem;font-weight:700;color:#e8edf3;">{bt}</div>
            <div style="color:{bc};font-size:0.8rem;">{bs}{best["pct"]:.1f}%</div>
        </div>''', unsafe_allow_html=True)
    with c5:
        wc = "#e74c3c" if worst["pct"] < 0 else "#00c48c"
        ws = "" if worst["pct"] < 0 else "+"
        wt = worst["t"].replace("-USD","")
        st.markdown(f'''<div class="kpi-card red">
            <div class="kpi-score-label">EN KÖTÜ</div>
            <div style="font-size:1rem;font-weight:700;color:#e8edf3;">{wt}</div>
            <div style="color:{wc};font-size:0.8rem;">{ws}{worst["pct"]:.1f}%</div>
        </div>''', unsafe_allow_html=True)
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                unsafe_allow_html=True)



# TAB 2 — PORTFOLIO
# ─────────────────────────────────────────────────────────────────────────────
with tab_portfolio:

    # ── Varlık Sınıfı Alt Sekmeleri ──────────────────────────────────────────
    pt_us, pt_crypto, pt_commodity, pt_tefas = st.tabs([
        "🇺🇸 ABD Hisseler",
        "₿  Kripto",
        "🥇 Emtia",
        "🇹🇷 TEFAS",
    ])

    # ═══════════════════════════════════════════════════════════════════════
    # ABD HİSSELER — Mevcut özet ve korelasyon analizi
    # ═══════════════════════════════════════════════════════════════════════
    with pt_us:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.5rem;">🇺🇸 ABD HİSSE YÖNETİMİ</div>',
            unsafe_allow_html=True)

        _us_all = [p for p in load_portfolio()
                   if p.get("asset_class", "us_equity") == "us_equity"
                   and float(p.get("shares", 0)) > 0]

        if _us_all:
            import yfinance as _yf_us
            import time as _t_us
            _us_cache_key = "us_price_cache"
            _us_ts_key    = "us_price_cache_ts"
            _us_tk_key    = str(sorted([p["ticker"] for p in _us_all]))
            _us_cached    = st.session_state.get(_us_cache_key, {})
            _us_last_ts   = st.session_state.get(_us_ts_key, 0)

            if (_us_cached and
                (_t_us.time() - _us_last_ts) < 300 and
                _us_cached.get("_tk_key") == _us_tk_key):
                _us_price_map  = _us_cached["price_map"]
                _us_change_map = _us_cached["change_map"]
                _us_sector_map = _us_cached.get("sector_map", {})
            else:
                with st.spinner("ABD hisse fiyatları ve sektörler çekiliyor..."):
                    _us_price_map  = {}
                    _us_change_map = {}
                    _us_sector_map = {}
                    for _p in _us_all:
                        try:
                            # .info ile sektör + fiyat birlikte alınır
                            _info = _yf_us.Ticker(_p["ticker"]).info
                            _pr   = float(_info.get("currentPrice") or
                                          _info.get("regularMarketPrice") or 0)
                            _pv   = float(_info.get("previousClose") or _pr or 1)
                            if _pr <= 0:  # fallback
                                _fi = _yf_us.Ticker(_p["ticker"]).fast_info
                                _pr = float(getattr(_fi, "last_price",     0) or 0)
                                _pv = float(getattr(_fi, "previous_close", _pr) or _pr)
                            _ch = (_pr - _pv) / _pv * 100 if _pv > 0 else 0
                            if _pr > 0:
                                _us_price_map[_p["ticker"]]  = _pr
                                _us_change_map[_p["ticker"]] = round(_ch, 2)
                            # Sektör: yfinance öncelikli, DB fallback
                            _sec_yf = _info.get("sector") or _info.get("industry") or ""
                            _sec_db = _p.get("sector", "")
                            _bad    = {"", "Diğer", "Diger", "Other"}
                            if _sec_yf and _sec_yf not in _bad:
                                _us_sector_map[_p["ticker"]] = _sec_yf
                            elif _sec_db and _sec_db not in _bad:
                                _us_sector_map[_p["ticker"]] = _sec_db
                        except Exception:
                            # fast_info ile sadece fiyat al
                            try:
                                _fi = _yf_us.Ticker(_p["ticker"]).fast_info
                                _pr = float(getattr(_fi, "last_price",     0) or 0)
                                _pv = float(getattr(_fi, "previous_close", _pr) or _pr)
                                _ch = (_pr - _pv) / _pv * 100 if _pv > 0 else 0
                                if _pr > 0:
                                    _us_price_map[_p["ticker"]]  = _pr
                                    _us_change_map[_p["ticker"]] = round(_ch, 2)
                            except Exception:
                                pass
                    st.session_state[_us_cache_key] = {
                        "price_map":  _us_price_map,
                        "change_map": _us_change_map,
                        "sector_map": _us_sector_map,
                        "_tk_key":    _us_tk_key,
                    }
                    st.session_state[_us_ts_key] = _t_us.time()

            _us_enriched = []
            _us_rows     = []
            for _p in _us_all:
                _cur = _us_price_map.get(_p["ticker"], float(_p.get("avg_cost", 0)))
                _chg = _us_change_map.get(_p["ticker"], 0.0)
                _avg = float(_p.get("avg_cost", 0))
                _val = float(_p.get("shares", 0)) * _cur
                _pnl = (_cur - _avg) / _avg * 100 if _avg > 0 else 0
                _p2  = dict(_p)
                _p2["current_price_usd"] = _cur
                _p2["currency"] = "USD"
                _us_enriched.append(_p2)
                _us_rows.append({
                    "Ticker":  _p["ticker"],
                    "Adet":    f"{float(_p['shares']):.2f}",
                    "Maliyet": f"${_avg:,.2f}",
                    "Güncel":  f"${_cur:,.2f}",
                    "24s %":   f"{_chg:+.1f}%",
                    "Değer":   f"${_val:,.2f}",
                    "K/Z %":   f"{_pnl:+.1f}%",
                    "Sektör":  _us_sector_map.get(_p["ticker"]) or _p.get("sector") or "—",
                })

            st.session_state["enriched_portfolio"] = [
                {**p, "current_value": float(p.get("shares",0)) * _us_price_map.get(p["ticker"], float(p.get("avg_cost",0))),
                 "current_price": _us_price_map.get(p["ticker"], float(p.get("avg_cost",0)))}
                for p in _us_all
            ]

            _render_asset_summary(_us_enriched, "ABD HİSSE")

            # Nakit özet
            _nakit_ozet_usd = get_cash_accounts().get("usd", 0.0)
            if _nakit_ozet_usd > 0:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:1rem;background:var(--color-background-secondary);'
                    f'border-radius:6px;padding:0.4rem 0.8rem;margin-bottom:0.5rem;font-size:0.75rem;">'
                    f'<span style="color:#5a6a7a;">💵 ABD/USD Nakit:</span>'
                    f'<span style="font-weight:700;color:#00c48c;">{_nakit_ozet_usd:,.0f} $</span>'
                    f'</div>',
                    unsafe_allow_html=True)

            st.dataframe(_us_rows, use_container_width=True)

            with st.expander("➕ ABD Hisse Ekle"):
                _u1, _u2, _u3 = st.columns(3)
                with _u1:
                    _u_tk = st.text_input("Ticker", placeholder="AAPL, NVDA", key="u_tk").upper().strip()
                with _u2:
                    _u_sh = st.number_input("Adet", min_value=0.0, step=1.0, key="u_sh")
                with _u3:
                    _u_co = st.number_input("Maliyet ($)", min_value=0.0, step=0.01, key="u_co")
                _u_nt = st.text_input("Not", key="u_nt")
                if st.button("💾 Ekle", key="btn_add_us"):
                    if _u_tk and _u_sh > 0 and _u_co > 0:
                        _sec = "Diğer"
                        try:
                            _sec = _yf_us.Ticker(_u_tk).info.get("sector", "Diğer") or "Diğer"
                        except Exception:
                            pass
                        add_position(_u_tk, _u_sh, _u_co, _sec, _u_nt,
                                    deduct_from_cash=True, asset_class="us_equity", currency="USD")
                        st.success(f"✅ {_u_tk} eklendi!")
                        st.session_state.pop(_us_cache_key, None)
                        st.rerun()

            _del_u = st.selectbox("Sil:", ["—"] + [p["ticker"] for p in _us_all], key="del_us_sel")
            if _del_u != "—":
                if st.button(f"🗑 {_del_u} Sil", key="del_us_btn"):
                    from portfolio_manager import remove_position
                    remove_position(_del_u)
                    st.session_state.pop(_us_cache_key, None)
                    st.rerun()
        else:
            st.info("Henüz ABD hisse pozisyonu yok.")
            with st.expander("➕ ABD Hisse Ekle"):
                _u1b, _u2b, _u3b = st.columns(3)
                with _u1b:
                    _u_tkb = st.text_input("Ticker", placeholder="AAPL, NVDA", key="u_tk_b").upper().strip()
                with _u2b:
                    _u_shb = st.number_input("Adet", min_value=0.0, step=1.0, key="u_sh_b")
                with _u3b:
                    _u_cob = st.number_input("Maliyet ($)", min_value=0.0, step=0.01, key="u_co_b")
                if st.button("💾 Ekle", key="btn_add_us_b"):
                    if _u_tkb and _u_shb > 0 and _u_cob > 0:
                        add_position(_u_tkb, _u_shb, _u_cob, "Diğer", "",
                                    deduct_from_cash=True, asset_class="us_equity", currency="USD")
                        st.success(f"✅ {_u_tkb} eklendi!")
                        st.rerun()

        # ── ABD / USD Nakit ──────────────────────────────────────────────────
        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                    unsafe_allow_html=True)
        _bal_usd_now = get_cash_accounts().get("usd", 0.0)
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;font-weight:600;">💵 ABD / USD Nakit</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:#00c48c;">{_bal_usd_now:,.0f} $</div>',
            unsafe_allow_html=True)
        _ui1, _ui2, _ui3, _ui4 = st.columns([2,1,1,1])
        with _ui1:
            _usd_inp = st.number_input("Miktar", min_value=0.0, value=0.0,
                                       step=100.0, key="cash_us_final", label_visibility="collapsed")
        with _ui2:
            if st.button("➕ Ekle", key="btn_usd_add", use_container_width=True, help="Üstüne ekle"):
                if _usd_inp > 0:
                    add_to_cash_account("usd", _usd_inp)
                    st.success(f"✅ {_usd_inp:,.0f} $ eklendi!")
                    st.rerun()
        with _ui3:
            if st.button("✏️ Ayarla", key="btn_usd_set", use_container_width=True, help="Tam değere ayarla"):
                set_cash_account("usd", _usd_inp)
                st.success(f"✅ {_usd_inp:,.0f} $ olarak ayarlandı!")
                st.rerun()
        with _ui4:
            if st.button("🗑 Sıfırla", key="btn_usd_rst", use_container_width=True):
                set_cash_account("usd", 0.0)
                st.success("Sıfırlandı.")
                st.rerun()

    # ═══════════════════════════════════════════════════════════════════════
    # KRİPTO
    # ═══════════════════════════════════════════════════════════════════════
    with pt_crypto:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.5rem;">₿ KRİPTO VARLIK YÖNETİMİ</div>',
            unsafe_allow_html=True)

        _crypto_all = [p for p in load_portfolio() if p.get("asset_class") == "crypto"
                       and float(p.get("shares", 0)) > 0]

        if _crypto_all:
            from crypto_fetcher import fetch_crypto_price_universal
            _c_rows      = []
            _c_enriched  = []
            _c_not_found = []
            with st.spinner("Kripto fiyatları çekiliyor..."):
                for _cp in _crypto_all:
                    _pd = fetch_crypto_price_universal(_cp["ticker"])
                    if _pd.get("found") and _pd.get("price", 0) > 0:
                        _cur = float(_pd["price"])
                        _chg = float(_pd.get("change_24h", 0))
                        _src = _pd.get("source", "?")
                    else:
                        _cur = float(_cp.get("avg_cost", 0))
                        _chg = 0.0
                        _src = "—"
                        _c_not_found.append(_cp["ticker"])
                    _cp["current_price_usd"] = _cur
                    _cp["currency"] = "USD"
                    _c_enriched.append(_cp)
                    _avg = float(_cp.get("avg_cost", 0))
                    _val = _cp["shares"] * _cur
                    _pnl = (_cur - _avg) / _avg * 100 if _avg > 0 else 0
                    _fmt = ",.8f" if _cur < 0.01 else (",.4f" if _cur < 1 else ",.2f")
                    _c_rows.append({
                        "Coin":    _cp["ticker"].replace("-USD",""),
                        "Miktar":  f"{_cp['shares']:.4f}",
                        "Maliyet": f"${_avg:{_fmt}}",
                        "Güncel":  f"${_cur:{_fmt}}",
                        "24s %":   f"{_chg:+.1f}%",
                        "Değer":   f"${_val:,.2f}",
                        "K/Z %":   f"{_pnl:+.1f}%",
                        "Kaynak":  _src,
                    })

            if _c_not_found:
                st.warning(f"⚠️ Fiyat bulunamadı: **{', '.join(_c_not_found)}**")

            _render_asset_summary(_c_enriched, "KRİPTO")

            _nakit_ozet_crypto_usd = get_cash_accounts().get("crypto_usd", 0.0)
            if _nakit_ozet_crypto_usd > 0:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:1rem;background:var(--color-background-secondary);'
                    f'border-radius:6px;padding:0.4rem 0.8rem;margin-bottom:0.5rem;font-size:0.75rem;">'
                    f'<span style="color:#5a6a7a;">💵 Kripto Borsa Nakiti:</span>'
                    f'<span style="font-weight:700;color:#00c48c;">{_nakit_ozet_crypto_usd:,.0f} $</span>'
                    f'</div>',
                    unsafe_allow_html=True)

            st.dataframe(_c_rows, use_container_width=True)

            _del_c = st.selectbox("Sil:", ["—"] + [p["ticker"] for p in _crypto_all], key="del_crypto_sel2")
            if _del_c != "—":
                if st.button(f"🗑 {_del_c} Sil", key="del_crypto_btn2"):
                    from portfolio_manager import remove_position
                    remove_position(_del_c)
                    st.rerun()

        with st.expander("➕ Kripto Pozisyon Ekle"):
            _cc1, _cc2, _cc3 = st.columns(3)
            with _cc1:
                _c_ticker = st.text_input("Ticker", placeholder="BTC-USD, ETH-USD", key="c_ticker2")
                if _c_ticker and "-" not in _c_ticker.upper():
                    _c_ticker = f"{_c_ticker.upper()}-USD"
                else:
                    _c_ticker = _c_ticker.upper().strip()
            with _cc2:
                _c_shares = st.number_input("Miktar", min_value=0.0, step=0.0001, format="%.4f", key="c_shares2")
            with _cc3:
                _c_cost = st.number_input("Maliyet ($/adet)", min_value=0.0, step=0.01, key="c_cost2")
            _c_notes = st.text_input("Not", key="c_notes2")
            if st.button("💾 Kripto Ekle", key="btn_add_crypto2"):
                if _c_ticker and _c_shares > 0 and _c_cost > 0:
                    add_position(_c_ticker, _c_shares, _c_cost, "Kripto", _c_notes,
                                deduct_from_cash=True, asset_class="crypto", currency="USD")
                    st.success(f"✅ {_c_ticker} eklendi!")
                    st.rerun()

        if not _crypto_all:
            st.info("Henüz kripto pozisyon yok.")

        # ── Kripto Borsa Nakiti ───────────────────────────────────────────────
        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                    unsafe_allow_html=True)
        _bal_cr = get_cash_accounts().get("crypto_usd", 0.0)
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;font-weight:600;">₿ Kripto Borsa Nakiti (USD)</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:#00c48c;">{_bal_cr:,.0f} $</div>',
            unsafe_allow_html=True)
        st.caption("Binance, Coinbase vb. borsalardaki USD/USDT bakiyeniz")
        _ci1, _ci2, _ci3, _ci4 = st.columns([2,1,1,1])
        with _ci1:
            _cr_inp = st.number_input("Miktar", min_value=0.0, value=0.0,
                                      step=100.0, key="cash_cr_final", label_visibility="collapsed")
        with _ci2:
            if st.button("➕ Ekle", key="btn_cr_add", use_container_width=True, help="Üstüne ekle"):
                if _cr_inp > 0:
                    add_to_cash_account("crypto_usd", _cr_inp)
                    st.success(f"✅ {_cr_inp:,.0f} $ eklendi!")
                    st.rerun()
        with _ci3:
            if st.button("✏️ Ayarla", key="btn_cr_set", use_container_width=True, help="Tam değere ayarla"):
                set_cash_account("crypto_usd", _cr_inp)
                st.success(f"✅ {_cr_inp:,.0f} $ olarak ayarlandı!")
                st.rerun()
        with _ci4:
            if st.button("🗑 Sıfırla", key="btn_cr_rst", use_container_width=True):
                set_cash_account("crypto_usd", 0.0)
                st.success("Sıfırlandı.")
                st.rerun()

    # ═══════════════════════════════════════════════════════════════════════
    # EMTİA
    # ═══════════════════════════════════════════════════════════════════════
    with pt_commodity:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.5rem;">🥇 EMTİA VARLIK YÖNETİMİ</div>',
            unsafe_allow_html=True)
        st.caption("💡 Altın gram TL: ALTIN_GRAM_TRY | Gümüş gram TL: GUMUS_GRAM_TRY | USD bazlı: GC=F, GLD, IAU, SI=F")

        _comm_all = [p for p in load_portfolio() if p.get("asset_class") == "commodity"
                     and float(p.get("shares", 0)) > 0]

        _GRAM = {
            "ALTIN_GRAM_TRY": {"src": "GC=F", "div": 31.1035},
            "GUMUS_GRAM_TRY": {"src": "SI=F", "div": 31.1035},
            "XAUTRY=X":       {"src": "GC=F", "div": 31.1035},
            "XAGTRY=X":       {"src": "SI=F", "div": 31.1035},
        }

        if _comm_all:
            import yfinance as _yf_c2
            _usd_try_c = 32.0
            try:
                _usd_try_c = float(_yf_c2.Ticker("USDTRY=X").fast_info.last_price or 32.0)
            except Exception:
                pass

            _e_rows     = []
            _e_enriched = []
            for _ep in _comm_all:
                _tk   = _ep["ticker"]
                _gram = _GRAM.get(_tk)
                _avg  = float(_ep.get("avg_cost", 0))

                if _gram:
                    try:
                        _fi     = _yf_c2.Ticker(_gram["src"]).fast_info
                        _usd_oz = float(getattr(_fi, "last_price", 0) or 0)
                        _cur_tl = _usd_oz * _usd_try_c / _gram["div"]
                    except Exception:
                        _cur_tl = _avg
                    _cur_usd = _cur_tl / _usd_try_c
                    _ep["current_price_usd"] = _cur_usd
                    _ep["currency"] = "TRY"
                    _val_usd = _ep["shares"] * _cur_usd
                    _pnl     = (_cur_tl - _avg) / _avg * 100 if _avg > 0 else 0
                    _e_rows.append({
                        "Varlık":  _tk.replace("_GRAM_TRY","").replace("=X",""),
                        "Gram":    f"{_ep['shares']:.2f}",
                        "Maliyet": f"{_avg:.2f} TL/g",
                        "Güncel":  f"{_cur_tl:.2f} TL/g",
                        "Değer":   f"${_val_usd:,.2f} ({_ep['shares']*_cur_tl:,.0f} TL)",
                        "K/Z %":   f"{_pnl:+.1f}%",
                    })
                else:
                    try:
                        _fi  = _yf_c2.Ticker(_tk).fast_info
                        _cur = float(getattr(_fi, "last_price", 0) or _avg)
                    except Exception:
                        _cur = _avg
                    _ep["current_price_usd"] = _cur
                    _ep["currency"] = "USD"
                    _val = _ep["shares"] * _cur
                    _pnl = (_cur - _avg) / _avg * 100 if _avg > 0 else 0
                    _e_rows.append({
                        "Varlık":  _tk,
                        "Adet":    f"{_ep['shares']:.4f}",
                        "Maliyet": f"${_avg:.2f}",
                        "Güncel":  f"${_cur:.2f}",
                        "Değer":   f"${_val:,.2f}",
                        "K/Z %":   f"{_pnl:+.1f}%",
                    })
                _e_enriched.append(_ep)

            _render_asset_summary(_e_enriched, "EMTİA", usd_try=_usd_try_c)

            _nakit_ozet_commodity_usd = get_cash_accounts().get("commodity_usd", 0.0)
            if _nakit_ozet_commodity_usd > 0:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:1rem;background:var(--color-background-secondary);'
                    f'border-radius:6px;padding:0.4rem 0.8rem;margin-bottom:0.5rem;font-size:0.75rem;">'
                    f'<span style="color:#5a6a7a;">💵 Emtia Hesap Nakiti:</span>'
                    f'<span style="font-weight:700;color:#00c48c;">{_nakit_ozet_commodity_usd:,.0f} $</span>'
                    f'</div>',
                    unsafe_allow_html=True)

            st.dataframe(_e_rows, use_container_width=True)

            _del_e = st.selectbox("Sil:", ["—"] + [p["ticker"] for p in _comm_all], key="del_comm_sel2")
            if _del_e != "—":
                if st.button(f"🗑 {_del_e} Sil", key="del_comm_btn2"):
                    from portfolio_manager import remove_position
                    remove_position(_del_e)
                    st.rerun()

        with st.expander("➕ Emtia Pozisyon Ekle"):
            _etype = st.radio("Tür:", ["🥇 Altın Gram (TL)", "🥈 Gümüş Gram (TL)", "💵 USD Bazlı"],
                             horizontal=True, key="e_type2")
            _EMAP = {
                "🥇 Altın Gram (TL)": {"ticker": "ALTIN_GRAM_TRY", "label": "TL/gram", "currency": "TRY"},
                "🥈 Gümüş Gram (TL)": {"ticker": "GUMUS_GRAM_TRY", "label": "TL/gram", "currency": "TRY"},
                "💵 USD Bazlı":        {"ticker": "",               "label": "$",       "currency": "USD"},
            }
            _ecfg = _EMAP[_etype]
            _em1, _em2, _em3 = st.columns(3)
            with _em1:
                if _ecfg["ticker"]:
                    st.text_input("Kaynak", value=_ecfg["ticker"], disabled=True, key="e_tk_disp2")
                    _e_tk2 = _ecfg["ticker"]
                else:
                    _e_tk2 = st.text_input("Ticker", placeholder="GC=F, GLD, IAU, SI=F", key="e_tk2").upper().strip()
            with _em2:
                _unit2 = "gram" if _ecfg["currency"] == "TRY" else "adet"
                _e_sh2 = st.number_input(f"Miktar ({_unit2})", min_value=0.0, step=0.01, key="e_sh2")
            with _em3:
                _e_co2 = st.number_input(f"Maliyet ({_ecfg['label']})", min_value=0.0, step=0.01, key="e_co2")
            _e_nt2 = st.text_input("Not", key="e_nt2")
            if st.button("💾 Ekle", key="btn_add_comm2"):
                if _e_tk2 and _e_sh2 > 0 and _e_co2 > 0:
                    add_position(_e_tk2, _e_sh2, _e_co2, "Emtia", _e_nt2,
                                deduct_from_cash=True,
                                asset_class="commodity", currency=_ecfg["currency"])
                    st.success(f"✅ Eklendi!")
                    st.rerun()

        if not _comm_all:
            st.info("Henüz emtia pozisyon yok.")

        # ── Emtia Hesap Nakiti ────────────────────────────────────────────────
        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                    unsafe_allow_html=True)
        _bal_em = get_cash_accounts().get("commodity_usd", 0.0)
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;font-weight:600;">🥇 Emtia Hesap Nakiti (USD)</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:#00c48c;">{_bal_em:,.0f} $</div>',
            unsafe_allow_html=True)
        _ei1, _ei2, _ei3, _ei4 = st.columns([2,1,1,1])
        with _ei1:
            _em_inp = st.number_input("Miktar", min_value=0.0, value=0.0,
                                      step=100.0, key="cash_em_final", label_visibility="collapsed")
        with _ei2:
            if st.button("➕ Ekle", key="btn_em_add", use_container_width=True, help="Üstüne ekle"):
                if _em_inp > 0:
                    add_to_cash_account("commodity_usd", _em_inp)
                    st.success(f"✅ {_em_inp:,.0f} $ eklendi!")
                    st.rerun()
        with _ei3:
            if st.button("✏️ Ayarla", key="btn_em_set", use_container_width=True, help="Tam değere ayarla"):
                set_cash_account("commodity_usd", _em_inp)
                st.success(f"✅ {_em_inp:,.0f} $ olarak ayarlandı!")
                st.rerun()
        with _ei4:
            if st.button("🗑 Sıfırla", key="btn_em_rst", use_container_width=True):
                set_cash_account("commodity_usd", 0.0)
                st.success("Sıfırlandı.")
                st.rerun()

    # ═══════════════════════════════════════════════════════════════════════
    # TEFAS
    # ═══════════════════════════════════════════════════════════════════════
    with pt_tefas:
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.12em;margin-bottom:0.5rem;">🇹🇷 TEFAS FON YÖNETİMİ</div>',
            unsafe_allow_html=True)
        st.caption("💡 Fon kodunu gir (örn: IIH, AEY, YAC). Fiyat TEFAS'tan otomatik çekilir.")

        _tefas_all = [p for p in load_portfolio() if p.get("asset_class") == "tefas"
                      and float(p.get("shares", 0)) > 0]

        if _tefas_all:
            import yfinance as _yf_t2
            _usd_try_t = 32.0
            try:
                _usd_try_t = float(_yf_t2.Ticker("USDTRY=X").fast_info.last_price or 32.0)
            except Exception:
                pass

            _t_rows    = []
            _t_enriched= []
            from turkey_fetcher import fetch_tefas_fund
            for _tp in _tefas_all:
                _avg_tl = float(_tp.get("avg_cost", 0))
                try:
                    _fd     = fetch_tefas_fund(_tp["ticker"])
                    _cur_tl = float(_fd.get("price", _avg_tl)) if _fd else _avg_tl
                    _r1m    = _fd.get("ret_1m", 0) if _fd else 0
                    _r1y    = _fd.get("ret_1y", 0) if _fd else 0
                except Exception:
                    _cur_tl, _r1m, _r1y = _avg_tl, 0, 0

                _cur_usd = _cur_tl / _usd_try_t
                _tp["current_price_usd"] = _cur_usd
                _tp["currency"] = "TRY"
                _val_tl  = _tp["shares"] * _cur_tl
                _val_usd = _val_tl / _usd_try_t
                _pnl     = (_cur_tl - _avg_tl) / _avg_tl * 100 if _avg_tl > 0 else 0
                _t_rows.append({
                    "Fon":     _tp["ticker"],
                    "Pay":     f"{_tp['shares']:,.0f}",
                    "Maliyet": f"{_avg_tl:.4f} TL",
                    "Güncel":  f"{_cur_tl:.4f} TL",
                    "Toplam":  f"{_val_tl:,.0f} TL",
                    "USD":     f"${_val_usd:,.0f}",
                    "K/Z %":   f"{_pnl:+.1f}%",
                    "1A %":    f"{_r1m:+.1f}%",
                    "1Y %":    f"{_r1y:+.1f}%",
                    "Not":     _tp.get("notes",""),
                })
                _t_enriched.append(_tp)

            _render_asset_summary(_t_enriched, "TEFAS", usd_try=_usd_try_t)

            _nakit_ozet_tefas_try = get_cash_accounts().get("tefas_try", 0.0)
            if _nakit_ozet_tefas_try > 0:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:1rem;background:var(--color-background-secondary);'
                    f'border-radius:6px;padding:0.4rem 0.8rem;margin-bottom:0.5rem;font-size:0.75rem;">'
                    f'<span style="color:#5a6a7a;">🇹🇷 TEFAS/TL Nakit:</span>'
                    f'<span style="font-weight:700;color:#00c48c;">{_nakit_ozet_tefas_try:,.0f} TL</span>'
                    f'</div>',
                    unsafe_allow_html=True)

            st.dataframe(_t_rows, use_container_width=True)

            _ttl = sum(_tp["shares"] * float(_t_rows[i]["Güncel"].replace(" TL","").replace(",",""))
                      for i, _tp in enumerate(_tefas_all))
            st.caption(f"💼 Toplam TEFAS: {_ttl:,.0f} TL = ${_ttl/_usd_try_t:,.0f} (1 USD = {_usd_try_t:.2f} TL)")

            _del_t = st.selectbox("Sil:", ["—"] + [p["ticker"] for p in _tefas_all], key="del_tefas_sel2")
            if _del_t != "—":
                if st.button(f"🗑 {_del_t} Sil", key="del_tefas_btn2"):
                    from portfolio_manager import remove_position
                    remove_position(_del_t)
                    st.rerun()

        with st.expander("➕ TEFAS Fon Ekle"):
            _tf1, _tf2, _tf3 = st.columns(3)
            with _tf1:
                _t_code2 = st.text_input("Fon Kodu", placeholder="IIH, AEY, YAC", key="t_code2").upper().strip()
            with _tf2:
                _t_sh2 = st.number_input("Pay Adedi", min_value=0.0, step=1.0, key="t_sh2")
            with _tf3:
                _t_co2 = st.number_input("Maliyet (TL/pay)", min_value=0.0, step=0.0001, format="%.4f", key="t_co2")
            _t_nt2 = st.text_input("Not", placeholder="Örn: Hisse senedi fonu", key="t_nt2")
            if st.button("💾 Fon Ekle", key="btn_add_tefas2"):
                if _t_code2 and _t_sh2 > 0 and _t_co2 > 0:
                    from turkey_fetcher import fetch_tefas_fund
                    _fd_chk = fetch_tefas_fund(_t_code2)
                    if _fd_chk:
                        add_position(_t_code2, _t_sh2, _t_co2, "TEFAS", _t_nt2,
                                    deduct_from_cash=True, asset_class="tefas", currency="TRY")
                        st.success(f"✅ {_t_code2} eklendi! Fiyat: {_fd_chk.get('price',0):.4f} TL")
                        st.rerun()
                    else:
                        st.warning(f"⚠️ '{_t_code2}' TEFAS'ta doğrulanamadı.")
                        if st.button("Yine de ekle", key="btn_force_tefas2"):
                            add_position(_t_code2, _t_sh2, _t_co2, "TEFAS", _t_nt2,
                                        deduct_from_cash=True, asset_class="tefas", currency="TRY")
                            st.success(f"✅ {_t_code2} eklendi!")
                            st.rerun()

        if not _tefas_all:
            st.info("Henüz TEFAS fonu yok.")

        # ── TEFAS / TL Nakit ─────────────────────────────────────────────────
        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                    unsafe_allow_html=True)
        _bal_tf = get_cash_accounts().get("tefas_try", 0.0)
        st.markdown(
            f'<div style="font-size:0.65rem;color:#5a6a7a;font-weight:600;">🇹🇷 TEFAS / TL Nakit</div>'
            f'<div style="font-size:1.1rem;font-weight:700;color:#00c48c;">{_bal_tf:,.0f} TL</div>',
            unsafe_allow_html=True)
        st.caption("Borsada veya bankada bekleyen TL birikiminiz")
        _ti1, _ti2, _ti3, _ti4 = st.columns([2,1,1,1])
        with _ti1:
            _tf_inp = st.number_input("Miktar (TL)", min_value=0.0, value=0.0,
                                      step=1000.0, key="cash_tf_final", label_visibility="collapsed")
        with _ti2:
            if st.button("➕ Ekle", key="btn_tf_add", use_container_width=True, help="Üstüne ekle"):
                if _tf_inp > 0:
                    add_to_cash_account("tefas_try", _tf_inp)
                    st.success(f"✅ {_tf_inp:,.0f} TL eklendi!")
                    st.rerun()
        with _ti3:
            if st.button("✏️ Ayarla", key="btn_tf_set", use_container_width=True, help="Tam değere ayarla"):
                set_cash_account("tefas_try", _tf_inp)
                st.success(f"✅ {_tf_inp:,.0f} TL olarak ayarlandı!")
                st.rerun()
        with _ti4:
            if st.button("🗑 Sıfırla", key="btn_tf_rst", use_container_width=True):
                set_cash_account("tefas_try", 0.0)
                st.success("Sıfırlandı.")
                st.rerun()


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

    # ── STRATEJİ ARŞİVİ ──────────────────────────────────────────────────
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1.5rem 0;">', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:0.8rem;">🧭 STRATEJİ ARŞİVİ</div>',
        unsafe_allow_html=True,
    )

    from analysis_memory     import get_strategy_history
    from strategy_engine     import generate_strategy_html
    from weekly_report_html  import generate_weekly_html  # PDF export için

    _strat_history = get_strategy_history(limit=10)

    if not _strat_history:
        st.info("Henüz arşivlenmiş strateji yok. Strateji sekmesinden 'Strateji Üret' butonuna bas.")
    else:
        for _shi, _sh in enumerate(_strat_history):
            _sh_id   = _sh.get("id", "")
            _sh_date = _sh.get("date", "")
            _sh_time = _sh.get("generated_at", "")[:16].replace("T", " ")
            _sh_pval = _sh.get("portfolio_value", 0)
            _sh_cash = _sh.get("cash", 0)
            _sh_summ = _sh.get("summary", "")[:100]
            _sh_strat = _sh.get("strategy", {})

            # Aksiyon özeti — kaç sat, kaç al, kaç bekle
            _aks      = _sh_strat.get("aksiyonlar", {})
            _n_sat    = len(_aks.get("sat_azalt", []))
            _n_al     = len(_aks.get("al_arttir", []))
            _n_bekle  = len(_aks.get("bekle_izle", []))

            with st.expander(
                f"🧭  {_sh_date}  ·  {_sh_time}  ·  "
                f"Portföy ${_sh_pval:,.0f}  ·  "
                f"🔴{_n_sat} Sat  🟢{_n_al} Al  🟡{_n_bekle} Bekle",
                expanded=False,
            ):
                # Özet
                if _sh_summ:
                    st.markdown(
                        f'<div style="font-size:0.78rem;color:var(--color-text-secondary);'
                        f'background:var(--color-background-secondary);'
                        f'border-left:3px solid #4fc3f7;border-radius:0 8px 8px 0;'
                        f'padding:0.6rem 1rem;margin-bottom:0.8rem;">'
                        f'{_sh_summ}</div>',
                        unsafe_allow_html=True,
                    )

                # Aksiyon kartları — kompakt 3 sütun
                if _aks:
                    _sc1, _sc2, _sc3 = st.columns(3)
                    with _sc1:
                        st.markdown('<div style="font-size:0.65rem;color:#e74c3c;font-weight:600;margin-bottom:4px;">📉 SAT / AZALT</div>', unsafe_allow_html=True)
                        for _it in _aks.get("sat_azalt", []):
                            st.markdown(
                                f'<div style="font-size:0.72rem;padding:4px 0;'
                                f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                                f'<b>{_it.get("ticker","")}</b> '
                                f'<span style="color:#e74c3c;">%{_it.get("miktar_pct",0)} azalt</span><br>'
                                f'<span style="color:var(--color-text-tertiary);font-size:0.65rem;">'
                                f'{_it.get("neden","")[:60]}</span></div>',
                                unsafe_allow_html=True,
                            )
                    with _sc2:
                        st.markdown('<div style="font-size:0.65rem;color:#00c48c;font-weight:600;margin-bottom:4px;">📈 AL / ARTIR</div>', unsafe_allow_html=True)
                        for _it in _aks.get("al_arttir", []):
                            st.markdown(
                                f'<div style="font-size:0.72rem;padding:4px 0;'
                                f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                                f'<b>{_it.get("ticker","")}</b> '
                                f'<span style="color:#00c48c;">%{_it.get("nakit_pct",0)} nakit</span><br>'
                                f'<span style="color:var(--color-text-tertiary);font-size:0.65rem;">'
                                f'{_it.get("neden","")[:60]}</span></div>',
                                unsafe_allow_html=True,
                            )
                    with _sc3:
                        st.markdown('<div style="font-size:0.65rem;color:#ffb300;font-weight:600;margin-bottom:4px;">⏳ BEKLE / KOŞULLU</div>', unsafe_allow_html=True)
                        for _it in _aks.get("bekle_izle", []):
                            st.markdown(
                                f'<div style="font-size:0.72rem;padding:4px 0;'
                                f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                                f'<b>{_it.get("ticker","")}</b> '
                                f'<span style="color:#ffb300;">{_it.get("islem","")}</span><br>'
                                f'<span style="color:var(--color-text-tertiary);font-size:0.65rem;">'
                                f'{_it.get("kosul","")[:60]}</span></div>',
                                unsafe_allow_html=True,
                            )

                # PDF download + Sil butonu
                _fake_result = {"success": True, "strategy": _sh_strat, "generated_at": _sh.get("generated_at", "")}
                _sh_html     = generate_strategy_html(_fake_result, _sh_pval, _sh_cash)

                _dl_col, _del_col = st.columns([3, 1])
                with _dl_col:
                    st.download_button(
                        label="📄 HTML İndir (PDF için Yazdır)",
                        data=_sh_html.encode("utf-8"),
                        file_name=f"strateji_{_sh_id}.html",
                        mime="text/html",
                        key=f"mem_dl_strat_{_shi}",
                        use_container_width=True,
                    )
                with _del_col:
                    if st.button("🗑 Sil", key=f"del_btn_{_shi}", use_container_width=True):
                        st.session_state[f"del_confirm_{_shi}"] = True

                # Onay — expander içinde, kolonların dışında
                if st.session_state.get(f"del_confirm_{_shi}"):
                    st.warning(f"**{_sh_id}** kaydını silmek istediğine emin misin?")
                    _yes, _no, _ = st.columns([1, 1, 3])
                    with _yes:
                        if st.button("✅ Evet Sil", key=f"del_yes_{_shi}", use_container_width=True):
                            from analysis_memory import delete_strategy_from_archive
                            # Önce ID ile dene, yoksa index ile sil
                            _del_key_val = _sh_id if _sh_id else str(_shi)
                            ok_del = delete_strategy_from_archive(_del_key_val)
                            if not ok_del:
                                # Fallback: generated_at ile dene
                                ok_del = delete_strategy_from_archive(_sh.get("generated_at", "")[:16])
                            st.session_state[f"del_confirm_{_shi}"] = False
                            st.session_state["strat_archive_cache"] = None
                            if ok_del:
                                st.success("Silindi!")
                            else:
                                st.error("Silinemedi — ID bulunamadı.")
                            st.rerun()
                    with _no:
                        if st.button("❌ İptal", key=f"del_no_{_shi}", use_container_width=True):
                            st.session_state[f"del_confirm_{_shi}"] = False
                            st.rerun()

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

        for _wri, _wr in enumerate(_wr_list):
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

                # ── PDF Download + Sil butonu ─────────────────────────────
                st.markdown('<div style="margin-top:0.8rem;"></div>', unsafe_allow_html=True)
                _html_content = generate_weekly_html(_wr)
                _wr_dl_col, _wr_del_col = st.columns([3, 1])
                with _wr_dl_col:
                    st.download_button(
                        label="📄 HTML Raporu İndir (PDF için tarayıcıdan Yazdır)",
                        data=_html_content.encode("utf-8"),
                        file_name=f"rapor_{_wr_id}.html",
                        mime="text/html",
                        key=f"dl_wr_{_wri}",
                        use_container_width=True,
                    )
                with _wr_del_col:
                    if st.button("🗑 Sil", key=f"del_wr_btn_{_wri}", use_container_width=True):
                        st.session_state[f"del_wr_confirm_{_wri}"] = True

                if st.session_state.get(f"del_wr_confirm_{_wri}"):
                    st.warning(f"**{_wr_id}** raporunu silmek istediğine emin misin?")
                    _wr_y, _wr_n, _ = st.columns([1, 1, 3])
                    with _wr_y:
                        if st.button("✅ Evet Sil", key=f"del_wr_yes_{_wri}", use_container_width=True):
                            from analysis_memory import delete_weekly_report
                            ok_del = delete_weekly_report(_wr_id)
                            st.session_state[f"del_wr_confirm_{_wri}"] = False
                            st.session_state["wr_cache"] = None
                            st.success("Silindi!") if ok_del else st.error("Silinemedi.")
                            st.rerun()
                    with _wr_n:
                        if st.button("❌ İptal", key=f"del_wr_no_{_wri}", use_container_width=True):
                            st.session_state[f"del_wr_confirm_{_wri}"] = False
                            st.rerun()

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
            radar_min_score = st.slider("🎯 Min Radar Puanı", 40, 90, 50)
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
            st.warning(
                f"📭 Belirlenen kriterlere uyan fırsat bulunamadı.\n\n"
                f"**Olası nedenler:**\n"
                f"- Haber kaynakları şu an yeterli sinyal üretmiyor (piyasa sakin olabilir)\n"
                f"- Min puan eşiği ({radar_min_score}) çok yüksek — sola kaydır\n"
                f"- Haber penceresi ({radar_hours} saat) çok dar — genişlet\n\n"
                f"Slider'ı 45'e indirip tekrar dene."
            )
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

            # Portföydeki ticker'ları al — radar'da özel etiket için
            _radar_port_tickers = {p["ticker"] for p in load_portfolio()}

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

                # Portföyde var mı? Varsa aksiyonu "Ağırlık Artır" yap
                _in_portfolio = ticker in _radar_port_tickers
                if _in_portfolio:
                    tavsiye = "Ağırlık Artır"
                    if pos_rec:
                        pos_rec = {**pos_rec, "action": "Ağırlık Artır",
                                   "rationale": pos_rec.get("rationale", "") + " | Portföyde mevcut"}

                # Sentiment skoru
                try:
                    from sentiment_analyzer import score_articles, format_sentiment_badge
                    _sent_result = score_articles(articles)
                    _sent_score  = _sent_result["avg_score"]
                    _sent_label  = _sent_result["label"]
                    _sent_color  = _sent_result["color"]
                    _sent_badge  = format_sentiment_badge(_sent_score)
                except Exception:
                    _sent_score, _sent_label, _sent_color, _sent_badge = 0.0, "—", "#8a9ab0", ""

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
                    f"{'💼 ' if _in_portfolio else '🎯 '}{ticker}"
                    f"{'  ✅ Portföyde' if _in_portfolio else ''}  —  Radar: {radar_score}  |  "
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
                    if _sent_badge:
                        _extras.append(f"📰 Haber Sentimenti: {_sent_label} ({_sent_score:+.2f})")
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
                from datetime import datetime as _dt_radar
                csv_radar = df_radar.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Radar Sonuçlarını İndir (CSV)",
                    data=csv_radar,
                    file_name=f"radar_{_dt_radar.now().strftime('%Y%m%d_%H%M')}.csv",
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
# ─── Makro Analiz HTML Raporu ve Arşiv ───────────────────────────────────────

def _generate_macro_html(analysis_text: str, macro_data: dict,
                          regime: dict, generated_at: str) -> str:
    """Makro analizi güzel bir HTML raporuna dönüştür."""
    import re
    # Markdown başlıklarını HTML'e çevir
    html_body = analysis_text
    html_body = re.sub(r'^## (.+)$', r'<h2></h2>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^### (.+)$', r'<h3></h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'\*\*(.+?)\*\*', r'<strong></strong>', html_body)
    html_body = re.sub(r'\*(.+?)\*', r'<em></em>', html_body)
    html_body = re.sub(r'^- (.+)$', r'<li></li>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'(<li>[^<]*</li>)+', lambda m: '<ul>'+m.group(0)+'</ul>', html_body)
    html_body = html_body.replace('\n', '<br>')

    regime_label = regime.get("label", "")
    regime_color = regime.get("color", "#5a6a7a")

    # Makro gösterge tablosu
    table_rows = ""
    for key, ind in macro_data.items():
        try:
            sig_color = {"red": "#e74c3c", "amber": "#ffb300",
                         "green": "#00c48c", "neutral": "#8a9ab0"}.get(
                getattr(ind, "signal", "neutral"), "#8a9ab0")
            table_rows += (
                f'<tr><td style="color:#b0bec5;">{getattr(ind,"label",key)}</td>'
                f'<td style="font-weight:600;">{getattr(ind,"value",0):.2f} {getattr(ind,"unit","")}</td>'
                f'<td style="color:{sig_color};">{getattr(ind,"change_pct",0):+.2f}%</td>'
                f'<td style="font-size:0.8rem;color:#8a9ab0;">{getattr(ind,"note","")[:60]}</td></tr>'
            )
        except Exception:
            pass

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Makro Analiz — {generated_at}</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:#0d1117; color:#e8edf3; padding:2rem; line-height:1.7; }}
  .container {{ max-width:860px; margin:0 auto; }}
  h1 {{ font-size:1.4rem; color:#4fc3f7; margin-bottom:0.2rem; }}
  h2 {{ font-size:1.05rem; color:#4fc3f7; margin:1.4rem 0 0.5rem;
        border-left:3px solid #4fc3f7; padding-left:0.6rem; }}
  h3 {{ font-size:0.95rem; color:#b0bec5; margin:0.8rem 0 0.3rem; }}
  p, li {{ font-size:0.88rem; color:#c8d4e0; margin-bottom:0.4rem; }}
  ul {{ margin-left:1.2rem; margin-bottom:0.6rem; }}
  strong {{ color:#e8edf3; }}
  .regime-badge {{ display:inline-block; padding:4px 14px; border-radius:14px;
                   font-weight:700; font-size:0.8rem;
                   background:{regime_color}22; color:{regime_color};
                   border:1px solid {regime_color}; }}
  .meta {{ color:#5a6a7a; font-size:0.78rem; margin-bottom:1.5rem; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:1.2rem; }}
  th {{ background:#1a2332; color:#8a9ab0; text-align:left; padding:6px 10px;
        font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; }}
  td {{ padding:6px 10px; border-bottom:1px solid #1e2833; }}
  .section {{ background:#111927; border-radius:8px; padding:1.2rem 1.5rem;
              margin-bottom:1.2rem; border:0.5px solid #1e2833; }}
  @media print {{ body {{ background:#fff; color:#000; }}
                  .section {{ border:1px solid #ccc; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>🌍 Makro Analiz Raporu</h1>
  <div class="meta">
    Üretildi: {generated_at} &nbsp;|&nbsp;
    Rejim: <span class="regime-badge">{regime_label}</span>
  </div>

  <div class="section">
    <h2>📊 Makro Göstergeler</h2>
    <table>
      <thead><tr><th>Gösterge</th><th>Değer</th><th>Değişim</th><th>Not</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <div class="section">
    {html_body}
  </div>

  <div style="text-align:center;color:#2a3a4a;font-size:0.72rem;margin-top:2rem;">
    AI Makro Analist — {generated_at}
  </div>
</div>
</body>
</html>"""


def _save_macro_analysis_to_archive(analysis_text: str, macro_data: dict,
                                     regime: dict, generated_at: str) -> bool:
    """Makro analizini JSON arşivine ekle (GitHub veya lokal)."""
    import json, base64, requests as _req
    ARCHIVE_FILE = "macro_analysis_archive.json"

    entry = {
        "generated_at":  generated_at,
        "regime":        regime.get("regime", ""),
        "regime_label":  regime.get("label", ""),
        "analysis_text": analysis_text,
        "key_metrics": {
            k: {"value": getattr(v,"value",0), "change_pct": getattr(v,"change_pct",0)}
            for k, v in (macro_data or {}).items()
        },
    }

    # Lokal yaz
    try:
        try:
            with open(ARCHIVE_FILE) as f:
                archive = json.load(f)
        except Exception:
            archive = []
        archive.append(entry)
        archive = archive[-30:]  # Son 30 analiz
        with open(ARCHIVE_FILE, "w") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # GitHub'a yaz (varsa)
    try:
        from portfolio_manager import _get_github_config
        token, repo = _get_github_config()
        if token and repo:
            url  = f"https://api.github.com/repos/{repo}/contents/{ARCHIVE_FILE}"
            hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            try:
                existing = _req.get(url, headers=hdrs, timeout=8).json()
                sha = existing.get("sha", "")
                old_content = json.loads(base64.b64decode(existing.get("content","e30=")).decode())
                if isinstance(old_content, list):
                    old_content.append(entry)
                    old_content = old_content[-30:]
                else:
                    old_content = [entry]
            except Exception:
                sha = ""
                old_content = [entry]

            payload = {
                "message": f"Macro analysis: {generated_at}",
                "content": base64.b64encode(
                    json.dumps(old_content, ensure_ascii=False, indent=2).encode()
                ).decode(),
            }
            if sha:
                payload["sha"] = sha
            _req.put(url, headers=hdrs, json=payload, timeout=15)
            return True
    except Exception:
        pass
    return True  # Lokal kayıt başarılıysa True


def _load_macro_analysis_archive() -> list:
    """Makro analiz arşivini yükle."""
    import json, base64, requests as _req
    ARCHIVE_FILE = "macro_analysis_archive.json"

    # GitHub'dan dene
    try:
        from portfolio_manager import _get_github_config
        token, repo = _get_github_config()
        if token and repo:
            url  = f"https://api.github.com/repos/{repo}/contents/{ARCHIVE_FILE}"
            hdrs = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            resp = _req.get(url, headers=hdrs, timeout=8)
            if resp.status_code == 200:
                data = json.loads(base64.b64decode(resp.json()["content"]).decode())
                if isinstance(data, list):
                    return data
    except Exception:
        pass

    # Lokal fallback
    try:
        with open(ARCHIVE_FILE) as f:
            return json.load(f)
    except Exception:
        return []



# TAB 7 — MAKRO GÖSTERGE PANELİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_macro:
    from macro_dashboard import (
        fetch_macro_data, compute_market_regime, build_claude_macro_context,
        get_defensive_context_for_claude, get_regime_stock_context,
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
            ("fear",      "Korku & Volatilite", ["VIX", "YIELD_CURVE", "OVX", "MOVE_PROXY"]),
            ("rates",     "Faiz Ortamı",        ["TNX", "IRX", "TLT", "FED_WATCH"]),
            ("fx_comm",   "Dolar & Emtia",      ["DXY", "GOLD", "OIL", "COPPER", "USDJPY"]),
            ("market",    "Piyasa & Likidite",  ["SPX", "NDX", "LIQUIDITY", "CREDIT_SPREAD"]),
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

        _mc1, _mc2 = st.columns([3, 1])
        with _mc1:
            _run_macro_claude = st.button(
                "🧠 Claude ile Makroyu Yorumla + Hisse Öner",
                key="btn_macro_claude", use_container_width=True, type="primary"
            )
        with _mc2:
            if st.session_state.get("macro_claude_analysis"):
                if st.button("🔄 Sil / Yenile", key="btn_macro_clear", use_container_width=True):
                    st.session_state.pop("macro_claude_analysis", None)
                    st.rerun()

        if _run_macro_claude:
            _macro_ctx    = build_claude_macro_context(_macro_data, _macro_regime)
            _regime_code  = _macro_regime.get("regime", "CAUTION")
            # VIX ve bakır verisini makro datadan çek — rejim kararını güçlendir
            try:
                _vix_val_ctx  = float(getattr(_macro_data.get("vix"),  "value", 20.0) or 20.0)
                _cu_chg_ctx   = float(getattr(_macro_data.get("copper"), "change_pct", 0.0) or 0.0)
            except Exception:
                _vix_val_ctx, _cu_chg_ctx = 20.0, 0.0
            _def_context  = get_regime_stock_context(
                regime=_regime_code,
                vix=_vix_val_ctx,
                copper_chg=_cu_chg_ctx,
            )
            _api_key      = os.getenv("ANTHROPIC_API_KEY", "")
            if not _api_key:
                st.error("ANTHROPIC_API_KEY eksik.")
            else:
                with st.spinner("Claude makro ortamı analiz ediyor ve hisse önerisi hazırlıyor..."):
                    import anthropic as _ant
                    _client = _ant.Anthropic(api_key=_api_key)
                    _prompt = f"""{_macro_ctx}
{_def_context}
{_crisis_ctx}

Sen deneyimli bir portföy yöneticisisin. Yukarıdaki makro verileri ve savunmacı hisse evrenini
kullanarak aşağıdaki 6 soruyu yanıtla. Duygulardan arınık, matematiksel ve veri odaklı ol.

## 1. 🔄 GENEL PİYASA ORTAMI
Şu an hangi döngü aşamasındayız? Temel göstergeleri birbirine bağla.
Sadece tekil gösterge yorumu değil — bakır+petrol+VIX+yield curve kombinasyonu ne söylüyor?

## 2. ⚠️ EN KRİTİK RİSK
Portföy için şu an en tehlikeli TEK gösterge nedir? Neden?
Matematiksel sonucu yaz: "Bu tetikleyici devreye girerse S&P %X düşer çünkü..."

## 3. ✅ EN ÖNEMLİ FIRSAT
Mevcut ortamda hangi sektör öne çıkıyor? Neden?

## 4. 💼 SOMUT HİSSE ÖNERİLERİ (Bu bölüm zorunlu)
Her önerilen sektör için referans listesinden 2-3 somut hisse seç.
Format:
**[Sektör Adı]** — [Neden bu sektör?]
- TICKER: [Tek cümle, bu hisseyi seçme gerekçesi, şu anki makro ile bağlantısı]

Önerilen Dağılım:
Nakit/Kısa Tahvil: %X | Defansif Hisse: %X | Altın: %X | Enerji: %X | Büyüme: %X

## 5. 🚫 KAÇINILACAKLAR
Hangi sektör/varlık şu an en riskli? Somut neden.

## 6. 📅 ÖNÜMÜZDEKİ 4-8 HAFTA
İzlenecek 3 kritik gelişme. Tarih/seviye bazlı eşikler ver.
Örn: "USD/JPY 155 altına kırarsa..." veya "VIX 30 geçerse..."

Türkçe yaz. Genel laflar değil, bu spesifik rakamlara dayalı somut yorum."""

                    try:
                        _resp = _client.messages.create(
                            model="claude-opus-4-5",
                            max_tokens=2500,
                            messages=[{"role": "user", "content": _prompt}]
                        )
                        _analysis_text = _resp.content[0].text
                        st.session_state["macro_claude_analysis"] = _analysis_text
                        st.session_state["macro_analysis_ts"]     = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
                    except Exception as _e:
                        st.error(f"Claude bağlantı hatası: {_e}")

        if st.session_state.get("macro_claude_analysis"):
            _analysis_text = st.session_state["macro_claude_analysis"]
            _analysis_ts   = st.session_state.get("macro_analysis_ts", "")

            # Analiz göster
            st.markdown(f'<div style="font-size:0.7rem;color:#5a6a7a;margin-bottom:0.5rem;">🕐 {_analysis_ts}</div>',
                       unsafe_allow_html=True)
            st.markdown(_analysis_text)

            # HTML raporu oluştur ve indir
            st.markdown("---")
            _report_html = _generate_macro_html(
                analysis_text = _analysis_text,
                macro_data    = _macro_data,
                regime        = _macro_regime,
                generated_at  = _analysis_ts,
            )
            _dl_col1, _dl_col2 = st.columns([1, 3])
            with _dl_col1:
                from datetime import datetime as _dt_macro
                st.download_button(
                    label="📄 Raporu İndir (HTML)",
                    data=_report_html.encode("utf-8"),
                    file_name=f"makro_analiz_{_dt_macro.now().strftime('%Y-%m-%d')}.html",
                    mime="text/html",
                    key="dl_macro_html",
                    use_container_width=True,
                )
            with _dl_col2:
                if st.button("💾 Arşive Kaydet", key="btn_macro_archive", use_container_width=True):
                    _saved = _save_macro_analysis_to_archive(
                        analysis_text = _analysis_text,
                        macro_data    = _macro_data,
                        regime        = _macro_regime,
                        generated_at  = _analysis_ts,
                    )
                    if _saved:
                        st.success("✅ Makro analiz arşive kaydedildi!")
                    else:
                        st.warning("Lokal kaydedildi, GitHub yazma hatası.")

            # Arşiv görüntüle
            with st.expander("📚 Makro Analiz Arşivi", expanded=False):
                _archive = _load_macro_analysis_archive()
                if _archive:
                    for _entry in _archive[-5:][::-1]:  # Son 5, en yeni üstte
                        st.markdown(
                            f'<div style="background:#111927;border-radius:6px;padding:0.6rem 1rem;'
                            f'margin-bottom:0.5rem;border-left:3px solid #4fc3f7;">'
                            f'<b style="color:#4fc3f7;">{_entry.get("generated_at","")}</b> — '
                            f'<span style="color:#8a9ab0;">{_entry.get("regime_label","")}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        with st.expander(f"  Analizi Görüntüle — {_entry.get('generated_at','')}"):
                            st.markdown(_entry.get("analysis_text",""))
                else:
                    st.caption("Henüz arşivlenmiş analiz yok.")


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

def _generate_strategy_html(director: dict, analyst_reports: dict, 
                              portfolio_value: float, generated_at: str) -> str:
    """Strateji raporunu güzel HTML formatında üret."""
    
    sig_colors = {
        "AL": "#00c48c", "GÜÇLÜ AL": "#00c48c", "ARTIR": "#4fc3f7",
        "TUT": "#8a9ab0", "BEKLE": "#ffb300",
        "AZALT": "#ff8c00", "SAT": "#e74c3c", "GÜÇLÜ SAT": "#c0392b",
    }
    
    def sig_badge(sinyal):
        color = sig_colors.get(sinyal, "#8a9ab0")
        return f'<span style="background:{color};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.75rem;font-weight:700;">{sinyal}</span>'
    
    d = director
    ar = analyst_reports

    # Analist özeti
    analist_html = ""
    as_data = d.get("analist_sentezi", {})
    for key, label in [("makro","🌍 Makro"), ("abd_hisse","🇺🇸 ABD Hisse"),
                        ("kripto","₿ Kripto"), ("emtia","🥇 Emtia"), ("turkiye","🇹🇷 Türkiye")]:
        item = as_data.get(key, {})
        if not item:
            # Fallback: analyst_reports'tan al
            raw = ar.get(key, ar.get(key.replace("_hisse",""), {}))
            item = {"sinyal": raw.get("sinyal","—"), "gerekce": raw.get("ana_gerekcce", raw.get("ana_gerekce",""))}
        sinyal  = item.get("sinyal", "—")
        gerekce = item.get("gerekce", item.get("gerekcce",""))
        analist_html += f"""
        <div style="background:#1a2332;border-left:3px solid {sig_colors.get(sinyal,'#8a9ab0')};
             padding:0.7rem 1rem;margin-bottom:0.5rem;border-radius:0 6px 6px 0;">
          <div style="display:flex;align-items:center;gap:0.7rem;margin-bottom:0.3rem;">
            <span style="font-weight:600;color:#e8edf3;">{label}</span>
            {sig_badge(sinyal)}
          </div>
          <div style="font-size:0.8rem;color:#b0bec5;">{gerekce}</div>
        </div>"""

    # Çelişkiler
    celiski_html = ""
    for c in d.get("celiskiler", []):
        celiski_html += f"""
        <div style="background:#1e2a1e;border:1px solid #ffb300;border-radius:6px;padding:0.7rem 1rem;margin-bottom:0.5rem;">
          <div style="font-weight:600;color:#ffb300;">⚡ {c.get('baslik','')}</div>
          <div style="font-size:0.8rem;color:#b0bec5;margin:0.3rem 0;">{c.get('aciklama','')}</div>
          <div style="font-size:0.8rem;color:#00c48c;font-weight:600;">→ Karar: {c.get('karar','')} (Kazanan: {c.get('kazanan','')})</div>
        </div>"""
    if not celiski_html:
        celiski_html = '<p style="color:#5a6a7a;font-size:0.85rem;">Analistler arasında büyük çelişki tespit edilmedi.</p>'

    # Aksiyonlar
    pa = d.get("portfoy_aksiyonlari", {})
    
    def aksiyon_list(items, border_color):
        if not items: return '<p style="color:#5a6a7a;font-size:0.85rem;">—</p>'
        html = ""
        for a in items:
            ticker = a.get("ticker","") or a.get("varlik","")
            eylem  = a.get("eylem","") or a.get("kosul","") or a.get("izlenecek","")
            neden  = a.get("neden","")
            stop   = a.get("stop_loss")
            hedef  = a.get("hedef")
            extra  = ""
            if stop:  extra += f' | Stop: <span style="color:#e74c3c;">{stop}</span>'
            if hedef: extra += f' | Hedef: <span style="color:#00c48c;">{hedef}</span>'
            html += f"""
            <div style="background:#1a2332;border-left:3px solid {border_color};
                 padding:0.5rem 0.8rem;margin-bottom:0.4rem;border-radius:0 4px 4px 0;font-size:0.82rem;">
              {'<b style="color:#e8edf3;">'+ticker+'</b> — ' if ticker else ''}{eylem}{extra}
              {'<div style="color:#8a9ab0;font-size:0.75rem;margin-top:2px;">'+neden+'</div>' if neden else ''}
            </div>"""
        return html

    nakit = pa.get("nakit_orani", {})
    nakit_html = f"""
    <div style="background:#1a2332;border:1px solid #4fc3f7;border-radius:6px;padding:0.7rem 1rem;margin-top:0.7rem;">
      <span style="color:#4fc3f7;font-weight:600;">💵 Nakit Oranı</span>
      <span style="color:#e8edf3;margin-left:1rem;">Önerilen: <b>%{nakit.get('onerilen_pct',0)}</b> | 
      Mevcut: %{nakit.get('mevcut_pct',0)}</span>
      <div style="color:#8a9ab0;font-size:0.8rem;margin-top:3px;">{nakit.get('neden','')}</div>
    </div>"""

    # Risk senaryosu
    rs = d.get("risk_senaryosu", {})
    rs_items = ""
    for item in rs.get("ilk_24_saat", []):
        rs_items += f'<li style="margin-bottom:3px;">{item}</li>'
    for item in rs.get("savunma", []):
        rs_items += f'<li style="margin-bottom:3px;color:#ffb300;">{item}</li>'
    
    firsat_html = ""
    for f_item in rs.get("firsat_listesi", []):
        firsat_html += f"""<span style="background:#1a3a1a;border:1px solid #00c48c;border-radius:4px;
        padding:2px 8px;margin-right:6px;font-size:0.78rem;">
        {f_item.get('ticker','')} @ {f_item.get('seviye','')} — {f_item.get('neden','')}</span>"""

    # Vade planları
    vp = d.get("vade_planlari", {})
    vade_html = ""
    for vkey, vlabel, vcolor in [("kisa","📅 Kısa Vade (1-3 ay)","#4fc3f7"),
                                   ("orta","📆 Orta Vade (3-12 ay)","#00c48c"),
                                   ("uzun","🗓 Uzun Vade (1-3 yıl)","#ce93d8")]:
        vd = vp.get(vkey, {})
        aksiyonlar = ""
        for ax in vd.get("aksiyonlar", []):
            aksiyonlar += f'<li style="font-size:0.8rem;color:#b0bec5;">{ax}</li>'
        
        tema = vd.get("tema","") or vd.get("pozisyonlama","") or vd.get("baz_senaryo","")
        vade_html += f"""
        <div style="background:#1a2332;border-top:3px solid {vcolor};border-radius:6px;
             padding:0.8rem 1rem;flex:1;min-width:200px;">
          <div style="font-weight:600;color:{vcolor};margin-bottom:0.5rem;">{vlabel}</div>
          <div style="font-size:0.8rem;color:#b0bec5;">{tema}</div>
          {('<ul style="margin:0.4rem 0 0 1rem;padding:0;">' + aksiyonlar + '</ul>') if aksiyonlar else ''}
        </div>"""

    # Yıl sonu
    yt = d.get("yil_sonu_hedefi", {})
    hedef_pct = yt.get("hedef_pct", 0)
    mevcut_pct = yt.get("mevcut_pct", 0)
    kalan = yt.get("kalan_pct", hedef_pct - mevcut_pct)
    
    # Bir sonraki kontrol
    snk = d.get("bir_sonraki_kontrol", {})
    tetik_html = ""
    for t in snk.get("tetikleyiciler", []):
        tip_color = {"fiyat": "#4fc3f7", "takvim": "#ffb300", "durum": "#ce93d8"}.get(t.get("tip",""), "#8a9ab0")
        tetik_html += f"""
        <div style="display:flex;gap:0.5rem;align-items:flex-start;margin-bottom:0.3rem;font-size:0.8rem;">
          <span style="background:{tip_color};color:#0d1117;padding:1px 6px;border-radius:3px;
          font-size:0.68rem;font-weight:700;white-space:nowrap;">{t.get('tip','').upper()}</span>
          <span style="color:#b0bec5;">{t.get('aciklama','')} — <b style="color:#e8edf3;">{t.get('esik','')}</b></span>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strateji Raporu — {generated_at}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0d1117; color: #e8edf3; padding: 2rem; line-height: 1.6; }}
  .container {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; color: #4fc3f7; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1rem; color: #8a9ab0; text-transform: uppercase;
        letter-spacing: 0.08em; margin-bottom: 1rem; border-bottom: 1px solid #1e2833;
        padding-bottom: 0.4rem; }}
  .section {{ background: #111927; border-radius: 8px; padding: 1.2rem 1.5rem;
              margin-bottom: 1.2rem; border: 0.5px solid #1e2833; }}
  .meta {{ color: #5a6a7a; font-size: 0.78rem; margin-bottom: 1.5rem; }}
  .flex {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
  @media print {{ body {{ background: #fff; color: #000; }}
                  .section {{ border: 1px solid #ccc; }} }}
</style>
</head>
<body>
<div class="container">

  <div style="margin-bottom:1.5rem;">
    <h1>🧭 Strateji Raporu</h1>
    <div class="meta">Üretildi: {generated_at} | Portföy: ${portfolio_value:,.0f}</div>
  </div>

  <!-- 1. Piyasa Özeti -->
  <div class="section">
    <h2>📊 Piyasa Özeti</h2>
    <p style="font-size:1rem;color:#e8edf3;line-height:1.8;">{d.get('piyasa_ozeti','')}</p>
  </div>

  <!-- 2. Analist Sentezi -->
  <div class="section">
    <h2>🔬 Analist Sinyalleri</h2>
    {analist_html}
  </div>

  <!-- 3. Çelişkiler -->
  <div class="section">
    <h2>⚡ Çelişki Çözümü</h2>
    {celiski_html}
  </div>

  <!-- 4. Aksiyon Planı -->
  <div class="section">
    <h2>🎯 Aksiyon Planı</h2>
    <div style="margin-bottom:0.8rem;">
      <div style="font-size:0.75rem;color:#e74c3c;font-weight:700;letter-spacing:0.05em;margin-bottom:0.4rem;">🔴 HEMEN YAP</div>
      {aksiyon_list(pa.get('hemen_yap',[]), '#e74c3c')}
    </div>
    <div style="margin-bottom:0.8rem;">
      <div style="font-size:0.75rem;color:#ffb300;font-weight:700;letter-spacing:0.05em;margin-bottom:0.4rem;">🟡 KOŞULLU YAP</div>
      {aksiyon_list(pa.get('kosullu_yap',[]), '#ffb300')}
    </div>
    <div style="margin-bottom:0.8rem;">
      <div style="font-size:0.75rem;color:#4fc3f7;font-weight:700;letter-spacing:0.05em;margin-bottom:0.4rem;">🔵 İZLE / KARAR VER</div>
      {aksiyon_list(pa.get('izle_karar_ver',[]), '#4fc3f7')}
    </div>
    {nakit_html}
  </div>

  <!-- 5. Risk Senaryosu -->
  <div class="section">
    <h2>⚠️ Risk Senaryosu</h2>
    <div style="color:#e74c3c;font-weight:600;margin-bottom:0.7rem;">Tetikleyici: {rs.get('tetikleyici','')}</div>
    <ul style="margin-left:1.2rem;margin-bottom:0.7rem;">{rs_items}</ul>
    {'<div style="margin-top:0.7rem;"><span style="color:#8a9ab0;font-size:0.8rem;">Fırsat Listesi: </span>' + firsat_html + '</div>' if firsat_html else ''}
    <div style="margin-top:0.7rem;color:#00c48c;font-size:0.85rem;">
      ✅ Toparlanma sinyali: {rs.get('toparlanma_sinyali','')}
    </div>
  </div>

  <!-- 6. Vade Planları -->
  <div class="section">
    <h2>📅 Vade Planları</h2>
    <div class="flex">{vade_html}</div>
  </div>

  <!-- 7. Yıl Sonu Hedefi -->
  <div class="section">
    <h2>🏆 Yıl Sonu Hedefi</h2>
    <div style="display:flex;gap:2rem;margin-bottom:0.7rem;flex-wrap:wrap;">
      <div><span style="color:#8a9ab0;font-size:0.8rem;">Hedef</span><br>
           <span style="font-size:1.3rem;font-weight:700;color:#4fc3f7;">%{hedef_pct:.0f}</span></div>
      <div><span style="color:#8a9ab0;font-size:0.8rem;">Mevcut</span><br>
           <span style="font-size:1.3rem;font-weight:700;color:#{'00c48c' if mevcut_pct>=0 else 'e74c3c'};">{'+' if mevcut_pct>=0 else ''}%{mevcut_pct:.1f}</span></div>
      <div><span style="color:#8a9ab0;font-size:0.8rem;">Kalan</span><br>
           <span style="font-size:1.3rem;font-weight:700;color:#ffb300;">%{kalan:.1f}</span></div>
    </div>
    <div style="color:#8a9ab0;font-size:0.85rem;margin-bottom:0.4rem;">{yt.get('risk_degerlendirmesi','')}</div>
    <div style="color:#4fc3f7;font-size:0.85rem;font-weight:600;">{yt.get('tavsiye','')}</div>
  </div>

  <!-- 8. Bir Sonraki Kontrol -->
  <div class="section">
    <h2>📌 Bir Sonraki Kontrol</h2>
    <div style="font-size:1.1rem;font-weight:700;color:#ce93d8;margin-bottom:0.3rem;">{snk.get('tarih','')}</div>
    <div style="color:#b0bec5;font-size:0.85rem;margin-bottom:0.7rem;">{snk.get('neden','')}</div>
    {tetik_html}
  </div>

  <div style="text-align:center;color:#2a3a4a;font-size:0.75rem;margin-top:2rem;">
    AI Strateji Direktörü — {generated_at}
  </div>

</div>
</body>
</html>"""
    return html


# TAB 10 — STRATEJİ MERKEZİ
# ─────────────────────────────────────────────────────────────────────────────

with tab_strategy:
    from strategy_data   import collect_all_strategy_data
    from strategy_engine import generate_strategy, save_strategy, generate_strategy_html

    st.markdown(
        '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
        'letter-spacing:0.1em;margin-bottom:1rem;">'
        '► STRATEJİ MERKEZİ — Kısa / Orta / Uzun Vade Aksiyon Planı</div>',
        unsafe_allow_html=True,
    )

    # ── Katman 1: Anlık Durum Panosu ─────────────────────────────────────
    _port_now     = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]

    # USD/TRY kuru — TRY varlıkları dönüştürmek için
    _usd_try_strat = 32.0
    try:
        import yfinance as _yf_strat
        _usd_try_strat = float(_yf_strat.Ticker("USDTRY=X").fast_info.last_price or 32.0)
    except Exception:
        pass

    # Çok sınıflı nakit — portföy sekmesinden girilen değerler
    _cash_info  = get_total_cash_usd(usd_try=_usd_try_strat)
    _cash_now   = _cash_info["total_usd"]
    _cash_break = _cash_info["breakdown"]   # {"ABD / USD": x, "Kripto": y, ...}

    # Varlık sınıfına göre doğru USD değeri hesapla
    _GRAM_MAP_STRAT = {
        "ALTIN_GRAM_TRY": "GC=F",
        "GUMUS_GRAM_TRY": "SI=F",
        "XAUTRY=X": "GC=F",
        "XAGTRY=X": "SI=F",
    }

    def _pos_value_usd(pos):
        shares   = float(pos.get("shares", 0))
        avg_cost = float(pos.get("avg_cost", 0))
        currency = pos.get("currency", "USD")
        ticker   = pos.get("ticker", "")
        cur_price = float(pos.get("current_price", 0) or 0)
        if cur_price <= 0:
            return shares * avg_cost / _usd_try_strat if currency == "TRY" else shares * avg_cost
        if currency == "TRY":
            if ticker in _GRAM_MAP_STRAT and cur_price > 500:
                cur_price_tl = cur_price * _usd_try_strat / 31.1035
                return shares * cur_price_tl / _usd_try_strat
            return shares * cur_price / _usd_try_strat
        return shares * cur_price

    def _pos_cost_usd(pos):
        """Pozisyonun maliyet bazını USD olarak hesapla."""
        shares   = float(pos.get("shares", 0))
        avg_cost = float(pos.get("avg_cost", 0))
        currency = pos.get("currency", "USD")
        if currency == "TRY":
            return shares * avg_cost / _usd_try_strat
        return shares * avg_cost

    _port_val_now  = sum(_pos_value_usd(p) for p in _port_now)
    _port_cost_now = sum(_pos_cost_usd(p)  for p in _port_now)
    _total_pnl     = _port_val_now - _port_cost_now
    _total_pnl_pct = (_total_pnl / _port_cost_now * 100) if _port_cost_now > 0 else 0
    _total_now     = _port_val_now + _cash_now
    _cash_ratio    = (_cash_now / _total_now * 100) if _total_now > 0 else 0

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

    # Fear & Greed hızlı — ABD (CNN/VIX proxy) + Kripto (alternative.me)
    try:
        from strategy_data import fetch_fear_greed, fetch_fed_calendar
        _fg_quick  = fetch_fear_greed()
        _fed_quick = fetch_fed_calendar()
        _fg_score  = _fg_quick.get("score", 50)
        _fg_rating = _fg_quick.get("tr_rating", "—")
        _fg_source = _fg_quick.get("source", "")
        _fg_color  = "#00c48c" if _fg_score <= 30 else ("#e74c3c" if _fg_score >= 70 else "#ffb300")
        _fomc_days = _fed_quick.get("days_until", "—")
    except Exception:
        _fg_score, _fg_rating, _fg_color, _fomc_days, _fg_source = 50, "—", "#ffb300", "—", ""

    # Kripto Fear & Greed (alternative.me)
    _crypto_fg_score = None
    try:
        from crypto_fetcher import fetch_crypto_fear_greed
        _cfg = fetch_crypto_fear_greed()
        _crypto_fg_score = _cfg.get("score", None)
        _crypto_fg_label = _cfg.get("tr_label", _cfg.get("label", ""))
    except Exception:
        pass

    # KPI bar — 6 kolon
    _kpi_cols = st.columns(6)
    _pnl_color = "#00c48c" if _total_pnl >= 0 else "#e74c3c"
    _pnl_sign  = "+" if _total_pnl >= 0 else ""
    # Nakit dökümü tooltip
    _cash_sub = " | ".join(
        f"{k}: ${v:,.0f}" if "TL" not in k else f"{k}: {v*_usd_try_strat:,.0f}₺"
        for k, v in _cash_break.items() if v > 0
    ) or f"%{_cash_ratio:.0f} oran"

    for _col, _label, _val, _clr, _sub in [
        (_kpi_cols[0], "Portföy Değeri",  f"${_port_val_now:,.0f}", "#4fc3f7", f"{len(_port_now)} pozisyon"),
        (_kpi_cols[1], "Toplam K/Z",      f"{_pnl_sign}${_total_pnl:,.0f}", _pnl_color, f"{_pnl_sign}{_total_pnl_pct:.1f}%"),
        (_kpi_cols[2], "Nakit (Toplam)",  f"${_cash_now:,.0f}", "#00c48c", f"%{_cash_ratio:.0f} oran"),
        (_kpi_cols[3], "Makro Rejim",     _regime_label,            _regime_color, f"VIX {_vix_val:.0f}"),
        (_kpi_cols[4], "Fear & Greed",    f"{_fg_score:.0f}/100",   _fg_color,
         f"{_fg_rating} | {_fg_source}" if _fg_source else _fg_rating),
        (_kpi_cols[5], "FOMC'a Kalan",    f"{_fomc_days} gün",      "#ce93d8", "Fed toplantısı"),
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

    # Nakit dökümü (portföy sekmesinden girilen değerler)
    if any(v > 0 for v in _cash_break.values()):
        _cash_parts = []
        for _k, _v in _cash_break.items():
            if _v > 0:
                _cash_parts.append(f"**{_k}:** ${_v:,.0f}")
        st.caption("💵 Nakit dökümü: " + " | ".join(_cash_parts) +
                   " — Portföy sekmesinden güncelle")

    # Kripto Fear & Greed (ayrı göster)
    if _crypto_fg_score is not None:
        _cfg_color = "#00c48c" if _crypto_fg_score <= 30 else ("#e74c3c" if _crypto_fg_score >= 70 else "#ffb300")
        st.caption(
            f"₿ Kripto Fear & Greed: **{_crypto_fg_score:.0f}/100** — {_crypto_fg_label} "
            f"(alternative.me) | 🇺🇸 ABD F&G: **{_fg_score:.0f}/100** — {_fg_rating} ({_fg_source})"
        )

    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)

    # ── Katman 1b: Finansal Takvim Widget ────────────────────────────────
    try:
        from financial_calendar import get_upcoming_events
        from datetime import datetime as _dt_cal

        _cal_port_tickers = [p["ticker"] for p in _port_now]
        try:
            from breakout_scanner import load_watchlist as _lw_cal
            _cal_port_tickers += _lw_cal()
        except Exception:
            pass
        _cal_port_tickers = list(dict.fromkeys(_cal_port_tickers))

        _cal_14 = get_upcoming_events(tickers=_cal_port_tickers, days_ahead=14, min_stars=1)

        if _cal_14:
            with st.expander(
                f"📅 Bu Hafta Finansal Takvim — {len(_cal_14)} olay",
                expanded=True,
            ):
                _star_colors = {3: "#e74c3c", 2: "#ffb300", 1: "#4fc3f7"}
                _star_emojis = {3: "🔴", 2: "🟡", 1: "🔵"}
                _cat_labels  = {
                    "fed": "🏛 FED",
                    "macro": "📊 MAKRO",
                    "earnings": "💼 EARNINGS",
                }

                # Olayları gün gruplarına ayır
                from itertools import groupby
                _grouped = {}
                for _ev in _cal_14:
                    _grouped.setdefault(_ev["date"], []).append(_ev)

                for _gdate, _gevents in sorted(_grouped.items()):
                    _gday = _dt_cal.strptime(_gdate, "%Y-%m-%d")
                    _today_dt = _dt_cal.now().date()
                    _diff = (_gday.date() - _today_dt).days
                    _day_label = (
                        "BUGÜN" if _diff == 0
                        else "YARIN" if _diff == 1
                        else _gday.strftime("%d %b, %A")
                    )
                    _has_critical = any(e.get("stars", 1) == 3 for e in _gevents)
                    _day_color = "#e74c3c" if _has_critical else "#ffb300" if _diff <= 2 else "#5a6a7a"

                    st.markdown(
                        f'<div style="font-size:0.65rem;font-weight:600;color:{_day_color};'
                        f'text-transform:uppercase;letter-spacing:0.08em;'
                        f'margin:0.6rem 0 0.3rem;border-left:3px solid {_day_color};'
                        f'padding-left:0.5rem;">{_day_label} — {_gdate}</div>',
                        unsafe_allow_html=True,
                    )

                    for _ev in _gevents:
                        _sc   = _star_colors.get(_ev.get("stars", 1), "#5a6a7a")
                        _sem  = _star_emojis.get(_ev.get("stars", 1), "🔵")
                        _cat  = _cat_labels.get(_ev.get("category", "macro"), "📊")
                        _tkr  = f" ({_ev['ticker']})" if _ev.get("ticker") else ""
                        _desc = _ev.get("description", "")[:120]
                        _watch= _ev.get("watch", "")[:100]

                        st.markdown(
                            f'<div style="background:var(--color-background-secondary);'
                            f'border-left:3px solid {_sc};'
                            f'border-radius:0 8px 8px 0;'
                            f'padding:0.5rem 0.8rem;margin-bottom:0.4rem;">'
                            f'<div style="display:flex;justify-content:space-between;'
                            f'align-items:center;">'
                            f'<span style="font-size:0.78rem;font-weight:600;">'
                            f'{_sem} {_cat}: {_ev["event"]}{_tkr}</span>'
                            f'<span style="font-size:0.65rem;color:{_sc};font-weight:500;">'
                            f'{"⭐"*_ev.get("stars",1)}</span>'
                            f'</div>'
                            f'<div style="font-size:0.72rem;color:var(--color-text-secondary);'
                            f'margin-top:3px;line-height:1.5;">{_desc}</div>'
                            + (f'<div style="font-size:0.68rem;color:#ffb300;margin-top:3px;">'
                               f'👁 {_watch}</div>' if _watch else '')
                            + f'</div>',
                            unsafe_allow_html=True,
                        )
    except Exception as _cal_e:
        st.caption(f"Takvim yüklenemedi: {_cal_e}")

    # ── Katman 2: Profil Ayarları ─────────────────────────────────────────
    # Profili GitHub'dan yükle (ilk açılışta veya cache yoksa)
    if st.session_state.get("user_profile_loaded") is None:
        _saved_profile = load_user_profile()
        st.session_state["user_profile_loaded"] = _saved_profile
    _saved_profile = st.session_state.get("user_profile_loaded", {})

    # Seçenek listelerinde kayıtlı değeri bul
    _th_opts  = ["1-3 yıl (Uzun Vade)", "3-12 ay (Orta Vade)", "1-3 ay (Kısa Vade)"]
    _rt_opts  = ["Orta-Yüksek (%20 düşüş tolere edilir)", "Orta (%10 düşüş tolere edilir)", "Düşük (koruma öncelikli)"]
    _cc_opts  = ["3 ayda bir", "Aylık düzenli", "Düzensiz / fırsata göre"]
    _th_idx   = _th_opts.index(_saved_profile.get("time_horizon", _th_opts[0])) if _saved_profile.get("time_horizon") in _th_opts else 0
    _rt_idx   = _rt_opts.index(_saved_profile.get("risk_tol", _rt_opts[0])) if _saved_profile.get("risk_tol") in _rt_opts else 0
    _cc_idx   = _cc_opts.index(_saved_profile.get("cash_cycle", _cc_opts[0])) if _saved_profile.get("cash_cycle") in _cc_opts else 0

    with st.expander("⚙️ Yatırımcı Profili — Strateji Parametreleri", expanded=False):
        _pr_c1, _pr_c2, _pr_c3 = st.columns(3)
        with _pr_c1:
            _time_horizon = st.selectbox(
                "Zaman Ufku:",
                _th_opts, index=_th_idx, key="st_time_horizon",
            )
            _risk_tol = st.selectbox(
                "Risk Toleransı:",
                _rt_opts, index=_rt_idx, key="st_risk_tol",
            )
        with _pr_c2:
            _cash_cycle = st.selectbox(
                "Nakit Döngüsü:",
                _cc_opts, index=_cc_idx, key="st_cash_cycle",
            )
            _deploy_cash = st.number_input(
                "Bu dönem dağıtılacak ek nakit ($):",
                min_value=0.0,
                value=float(_saved_profile.get("deploy_cash", 0.0)),
                step=100.0, key="st_deploy_cash",
            )
        with _pr_c3:
            _goal = st.text_area(
                "Yatırım Hedefi:",
                value=_saved_profile.get("goal",
                    "Uzun vadeli büyüme odaklı, volatiliteyi minimize ederek "
                    "portföyü sistematik şekilde büyütmek."),
                height=80, key="st_goal",
            )
            _year_target = st.number_input(
                "Yıl Sonu Hedefi (%):",
                min_value=0.0, max_value=500.0,
                value=float(_saved_profile.get("year_target_pct", 40.0)),
                step=5.0, key="st_year_target",
            )

        _save_prof_col, _ = st.columns([1, 3])
        with _save_prof_col:
            if st.button("💾 Profili Kaydet", key="btn_save_profile", use_container_width=True):
                _new_profile = {
                    "time_horizon":     _time_horizon,
                    "risk_tol":         _risk_tol,
                    "cash_cycle":       _cash_cycle,
                    "deploy_cash":      float(_deploy_cash),
                    "goal":             _goal,
                    "year_target_pct":  float(_year_target),
                }
                ok_prof = save_user_profile(_new_profile)
                st.session_state["user_profile_loaded"] = _new_profile
                if ok_prof:
                    st.success("✅ Profil kaydedildi!")
                else:
                    st.warning("Profil lokal kaydedildi, GitHub yazma hatası.")

    # ── Katman 3: Strateji Üret ───────────────────────────────────────────
    st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">', unsafe_allow_html=True)

    _strat_c1, _strat_c2, _strat_c3 = st.columns([2, 1, 1])
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
    with _strat_c3:
        _run_simulation = st.button(
            "🧪 Senaryo Simülasyonu",
            key="btn_simulation", use_container_width=True,
            help="Olası piyasa senaryolarında portföyü test et",
        )

    # ── Senaryo Simülasyonu ─────────────────────────────────────────────
    # Session state ile buton durumu takip edilir — Streamlit rerun sorunu çözüldü
    if _run_simulation:
        st.session_state["show_simulation"] = True

    if st.session_state.get("show_simulation"):
        from scenario_simulator import (
            SCENARIOS, build_scenario_data, build_scenario_director_prompt
        )
        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:0.5rem 0;">',
                    unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.7rem;color:#5a6a7a;text-transform:uppercase;'
            'letter-spacing:0.1em;margin-bottom:0.8rem;">🧪 SENARYO SİMÜLASYONU</div>',
            unsafe_allow_html=True)

        _sim_col1, _sim_col2, _sim_col3 = st.columns([2, 1, 1])
        with _sim_col1:
            _sim_scenarios = {k: v["isim"] for k, v in SCENARIOS.items()}
            _sim_key = st.selectbox(
                "Senaryo Seç:",
                options=list(_sim_scenarios.keys()),
                format_func=lambda x: _sim_scenarios[x],
                key="sim_scenario_sel",
            )
        with _sim_col2:
            _run_sim_now = st.button(
                "▶ Simülasyonu Çalıştır",
                key="btn_run_sim", use_container_width=True, type="primary"
            )
        with _sim_col3:
            if st.button("✕ Kapat", key="btn_sim_close", use_container_width=True):
                st.session_state.pop("show_simulation", None)
                st.session_state.pop("simulation_result", None)
                st.session_state.pop("simulation_data", None)
                st.rerun()

        # Seçili senaryonun açıklaması
        if _sim_key:
            _sc_info = SCENARIOS[_sim_key]
            st.info(f"**{_sc_info['isim']}**\n\n{_sc_info['ozet']}")

        # Simülasyonu çalıştır
        if _run_sim_now:
            # Mevcut portföyü fiyatlarıyla birlikte al
            _sim_port = [
                {**p, "current_price": p.get("avg_cost", 0)}
                for p in _port_now if float(p.get("shares", 0)) > 0
            ]
            _usd_try_sim = 38.0
            try:
                import yfinance as _yf_sim
                _usd_try_sim = float(_yf_sim.Ticker("USDTRY=X").fast_info.last_price or 38.0)
            except Exception:
                pass

            _sim_data = build_scenario_data(
                scenario_key        = _sim_key,
                portfolio_positions = _sim_port,
                portfolio_cash      = _cash_now,
                user_profile        = {
                    "risk_tol":        _risk_tol,
                    "time_horizon":    _time_horizon,
                    "goal":            _goal,
                    "year_target_pct": float(st.session_state.get("st_year_target", 40.0)),
                },
                usd_try = _usd_try_sim,
            )
            st.session_state["simulation_data"] = _sim_data

            # Özet metrikler
            _s1, _s2, _s3 = st.columns(3)
            with _s1:
                st.metric("Mevcut Portföy",
                          f"${_sim_data['portfolio']['analytics']['total_with_cash']:,.0f}")
            with _s2:
                _proj = _sim_data['projected_total']
                _loss = _sim_data['projected_loss']
                st.metric("Senaryo Sonrası", f"${_proj:,.0f}", delta=f"{_loss:+,.0f}$")
            with _s3:
                _tot = _sim_data['portfolio']['analytics']['total_with_cash']
                _pct = _loss / max(_tot, 1) * 100
                st.metric("Etki %", f"{_pct:+.1f}%")

            # Mevcut ağırlıklar
            st.markdown("**Mevcut Ağırlıklar:**")
            _ac_labels = {"us_equity":"🇺🇸 ABD", "crypto":"₿ Kripto",
                          "commodity":"🥇 Emtia", "tefas":"🇹🇷 TEFAS", "other":"Diğer"}
            _aw_items = sorted(_sim_data['class_weights_now'].items(), key=lambda x:-x[1])
            _aw_cols  = st.columns(max(len(_aw_items), 1))
            for i, (ac, pct) in enumerate(_aw_items):
                with _aw_cols[i]:
                    st.metric(_ac_labels.get(ac, ac), f"%{pct:.1f}")


        # Direktör çağrısı — veri hazır ama sonuç yoksa çalıştır
        _sim_data_ready = st.session_state.get("simulation_data")
        _sim_needs_run  = _sim_data_ready and not st.session_state.get("simulation_result")
        if _sim_needs_run:
            with st.spinner("🧭 Direktör senaryo analizi yapıyor (~30 sn)..."):
                _sim_prompt = build_scenario_director_prompt(_sim_data_ready)
                _api_key = os.getenv("ANTHROPIC_API_KEY", "")
                if not _api_key:
                    st.error("ANTHROPIC_API_KEY eksik.")
                else:
                    try:
                        import anthropic as _ant_sim
                        _sim_client = _ant_sim.Anthropic(api_key=_api_key)
                        _sim_system = """Sen çok varlıklı portföy yönetiminde uzmanlaşmış strateji direktörüsün.
    ABD hisse, kripto, emtia ve TEFAS fonlarını aynı anda yönetiyorsun.
    Bu bir SENARYO SİMÜLASYONU — senaryo şu an GERÇEKLEŞIYOR.

    ═══ MİKRO-METRİK ODAĞI ═══
    Her ABD hissesini şu etiketlerle değerlendir:
    - [Faiz_indirim_pozitif] veya [Faiz_indirim_negatif]
    - [Resesyon_defansif] veya [Resesyon_hassas]
    - [Yuksek_FCF] veya [Dusuk_FCF]
    FCF yield yüksek + borç düşük = koru. Tersini azalt/sat.

    ═══ TEFAS LOOK-THROUGH ═══
    IIH = %90 büyük şirket hissesi → resesyon duyarlılığı YÜKSEK
    AEY = %80 altın → resesyon koruması YÜKSEK
    Her fonun içeriğine göre ayrı karar ver.

    ═══ SENARYO OLASILILANDIRMASI (ZORUNLU) ═══
    Kararları 3 senaryonun ağırlıklı ortalaması olarak ver:
    - Baz (%55): Fed önleyici indirim → soft landing, 6-9 ay toparlanma
    - Alternatif (%35): Hard landing → resesyon derinleşiyor, 12-18 ay baskı
    - Kuyruk (%10): Sistemik kriz → carry trade çöküşü + kredi donması
    Ağırlıklı beklenen etki = Σ(olasılık × portföy_etkisi). Negatif beklentide agresif pozisyon alma.

    ═══ KORElASYON SİGORTASI ═══
    VIX 34 + USDJPY 142 = yüksek korelasyon ortamı.
    Kripto-Nasdaq-BIST birlikte düşüyorsa nakit önerisini 1.5x artır ve bunu belirt.

    Yanıtını SADECE aşağıdaki JSON formatında ver (açıklama ekleme):
    {
      "senaryo_yorumu": "2-3 cümle — hangi olasılık ağır basıyor, neden?",
      "senaryo_olasiliklari": {
        "baz":        {"tanim": "...", "olasilik_pct": 55, "portfoy_etkisi": "+/-%X"},
        "alternatif": {"tanim": "...", "olasilik_pct": 35, "portfoy_etkisi": "+/-%X"},
        "kuyruk":     {"tanim": "...", "olasilik_pct": 10, "portfoy_etkisi": "+/-%X"}
      },
      "harmonize_strateji": "Ağırlıklı ortalama sonucu — tek cümle net karar",
      "onerilen_agirliklar": {
        "us_equity":  {"pct": 0, "onceki_pct": 19, "degisim_pp": 0, "gerekce": "tek cümle"},
        "crypto":     {"pct": 0, "onceki_pct": 20, "degisim_pp": 0, "gerekce": "tek cümle"},
        "commodity":  {"pct": 0, "onceki_pct": 17, "degisim_pp": 0, "gerekce": "tek cümle"},
        "tefas":      {"pct": 0, "onceki_pct": 40, "degisim_pp": 0, "gerekce": "tek cümle"},
        "nakit":      {"pct": 0, "onceki_pct":  4, "degisim_pp": 0, "gerekce": "tek cümle"}
      },
      "hisse_bazli_kararlar": [
        {
          "ticker": "TICKER",
          "etiketler": ["Faiz_indirim_pozitif", "Resesyon_defansif"],
          "fcf_durumu": "Yuksek_FCF|Dusuk_FCF|N/A",
          "karar": "KORU|ARTIR|AZALT|SAT",
          "gerekce": "tek cümle"
        }
      ],
      "tefas_kararlari": [
        {
          "ticker": "IIH",
          "icerik": "%90 hisse yogun",
          "resesyon_duyarlilik": "YUKSEK",
          "karar": "AZALT|TUT|ARTIR",
          "gerekce": "tek cümle"
        }
      ],
      "korelasyon_sigortasi": {
        "aktif": true,
        "neden": "VIX 34 + USDJPY 142 — korelasyon artıyor",
        "nakit_artirim_pp": 5
      },
      "zamanlama": "hemen|kademeli_1hafta|bekle_teyit",
      "zamanlama_gerekce": "neden bu zamanlama",
      "kritik_aksiyonlar": [
        {"oncelik": 1, "ticker": "...", "aksiyon": "...", "neden": "..."},
        {"oncelik": 2, "ticker": "...", "aksiyon": "...", "neden": "..."},
        {"oncelik": 3, "ticker": "...", "aksiyon": "...", "neden": "..."}
      ],
      "senaryo_sonu_sinyali": "Hangi 3-4 gösterge risk-on'a dönüşü teyit eder",
      "en_buyuk_yanilma_riski": "Bu analizde en çok yanılabileceğimiz nokta"
    }
    Türkçe yaz. Ağırlıklar toplamı %100 olmalı."""

                        _sim_resp = _sim_client.messages.create(
                            model="claude-opus-4-5",
                            max_tokens=3000,
                            system=_sim_system,
                            messages=[{"role": "user", "content": _sim_prompt}]
                        )
                        st.session_state["simulation_result"] = _sim_resp.content[0].text
                    except Exception as _se:
                        st.error(f"Simülasyon hatası: {_se}")

        # ── Sonuçları Göster ─────────────────────────────────────────────────
        if st.session_state.get("simulation_result"):
            import re as _re_sim
            _raw = st.session_state["simulation_result"]

            # JSON parse
            _sim_json = {}
            try:
                _m = _re_sim.search(r'\{.*\}', _raw, _re_sim.DOTALL)
                if _m:
                    _sim_json = json.loads(_m.group())
            except Exception:
                pass

            if _sim_json:
                _karar_renk = {"KORU":"#00c48c","ARTIR":"#4fc3f7","AZALT":"#ffb300","SAT":"#e74c3c"}

                # ── 1. Direktör yorumu ───────────────────────────────────
                st.markdown(
                    f'<div style="background:#111927;border-left:4px solid #4fc3f7;'
                    f'border-radius:6px;padding:1rem;margin:1rem 0;">'
                    f'<div style="font-size:0.65rem;color:#5a6a7a;font-weight:700;margin-bottom:0.4rem;">'
                    f'🧠 DİREKTÖR SENARYO YORUMU</div>'
                    f'<div style="color:#e8edf3;">{_sim_json.get("senaryo_yorumu","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True)

                # ── 2. Senaryo olasılıklandırması ────────────────────────
                _so = _sim_json.get("senaryo_olasiliklari", {})
                _hs = _sim_json.get("harmonize_strateji", "")
                if _so:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                        'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">🎲 SENARYO OLASILILANDIRMASI</div>',
                        unsafe_allow_html=True)
                    _sc1, _sc2, _sc3 = st.columns(3)
                    for _col, _skey, _slabel, _scolor in [
                        (_sc1, "baz",        "Baz Senaryo",  "#00c48c"),
                        (_sc2, "alternatif", "Alternatif",    "#ffb300"),
                        (_sc3, "kuyruk",     "Kuyruk Riski",  "#e74c3c"),
                    ]:
                        _sd = _so.get(_skey, {})
                        if _sd:
                            with _col:
                                st.markdown(
                                    f'<div style="background:#1a2332;border-top:3px solid {_scolor};'
                                    f'border-radius:6px;padding:0.7rem;text-align:center;">'
                                    f'<div style="font-size:0.62rem;color:{_scolor};font-weight:700;">{_slabel}</div>'
                                    f'<div style="font-size:1.2rem;font-weight:700;color:#e8edf3;">%{_sd.get("olasilik_pct",0)}</div>'
                                    f'<div style="font-size:0.72rem;color:#b0bec5;">{_sd.get("tanim","")}</div>'
                                    f'<div style="font-size:0.72rem;color:{_scolor};font-weight:600;">{_sd.get("portfoy_etkisi","")}</div>'
                                    f'</div>',
                                    unsafe_allow_html=True)
                if _hs:
                    st.markdown(
                        f'<div style="background:#1a1a2e;border-left:3px solid #ce93d8;'
                        f'border-radius:0 6px 6px 0;padding:0.6rem 1rem;margin:0.5rem 0;'
                        f'font-size:0.85rem;color:#e8edf3;">🎯 <b>Harmonize Strateji:</b> {_hs}</div>',
                        unsafe_allow_html=True)

                # ── 3. Önerilen ağırlıklar ───────────────────────────────
                st.markdown("**📊 Önerilen Yeniden Ağırlıklandırma:**")
                _ow = _sim_json.get("onerilen_agirliklar", {})
                _ac_emoji = {"us_equity":"🇺🇸","crypto":"₿","commodity":"🥇","tefas":"🇹🇷","nakit":"💵"}
                _ow_cols = st.columns(max(len(_ow), 1))
                _sim_data_ss = st.session_state.get("simulation_data", {})
                _cw_now = _sim_data_ss.get("class_weights_now", {})
                for i, (ac, info) in enumerate(_ow.items()):
                    with _ow_cols[i]:
                        _pct_new = info.get("pct", 0)
                        _delta   = info.get("degisim_pp", _pct_new - _cw_now.get(ac, 0))
                        _dc = "#00c48c" if _delta >= 0 else "#e74c3c"
                        st.markdown(
                            f'<div style="background:#1a2332;border-radius:8px;padding:0.7rem;text-align:center;">'
                            f'<div style="font-size:0.7rem;color:#8a9ab0;">{_ac_emoji.get(ac,"📌")} {ac.upper()}</div>'
                            f'<div style="font-size:1.3rem;font-weight:700;color:#e8edf3;">%{_pct_new}</div>'
                            f'<div style="font-size:0.85rem;color:{_dc};font-weight:600;">{_delta:+.0f}pp</div>'
                            f'<div style="font-size:0.68rem;color:#8a9ab0;margin-top:4px;">{info.get("gerekce","")[:60]}</div>'
                            f'</div>',
                            unsafe_allow_html=True)

                # ── 4. Hisse bazlı mikro kararlar ────────────────────────
                _hk = _sim_json.get("hisse_bazli_kararlar", [])
                if _hk:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                        'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">🎯 HİSSE BAZLI MİKRO KARARLAR</div>',
                        unsafe_allow_html=True)
                    for _hisse in _hk:
                        _kr   = _hisse.get("karar","KORU")
                        _kc   = _karar_renk.get(_kr, "#8a9ab0")
                        _tags = _hisse.get("etiketler", [])
                        _tag_html = " ".join(
                            f'<span style="background:#1e2833;border:1px solid #4fc3f755;'
                            f'border-radius:3px;padding:1px 6px;font-size:0.65rem;color:#4fc3f7;">{t}</span>'
                            for t in _tags
                        )
                        st.markdown(
                            f'<div style="border-left:3px solid {_kc};padding:0.4rem 0.8rem;'
                            f'background:#1a2332;border-radius:0 6px 6px 0;margin-bottom:0.3rem;">'
                            f'<span style="font-weight:700;color:{_kc};">{_kr}</span> '
                            f'<b style="color:#e8edf3;">{_hisse.get("ticker","")}</b> '
                            f'{_tag_html} '
                            f'<span style="color:#8a9ab0;font-size:0.78rem;">'
                            f'FCF: {_hisse.get("fcf_durumu","N/A")} — {_hisse.get("gerekce","")}</span>'
                            f'</div>',
                            unsafe_allow_html=True)

                # ── 5. TEFAS look-through kararları ──────────────────────
                _tk = _sim_json.get("tefas_kararlari", [])
                if _tk:
                    st.markdown(
                        '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                        'letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">🇹🇷 TEFAS LOOK-THROUGH</div>',
                        unsafe_allow_html=True)
                    for _tf in _tk:
                        _tkr  = _tf.get("karar","TUT")
                        _tkc  = _karar_renk.get(_tkr, "#8a9ab0")
                        _duy  = _tf.get("resesyon_duyarlilik","?")
                        _duyc = "#e74c3c" if any(x in _duy for x in ["YÜKSEK","YUKSEK","YOK"]) else "#00c48c"
                        st.markdown(
                            f'<div style="border-left:3px solid {_tkc};padding:0.4rem 0.8rem;'
                            f'background:#1a2332;border-radius:0 6px 6px 0;margin-bottom:0.3rem;">'
                            f'<span style="font-weight:700;color:{_tkc};">{_tkr}</span> '
                            f'<b style="color:#e8edf3;">{_tf.get("ticker","")}</b> '
                            f'<span style="color:#8a9ab0;font-size:0.75rem;">{_tf.get("icerik","")}</span> '
                            f'<span style="background:{_duyc}22;color:{_duyc};border-radius:3px;'
                            f'padding:1px 5px;font-size:0.65rem;">Resesyon: {_duy}</span> — '
                            f'<span style="color:#8a9ab0;font-size:0.78rem;">{_tf.get("gerekce","")}</span>'
                            f'</div>',
                            unsafe_allow_html=True)

                # ── 6. Korelasyon sigortası ──────────────────────────────
                _ks = _sim_json.get("korelasyon_sigortasi", {})
                if _ks and _ks.get("aktif"):
                    st.warning(
                        f"⚠️ **Korelasyon Sigortası Aktif** — {_ks.get('neden','')} "
                        f"| Nakit artırım: +%{_ks.get('nakit_artirim_pp', 0)}")

                # ── 7. Zamanlama ─────────────────────────────────────────
                _zam = _sim_json.get("zamanlama", "")
                _zam_color = {"hemen":"#e74c3c","kademeli_1hafta":"#ffb300",
                              "bekle_teyit":"#4fc3f7"}.get(_zam, "#8a9ab0")
                st.markdown(
                    f'<div style="margin:0.8rem 0;padding:0.6rem 1rem;background:#1a2332;border-radius:6px;">'
                    f'<span style="color:{_zam_color};font-weight:700;">'
                    f'⏱ {_zam.replace("_"," ").upper()}</span>'
                    f' — {_sim_json.get("zamanlama_gerekce","")}</div>',
                    unsafe_allow_html=True)

                # ── 8. Kritik aksiyonlar ─────────────────────────────────
                _aksiyonlar = _sim_json.get("kritik_aksiyonlar", [])
                if _aksiyonlar:
                    st.markdown("**🎯 Kritik Aksiyonlar:**")
                    for _ak in _aksiyonlar:
                        _pr = _ak.get("oncelik", 0)
                        _cl = "#e74c3c" if _pr == 1 else ("#ffb300" if _pr == 2 else "#4fc3f7")
                        st.markdown(
                            f'<div style="border-left:3px solid {_cl};padding:0.5rem 0.8rem;'
                            f'background:#1a2332;border-radius:0 6px 6px 0;margin-bottom:0.3rem;">'
                            f'<b style="color:{_cl};">#{_pr} {_ak.get("ticker","")}</b> — '
                            f'{_ak.get("aksiyon","")} '
                            f'<span style="color:#8a9ab0;font-size:0.78rem;">({_ak.get("neden","")})</span>'
                            f'</div>',
                            unsafe_allow_html=True)

                # ── 9. Alt bilgiler ──────────────────────────────────────
                _rb1, _rb2 = st.columns(2)
                with _rb1:
                    st.success(f"✅ **Senaryo Sonu:** {_sim_json.get('senaryo_sonu_sinyali','')}")
                with _rb2:
                    _risk_txt = _sim_json.get("en_buyuk_yanilma_riski") or _sim_json.get("en_buyuk_risk","")
                    st.warning(f"⚠️ **Yanılma Riski:** {_risk_txt}")

    # Strateji çalıştır — İKİ AŞAMALI SİSTEM
    if _run_strategy:
        # Progress takibi için
        _prog_bar  = st.progress(0)
        _prog_text = st.empty()

        def _two_phase_progress(step, total, message):
            _prog_bar.progress(step / total)
            _prog_text.markdown(
                f'<div style="font-size:0.75rem;color:#4fc3f7;">'
                f'⚙️ Adım {step}/{total}: {message}</div>',
                unsafe_allow_html=True,
            )

        try:
            from breakout_scanner import load_watchlist as _lw_strat
            from strategy_data    import collect_all_strategy_data
            from signal_engine    import generate_all_signals
            from strategy_director import run_two_phase_analysis

            _watchlist_tickers = _lw_strat()
            _port_enriched = [
                {**p, "current_price": p.get("current_price", p.get("avg_cost", 0))}
                for p in _port_now if float(p.get("shares", 0)) > 0
            ]

            # Kullanıcı profili
            _user_profile_strat = {
                "time_horizon":    _time_horizon,
                "risk_tol":        _risk_tol,
                "cash_cycle":      _cash_cycle,
                "goal":            _goal,
                "year_target_pct": float(st.session_state.get("st_year_target", 40.0)),
            }

            _two_phase_progress(1, 8, "Tüm veriler toplanıyor...")

            # Tüm veri topla — paralel mod, veri kalitesi raporlu
            _strat_data = collect_all_strategy_data(
                positions          = _port_enriched,
                watchlist_tickers  = _watchlist_tickers,
                cash               = _cash_now,
            )
            _strat_data["user_profile"] = _user_profile_strat

            # Veri kalitesi kontrolü — hangi katman başarılı, hangisi hatalı
            _vk = _strat_data.get("veri_kalitesi", {})
            _sure = _vk.get("_sure_sn", "?")
            _hatali = {k: v for k, v in _vk.items()
                       if k != "_sure_sn" and "HATA" in str(v)}
            _prog_text.markdown(
                f'<div style="font-size:0.75rem;color:#4fc3f7;">✅ Veri toplama tamamlandı '
                f'({_sure}s) — {len(_vk)-1} katman | '
                + (f'<span style="color:#ffb300;">⚠️ {len(_hatali)} katman hatalı: '
                   + ", ".join(_hatali.keys()) + '</span>' if _hatali else
                   '<span style="color:#00c48c;">Tüm katmanlar sağlıklı</span>')
                + '</div>',
                unsafe_allow_html=True,
            )

            _two_phase_progress(2, 8, "Sinyal motoru çalışıyor...")

            # Sinyal motoru
            try:
                _signals = generate_all_signals(
                    macro_data      = _strat_data.get("macro",     {}),
                    economic_data   = _strat_data,
                    crypto_data     = _strat_data.get("crypto",    {}),
                    commodity_data  = _strat_data.get("commodity", {}),
                    turkey_data     = _strat_data.get("turkey",    {}),
                    portfolio_data  = _strat_data.get("portfolio", {}),
                    year_target_pct = float(_user_profile_strat.get("year_target_pct", 40)),
                )
                _strat_data["signals"] = _signals
            except Exception as _se:
                logger.warning("Signal engine failed: %s", _se)
                _strat_data["signals"] = {}

            # İki aşamalı analiz
            _two_phase_result = run_two_phase_analysis(
                all_data          = _strat_data,
                progress_callback = lambda s, t, m: _two_phase_progress(s + 2, t + 2, m),
            )

            _prog_bar.progress(1.0)
            _prog_text.empty()

            st.session_state["two_phase_result"] = _two_phase_result
            st.session_state["two_phase_data"]   = _strat_data

            if _two_phase_result.get("success"):
                # Arşivle
                from analysis_memory import save_strategy_to_archive
                _dir_out = _two_phase_result.get("director", {})
                save_strategy_to_archive(
                    strategy        = _dir_out,
                    portfolio_value = _port_val_now,
                    cash            = _cash_now,
                    summary         = _dir_out.get("piyasa_ozeti", "")[:150],
                )
                from datetime import datetime as _dt_strat
                st.session_state["strategy_generated_at"] = _dt_strat.now().strftime("%Y-%m-%d %H:%M")
                st.success("✅ İki aşamalı analiz tamamlandı ve arşivlendi!")
                st.rerun()
            else:
                st.error("Analiz başarısız oldu.")

        except Exception as _e:
            _prog_bar.empty()
            _prog_text.empty()
            st.error(f"Hata: {_e}")
            import traceback
            st.code(traceback.format_exc())

    # ── Katman 4: Strateji Görüntüleme — YENİ İKİ AŞAMALI FORMAT ─────────
    _tpr = st.session_state.get("two_phase_result", {})
    if _tpr and _tpr.get("success"):
        _dir = _tpr.get("director", {})
        _ar  = _tpr.get("analyst_reports", {})

        # Sinyal renk haritası — tüm bölümlerde kullanılır
        _sig_colors = {
            "AL": "#00c48c", "GÜÇLÜ AL": "#00c48c", "ARTIR": "#4fc3f7",
            "TUT": "#8a9ab0", "BEKLE": "#ffb300",
            "AZALT": "#ff8c00", "SAT": "#e74c3c", "GÜÇLÜ SAT": "#c0392b",
        }

        # ── BÖLÜM 1: PİYASA ÖZETİ + ANALİST SENTEZİ ─────────────────────
        # Kullanıcı buraya önce bakıyor — en büyük, en net kısım
        _poz = _dir.get("piyasa_ozeti", "")
        if _poz:
            st.markdown(
                f'<div style="background:var(--color-background-secondary);'
                f'border-left:4px solid #4fc3f7;border-radius:0 12px 12px 0;'
                f'padding:1rem 1.2rem;margin:1rem 0;font-size:0.85rem;line-height:1.7;">'
                f'<div style="font-size:0.6rem;color:#4fc3f7;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:6px;">'
                f'🌍 PİYASA ÖZETİ</div>{_poz}</div>',
                unsafe_allow_html=True,
            )

        # Analist sentezi — 5 analist tek satırda
        _as = _dir.get("analist_sentezi", {})
        if _as:
            st.markdown(
                '<div style="font-size:0.6rem;color:#5a6a7a;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">'
                '📊 ANALİST SENTEZİ</div>',
                unsafe_allow_html=True,
            )
            _as_cols = st.columns(5)
            _as_items = [
                ("🌍 Makro",        _as.get("makro",     {})),
                ("🇺🇸 ABD Hisse",   _as.get("abd_hisse", {})),
                ("₿  Kripto",       _as.get("kripto",    {})),
                ("🥇 Emtia",        _as.get("emtia",     {})),
                ("🇹🇷 Türkiye",     _as.get("turkiye",   {})),
            ]
            for i, (label, item) in enumerate(_as_items):
                with _as_cols[i]:
                    sinyal = item.get("sinyal", "—")
                    gerek  = item.get("gerekcce", item.get("gerekçe", ""))[:60]
                    color  = _sig_colors.get(sinyal, "#8a9ab0")
                    st.markdown(
                        f'<div style="background:var(--color-background-secondary);'
                        f'border-top:3px solid {color};border-radius:4px;'
                        f'padding:0.6rem;text-align:center;">'
                        f'<div style="font-size:0.65rem;color:#8a9ab0;">{label}</div>'
                        f'<div style="font-size:1rem;font-weight:700;color:{color};">{sinyal}</div>'
                        f'<div style="font-size:0.62rem;color:#5a6a7a;margin-top:4px;">{gerek}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        # Analist detayları
        if _ar:
            with st.expander("🔬 Analist Raporları Detayı", expanded=False):
                for _ar_key, _ar_label in [
                    ("makro", "🌍 Makro"), ("abd", "🇺🇸 ABD Hisse"),
                    ("kripto", "₿ Kripto"), ("emtia", "🥇 Emtia"), ("turkiye", "🇹🇷 Türkiye")
                ]:
                    _rep = _ar.get(_ar_key, {})
                    if not _rep:
                        continue
                    sinyal = _rep.get("sinyal", "—")
                    color  = _sig_colors.get(sinyal, "#8a9ab0")
                    st.markdown(
                        f'<div style="border-left:3px solid {color};padding:0.5rem 0.8rem;'
                        f'margin-bottom:0.6rem;background:var(--color-background-secondary);'
                        f'border-radius:0 6px 6px 0;">'
                        f'<b style="color:{color};">{_ar_label}: {sinyal}</b> '
                        f'(Güven: {_rep.get("guven","?")}/10)<br>'
                        f'<span style="font-size:0.75rem;">{_rep.get("ana_gerekcce","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    for _d in _rep.get("destekleyen", [])[:2]:
                        st.markdown(f'<div style="font-size:0.7rem;color:#00c48c;padding-left:1rem;">✅ {_d}</div>', unsafe_allow_html=True)
                    for _r in _rep.get("riskler", [])[:2]:
                        st.markdown(f'<div style="font-size:0.7rem;color:#ffb300;padding-left:1rem;">⚠️ {_r}</div>', unsafe_allow_html=True)
                    if _rep.get("oneri"):
                        st.caption(f"Öneri: {_rep['oneri']}")

        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1rem 0;">', unsafe_allow_html=True)

        # ── BÖLÜM 2: ÇELİŞKİLER ─────────────────────────────────────────
        _cel = _dir.get("celiskiler", [])
        if _cel:
            st.markdown(
                '<div style="font-size:0.6rem;color:#ffb300;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.4rem;">'
                '⚡ ÇELİŞKİ ÇÖZÜMÜ</div>',
                unsafe_allow_html=True,
            )
            for _c in _cel:
                st.markdown(
                    f'<div style="background:#2b1f00;border-left:3px solid #ffb300;'
                    f'border-radius:0 8px 8px 0;padding:0.6rem 0.8rem;margin-bottom:0.4rem;">'
                    f'<b style="color:#ffb300;">{_c.get("baslik","")}</b><br>'
                    f'<span style="font-size:0.73rem;">{_c.get("aciklama","")}</span><br>'
                    f'<span style="font-size:0.7rem;color:#4fc3f7;">→ Karar: {_c.get("karar","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1rem 0;">', unsafe_allow_html=True)

        # ── BÖLÜM 3: PORTFÖY AKSİYONLARI ────────────────────────────────
        _pa = _dir.get("portfoy_aksiyonlari", {})
        if _pa:
            st.markdown(
                '<div style="font-size:0.6rem;color:#e74c3c;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.6rem;">'
                '🎯 AKSİYON PLANI</div>',
                unsafe_allow_html=True,
            )
            _ac1, _ac2, _ac3 = st.columns(3)

            # Hemen yap
            with _ac1:
                st.markdown('<div style="font-size:0.65rem;color:#e74c3c;font-weight:600;margin-bottom:6px;">🔴 HEMEN YAP</div>', unsafe_allow_html=True)
                for _item in _pa.get("hemen_yap", []):
                    _ticker = _item.get("ticker", "") or _item.get("varlik_sinifi", "")
                    _eylem  = _item.get("eylem",  "")
                    _neden  = _item.get("neden",  "")[:70]
                    _sl     = _item.get("stop_loss")
                    _hedef  = _item.get("hedef")
                    _miktar = _item.get("miktar_pct", 0)
                    st.markdown(
                        f'<div style="font-size:0.73rem;padding:5px 0;'
                        f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                        f'<b>{_ticker}</b> — {_eylem}'
                        + (f' %{_miktar}' if _miktar else '')
                        + f'<br><span style="color:var(--color-text-tertiary);font-size:0.65rem;">{_neden}</span>'
                        + (f'<br><span style="font-size:0.62rem;color:#ffb300;">SL: ${_sl:,.0f}</span>' if _sl else '')
                        + (f' <span style="font-size:0.62rem;color:#00c48c;">Hedef: ${_hedef:,.0f}</span>' if _hedef else '')
                        + f'</div>',
                        unsafe_allow_html=True,
                    )
                if not _pa.get("hemen_yap"):
                    st.caption("Acil aksiyon yok")

            # Koşullu yap
            with _ac2:
                st.markdown('<div style="font-size:0.65rem;color:#ffb300;font-weight:600;margin-bottom:6px;">🟡 KOŞULLU YAP</div>', unsafe_allow_html=True)
                for _item in _pa.get("kosullu_yap", []):
                    _kosul  = _item.get("kosul",  "")[:60]
                    _eylem  = _item.get("eylem",  "")
                    _ticker = _item.get("ticker", "")
                    st.markdown(
                        f'<div style="font-size:0.73rem;padding:5px 0;'
                        f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                        f'<span style="color:#ffb300;font-size:0.65rem;">Koşul: {_kosul}</span><br>'
                        f'<b>{_ticker}</b> {_eylem}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                if not _pa.get("kosullu_yap"):
                    st.caption("Koşullu aksiyon yok")

            # İzle/karar ver
            with _ac3:
                st.markdown('<div style="font-size:0.65rem;color:#4fc3f7;font-weight:600;margin-bottom:6px;">🔵 İZLE / KARAR VER</div>', unsafe_allow_html=True)
                for _item in _pa.get("izle_karar_ver", []):
                    _varlik    = _item.get("varlik",    "")
                    _izlenecek = _item.get("izlenecek", "")[:60]
                    _eylem     = _item.get("eylem",     "")
                    st.markdown(
                        f'<div style="font-size:0.73rem;padding:5px 0;'
                        f'border-bottom:0.5px solid var(--color-border-tertiary);">'
                        f'<b>{_varlik}</b><br>'
                        f'<span style="color:#4fc3f7;font-size:0.65rem;">{_izlenecek}</span><br>'
                        f'<span style="font-size:0.65rem;">→ {_eylem}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                if not _pa.get("izle_karar_ver"):
                    st.caption("İzleme listesi boş")

            # Nakit oranı
            _nakit = _pa.get("nakit_orani", {})
            if _nakit:
                _nakit_mev = _nakit.get("mevcut_pct",   0)
                _nakit_one = _nakit.get("onerilen_pct",  15)
                _nakit_ren = "#e74c3c" if _nakit_mev < _nakit_one - 5 else "#00c48c"
                st.markdown(
                    f'<div style="background:var(--color-background-secondary);'
                    f'border-radius:8px;padding:0.5rem 0.8rem;margin-top:0.6rem;font-size:0.73rem;">'
                    f'💵 <b>Nakit:</b> Mevcut %{_nakit_mev:.0f} → '
                    f'<span style="color:{_nakit_ren};">Önerilen %{_nakit_one:.0f}</span>'
                    f' — {_nakit.get("neden","")[:80]}</div>',
                    unsafe_allow_html=True,
                )

        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1rem 0;">', unsafe_allow_html=True)

        # ── BÖLÜM 4: RİSK SENARYOSU ──────────────────────────────────────
        _rs = _dir.get("risk_senaryosu", {})
        if _rs:
            with st.expander(f"🚨 Risk Senaryosu — {_rs.get('tetikleyici','')[:60]}", expanded=False):
                _rs1, _rs2 = st.columns(2)
                with _rs1:
                    st.markdown('<div style="font-size:0.65rem;color:#e74c3c;font-weight:600;margin-bottom:4px;">🚨 İlk 24 Saat</div>', unsafe_allow_html=True)
                    for _a in _rs.get("ilk_24_saat", []):
                        st.markdown(f'<div style="font-size:0.73rem;padding:3px 0;">• {_a}</div>', unsafe_allow_html=True)
                    st.markdown('<div style="font-size:0.65rem;color:#ffb300;font-weight:600;margin:8px 0 4px;">🛡️ Savunma</div>', unsafe_allow_html=True)
                    for _a in _rs.get("savunma", []):
                        st.markdown(f'<div style="font-size:0.73rem;padding:3px 0;">• {_a}</div>', unsafe_allow_html=True)
                with _rs2:
                    st.markdown('<div style="font-size:0.65rem;color:#00c48c;font-weight:600;margin-bottom:4px;">🎯 Alım Fırsatları</div>', unsafe_allow_html=True)
                    for _f in _rs.get("firsat_listesi", []):
                        st.markdown(
                            f'<div style="font-size:0.73rem;padding:3px 0;">'
                            f'<b>{_f.get("ticker","")}</b> ${_f.get("seviye",0):,.0f} — {_f.get("neden","")[:50]}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown('<div style="font-size:0.65rem;color:#4fc3f7;font-weight:600;margin:8px 0 4px;">📈 Toparlanma Sinyali</div>', unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:0.73rem;">{_rs.get("toparlanma_sinyali","")}</div>', unsafe_allow_html=True)

        # ── BÖLÜM 5: VADE PLANLARI ───────────────────────────────────────
        _vp = _dir.get("vade_planlari", {})
        if _vp:
            st.markdown(
                '<div style="font-size:0.6rem;color:#8a9ab0;font-weight:700;'
                'text-transform:uppercase;letter-spacing:0.1em;margin:0.8rem 0 0.4rem;">'
                '📅 VADE PLANLARI</div>',
                unsafe_allow_html=True,
            )
            _vp1, _vp2, _vp3 = st.columns(3)
            for _col, _key, _label, _color in [
                (_vp1, "kisa",  "📅 Kısa Vade (1-3 Ay)",   "#4fc3f7"),
                (_vp2, "orta",  "📆 Orta Vade (3-12 Ay)",  "#ffb300"),
                (_vp3, "uzun",  "🗓 Uzun Vade (1-3 Yıl)",  "#00c48c"),
            ]:
                _vd = _vp.get(_key, {})
                with _col:
                    st.markdown(
                        f'<div style="background:var(--color-background-secondary);'
                        f'border-top:3px solid {_color};border-radius:4px;padding:0.7rem;">'
                        f'<div style="font-size:0.65rem;color:{_color};font-weight:600;">{_label}</div>'
                        f'<div style="font-size:0.65rem;color:#8a9ab0;margin:4px 0 2px;">Ana Senaryo</div>'
                        f'<div style="font-size:0.72rem;">{_vd.get("baz_senaryo", _vd.get("tema",""))[:120]}</div>'
                        f'<div style="font-size:0.65rem;color:#ffb300;margin:4px 0 2px;">Risk Senaryosu</div>'
                        f'<div style="font-size:0.72rem;">{_vd.get("risk_senaryosu", _vd.get("pozisyonlama",""))[:120]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown('<hr style="border-color:var(--color-border-tertiary);margin:1rem 0;">', unsafe_allow_html=True)

        # ── BÖLÜM 6: YIL SONU HEDEFİ ────────────────────────────────────
        _yt = _dir.get("yil_sonu_hedefi", {})
        if _yt:
            _yt_c1, _yt_c2, _yt_c3, _yt_c4 = st.columns(4)
            with _yt_c1:
                st.metric("Hedef", f"%{_yt.get('hedef_pct',40):.0f}")
            with _yt_c2:
                st.metric("Mevcut", f"%{_yt.get('mevcut_pct',0):+.1f}")
            with _yt_c3:
                st.metric("Kalan", f"%{_yt.get('kalan_pct',0):.1f}")
            with _yt_c4:
                st.metric("Aylık Gereken", f"%{_yt.get('gerekan_aylik_pct',0):.1f}")
            if _yt.get("tavsiye"):
                st.info(_yt["tavsiye"])

        # ── BÖLÜM 7: BİR SONRAKİ KONTROL ────────────────────────────────
        _snk = _dir.get("bir_sonraki_kontrol", {})
        if _snk and _snk.get("tarih"):
            st.markdown(
                f'<div style="background:#0d2b1a;border:1px solid #00c48c44;'
                f'border-radius:8px;padding:0.8rem 1rem;margin-top:0.5rem;">'
                f'<div style="font-size:0.65rem;color:#00c48c;font-weight:700;'
                f'text-transform:uppercase;margin-bottom:4px;">📅 BİR SONRAKİ KONTROL</div>'
                f'<div style="font-size:0.85rem;font-weight:600;">{_snk.get("tarih","")}</div>'
                f'<div style="font-size:0.73rem;color:#8a9ab0;">{_snk.get("neden","")}</div>',
                unsafe_allow_html=True,
            )
            for _t in _snk.get("tetikleyiciler", [])[:3]:
                _tip   = _t.get("tip",   "")
                _acik  = _t.get("aciklama", "")
                _esik  = _t.get("esik",  "")
                _tip_emoji = {"fiyat": "💰", "takvim": "📅", "durum": "📊"}.get(_tip, "•")
                st.markdown(
                    f'<div style="font-size:0.7rem;padding:2px 0;">'
                    f'{_tip_emoji} {_acik}'
                    + (f' — <b>{_esik}</b>' if _esik else '')
                    + f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

        # ── Senaryo Olasılıklandırması ────────────────────────────────────
        _so = _dir.get("senaryo_olasiliklari", {})
        _hs = _dir.get("harmonize_strateji", "")
        _ks = _dir.get("korelasyon_sigortasi", {})
        if _so or _hs:
            st.markdown(
                '<div style="font-size:0.65rem;color:#5a6a7a;text-transform:uppercase;'
                'letter-spacing:0.1em;margin:1rem 0 0.4rem;">🎲 SENARYO OLASILILANDIRMASI</div>',
                unsafe_allow_html=True)
            if _so:
                _sc1, _sc2, _sc3 = st.columns(3)
                for _col, _key, _label, _color in [
                    (_sc1, "baz",        "Baz Senaryo",   "#00c48c"),
                    (_sc2, "alternatif", "Alternatif",     "#ffb300"),
                    (_sc3, "kuyruk",     "Kuyruk Riski",   "#e74c3c"),
                ]:
                    _sd = _so.get(_key, {})
                    if _sd:
                        with _col:
                            st.markdown(
                                f'<div style="background:#1a2332;border-top:3px solid {_color};'
                                f'border-radius:6px;padding:0.7rem;text-align:center;">'
                                f'<div style="font-size:0.62rem;color:{_color};font-weight:700;">'
                                f'{_label}</div>'
                                f'<div style="font-size:1.1rem;font-weight:700;color:#e8edf3;">'
                                f'%{_sd.get("olasilik_pct",0)}</div>'
                                f'<div style="font-size:0.72rem;color:#b0bec5;">'
                                f'{_sd.get("tanim","")}</div>'
                                f'<div style="font-size:0.72rem;color:{_color};">'
                                f'{_sd.get("portfoy_etkisi","")}</div>'
                                f'</div>',
                                unsafe_allow_html=True)
            if _hs:
                st.markdown(
                    f'<div style="background:#111927;border-left:3px solid #ce93d8;'
                    f'border-radius:0 6px 6px 0;padding:0.6rem 1rem;margin-top:0.5rem;'
                    f'font-size:0.82rem;color:#e8edf3;">🎯 {_hs}</div>',
                    unsafe_allow_html=True)

        # ── Korelasyon Sigortası ──────────────────────────────────────────
        if _ks and _ks.get("aktif"):
            st.warning(
                f"⚠️ **Korelasyon Sigortası Aktif** — {_ks.get('neden','')} "
                f"| Nakit artırım önerisi: +%{_ks.get('nakit_artirim_pct',0)}"
            )

        # ── HTML Export ───────────────────────────────────────────────────
        st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
        from datetime import datetime as _dt_strat2
        _export_ts = _dt_strat2.now().strftime("%Y-%m-%d %H:%M")
        _html_report = _generate_strategy_html(
            director        = _dir,
            analyst_reports = _ar,
            portfolio_value = _port_val_now,
            generated_at    = _export_ts,
        )
        st.download_button(
            label="📄 Raporu İndir (HTML)",
            data=_html_report.encode("utf-8"),
            file_name=f"strateji_{_dt_strat2.now().strftime('%Y-%m-%d')}.html",
            mime="text/html",
            key="dl_strategy_html",
            use_container_width=False,
        )

