# strategy_engine.py — Claude Destekli Strateji Motoru
#
# Bu modül tüm veri kaynaklarını birleştirerek Claude'a gönderir ve
# somut bir aksiyon planı üretir:
#   - Ne sat / azalt (ve neden)
#   - Nakdi nereye dağıt (somut hisse, yüzde, fiyat hedefi)
#   - Koşullu senaryolar ("eğer X olursa Y yap")
#   - Kısa / orta / uzun vade planı

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─── System Prompt ───────────────────────────────────────────────────────────
# Bu prompt Claude'a tam olarak nasıl düşünmesi gerektiğini öğretiyor.
# Soyut değil, somut. "Değerlendirilebilir" değil, "%35 ile al, hedef $X, stop $Y".

STRATEGY_SYSTEM_PROMPT = """Sen deneyimli bir portföy yöneticisi ve kıdemli analistsin.
Görevin: verilen tüm verileri analiz edip bu yatırımcı için SOMUT bir aksiyon planı üretmek.

TEMEL KURALLAR:
1. Soyut tavsiye YASAK. "Değerlendirilebilir", "izlenebilir" gibi ifadeler kullanma.
   Doğru: "Nakdin %30'u ile LLY al, hedef $1,150, stop loss $920"
   Yanlış: "LLY potansiyel olarak değerlendirilebilir"

2. Her tavsiyenin gerekçesi olmalı. Neden satıyorsun, neden alıyorsun — tek cümle.

3. Çelişkileri tespit et ve çöz. Portföy analizi "azalt" ama analist "al" diyorsa
   bu çelişkiyi açıkla ve zaman ufkuna göre çöz.

4. Her vade planında (kisa_vade, orta_vade) "risk_aksiyonlar" alanı ZORUNLUDUR.
   Bu alan ASLA boş bırakılmaz. Şu formatta doldur:
   "Risk senaryosu gerçekleşirse: [hisse] [işlem] — örn: RKLB %100 kapat, nakdi %40a çıkar"
   Her risk_aksiyonlar listesinde somut hisse isimleri ve yüzdeler olmalı.
   Maksimum 150 karakter per madde.

4. Portföy önce gelir. Yeni alımdan önce mevcut pozisyonların sağlığını değerlendir.

5. Koşullu senaryolar somut olmalı. "AVGO $200'a gelirse" değil,
   "AVGO $195-205 bandına çekilirse nakdin %20'si ile al, bu seviyelerde RSI 35 olur ve
   analist hedefine %42 upside kalır"

6. Risk yönetimi şart. Her yeni alım için stop loss seviyesi belirt.

7. FOMC ve earnings tarihlerine dikkat et. Yaklaşan toplantı/açıklama varsa
   o hisse için "earnings sonrasına bekle" veya "FOMC öncesi pozisyon küçült" de.

8. risk_senaryosu_aksiyonlari ZORUNLU — bu alanı MUTLAKA doldur, boş bırakma.
   "Kötü senaryo gerçekleşirse ne yapmalısın?" sorusunu somut adımlarla yanıtla.
   tetikleyici: "VIX 35 üzerine çıkarsa VEYA Fed hawkish sürpriz yaparsa VEYA portföy
   %15 geriye giderse" gibi ölçülebilir koşullar belirt.
   acil_aksiyonlar: ilk 48 saatte kapatılacak pozisyonlar (somut ticker + fiyat).
   savunma_aksiyonlar: nakit oranını yükselt, stop-loss'ları sıkılaştır.
   firsat_aksiyonlar: hangi fiyat seviyelerinde hangi hisseye alım yapılabilir.
   recovery_isaretleri: toparlanma başladığını gösteren somut göstergeler.

9. Yanıtını kesinlikle JSON formatında ver, başka hiçbir şey yazma.
   KRİTİK: Her string alanı maksimum 150 karakter olsun. Uzun açıklama yazma.
   Aksiyonlar için "neden" alanı tek kısa cümle. Senaryolar 2-3 cümle.
   JSON mutlaka tam ve geçerli olmalı — yarıda kesilmiş JSON kabul edilmez.
   Yanıt:
{
  "ozet": "Tek paragraf genel durum özeti",
  "piyasa_degerlendirmesi": "Makro + sentiment + teknik genel bakış",
  "celiskiler": [
    {
      "hisse": "TICKER",
      "celisik_sinyaller": "Portföy skoru düşük AMA analist güçlü alım diyor",
      "cozum": "Kısa vadede azalt, uzun vadede fırsat olarak izle"
    }
  ],
  "aksiyonlar": {
    "sat_azalt": [
      {
        "ticker": "TICKER",
        "islem": "Azalt",
        "miktar_pct": 20,
        "gercekle": "Hemen / Koşullu",
        "konu_fiyat": 0,
        "neden": "Tek cümle gerekçe"
      }
    ],
    "al_arttir": [
      {
        "ticker": "TICKER",
        "islem": "Al",
        "nakit_pct": 30,
        "hedef_fiyat": 0,
        "stop_loss": 0,
        "kaynak": "watchlist / radar / sürpriz",
        "neden": "Tek cümle gerekçe"
      }
    ],
    "bekle_izle": [
      {
        "ticker": "TICKER",
        "kosul": "FOMC sonrası / $X seviyesine gelirse / RSI < 35 olursa",
        "islem": "Al / Arttır",
        "nakit_pct": 20,
        "neden": "Tek cümle gerekçe"
      }
    ],
    "nakit_rezerv_pct": 25,
    "nakit_rezerv_neden": "Neden bu kadar nakit tutulacak"
  },
  "kisa_vade": {
    "sure": "1-3 ay",
    "senaryo_baz": "Ana senaryo nedir — tek cümle",
    "senaryo_risk": "Risk senaryosu nedir — tek cümle (tetikleyici seviyeyle: VIX 32+ veya S&P -%8 gibi)",
    "aksiyonlar": ["Ana senaryoda yapılacaklar — en az 3 madde"],
    "risk_aksiyonlar": ["Risk senaryosu gerçekleşirse SOMUT adımlar — en az 3 madde, hisse isimleri ve yüzdelerle"]
  },
  "orta_vade": {
    "sure": "3-12 ay",
    "senaryo_baz": "Ana senaryo nedir — tek cümle",
    "senaryo_risk": "Risk senaryosu nedir — tek cümle",
    "aksiyonlar": ["Ana senaryoda yapılacaklar — en az 3 madde"],
    "risk_aksiyonlar": ["Risk senaryosu gerçekleşirse SOMUT adımlar — en az 2 madde"]
  },
  "uzun_vade": {
    "sure": "1-3 yıl",
    "hedef_portfoy": "İdeal portföy yapısı nasıl olmalı",
    "aksiyonlar": ["Madde madde uzun vade aksiyonları"]
  },
  "risk_uyarilari": ["Kritik risk uyarıları — kısa maddeler"],
  "guc_sinyalleri": ["Pozitif güçlü sinyaller — kısa maddeler"]
}"""


