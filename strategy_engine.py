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

4. Portföy önce gelir. Yeni alımdan önce mevcut pozisyonların sağlığını değerlendir.

5. Koşullu senaryolar somut olmalı. "AVGO $200'a gelirse" değil,
   "AVGO $195-205 bandına çekilirse nakdin %20'si ile al, bu seviyelerde RSI 35 olur ve
   analist hedefine %42 upside kalır"

6. Risk yönetimi şart. Her yeni alım için stop loss seviyesi belirt.

7. FOMC ve earnings tarihlerine dikkat et. Yaklaşan toplantı/açıklama varsa
   o hisse için "earnings sonrasına bekle" veya "FOMC öncesi pozisyon küçült" de.

8. Yanıtını kesinlikle JSON formatında ver, başka hiçbir şey yazma:
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
    "senaryo_baz": "Ana senaryo nedir",
    "senaryo_risk": "Riskli senaryo nedir",
    "aksiyonlar": ["Madde madde kısa vade aksiyonları"]
  },
  "orta_vade": {
    "sure": "3-12 ay",
    "senaryo_baz": "Ana senaryo nedir",
    "senaryo_risk": "Riskli senaryo nedir",
    "aksiyonlar": ["Madde madde orta vade aksiyonları"]
  },
  "uzun_vade": {
    "sure": "1-3 yıl",
    "hedef_portfoy": "İdeal portföy yapısı nasıl olmalı",
    "aksiyonlar": ["Madde madde uzun vade aksiyonları"]
  },
  "risk_uyarilari": ["Kritik risk uyarıları listesi"],
  "guc_sinyalleri": ["Pozitif güçlü sinyaller listesi"]
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
            max_tokens=4000,  # Strateji detaylı olmalı
            system=STRATEGY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": full_prompt}],
        )

        raw = (message.content[0].text if message.content else "").strip()

        # JSON parse
        import re
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()

        strategy = json.loads(raw)

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
