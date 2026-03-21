# strategy_director.py — İki Aşamalı Claude Analiz Motoru
#
# FELSEFE:
#   Tek bir büyük Claude çağrısı yerine, gerçek bir yatırım bankasının
#   çalışma şeklini taklit ediyoruz:
#   - Aşama A: Her alan için uzman analist → kendi alanını derinlemesine inceler
#   - Aşama B: Strateji direktörü → 5 analist raporunu alır, sentezler, karar verir
#
# NEDEN İKİ AŞAMA?
#   Claude'un dikkat kapasitesi sınırlı. 50 metrik + 10 hisse + 3 varlık sınıfı
#   aynı anda verilirse hiçbirini derinlemesine işleyemez.
#   Uzman analistler kendi alanlarında derinleşir, direktör sadece sentez yapar.

import os
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CLAUDE_MODEL   = "claude-opus-4-5"
MAX_TOKENS_ANALYST  = 800    # Her analist raporu için — özlü ama derin
MAX_TOKENS_DIRECTOR = 8000   # Direktör için — kapsamlı sentez


# ─── Claude API Yardımcı Fonksiyonu ──────────────────────────────────────────

def _call_claude(system_prompt: str, user_message: str,
                 max_tokens: int = 1000, retries: int = 2) -> str | None:
    """
    Claude API'ye tek bir çağrı yap.
    Hata durumunda retry ile tekrar dene.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    for attempt in range(retries + 1):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except Exception as e:
            logger.warning("Claude API attempt %d failed: %s", attempt + 1, e)
            if attempt < retries:
                time.sleep(2 ** attempt)  # Exponential backoff
    return None


def _safe_json(text: str, fallback: dict = None) -> dict:
    """
    Claude çıktısından JSON parse et.
    Kısmi JSON bile olsa kurtarmaya çalış.
    """
    if not text:
        logger.warning("_safe_json: boş metin")
        return fallback or {}

    original = text
    text = text.strip()

    # Markdown kod bloğu temizle
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # İlk { ile son } arasını al
    first = text.find("{")
    last  = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last+1]

    # Doğrudan parse dene
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Brace recovery — JSON eksik kapanıyorsa kapat
    open_b  = text.count("{")
    close_b = text.count("}")
    if open_b > close_b:
        text += "}" * (open_b - close_b)
    try:
        return json.loads(text)
    except Exception:
        pass

    # Son çare: sadece piyasa_ozeti çıkarmaya çalış
    try:
        import re
        match = re.search(r'"piyasa_ozeti"\s*:\s*"([^"]+)"', original)
        if match and fallback:
            result = dict(fallback)
            result["piyasa_ozeti"] = match.group(1)
            logger.warning("JSON tam parse edilemedi, sadece piyasa_ozeti kurtarıldı")
            return result
    except Exception:
        pass

    logger.warning("JSON parse tamamen başarısız. İlk 500 karakter: %s", original[:500])
    return fallback or {}


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA A — UZMAN ANALİSTLER
# ═══════════════════════════════════════════════════════════════════════════

# ─── Makro Analist ───────────────────────────────────────────────────────────

MACRO_ANALYST_SYSTEM = """Sen küresel makroekonomik analizde uzmanlaşmış kıdemli bir portföy analistisin.
Fed politikası, küresel likidite döngüleri, kredi piyasaları ve jeopolitik risklerin piyasalara
etkisini değerlendirme konusunda 15 yıllık deneyimin var.

GÖREV SINIRI: Yalnızca sana verilen makroekonomik verileri analiz et. Cross-asset portföy 
kararları verme — bu direktörün işi. Sadece makro ortamı değerlendir.

YANIT FORMATI: Aşağıdaki JSON formatında yanıt ver, hiçbir alanı boş bırakma:
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net ve somut — neden bu sinyal?",
  "destekleyen": ["Metrik 1 ne söylüyor", "Metrik 2 ne söylüyor"],
  "riskler": ["Bu sinyali bozabilecek faktör 1", "Faktör 2"],
  "oneri": "Makro ortama göre yatırımcıya somut bir tavsiye",
  "izle": "Önümüzdeki 2 haftada en kritik gösterge nedir ve neden?"
}"""


def analyze_macro_with_claude(macro_data: dict, economic_data: dict) -> dict:
    """Makro analist — Fed, likidite, büyüme, risk ortamı."""
    # Özet veri hazırla — ham sayı değil yorumlanmış metrikler
    indicators = macro_data.get("indicators", {})
    regime     = macro_data.get("regime",     {})

    lines = ["=== MAKRO GÖSTERGELERİN ÖZETI ==="]

    # Sinyal motoru zaten yorumladı — onları kullan
    for key, ind in indicators.items():
        if isinstance(ind, dict) and ind.get("note"):
            sig = ind.get("signal", "neutral")
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.get('label', key)}: {ind.get('note', '')}")
        elif hasattr(ind, "note") and ind.note:
            sig = ind.signal
            emoji = {"green": "✅", "red": "⚠️", "amber": "⚡", "neutral": "—"}.get(sig, "—")
            lines.append(f"{emoji} {ind.label}: {ind.note}")

    if regime:
        lines.append(f"\nPiyasa Rejimi: {regime.get('label', '—')} — {regime.get('description', '')}")

    # Ekonomik göstergeler ekle
    econ = economic_data.get("macro_econ", {})
    if econ:
        lines.append("\n=== EKONOMİK VERİLER ===")
        for key, ind in econ.items():
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    message = "\n".join(lines)
    result  = _call_claude(MACRO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Makro veri alınamadı",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_macro"
    return parsed


# ─── ABD Hisse Analisti ──────────────────────────────────────────────────────

US_EQUITY_ANALYST_SYSTEM = """Sen ABD hisse senedi piyasalarında uzmanlaşmış kıdemli bir portföy analistisin.
S&P 500 değerlemesi, sektör rotasyonu, kurumsal kazanç döngüleri ve teknik analiz konularında
derinlemesine bilgiye sahipsin.