# ─── Veri Zenginleştirme ─────────────────────────────────────────────────────

def _enrich_with_weekly_reports(prompt_lines: list, weekly_reports: list) -> list:
    """
    Son haftalık raporlardan öne çıkan hisseleri prompt'a ekle.
    Sürpriz radar'da yüksek skor alan ama portföyde olmayan hisseler
    "fırsat" olarak işaretlenir.
    """
    if not weekly_reports:
        return prompt_lines

    prompt_lines.append("\n=== HAFTALIK RAPOR ÖZETI (Son 2 Rapor) ===")

    for report in weekly_reports[:2]:
        rtype   = report.get("type", "")
        rdate   = report.get("date", "")
        results = report.get("results", [])

        if not results:
            continue

        label = {"portfolio": "💼 Portföy", "surprise": "🔭 Sürpriz", "macro": "🌍 Makro"}.get(rtype, rtype)
        prompt_lines.append(f"\n{label} Raporu ({rdate}):")

        # En yüksek skorlu 5 hisseyi al
        top = sorted(results, key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True)[:5]
        for r in top:
            ticker  = r.get("hisse_sembolu") or r.get("ticker", "")
            score   = r.get("nihai_guven_skoru", 0)
            tavsiye = r.get("tavsiye", "")
            ozet    = r.get("analiz_ozeti", "")[:80]
            prompt_lines.append(f"  {ticker}: {score}/100 — {tavsiye} — {ozet}")

    return prompt_lines


