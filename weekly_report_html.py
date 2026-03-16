# weekly_report_html.py — Haftalık Rapor HTML Generator
#
# Güzel, yazdırılabilir HTML rapor üretir.
# Tarayıcıdan Ctrl+P → PDF olarak kaydet → mükemmel çıktı.

from datetime import datetime


def _score_color(score: int) -> str:
    if score >= 75: return "#00a86b"
    if score >= 55: return "#f5a623"
    return "#e74c3c"


def _rec_badge(rec: str) -> str:
    colors = {
        "Ağırlık Artır": ("#00a86b", "#e8f8f3"),
        "Tut":           ("#f5a623", "#fef9ee"),
        "Azalt":         ("#e74c3c", "#fdf0ef"),
    }
    bg, fg_bg = colors.get(rec, ("#888", "#f5f5f5"))
    return (f'<span style="background:{fg_bg};color:{bg};border:1px solid {bg}33;'
            f'padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;">{rec}</span>')


def generate_weekly_html(report: dict) -> str:
    """
    Haftalık rapor dict'inden print-ready HTML üret.
    """
    report_type = report.get("type", "portfolio")
    date_str    = report.get("date", datetime.now().strftime("%Y-%m-%d"))
    results     = report.get("results", [])
    macro       = report.get("macro", {})
    summary     = report.get("summary", "")
    week        = report.get("week", "")

    type_labels = {
        "portfolio": ("💼 Portföy Raporu",   "#1a6ba0"),
        "surprise":  ("🔭 Sürpriz Radar",    "#7b3fa8"),
        "macro":     ("🌍 Makro Özet",        "#1a7a4a"),
    }
    title, accent = type_labels.get(report_type, ("📊 Rapor", "#333"))

    # ── Hisse kartları ────────────────────────────────────────────────────
    cards_html = ""
    for i, r in enumerate(results, 1):
        ticker   = r.get("hisse_sembolu") or r.get("ticker", "—")
        score    = int(r.get("nihai_guven_skoru", 0))
        ozet     = r.get("analiz_ozeti", "")
        tavsiye  = r.get("tavsiye", "Tut")
        kategori = r.get("kategori", "")
        risks    = r.get("kritik_riskler", {})
        macro_r  = risks.get("global_makro", "") if isinstance(risks, dict) else ""
        firm_r   = risks.get("finansal_sirket_ozel", "") if isinstance(risks, dict) else ""
        sc       = _score_color(score)
        badge    = _rec_badge(tavsiye)

        # Ek veriler
        price    = r.get("price", 0)
        rev_gr   = r.get("revenue_growth") or r.get("rev_gr", 0)
        beta_val = r.get("beta", 0)
        sector   = r.get("sector", "")
        ins_bon  = r.get("insider_bonus", 0)
        momentum = r.get("momentum_score", 0)
        fund_sc  = r.get("fund_score") or r.get("fundamental_score", 0)

        price_str  = f"${price:.2f}" if price else ""
        rev_str    = f"%{rev_gr*100:.0f} büyüme" if rev_gr else ""
        beta_str   = f"Beta {beta_val:.1f}" if beta_val else ""
        ins_str    = f"👔 Insider +{ins_bon:.0f}" if ins_bon and ins_bon > 0 else ""

        meta_parts = [x for x in [price_str, sector, rev_str, beta_str] if x]
        meta_line  = "  ·  ".join(meta_parts)

        cards_html += f"""
        <div class="card">
          <div class="card-header">
            <div style="display:flex;align-items:center;gap:12px;">
              <div class="rank">#{i}</div>
              <div>
                <div class="ticker">{ticker}</div>
                <div class="kategori">{kategori}</div>
                {"<div class='meta-line'>" + meta_line + "</div>" if meta_line else ""}
              </div>
            </div>
            <div style="text-align:right;">
              <div class="score" style="color:{sc};">{score}</div>
              <div class="score-label">/ 100</div>
              {badge}
              {('<div class="insider-badge">' + ins_str + '</div>') if ins_str else ''}
            </div>
          </div>
          <div class="ozet">{ozet}</div>
          {"<div class='risk-row'><span class='risk-label'>🌍 Makro Risk:</span> " + macro_r + "</div>" if macro_r else ""}
          {"<div class='risk-row'><span class='risk-label'>🏢 Şirket Riski:</span> " + firm_r + "</div>" if firm_r else ""}
          {f'<div class="score-bar-wrap"><div class="score-bar-fill" style="width:{score}%"></div></div>' if score else ''}
        </div>
        """

    # ── Makro özet ────────────────────────────────────────────────────────
    macro_html = ""
    if macro:
        regime = macro.get("regime") or macro.get("label", "")
        macro_html = f"""
        <div class="macro-box">
          <div class="macro-title">🌍 Makro Ortam</div>
          <div class="macro-regime">{regime}</div>
        </div>
        """

    # ── Özet istatistik ───────────────────────────────────────────────────
    if results:
        scores  = [r.get("nihai_guven_skoru", 0) for r in results]
        avg_sc  = sum(scores) / len(scores)
        buy_cnt = sum(1 for r in results if "Artır" in r.get("tavsiye", ""))
        hold_cnt= sum(1 for r in results if r.get("tavsiye") == "Tut")
        sell_cnt= sum(1 for r in results if "Azalt" in r.get("tavsiye", ""))
        stats_html = f"""
        <div class="stats-row">
          <div class="stat-card"><div class="stat-n">{len(results)}</div><div class="stat-l">Analiz Edilen</div></div>
          <div class="stat-card"><div class="stat-n" style="color:#00a86b;">{buy_cnt}</div><div class="stat-l">Ağırlık Artır</div></div>
          <div class="stat-card"><div class="stat-n" style="color:#f5a623;">{hold_cnt}</div><div class="stat-l">Tut</div></div>
          <div class="stat-card"><div class="stat-n" style="color:#e74c3c;">{sell_cnt}</div><div class="stat-l">Azalt</div></div>
          <div class="stat-card"><div class="stat-n">{avg_sc:.0f}</div><div class="stat-l">Ort. Skor</div></div>
        </div>
        """
    else:
        stats_html = ""

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {date_str}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 13px;
      color: #1a1a2e;
      background: #fff;
      padding: 24px;
      max-width: 900px;
      margin: 0 auto;
    }}

    /* ── Başlık ── */
    .header {{
      border-bottom: 3px solid {accent};
      padding-bottom: 16px;
      margin-bottom: 20px;
    }}
    .header-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }}
    .report-title {{
      font-size: 22px;
      font-weight: 700;
      color: {accent};
    }}
    .report-meta {{
      font-size: 11px;
      color: #888;
      margin-top: 4px;
    }}
    .logo-text {{
      font-size: 11px;
      color: #888;
      text-align: right;
    }}

    /* ── İstatistik bar ── */
    .stats-row {{
      display: flex;
      gap: 12px;
      margin-bottom: 20px;
    }}
    .stat-card {{
      flex: 1;
      background: #f8f9fa;
      border: 1px solid #e9ecef;
      border-radius: 8px;
      padding: 10px 12px;
      text-align: center;
    }}
    .stat-n {{
      font-size: 20px;
      font-weight: 700;
      color: #1a1a2e;
    }}
    .stat-l {{
      font-size: 10px;
      color: #888;
      margin-top: 2px;
    }}

    /* ── Makro kutu ── */
    .macro-box {{
      background: #f0f7f4;
      border: 1px solid #b8ddd0;
      border-left: 4px solid #00a86b;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 20px;
    }}
    .macro-title {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }}
    .macro-regime {{ font-size: 14px; font-weight: 600; color: #1a1a2e; margin-top: 4px; }}

    /* ── Özet ── */
    .summary-box {{
      background: #f8f9fa;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 20px;
      font-size: 13px;
      color: #444;
      line-height: 1.6;
    }}

    /* ── Hisse kartları ── */
    .section-title {{
      font-size: 11px;
      font-weight: 600;
      color: #888;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-bottom: 12px;
      padding-bottom: 6px;
      border-bottom: 1px solid #eee;
    }}
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }}
    .card {{
      border: 1px solid #e9ecef;
      border-radius: 10px;
      padding: 14px 16px;
      page-break-inside: avoid;
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 10px;
    }}
    .rank {{
      font-size: 11px;
      color: #888;
      font-weight: 600;
    }}
    .ticker {{
      font-size: 17px;
      font-weight: 700;
      color: #1a1a2e;
    }}
    .kategori {{
      font-size: 11px;
      color: #888;
      margin-top: 1px;
    }}
    .score {{
      font-size: 26px;
      font-weight: 800;
      line-height: 1;
    }}
    .score-label {{
      font-size: 10px;
      color: #aaa;
      margin-bottom: 4px;
    }}
    .ozet {{
      font-size: 12px;
      color: #444;
      line-height: 1.6;
      margin-bottom: 8px;
    }}
    .risk-row {{
      font-size: 11px;
      color: #666;
      line-height: 1.5;
      margin-top: 4px;
    }}
    .risk-label {{
      font-weight: 600;
    }}

    /* ── Footer ── */
    .footer {{
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid #eee;
      font-size: 10px;
      color: #aaa;
      text-align: center;
    }}

    .meta-line {{
      font-size: 10px;
      color: #aaa;
      margin-top: 2px;
    }}
    .insider-badge {{
      font-size: 10px;
      color: #00a86b;
      font-weight: 600;
      margin-top: 3px;
    }}
    .score-bar-wrap {{
      height: 3px;
      background: #f0f0f0;
      border-radius: 2px;
      margin-top: 8px;
      overflow: hidden;
    }}
    .score-bar-fill {{
      height: 100%;
      background: linear-gradient(90deg, #00a86b, #f5a623, #e74c3c);
      background-size: 300px 100%;
      border-radius: 2px;
    }}

    /* ── Print ── */
    @media print {{
      body {{ padding: 12px; }}
      .cards-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .card {{ border: 1px solid #ddd; }}
      @page {{ margin: 1cm; size: A4; }}
    }}
  </style>
</head>
<body>

  <div class="header">
    <div class="header-top">
      <div>
        <div class="report-title">{title}</div>
        <div class="report-meta">📅 {date_str} &nbsp;·&nbsp; {week} &nbsp;·&nbsp; {len(results)} hisse analiz edildi</div>
      </div>
      <div class="logo-text">
        AI Destekli Hisse Analiz Dashboard<br>
        <span style="color:{accent};font-weight:600;">Stock Dashboard</span>
      </div>
    </div>
  </div>

  {macro_html}

  {"<div class='summary-box'>" + summary + "</div>" if summary else ""}

  {stats_html}

  {"<div class='section-title'>Hisse Analizleri</div><div class='cards-grid'>" + cards_html + "</div>" if results else ""}

  <div class="footer">
    Bu rapor yapay zeka destekli analiz sistemi tarafından otomatik olarak oluşturulmuştur.
    Yatırım tavsiyesi niteliği taşımaz. &nbsp;·&nbsp;
    Oluşturulma: {datetime.now().strftime("%d.%m.%Y %H:%M")}
  </div>

</body>
</html>"""

    return html