GÖREV SINIRI: Yalnızca ABD hisse senedi piyasasını analiz et.

KESKİN NİŞANCI MODU — MİKRO METRİK ODAĞI:
Makro görüşün yanında, portföydeki her ABD hissesini aşağıdaki üç filtreden geçir:

1. FCF YİELD & BORÇLULUK (Resesyon Direnci):
   - Serbest nakit akışı getirisi yüksek (>%5) ve borç/özkaynak düşük (<1.0) şirketler
     resesyon döneminde hayatta kalır. Bunları "Defansif Kalite" olarak etiketle.
   - Borç yükü yüksek ve negatif FCF'li şirketler faiz artışında ilk çökenlerdir.

2. AI ÜRETKENLİK İZİ (Revenue per Employee Trendi):
   - Şirketin son 2-4 çeyrekte çalışan başına geliri artıyorsa AI operasyonel kazanım
     sağlıyor demektir. Bu şirketi "AI Verimlilik Lideri" olarak etiketle.
   - Azalıyorsa kalabalık iş gücü maliyeti rekabet avantajını yiyor.

3. MAKRO DUYARLILIK ETİKETİ:
   Her hisse için şu etiketleri kullan:
   - Faiz_indirim_pozitif / Faiz_indirim_negatif
   - Resesyon_defansif / Resesyon_hassas
   - Dolar_zayiflama_pozitif / Dolar_zayiflama_negatif

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "sektor_gorusu": "Hangi sektör güçlü/zayıf",
  "deger_leme": "Piyasa ucuz mu pahalı mı",
  "hisse_mikro_analiz": [
    {
      "ticker": "TICKER",
      "beta": 0.0,
      "fcf_yield_tahmini": "yüksek|orta|düşük|negatif",
      "borc_durumu": "güçlü|orta|riskli",
      "ai_uretkenlik": "lider|orta|geri_kaliyor",
      "makro_duyarlilik": ["Faiz_indirim_pozitif", "Resesyon_defansif"],
      "aksiyon": "KORU|ARTIR|AZALT|SAT",
      "gerekce": "tek cümle"
    }
  ],
  "destekleyen": ["Faktör 1", "Faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut genel öneri",
  "izle": "Kritik gösterge"
}"""


def analyze_us_equity_with_claude(economic_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """ABD hisse analisti — değerleme, sektör rotasyonu, kazanç."""
    lines = ["=== ABD HİSSE PİYASASI ANALİZİ ==="]

    # Değerleme
    val = economic_data.get("sp500_valuation", {})
    if val:
        lines.append(f"S&P 500 Değerleme: {val.get('note', '')}")

    # Sektör rotasyonu
    sr = economic_data.get("sector_rotation", {})
    if sr:
        note = sr.get("rotation_note", "")
        if note:
            lines.append(f"Sektör Rotasyonu: {note}")
        secs = sr.get("sectors", [])
        if secs:
            top3    = sorted(secs, key=lambda x: x.get("rel_1m", 0), reverse=True)[:3]
            bottom3 = sorted(secs, key=lambda x: x.get("rel_1m", 0))[:3]
            lines.append("Lider sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in top3))
            lines.append("Zayıf sektörler: " + ", ".join(f"{s['label']} ({s['ret_1m']:+.1f}%)" for s in bottom3))

    # Ekonomik veriler
    econ = economic_data.get("macro_econ", {})
    for key in ["ISM_MFG", "ISM_SVC", "NFP", "GDP"]:
        ind = econ.get(key)
        if ind:
            note = ind.note if hasattr(ind, "note") else ind.get("note", "")
            if note:
                lines.append(f"• {note}")

    # Portföydeki hisseler — mikro metriklerle
    us_positions = [p for p in portfolio_positions
                    if p.get("asset_class", "us_equity") == "us_equity"
                    and float(p.get("shares", 0)) > 0]
    if us_positions:
        lines.append("\n=== PORTFÖYDEKİ ABD HİSSELERİ (MİKRO ANALİZ) ===")
        lines.append("Her hisse için FCF yield, beta, borç durumu ve makro duyarlılığını değerlendir.")
        
        # yfinance'ten mikro metrikler çek
        try:
            import yfinance as _yf_micro
            for p in us_positions[:10]:
                ticker = p["ticker"]
                cur    = p.get("current_price", p["avg_cost"])
                avg    = p["avg_cost"]
                pnl    = (cur - avg) / avg * 100 if avg > 0 else 0
                shares = float(p.get("shares", 0))
                val    = shares * cur
                
                # Temel metrikler
                try:
                    info = _yf_micro.Ticker(ticker).info
                    beta         = info.get("beta", "?")
                    fcf          = info.get("freeCashflow", 0) or 0
                    market_cap   = info.get("marketCap", 0) or 0
                    fcf_yield    = (fcf / market_cap * 100) if market_cap > 0 and fcf else 0
                    de_ratio     = info.get("debtToEquity", 0) or 0
                    rev_per_emp_note = ""
                    rev = info.get("totalRevenue", 0) or 0
                    emp = info.get("fullTimeEmployees", 0) or 0
                    if rev > 0 and emp > 0:
                        rev_per_emp = rev / emp / 1000  # K dolar
                        rev_per_emp_note = f"Gelir/Çalışan: ${rev_per_emp:.0f}K"
                    
                    lines.append(
                        f"• {ticker}: K/Z %{pnl:+.0f} | Değer: ${val:,.0f} | "
                        f"Beta: {beta} | FCF Getirisi: {fcf_yield:+.1f}% | "
                        f"Borç/Özkaynak: {de_ratio:.1f} | {rev_per_emp_note} | "
                        f"Sektör: {p.get('sector','?')}"
                    )
                except Exception:
                    lines.append(f"• {ticker}: K/Z %{pnl:+.0f}, Değer: ${val:,.0f}, Sektör: {p.get('sector','?')}")
        except Exception:
            for p in us_positions[:8]:
                pnl = ((p.get("current_price", p["avg_cost"]) - p["avg_cost"])
                       / p["avg_cost"] * 100) if p["avg_cost"] > 0 else 0
                lines.append(f"• {p['ticker']}: K/Z %{pnl:+.0f}, Sektör: {p.get('sector','?')}")

    # Sinyal motoru sinyali
    us_sig = signal_summary.get("us_equity", {})
    if us_sig:
        lines.append(f"\nSinyal Motoru: {us_sig.get('signal','?')} (güven: {us_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(US_EQUITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "sektor_gorusu": "", "deger_leme": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_us_equity"
    return parsed


# ─── Kripto Analisti ─────────────────────────────────────────────────────────

CRYPTO_ANALYST_SYSTEM = """Sen kripto varlık piyasalarında uzmanlaşmış kıdemli bir analistin.
On-chain metrikler, Bitcoin halving döngüleri, altcoin dinamikleri ve kripto piyasası
psikolojisi konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca kripto piyasasını analiz et. Hisse senetleri, Türkiye veya emtia 
hakkında yorum yapma.

