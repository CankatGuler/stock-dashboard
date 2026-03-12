# app.py — AI-Powered Stock Analysis & Decision Dashboard
# Run with:  streamlit run app.py

import os
import time
import logging

import streamlit as st
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
from radar_engine import run_radar


def determine_category(stock: dict) -> str:
    """Yeni kategori sistemi: Rocket / Balanced / Shield — mktCap + Beta bazlı."""
    from utils import categorise_stock as _cat
    return _cat(stock)
from portfolio_manager import (
    load_portfolio, add_position, remove_position, update_position,
    sell_position, enrich_portfolio_with_prices, portfolio_summary,
    import_from_csv, export_to_csv, generate_csv_template,
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
selected_sectors = ["Savunma Sanayii"]
strategy         = "İkisi de"
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
tab_screener, tab_portfolio, tab_radar, tab_lookup = st.tabs(["📡  Sektör Tarayıcı", "💼  Portföyüm", "🔭  Fırsat Radarı", "🔍  Hisse Sorgula"])

# ─────────────────────────────────────────────────────────────────────────────
# STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
if "analysis_results" not in st.session_state:
    st.session_state["analysis_results"] = []
if "enriched_stocks"   not in st.session_state:
    st.session_state["enriched_stocks"]   = []
if "news_map"          not in st.session_state:
    st.session_state["news_map"]          = {}


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
                default=["Savunma Sanayii"],
                help="Analiz edilecek sektörleri seçin.",
            )
        with fc2:
            strategy = st.radio(
                "🎯 STRATEJİ",
                options=["Rocket 🚀", "Balanced ⚖️", "Shield 🛡️", "Hepsi"],
                index=2,
                horizontal=True,
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
                    f'<br>{recommendation_badge(tavsiye)}'
                    f'<div class="kpi-meta" style="margin-top:0.7rem;">'
                    f'  Sektör : {meta.get("sector","N/A")}<br>'
                    f'  Fiyat  : ${meta.get("price",0):.2f} ({meta.get("change_pct",0):+.1f}%)<br>'
                    f'  Mkt Cap: ${meta.get("mktCap",0)/1e9:.2f}B<br>'
                    f'  Beta   : {meta.get("beta",0):.2f}<br>'
                    f'  P/E    : {meta.get("peRatio",0):.1f}<br>'
                    f'  D/E    : {meta.get("debtToEquity",0):.2f}<br>'
                    f'  ROIC   : {meta.get("roic",0):.1%}<br>'
                    f'  FCF    : ${meta.get("freeCashFlow",0)/1e6:.0f}M'
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
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([1.2, 1, 1, 1.5, 1])
        with col_f1:
            p_ticker   = st.text_input("Ticker", placeholder="AAPL", key="p_ticker").upper().strip()
        with col_f2:
            p_shares   = st.number_input("Hisse Adedi", min_value=0.0, step=1.0, key="p_shares")
        with col_f3:
            p_cost     = st.number_input("Ortalama Maliyet ($)", min_value=0.0, step=0.01, key="p_cost")
        with col_f4:
            p_sector   = st.selectbox("Sektör", options=["Diğer"] + list(SECTOR_TICKERS.keys()), key="p_sector")
        with col_f5:
            p_notes    = st.text_input("Not", placeholder="İsteğe bağlı", key="p_notes")

        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            if st.button("💾  Kaydet", key="btn_add_pos"):
                if p_ticker and p_shares > 0 and p_cost > 0:
                    add_position(p_ticker, p_shares, p_cost, p_sector, p_notes)
                    st.success(f"✅ {p_ticker} portföye eklendi!")
                    st.rerun()
                else:
                    st.error("Ticker, hisse adedi ve maliyet zorunludur.")

    # ── Sell Position Form ──────────────────────────────────────────────────
    with st.expander("📉  Satış Yap (Pozisyon Azalt / Kapat)", expanded=False):
        st.markdown(
            '<div style="font-size:0.65rem;color:#5a6a7a;margin-bottom:0.8rem;">'
            'Kısmi satış: Adet gir → pozisyon azalır. '
            'Tam satış: Tüm adedi gir → pozisyon kapanır.'
            '</div>',
            unsafe_allow_html=True,
        )
        sell_col1, sell_col2, sell_col3 = st.columns([1.2, 1, 1.5])
        with sell_col1:
            s_ticker = st.text_input("Ticker", placeholder="AAPL", key="s_ticker").upper().strip()
        with sell_col2:
            s_shares = st.number_input("Satılan Adet", min_value=0.0, step=1.0, key="s_shares")
        with sell_col3:
            st.markdown('<div style="margin-top:1.65rem;"></div>', unsafe_allow_html=True)
            if st.button("📉  Satışı Onayla", key="btn_sell"):
                if s_ticker and s_shares > 0:
                    _, msg = sell_position(s_ticker, s_shares)
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
        # Fetch live prices for all portfolio tickers
        failed_tickers = []
        with st.spinner("📊 Canlı fiyatlar çekiliyor..."):
            price_map: dict[str, float] = {}
            change_map: dict[str, float] = {}
            for pos in positions:
                ticker_sym = pos["ticker"]
                q = get_quote(ticker_sym)
                if q and float(q.get("price", 0) or 0) > 0:
                    price_map[ticker_sym]  = float(q.get("price", 0))
                    change_map[ticker_sym] = float(q.get("changesPercentage", 0) or 0)
                else:
                    failed_tickers.append(ticker_sym)

        if failed_tickers:
            st.warning(
                f"⚠️ Şu hisseler için fiyat çekilemedi: **{', '.join(failed_tickers)}**  \n"
                "Olası nedenler: FMP ücretsiz plan limiti, ETF/yabancı hisse, "
                "veya yanlış ticker sembolü. Bu hisseler $0 olarak gösterilir.",
                icon="📡",
            )

        enriched_pos = enrich_portfolio_with_prices(positions, price_map)
        summary      = portfolio_summary(enriched_pos)

        # ── Summary KPI Bar ─────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)

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
                })

            df_port = pd.DataFrame(rows)

            def color_pnl(val):
                if isinstance(val, str) and val.startswith("+"):
                    return "color: #00c48c; font-weight: 600"
                if isinstance(val, str) and val.startswith("-"):
                    return "color: #e74c3c; font-weight: 600"
                return ""

            st.dataframe(
                df_port.style.map(color_pnl, subset=["K/Z ($)", "K/Z (%)"]),
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