def _enrich_with_radar(prompt_lines: list, radar_results: list) -> list:
    """
    Son fırsat radarı sonuçlarını prompt'a ekle.
    Yüksek radar skoru alan hisseler "fırsat listesi" olarak sunulur.
    """
    if not radar_results:
        return prompt_lines

    high = [r for r in radar_results if r.get("radar_score", 0) >= 65]
    if not high:
        return prompt_lines

    prompt_lines.append("\n=== FIRSAT RADARI (Yüksek Skorlu) ===")
    for r in sorted(high, key=lambda x: x["radar_score"], reverse=True)[:6]:
        ticker   = r.get("ticker", "")
        rscore   = r.get("radar_score", 0)
        neden    = r.get("neden", "")[:80]
        tavsiye  = r.get("tavsiye", "")
        pos_rec  = r.get("position_rec", {})
        action   = pos_rec.get("action", "")
        pos_pct  = pos_rec.get("position_pct", 0)
        prompt_lines.append(
            f"  {ticker}: Radar {rscore} — {tavsiye}"
            + (f" — Önerilen pozisyon: %{pos_pct:.0f}" if pos_pct > 0 else "")
            + f"\n    Neden: {neden}"
        )

    return prompt_lines


def _enrich_with_watchlist(prompt_lines: list, watchlist_data: list) -> list:
    """
    Watchlist tablosundaki hisseleri upside ve analist konsensüs ile ekle.
    Yüksek upside + güçlü konsensüs = öncelikli alım adayı.
    """
    if not watchlist_data:
        return prompt_lines

    # Upside'a göre sırala, yüksek olanları öne al
    high_upside = sorted(
        [w for w in watchlist_data if w.get("upside", 0) >= 10],
        key=lambda x: x["upside"], reverse=True
    )[:8]

    if not high_upside:
        return prompt_lines

    prompt_lines.append("\n=== TAKİP LİSTESİ (Yüksek Potansiyel) ===")
    for w in high_upside:
        ticker   = w.get("ticker", "")
        upside   = w.get("upside", 0)
        rec      = w.get("rec", "")
        n_an     = w.get("n_analysts", 0)
        trend    = w.get("trend", {})
        tr_dir   = trend.get("direction", "nötr")
        price    = w.get("price", 0)
        mean_tgt = w.get("mean", 0)

        trend_str = {
            "güçlü_yukarı": "⬆⬆ Hedef hızla yükseltiliyor",
            "yukarı":       "⬆ Hedef yükseltildi",
            "nötr":         "Stabil",
            "aşağı":        "⬇ Hedef düşürüldü",
            "güçlü_aşağı":  "⬇⬇ Hedef hızla düşürülüyor",
        }.get(tr_dir, "—")

        prompt_lines.append(
            f"  {ticker}: ${price:.2f} → Hedef ${mean_tgt:.2f} "
            f"(+%{upside:.0f} upside) | {rec} ({n_an} analist) | {trend_str}"
        )

    return prompt_lines


# ─── Ana Strateji Motoru ─────────────────────────────────────────────────────