NOT: MVRV, SOPR gibi değerler yfinance'ten hesaplanan proxy değerlerdir, Glassnode'dan 
gerçek on-chain veri değil. Bunu yorumlarında göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dongu_pozisyonu": "Halving döngüsünde neredeyiz?",
  "onchain_ozet": "On-chain metrikler ne söylüyor?",
  "btc_vs_altcoin": "BTC mi altcoin mi tercih edilmeli?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_crypto_with_claude(crypto_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Kripto analisti — on-chain, döngü, sentiment."""
    lines = ["=== KRİPTO PİYASASI ANALİZİ ==="]

    fg  = crypto_data.get("fear_greed",  {})
    dom = crypto_data.get("dominance",   {})
    hal = crypto_data.get("halving",     {})
    onc = crypto_data.get("onchain",     {})
    stb = crypto_data.get("stablecoin",  {})
    ls  = crypto_data.get("long_short",  {})
    nvt = crypto_data.get("nvt",         {})
    spr = crypto_data.get("sopr",        {})
    prc = crypto_data.get("prices",      {})

    if fg.get("note"):   lines.append(f"Fear & Greed: {fg['note']}")
    if hal.get("note"):  lines.append(f"Halving Döngüsü: {hal['note']}")
    if dom.get("dom_note"): lines.append(f"Dominance: {dom['dom_note']}")

    mvrv = onc.get("mvrv_proxy", {})
    if mvrv.get("note"):  lines.append(f"MVRV Proxy: {mvrv['note']}")
    rsi  = onc.get("btc_rsi", {})
    if rsi.get("note"):   lines.append(f"BTC RSI: {rsi['note']}")
    if spr.get("note"):   lines.append(f"SOPR Proxy: {spr['note']}")
    if nvt.get("note"):   lines.append(f"NVT Signal: {nvt['note']}")
    if ls.get("note"):    lines.append(f"Long/Short: {ls['note']}")
    if stb.get("note"):   lines.append(f"Stablecoin: {stb['note']}")

    # BTC fiyatı
    btc = prc.get("BTC", {})
    if btc.get("price"):
        lines.append(f"BTC: ${btc['price']:,.0f} ({btc.get('change_24h',0):+.1f}%), 52H pos: %{btc.get('52h_pos',0):.0f}")

    # Kripto pozisyonları
    crypto_pos = [p for p in portfolio_positions if p.get("asset_class") == "crypto"
                  and float(p.get("shares", 0)) > 0]
    if crypto_pos:
        lines.append("\n=== KRİPTO POZİSYONLARI ===")
        for p in crypto_pos:
            pnl = ((p.get("current_price", p["avg_cost"]) - p["avg_cost"])
                   / p["avg_cost"] * 100) if p["avg_cost"] > 0 else 0
            lines.append(f"• {p['ticker']}: {p['shares']:.4f} adet, K/Z %{pnl:+.0f}")

    crypto_sig = signal_summary.get("crypto", {})
    if crypto_sig:
        lines.append(f"\nSinyal Motoru: {crypto_sig.get('signal','?')} (güven: {crypto_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(CRYPTO_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "dongu_pozisyonu": "", "onchain_ozet": "", "btc_vs_altcoin": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_crypto"
    return parsed


# ─── Emtia Analisti ──────────────────────────────────────────────────────────

COMMODITY_ANALYST_SYSTEM = """Sen emtia piyasalarında, özellikle altın ve enerji sektöründe
uzmanlaşmış kıdemli bir analistin. Reel faiz dinamikleri, merkez bankası politikaları,
jeopolitik risk ve emtia döngüleri konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca emtia piyasasını analiz et.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "altin_gorusu": "Altın için temel tez nedir?",
  "petrol_gorusu": "Petrol piyasası ne söylüyor?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_commodity_with_claude(commodity_data: dict, portfolio_positions: list,
                                   signal_summary: dict) -> dict:
    """Emtia analisti — altın reel faiz, petrol, jeopolitik."""
    lines = ["=== EMTİA PİYASASI ANALİZİ ==="]

    grr = commodity_data.get("gold_real_rate", {})
    cbg = commodity_data.get("cb_gold_proxy",  {})
    udg = commodity_data.get("us_debt_gold",   {})
    oil = commodity_data.get("oil",            {})
    cu  = commodity_data.get("copper",         {})
    geo = commodity_data.get("geo_news",       {})
    prc = commodity_data.get("prices",         {})

    if grr.get("note"): lines.append(f"Reel Faiz: {grr['note']}")
    if cbg.get("note"): lines.append(f"MB Altın Alımı Proxy: {cbg['note']}")
    if udg.get("note"): lines.append(f"ABD Borç/Altın Tezi: {udg['note'][:120]}")
    if oil.get("note"): lines.append(f"Petrol: {oil['note']}")
    if cu.get("gc_note"): lines.append(f"Altın/Bakır Oranı: {cu['gc_note']}")
    if geo.get("note"): lines.append(f"Jeopolitik: {geo['note']}")

    gold = prc.get("GOLD", {})
    if gold.get("price"):
        lines.append(f"Altın: ${gold['price']:,.0f}/oz ({gold.get('change',0):+.1f}%), 52H: %{gold.get('pos_52h',0):.0f}")

    comm_pos = [p for p in portfolio_positions if p.get("asset_class") == "commodity"
                and float(p.get("shares", 0)) > 0]
    if comm_pos:
        lines.append("\n=== EMTİA POZİSYONLARI ===")
        for p in comm_pos:
            pnl = ((p.get("current_price", p["avg_cost"]) - p["avg_cost"])
                   / p["avg_cost"] * 100) if p["avg_cost"] > 0 else 0
            lines.append(f"• {p['ticker']}: K/Z %{pnl:+.0f}")

    comm_sig = signal_summary.get("commodity", {})
    if comm_sig:
        lines.append(f"\nSinyal Motoru: {comm_sig.get('signal','?')} (güven: {comm_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(COMMODITY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "TUT", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "altin_gorusu": "", "petrol_gorusu": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_commodity"
    return parsed


# ─── Türkiye Analisti ─────────────────────────────────────────────────────────

TURKEY_ANALYST_SYSTEM = """Sen Türkiye hisse senedi piyasası ve gelişen piyasalarda uzmanlaşmış
kıdemli bir analistin. BIST dinamikleri, TL/kur riski, TCMB politikası, bankacılık sektörü
ve yabancı yatırımcı akışları konularında derin bilgiye sahipsin.

GÖREV SINIRI: Yalnızca Türkiye piyasasını analiz et.

ÖNEMLİ: Tüm getiri hesaplamalarında hem TL bazlı hem dolar bazlı değerlendirme yap.
TL bazında kazanç, dolar bazında kayıp olabilir — her zaman dolar bazlı gerçek getiriyi göz önünde bulundur.

YANIT FORMATI (JSON — hiçbir alan boş olamaz):
{
  "sinyal": "AL|TUT|BEKLE|AZALT|SAT",
  "guven": 1-10,
  "ana_gerekcce": "Tek cümle, net",
  "dolar_bazli_degerleme": "BIST dolar bazlı ucuz mu pahalı mı?",
  "xbank_gorusu": "XBANK sinyali ne söylüyor?",
  "kur_riski": "TL riski ne durumda?",
  "destekleyen": ["Pozitif faktör 1", "Pozitif faktör 2"],
  "riskler": ["Risk 1", "Risk 2"],
  "oneri": "Somut eylem önerisi",
  "izle": "Önümüzdeki 2 haftada kritik gösterge"
}"""


def analyze_turkey_with_claude(turkey_data: dict, portfolio_positions: list,
                                signal_summary: dict) -> dict:
    """Türkiye analisti — BIST dolar bazlı, XBANK, kur, yabancı."""
    lines = ["=== TÜRKİYE BORSASI ANALİZİ ==="]

    from turkey_fetcher import build_turkey_prompt
    lines.append(build_turkey_prompt(turkey_data))

    tefas_pos = [p for p in portfolio_positions if p.get("asset_class") == "tefas"
                 and float(p.get("shares", 0)) > 0]
    if tefas_pos:
        lines.append("\n=== TEFAS POZİSYONLARI (LOOK-THROUGH ANALİZİ) ===")
        # Bilinen fon içerik haritası — KAP aylık raporlarından derlendi
        TEFAS_MAP = {
            "IIH":  ("Hisse Yoğun",          "Büyük Şirket ~%90",         "YÜKSEK", "ORTA"),
            "AEY":  ("Altın/Kıymetli Maden", "Altın ~%80",                "DÜŞÜK",  "DÜŞÜK"),
            "YAC":  ("Dengeli",               "Hisse %50 Tahvil %50",      "ORTA",   "DÜŞÜK"),
            "TTE":  ("Hisse (Teknoloji)",     "Teknoloji ~%85",            "YÜKSEK", "ORTA"),
            "GAF":  ("Kamu Menkul Kıymet",   "Devlet Tahvili ~%90",       "DÜŞÜK",  "YÜKSEK"),
            "MAC":  ("Hisse (Banka)",         "Bankacılık ~%80",           "ÇOK YÜK","ORTA"),
            "NNF":  ("Hisse (Büyüme)",        "Küçük/Orta Şirket ~%85",   "YÜKSEK", "ORTA"),
        }
        for p in tefas_pos:
            kod  = p["ticker"].upper()
            tip, icerik, ress_duy, kur_risk = TEFAS_MAP.get(
                kod, ("Bilinmiyor", "KAP'tan kontrol et", "?", "?")
            )
            val_tl = float(p.get("shares", 0)) * float(p.get("current_price", p.get("avg_cost", 0)))
            lines.append(
                f"• {kod} [{tip}]: {p['shares']:,.0f} adet | ~{val_tl:,.0f} TL | "
                f"İçerik: {icerik} | Resesyon Duyar.: {ress_duy} | Kur Riski: {kur_risk}"
            )
        lines.append("Analiz: Her fonun içeriğine göre resesyon/kur riskini ayrı ayrı değerlendir.")

    tr_sig = signal_summary.get("turkey", {})
    if tr_sig:
        lines.append(f"\nSinyal Motoru: {tr_sig.get('signal','?')} (güven: {tr_sig.get('confidence','?')}/10)")

    message = "\n".join(lines)
    result  = _call_claude(TURKEY_ANALYST_SYSTEM, message, MAX_TOKENS_ANALYST)
    parsed  = _safe_json(result, {
        "sinyal": "BEKLE", "guven": 5,
        "ana_gerekcce": "Veri alınamadı",
        "dolar_bazli_degerleme": "", "xbank_gorusu": "", "kur_riski": "",
        "destekleyen": [], "riskler": [], "oneri": "", "izle": ""
    })
    parsed["_source"] = "claude_turkey"
    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# AŞAMA B — STRATEJİ DİREKTÖRÜ
# ═══════════════════════════════════════════════════════════════════════════

def _build_director_system(user_profile: dict, year_target_pct: float) -> str:
    """
    Direktörün sistem promptunu kullanıcı profiline göre oluştur.
    Kimlik + karar çerçevesi + kişisel parametreler + zorunlu çıktılar.
    """
    time_horizon  = user_profile.get("time_horizon",  "1-3 yıl (Uzun Vade)")
    risk_tol      = user_profile.get("risk_tol",      "Orta-Yüksek")
    cash_cycle    = user_profile.get("cash_cycle",    "3 ayda bir")
    goal          = user_profile.get("goal",          "Uzun vadeli büyüme")

    return f"""Sen çok varlıklı portföy yönetiminde uzmanlaşmış kıdemli bir strateji direktörüsün.
ABD hisse senetleri, kripto varlıklar, emtialar (özellikle altın) ve Türkiye borsası olmak üzere
dört farklı piyasayı eş zamanlı yönetme deneyimine sahipsin.

Beş farklı uzman analistten rapor alıyorsun (makro, ABD hisse, kripto, emtia, Türkiye).
Görevin bu raporları sentezleyip müşteri için kişiselleştirilmiş, somut ve eyleme 
dönüştürülebilir bir strateji üretmek.

═══ KARAR ÇERÇEVESİ HİYERARŞİSİ ═══
Çelişkili sinyaller olduğunda şu öncelik sırasını uygula:
1. MAKRO REJİM — Risk-off modu aktifse bireysel varlık AL sinyalleri ikincil plana düşer
2. KORELASYONsuz ÇEŞİTLENDİRME — Yüksek korelasyonlu varlıklar (BTC/Tech gibi) 
   aynı anda artırılamaz. Bu çeşitlendirme yanılgısıdır.
3. RİSK/ÖDÜL DENGESİ — Her öneride potansiyel kazancı potansiyel kayıpla kıyasla
4. LİKİDİTE — Nakit yetersizse önce en riskli pozisyonlar küçültülür

═══ MÜŞTERİ PROFİLİ ═══
• Zaman ufku: {time_horizon}
• Risk toleransı: {risk_tol} (%20 drawdown tolere edilir)
• Nakit döngüsü: {cash_cycle}
• Hedef: {goal}
• Yıl sonu getiri hedefi: %{year_target_pct:.0f}
• Konum: Türkiye'de yaşıyor — enflasyonu yenmek öncelik, dolar bazlı getiri kritik
• Bu yatırımlar daha büyük bir portföyün parçası

═══ ZORUNLU YANIT ALANLARI ═══
Aşağıdaki her alan dolu olmalı — hiçbirini boş bırakma:

piyasa_ozeti: Piyasada dominant tema nedir? (2-3 cümle, anlaşılır)
analist_sentezi: Her analistin sinyali + tek cümle gerekçe
celiskiler: Analistler arasındaki çelişkileri tespit et ve çöz (hangi görüş neden üstün?)
portfoy_aksiyonlari: Hemen yap / koşullu yap / izle-karar ver
risk_senaryosu: Kötü senaryo tetikleyici + somut adımlar
vade_planlari: Kısa/orta/uzun vade için baz ve risk senaryoları
yil_sonu_hedefi: Hedefe ulaşmak için ne kadar risk gerekiyor?
bir_sonraki_kontrol: Tarih + tetikleyiciler (max 3)

═══ SENARYO OLASILILANDIRMASI (KRİTİK) ═══
Tek bir senaryoya %100 güvenme. Her kararı üç olasılığın matematiksel harmanı yap:

1. BAZI SENARYO (dominant) — en yüksek olasılık, verilerle destekli
2. ALTERNATİF SENARYO — %20-35 ihtimalle gerçekleşebilecek zıt senaryo  
3. KUYRUK RİSKİ — %5-15 ihtimalle ancak çok yıkıcı uç senaryo

Örnek format:
"senaryo_olasılıkları": {
  "baz": {"tanim": "Soft landing", "olasilik_pct": 55, "portfoy_etkisi": "+8%"},
  "alternatif": {"tanim": "Hard landing resesyon", "olasilik_pct": 35, "portfoy_etkisi": "-18%"},
  "kuyruk": {"tanim": "Likidite krizi", "olasilik_pct": 10, "portfoy_etkisi": "-45%"}
}
"harmonize_strateji": "Bu üç olasılığın ağırlıklı ortalamasına göre önerim şu..."

Ağırlıklı beklenen getiri = Σ(olasılık × etki). Negatif beklenen değerde agresif pozisyon alma.

═══ KORElASYON SİGORTASI ═══
Eğer portföydeki varlık sınıfları arasındaki 30 günlük korelasyon 0.7'yi geçiyorsa
(likidite krizinde hepsi birlikte düşüyorsa), nakit oranı otomatik olarak
önerilen seviyenin 1.5 katına çıkarılmalı. Bunu her analizde kontrol et.

═══ ÇIKTI KURALLARI ═══
• Her aksiyon somut olmalı: "risk azalt" değil, "AVGO pozisyonunu %20 küçült"
• Nakit oranı her zaman belirtilmeli
• Stop-loss ve hedef fiyat mümkün olduğunda verilmeli
• Türkçe yaz
• JSON formatında yanıt ver — aşağıdaki şemayı kullan:

{
  "piyasa_ozeti": "2-3 cümle — dominant tema",
  "analist_sentezi": {
    "makro": {"sinyal": "AL|SAT|BEKLE|TUT|AZALT|ARTIR", "gerekce": "tek cümle"},
    "abd_hisse": {"sinyal": "...", "gerekce": "..."},
    "kripto": {"sinyal": "...", "gerekce": "..."},
    "emtia": {"sinyal": "...", "gerekce": "..."},
    "turkiye": {"sinyal": "...", "gerekce": "..."}
  },
  "celiskiler": [{"baslik": "...", "aciklama": "...", "karar": "...", "kazanan": "..."}],
  "portfoy_aksiyonlari": {
    "hemen_yap": [{"varlik_sinifi": "...", "ticker": "...", "eylem": "...", "miktar_pct": 0, "kaynak": "nakit", "neden": "...", "stop_loss": null, "hedef": null}],
    "kosullu_yap": [{"kosul": "...", "eylem": "...", "ticker": "...", "neden": "..."}],
    "izle_karar_ver": [{"varlik": "...", "izlenecek": "...", "eylem": "..."}],
    "nakit_orani": {"onerilen_pct": 0, "mevcut_pct": 0, "neden": "..."}
  },
  "risk_senaryosu": {
    "tetikleyici": "...", "ilk_24_saat": ["..."],
    "savunma": ["..."],
    "firsat_listesi": [{"ticker": "...", "seviye": 0, "islem": "AL", "neden": "..."}],
    "toparlanma_sinyali": "..."
  },
  "vade_planlari": {
    "kisa": {"sure": "1-3 ay", "baz_senaryo": "...", "risk_senaryosu": "...", "aksiyonlar": ["..."]},
    "orta": {"sure": "3-12 ay", "baz_senaryo": "...", "risk_senaryosu": "...", "aksiyonlar": ["..."]},
    "uzun": {"sure": "1-3 yil", "tema": "...", "pozisyonlama": "..."}
  },
  "yil_sonu_hedefi": {"hedef_pct": 0, "mevcut_pct": 0, "kalan_pct": 0, "gerekan_aylik_pct": 0, "risk_degerlendirmesi": "...", "tavsiye": "..."},
  "senaryo_olasiliklari": {
    "baz":        {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "alternatif": {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."},
    "kuyruk":     {"tanim": "...", "olasilik_pct": 0, "portfoy_etkisi": "..."}
  },
  "harmonize_strateji": "Üç olasılığın ağırlıklı ortalaması olarak özet strateji",
  "korelasyon_sigortasi": {
    "aktif": true,
    "neden": "...",
    "nakit_artirim_pct": 0
  },
  "bir_sonraki_kontrol": {
    "tarih": "YYYY-MM-DD", "neden": "...",
    "tetikleyiciler": [{"tip": "fiyat|takvim|durum", "aciklama": "...", "esik": "..."}]
  }
}"""


def _build_director_message(
    macro_report:     dict,
    us_report:        dict,
    crypto_report:    dict,
    commodity_report: dict,
    turkey_report:    dict,
    portfolio_state:  dict,
    correlations:     dict,
    signal_summary:   dict,
    financial_calendar: list,
    year_target_pct:  float,
) -> str:
    """
    Direktöre gönderilecek kullanıcı mesajını oluştur.
    Ham metrikler değil — yorumlanmış analist raporları.
    """
    lines = []

    # ── 5 Analist Raporu ─────────────────────────────────────────────────
    lines.append("═══ ANALİST RAPORLARI ═══\n")

    reports = [
        ("MAKRO ANALİST",     macro_report),
        ("ABD HİSSE ANALİSTİ", us_report),
        ("KRİPTO ANALİSTİ",   crypto_report),
        ("EMTİA ANALİSTİ",    commodity_report),
        ("TÜRKİYE ANALİSTİ", turkey_report),
    ]

    for title, rep in reports:
        # ana_gerekcce veya ana_gerekce — her iki yazım da kabul edilir
        _ana_key = "ana_gerekcce" if rep.get("ana_gerekcce") else "ana_gerekce"
        if not rep or not rep.get(_ana_key):
            lines.append(f"[{title}] — Veri alınamadı\n")
            continue
        sinyal = rep.get("sinyal", "?")
        guven  = rep.get("guven",  "?")
        ana    = rep.get(_ana_key, "")
        oneri  = rep.get("oneri", "")
        izle   = rep.get("izle",  "")
        # Her analist için özlü format — token tasarrufu
        lines.append(f"[{title}] {sinyal} ({guven}/10): {ana}")
        dest = rep.get("destekleyen", [])[:2]
        risk = rep.get("riskler", [])[:2]
        if dest: lines.append("  ✅ " + " | ".join(dest))
        if risk: lines.append("  ⚠️ " + " | ".join(risk))
        if oneri: lines.append(f"  → Öneri: {oneri[:150]}")
        if izle:  lines.append(f"  → İzle: {izle[:100]}")
        lines.append("")

    # ── Korelasyon Özeti ─────────────────────────────────────────────────
    # Korelasyon analizi + sigorta sinyali
    corr_prompt = correlations.get("prompt", "") if correlations else ""
    if corr_prompt:
        lines.append("═══ KORELASYON ANALİZİ ═══")
        lines.append(corr_prompt[:400])
        lines.append("")

    # Korelasyon sigortası — kritik eşik kontrolü
    try:
        if correlations:
            pairs = correlations.get("cross_asset_pairs", {})
            high_corr = []
            for pair_key, pair_data in pairs.items():
                corr_val = float(pair_data.get("corr_30d", 0) or 0)
                if abs(corr_val) > 0.70:
                    high_corr.append(f"{pair_key}: {corr_val:.2f}")
            if len(high_corr) >= 3:
                lines.append(
                    f"⚠️ KORElASYON SİGORTASI TETİKLENDİ: "
                    f"{len(high_corr)} varlık çifti 0.70 üzerinde korelasyon gösteriyor. "
                    f"({', '.join(high_corr[:3])}) "
                    f"Nakit oranı önerilen seviyenin 1.5 katına çıkarılmalı!"
                )
    except Exception:
        pass

    # ── Portföy Mevcut Durumu ────────────────────────────────────────────
    pa = portfolio_state.get("analytics", {})
    lines.append("═══ PORTFÖY MEVCUT DURUMU ═══")
    lines.append(f"Toplam Değer: ${pa.get('total_value',0):,.0f}")
    lines.append(f"Nakit: ${portfolio_state.get('cash',0):,.0f} (%{portfolio_state.get('cash',0)/(pa.get('total_value',1)+portfolio_state.get('cash',0))*100:.0f})")
    lines.append(f"K/Z: ${pa.get('total_pnl',0):,.0f} (%{pa.get('total_pnl_pct',0):.1f})")

    # Varlık sınıfı dağılımı
    positions = portfolio_state.get("positions", [])
    class_values = {}
    for p in positions:
        ac = p.get("asset_class", "us_equity")
        val = float(p.get("shares",0)) * float(p.get("current_price", p.get("avg_cost",0)))
        class_values[ac] = class_values.get(ac, 0) + val
    total_val = sum(class_values.values()) + portfolio_state.get("cash", 0)
    if total_val > 0:
        lines.append("Varlık Dağılımı: " + " | ".join(
            f"{k}: %{v/total_val*100:.0f}" for k, v in class_values.items()
        ))

    # ── Yaklaşan Önemli Olaylar ─────────────────────────────────────────
    if financial_calendar:
        critical = [e for e in financial_calendar if e.get("stars", 1) >= 3][:3]
        if critical:
            lines.append("\n═══ YAKLAŞAN KRİTİK OLAYLAR ═══")
            for e in critical:
                lines.append(f"• {e['date']}: {e['event']} ({e.get('days_until',0)} gün)")

    # ── Tarihsel Kriz Karşılaştırması ────────────────────────────────────
    _crisis_ctx = all_data.get("crisis_context", "") if isinstance(all_data, dict) else ""
    if _crisis_ctx:
        lines.append(_crisis_ctx)
    elif all_data and isinstance(all_data, dict):
        _comps = all_data.get("crisis_comparisons", [])
        if _comps:
            lines.append("\n═══ TARİHSEL BENZERLİK ═══")
            for c in _comps[:2]:
                lines.append(
                    f"• {c['label']}: %{c['similarity_pct']:.0f} benzerlik | "
                    f"Risk: {c['risk_level']} | Tetikleyici: {c['trigger']}"
                )

    # ── Sistematik Risk Göstergeleri ─────────────────────────────────────
    _sys = all_data.get("systemic_risk", {}) if isinstance(all_data, dict) else {}
    _buffett = _sys.get("buffett", {})
    if isinstance(_buffett, dict) and _buffett.get("ratio"):
        lines.append(f"\nBuffett Göstergesi: %{_buffett['ratio']:.0f} "
                     f"(ort. %100, 2000 zirvesi %148, 2007 %105) — {_buffett.get('note','')[:80]}")

    _finstress = all_data.get("financial_stress", {}) if isinstance(all_data, dict) else {}
    if _finstress:
        kre = _finstress.get("KRE")
        if kre and hasattr(kre, "note"):
            lines.append(f"Bölgesel Banka Stres (KRE): {kre.note[:80]}")

    # ── Yıl Sonu Hedefi Bağlamı ─────────────────────────────────────────
    lines.append(f"\n═══ YIL SONU HEDEFİ ═══")
    lines.append(f"Hedef: %{year_target_pct:.0f} | Mevcut portföy: ${pa.get('total_value',0):,.0f}")

    # ── Direktöre Yanıtlaması Gereken Sorular ───────────────────────────
    lines.append("""
═══ YANITMANI GEREKTİREN SORULAR ═══
1. Bu portföy için şu an en doğru strateji ne? (piyasa_ozeti)
2. Analistlerin çelişkilerini nasıl çözüyorsun? (celiskiler)
3. Hemen, koşullu ve bekle olarak aksiyonları sırala (portfoy_aksiyonlari)
4. Risk senaryosu gelirse ne yapmalıyım? (risk_senaryosu)
5. Kısa/orta/uzun vadede ne yapmalıyım? (vade_planlari)
6. Yıl sonu hedefine ulaşmak için yeterli risk alıyor muyum? (yil_sonu_hedefi)
7. Bir sonraki ne zaman ve neye bakmalıyım? (bir_sonraki_kontrol)

Yanıtını aşağıdaki JSON formatında ver:""")

    lines.append("""
════════════════════════════════════
Yukarıdaki analist raporlarını sentezle ve sistem promptundaki JSON formatında yanıt ver.
Tüm alanları doldur, hiçbirini boş bırakma. Sadece JSON döndür, açıklama ekleme.
""")
    return "\n".join(lines)


def run_director(
    macro_report:       dict,
    us_report:          dict,
    crypto_report:      dict,
    commodity_report:   dict,
    turkey_report:      dict,
    portfolio_state:    dict,
    correlations:       dict,
    signal_summary:     dict,
    financial_calendar: list,
    user_profile:       dict,
    year_target_pct:    float = 40.0,
) -> dict:
    """
    Strateji direktörü — 5 analist raporunu alıp sentezler.
    """
    system  = _build_director_system(user_profile, year_target_pct)
    message = _build_director_message(
        macro_report, us_report, crypto_report,
        commodity_report, turkey_report,
        portfolio_state, correlations, signal_summary,
        financial_calendar, year_target_pct,
    )

    logger.info("Direktör analizi başlıyor...")
    result = _call_claude(system, message, MAX_TOKENS_DIRECTOR, retries=2)

    parsed = _safe_json(result, {
        "piyasa_ozeti": "Direktör analizi alınamadı.",
        "analist_sentezi": {},
        "celiskiler": [],
        "portfoy_aksiyonlari": {
            "hemen_yap": [], "kosullu_yap": [],
            "izle_karar_ver": [],
            "nakit_orani": {"onerilen_pct": 15, "mevcut_pct": 0, "neden": "Varsayılan"}
        },
        "risk_senaryosu": {
            "tetikleyici": "VIX 30+ veya S&P %8 düşüş",
            "ilk_24_saat": ["Spekülatif pozisyonları %50 küçült"],
            "savunma": ["Nakidi %30'a çıkar"],
            "firsat_listesi": [],
            "toparlanma_sinyali": "VIX 20 altına düşünce"
        },
        "vade_planlari": {
            "kisa": {"sure": "1-3 ay", "baz_senaryo": "", "risk_senaryosu": "", "aksiyonlar": []},
            "orta": {"sure": "3-12 ay", "baz_senaryo": "", "risk_senaryosu": "", "aksiyonlar": []},
            "uzun": {"sure": "1-3 yıl", "tema": "", "pozisyonlama": ""},
        },
        "yil_sonu_hedefi": {
            "hedef_pct": year_target_pct, "mevcut_pct": 0,
            "kalan_pct": year_target_pct, "gerekan_aylik_pct": 0,
            "risk_degerlendirmesi": "", "tavsiye": ""
        },
        "bir_sonraki_kontrol": {
            "tarih": "", "neden": "", "tetikleyiciler": []
        }
    })

    parsed["_generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["_analyst_reports"] = {
        "makro":   macro_report,
        "abd":     us_report,
        "kripto":  crypto_report,
        "emtia":   commodity_report,
        "turkiye": turkey_report,
    }

    logger.info("Direktör analizi tamamlandı.")
    return parsed


# ═══════════════════════════════════════════════════════════════════════════
# ANA ORKESTRATÖR — İki Aşamanın Koordinasyonu
# ═══════════════════════════════════════════════════════════════════════════

def run_two_phase_analysis(
    all_data:        dict,
    progress_callback = None,  # Streamlit progress güncellemesi için
) -> dict:
    """
    İki aşamalı analizi baştan sona yürüt.

    all_data içermeli: macro, economic, crypto, commodity, turkey,
                       portfolio, correlations, signals, calendar, user_profile

    progress_callback(step: int, total: int, message: str) formatında çağrılır.
    """
    total_steps = 7  # 5 analist + 1 direktör + 1 hazırlık
    step        = 0

    def _progress(msg: str):
        nonlocal step
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, msg)
        logger.info("Analiz adımı %d/%d: %s", step, total_steps, msg)

    portfolio_positions = all_data.get("portfolio", {}).get("positions", [])
    user_profile        = all_data.get("user_profile", {})
    year_target         = float(user_profile.get("year_target_pct", 40.0))
    signal_summary      = {}

    # Sinyal motoru çıktılarını özetle
    signals_raw = all_data.get("signals", {})
    for key in ["macro", "us_equity", "crypto", "commodity", "turkey"]:
        s = signals_raw.get(key)
        if s:
            signal_summary[key] = {
                "signal":     s.signal     if hasattr(s, "signal")     else s.get("signal",    "?"),
                "confidence": s.confidence if hasattr(s, "confidence") else s.get("confidence", 5),
                "reason":     s.reason     if hasattr(s, "reason")     else s.get("reason",    ""),
            }

    # ── Aşama A: 5 Uzman Analist ─────────────────────────────────────────
    _progress("Makro analist çalışıyor...")
    macro_report = analyze_macro_with_claude(
        all_data.get("macro",    {}),
        all_data.get("economic", {}),
    )
    time.sleep(0.5)

    _progress("ABD hisse analisti çalışıyor...")
    us_report = analyze_us_equity_with_claude(
        all_data.get("economic", {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Kripto analisti çalışıyor...")
    crypto_report = analyze_crypto_with_claude(
        all_data.get("crypto",  {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Emtia analisti çalışıyor...")
    commodity_report = analyze_commodity_with_claude(
        all_data.get("commodity", {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    _progress("Türkiye analisti çalışıyor...")
    turkey_report = analyze_turkey_with_claude(
        all_data.get("turkey",  {}),
        portfolio_positions,
        signal_summary,
    )
    time.sleep(0.5)

    # ── Aşama B: Strateji Direktörü ──────────────────────────────────────
    _progress("Strateji direktörü sentez yapıyor...")
    director_output = run_director(
        macro_report       = macro_report,
        us_report          = us_report,
        crypto_report      = crypto_report,
        commodity_report   = commodity_report,
        turkey_report      = turkey_report,
        portfolio_state    = all_data.get("portfolio",    {}),
        correlations       = all_data.get("correlations", {}),
        signal_summary     = signal_summary,
        financial_calendar = all_data.get("calendar",    []),
        user_profile       = user_profile,
        year_target_pct    = year_target,
    )

    return {
        "success":         True,
        "director":        director_output,
        "analyst_reports": {
            "makro":   macro_report,
            "abd":     us_report,
            "kripto":  crypto_report,
            "emtia":   commodity_report,
            "turkiye": turkey_report,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