def generate_strategy(
    strategy_data: dict,
    weekly_reports: list = None,
    radar_results:  list = None,
    watchlist_data: list = None,
    user_cash_to_deploy: float = 0,  # Bu dönem dağıtılacak nakit
) -> dict:
    """
    Claude'a tüm veriyi göndererek somut aksiyon planı üret.

    Dönüş:
    {
      "success": bool,
      "strategy": dict,   # Claude'un JSON çıktısı
      "prompt_used": str, # Debug için
      "generated_at": str,
      "error": str | None,
    }
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY eksik.", "strategy": {}}

    # Temel prompt'u oluştur
    from strategy_data import build_strategy_prompt
    base_prompt = build_strategy_prompt(strategy_data)

    # Ek veri kaynaklarını zenginleştir
    extra_lines = [base_prompt]
    extra_lines = _enrich_with_weekly_reports(extra_lines, weekly_reports or [])
    extra_lines = _enrich_with_radar(extra_lines, radar_results or [])
    extra_lines = _enrich_with_watchlist(extra_lines, watchlist_data or [])

    # Dağıtılacak nakit varsa ekle
    if user_cash_to_deploy > 0:
        extra_lines.append(
            f"\n=== BU DÖNEM DAĞITILACAK NAKİT ===\n"
            f"Yatırımcı bu strateji döneminde ${user_cash_to_deploy:,.0f} ek nakit dağıtmayı planlıyor.\n"
            f"Bu nakdi de alım önerilerine dahil et."
        )

    full_prompt = "\n".join(str(x) for x in extra_lines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=8000,  # Strateji detaylı olmalı — JSON kesilmesin
            system=STRATEGY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": full_prompt}],
        )

        raw = (message.content[0].text if message.content else "").strip()

        # JSON parse
        import re
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

        # JSON kesilmişse sonuna kapanış ekleyerek kurtarmayı dene
        try:
            strategy = json.loads(raw)
        except json.JSONDecodeError:
            # Kesik JSON'u kurtarmaya çalış — eksik parantezleri tamamla
            fixed = raw
            # Açık string varsa kapat
            open_brackets = fixed.count('{') - fixed.count('}')
            open_arrays   = fixed.count('[') - fixed.count(']')
            if open_arrays > 0:
                fixed += ']' * open_arrays
            if open_brackets > 0:
                fixed += '}' * open_brackets
            try:
                strategy = json.loads(fixed)
                logger.warning("JSON kurtarıldı (eksik %d parantez tamamlandı)", open_brackets)
            except json.JSONDecodeError as e2:
                raise json.JSONDecodeError(str(e2), raw, e2.pos)

        return {
            "success":      True,
            "strategy":     strategy,
            "prompt_used":  full_prompt[:500] + "...",  # İlk 500 karakter debug için
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error":        None,
        }

    except json.JSONDecodeError as e:
        logger.error("Strategy JSON parse failed: %s\nRaw: %s", e, raw[:500])
        return {
            "success": False,
            "error":   f"JSON parse hatası: {e}",
            "strategy": {},
            "raw_response": raw[:1000],
        }
    except Exception as e:
        logger.error("Strategy generation failed: %s", e)
        return {"success": False, "error": str(e), "strategy": {}}


# ─── Strateji Kaydetme ────────────────────────────────────────────────────────

def save_strategy(strategy_result: dict, portfolio_value: float, cash: float) -> bool:
    """
    Üretilen stratejiyi GitHub'a kaydet — geçmiş stratejileri takip etmek için.
    Dosya: strategy_history.json
    """
    try:
        import requests, base64, os as _os, json as _json

        token = _os.getenv("GH_PAT", "") or _os.getenv("GITHUB_TOKEN", "")
        repo  = _os.getenv("GITHUB_REPO", "")

        record = {
            "date":            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "generated_at":    strategy_result.get("generated_at", ""),
            "portfolio_value": portfolio_value,
            "cash":            cash,
            "strategy":        strategy_result.get("strategy", {}),
        }

        # Mevcut geçmişi oku
        history = []
        if token and repo:
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            url = f"https://api.github.com/repos/{repo}/contents/strategy_history.json"
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                content = base64.b64decode(r.json()["content"]).decode()
                history = _json.loads(content)

        history.append(record)
        history = history[-20:]  # Son 20 strateji

        # Kaydet
        content_str = _json.dumps(history, ensure_ascii=False, indent=2)
        encoded     = base64.b64encode(content_str.encode()).decode()

        if token and repo:
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            url = f"https://api.github.com/repos/{repo}/contents/strategy_history.json"
            sha = None
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                sha = r.json().get("sha")

            payload = {
                "message": f"strategy {record['date']}",
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            requests.put(url, headers=headers, json=payload, timeout=15)

        # Lokal fallback
        with open("strategy_history.json", "w") as f:
            _json.dump(history, f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        logger.warning("Strategy save failed: %s", e)
        return False


# ─── HTML / PDF Export ───────────────────────────────────────────────────────

def generate_strategy_html(strategy_result: dict, portfolio_value: float, cash: float) -> str:
    """
    Strateji sonucunu yazdırılabilir HTML'e dönüştür.
    Tarayıcıdan Ctrl+P → PDF olarak kaydet.
    """
    from datetime import datetime
    s          = strategy_result.get("strategy", {})
    gen_at     = strategy_result.get("generated_at", "")[:16]
    aks        = s.get("aksiyonlar", {})
    now_str    = datetime.now().strftime("%d.%m.%Y %H:%M")

    def _badge(text, color):
        return f'<span style="background:{color}22;color:{color};border:1px solid {color}44;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;">{text}</span>'

    # Çelişkiler
    celiski_html = ""
    for c in s.get("celiskiler", []):
        celiski_html += f"""
        <div class="conflict-card">
          <b>{c.get('hisse','')}</b> — {c.get('celisik_sinyaller','')}
          <div class="resolution">→ {c.get('cozum','')}</div>
        </div>"""

    # Aksiyon kartları
    def _action_cards(items, color, label_key, pct_key, extra_fn=None):
        html = ""
        for item in items:
            ticker = item.get("ticker", "")
            pct    = item.get(pct_key, 0)
            neden  = item.get("neden", "")
            extra  = extra_fn(item) if extra_fn else ""
            html += f"""
            <div class="action-card" style="border-left:3px solid {color};">
              <div style="display:flex;justify-content:space-between;">
                <b style="font-size:15px;">{ticker}</b>
                <span style="color:{color};font-weight:600;">%{pct} {label_key}</span>
              </div>
              {extra}
              <div class="reason">{neden}</div>
            </div>"""
        return html

    sat_html = _action_cards(
        aks.get("sat_azalt", []), "#e74c3c", "azalt", "miktar_pct",
        lambda i: f'<div class="sub">{i.get("gercekle","Hemen")}</div>'
    )
    al_html = _action_cards(
        aks.get("al_arttir", []), "#00a86b", "nakit", "nakit_pct",
        lambda i: (f'<div class="sub">Hedef: ${i.get("hedef_fiyat",0):.0f} · Stop: ${i.get("stop_loss",0):.0f}</div>'
                   if i.get("hedef_fiyat") else "")
    )
    bekle_html = ""
    for item in aks.get("bekle_izle", []):
        bekle_html += f"""
        <div class="action-card" style="border-left:3px solid #f5a623;">
          <b>{item.get('ticker','')}</b> — <span style="color:#f5a623;">{item.get('islem','')}</span>
          <div class="condition">📌 {item.get('kosul','')}</div>
          <div class="reason">{item.get('neden','')}</div>
        </div>"""

    # Vade planları
    def _vade_html(key, label, color):
        v = s.get(key, {})
        if not v:
            return ""
        acts = "".join(f"<li>{a}</li>" for a in v.get("aksiyonlar", []))
        baz  = v.get("senaryo_baz") or v.get("hedef_portfoy", "")
        risk = v.get("senaryo_risk", "")
        return f"""
        <div class="vade-section">
          <div class="vade-title" style="color:{color};">{label}</div>
          <div class="vade-grid">
            <div><div class="vade-label">Ana Senaryo</div><div class="vade-text">{baz}</div></div>
            {"<div><div class='vade-label risk-label'>Risk Senaryosu</div><div class='vade-text'>{}</div></div>".format(risk) if risk else ""}
          </div>
          <ul class="act-list">{acts}</ul>
        </div>"""

    # Yapılacaklar özeti
    def _todo_summary():
        todos = []
        for item in aks.get("sat_azalt", []):
            todos.append(f"🔴 {item.get('ticker','')} — %{item.get('miktar_pct',0)} azalt ({item.get('gercekle','Hemen')})")
        for item in aks.get("al_arttir", []):
            todos.append(f"🟢 {item.get('ticker','')} — Nakit %{item.get('nakit_pct',0)} ile al (Hedef: ${item.get('hedef_fiyat',0):.0f})")
        for item in aks.get("bekle_izle", []):
            todos.append(f"🟡 {item.get('ticker','')} — {item.get('kosul','')} olursa {item.get('islem','al')}")
        if aks.get("nakit_rezerv_pct", 0):
            todos.append(f"💵 Nakdin %{aks['nakit_rezerv_pct']}'ini rezervde tut — {aks.get('nakit_rezerv_neden','')}")
        for act in s.get("kisa_vade", {}).get("aksiyonlar", []):
            todos.append(f"📅 Kısa vade: {act}")
        return "".join(f'<li class="todo-item">{t}</li>' for t in todos)

    # Risk & Güç
    risk_html = "".join(f"<li>{r}</li>" for r in s.get("risk_uyarilari", []))
    guc_html  = "".join(f"<li>{g}</li>" for g in s.get("guc_sinyalleri", []))

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>Strateji Raporu — {now_str}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         font-size: 13px; color: #1a1a2e; background: #fff; padding: 24px; max-width: 960px; margin: 0 auto; }}
  .header {{ border-bottom: 3px solid #1a6ba0; padding-bottom: 14px; margin-bottom: 18px; display:flex; justify-content:space-between; }}
  .title {{ font-size: 20px; font-weight: 700; color: #1a6ba0; }}
  .meta  {{ font-size: 11px; color: #888; margin-top: 4px; }}
  .kpi-row {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:18px; }}
  .kpi {{ background:#f8f9fa; border-radius:8px; padding:10px; text-align:center; }}
  .kpi-n {{ font-size:18px; font-weight:700; }}
  .kpi-l {{ font-size:10px; color:#888; margin-top:2px; }}
  .section-title {{ font-size:11px; font-weight:600; color:#888; text-transform:uppercase;
                    letter-spacing:.08em; margin:16px 0 8px; padding-bottom:4px; border-bottom:1px solid #eee; }}
  .ozet {{ background:#f0f7ff; border-left:4px solid #1a6ba0; border-radius:0 8px 8px 0;
           padding:12px 16px; font-size:13px; line-height:1.7; margin-bottom:16px; }}
  .conflict-card {{ border-left:3px solid #f5a623; padding:8px 12px; margin-bottom:8px; background:#fffbf0; border-radius:0 6px 6px 0; }}
  .resolution {{ color:#00a86b; font-size:12px; margin-top:4px; }}
  .actions-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:16px; }}
  .action-col-title {{ font-size:11px; font-weight:600; text-transform:uppercase; margin-bottom:8px; }}
  .action-card {{ border-radius:0 8px 8px 0; padding:10px 12px; margin-bottom:8px; background:#fafafa; }}
  .sub {{ font-size:11px; color:#888; margin:3px 0; }}
  .condition {{ font-size:11px; color:#f5a623; margin:3px 0; }}
  .reason {{ font-size:11px; color:#555; margin-top:4px; line-height:1.5; }}
  .nakit-box {{ background:#f0fff4; border:1px solid #00a86b44; border-radius:8px;
               padding:10px 14px; font-size:13px; margin-bottom:16px; }}
  .vade-section {{ border:1px solid #eee; border-radius:8px; padding:14px; margin-bottom:12px; }}
  .vade-title {{ font-size:14px; font-weight:600; margin-bottom:10px; }}
  .vade-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:10px; }}
  .vade-label {{ font-size:10px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; }}
  .risk-label {{ color:#e74c3c !important; }}
  .vade-text {{ font-size:12px; line-height:1.6; }}
  .act-list {{ padding-left:18px; }}
  .act-list li {{ font-size:12px; margin:4px 0; line-height:1.5; }}
  .rg-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }}
  .rg-grid ul {{ padding-left:18px; }}
  .rg-grid li {{ font-size:12px; margin:4px 0; }}
  .todo-section {{ background:#1a1a2e; color:#fff; border-radius:10px; padding:16px 20px; margin:20px 0; }}
  .todo-title {{ font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:#4fc3f7; margin-bottom:12px; }}
  .todo-item {{ font-size:12px; margin:6px 0; line-height:1.6; }}
  .footer {{ margin-top:24px; padding-top:12px; border-top:1px solid #eee; font-size:10px; color:#aaa; text-align:center; }}
  @media print {{ body {{ padding:12px; }} @page {{ margin:1cm; size:A4; }} }}
</style>
</head>
<body>
<div class="header">
  <div>
    <div class="title">🧭 Strateji Raporu</div>
    <div class="meta">📅 {now_str} · Portföy: ${portfolio_value:,.0f} · Nakit: ${cash:,.0f}</div>
  </div>
  <div style="text-align:right;font-size:11px;color:#888;">
    AI Destekli Hisse Analiz Dashboard<br>
    <span style="color:#1a6ba0;font-weight:600;">Stock Dashboard</span>
  </div>
</div>

<div class="ozet">{s.get('ozet','')}</div>

<div class="section-title">⚡ Tespit Edilen Çelişkiler</div>
{celiski_html if celiski_html else '<p style="color:#888;font-size:12px;">Çelişki tespit edilmedi.</p>'}

<div class="section-title">🎯 Aksiyon Planı</div>
<div class="actions-grid">
  <div>
    <div class="action-col-title" style="color:#e74c3c;">📉 Sat / Azalt</div>
    {sat_html or '<p style="color:#888;font-size:12px;">Aksiyon yok</p>'}
  </div>
  <div>
    <div class="action-col-title" style="color:#00a86b;">📈 Al / Artır</div>
    {al_html or '<p style="color:#888;font-size:12px;">Aksiyon yok</p>'}
  </div>
  <div>
    <div class="action-col-title" style="color:#f5a623;">⏳ Koşullu / Bekle</div>
    {bekle_html or '<p style="color:#888;font-size:12px;">Aksiyon yok</p>'}
  </div>
</div>

{f'<div class="nakit-box">💵 <b>Nakit Rezerv: %{aks.get("nakit_rezerv_pct",0)}</b> — {aks.get("nakit_rezerv_neden","")}</div>' if aks.get("nakit_rezerv_pct") else ''}

<div class="section-title">📅 Vade Planları</div>
{_vade_html("kisa_vade", "📅 Kısa Vade (1-3 Ay)", "#4fc3f7")}
{_vade_html("orta_vade", "📆 Orta Vade (3-12 Ay)", "#ce93d8")}
{_vade_html("uzun_vade", "🗓️ Uzun Vade (1-3 Yıl)", "#f5a623")}

<div class="rg-grid">
  <div>
    <div class="section-title" style="color:#e74c3c;">⚠️ Risk Uyarıları</div>
    <ul>{risk_html}</ul>
  </div>
  <div>
    <div class="section-title" style="color:#00a86b;">💪 Güç Sinyalleri</div>
    <ul>{guc_html}</ul>
  </div>
</div>

<div class="todo-section">
  <div class="todo-title">✅ Yapılacaklar Özeti — Kısa'dan Uzun Vadeye</div>
  <ol class="act-list">{_todo_summary()}</ol>
</div>

<div class="footer">
  Bu rapor yapay zeka destekli analiz sistemi tarafından oluşturulmuştur. Yatırım tavsiyesi değildir. · {now_str}
</div>
</body>
</html>"""
