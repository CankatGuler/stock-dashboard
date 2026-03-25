# trigger_alerts.py — Güçlü Telegram Alarm Mesajları
#
# Her alarm:
#   1. Ne oldu + sayısal değerler (ATR bağlamı)
#   2. Portföye spesifik etki
#   3. Direktörün somut aksiyonları
#   4. Cephane durumu + rotasyon
#   5. Onay mekanizması

import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta

logger        = logging.getLogger(__name__)
TELEGRAM_API  = "https://api.telegram.org/bot{token}/{method}"
DASHBOARD_URL = "https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app"

SEVERITY_EMOJI = {"CRITICAL":"🚨","HIGH":"⚠️","MEDIUM":"⚡","LOW":"💡"}
EYLEM_EMOJI    = {"SAT":"🔴","AZALT":"🔻","AL":"🟢","ARTIR":"🔺","BEKLE":"⏸️","EMIR_VER":"📝","KORU":"🔵"}


def _send(text: str, parse_mode: str = "HTML") -> bool:
    token   = os.getenv("TELEGRAM_BOT_TOKEN","")
    chat_id = os.getenv("TELEGRAM_CHAT_ID","")
    if not token or not chat_id:
        logger.warning("Telegram credentials eksik.")
        return False
    for chunk in [text[i:i+4000] for i in range(0,len(text),4000)]:
        try:
            r = requests.post(
                TELEGRAM_API.format(token=token,method="sendMessage"),
                json={"chat_id":chat_id,"text":chunk,"parse_mode":parse_mode,
                      "disable_web_page_preview":True},timeout=15)
            r.raise_for_status()
        except Exception as e:
            logger.error("Telegram hatası: %s",e); return False
    return True


def _tr_now() -> str:
    return (datetime.now(timezone.utc)+timedelta(hours=3)).strftime("%d %b %Y, %H:%M")


def _format_trigger_block(s: dict) -> str:
    lines = []
    emoji = SEVERITY_EMOJI.get(s["severity"],"•")
    tk    = s["trigger"]

    if tk == "vix_spike":
        vix,chg,atr = s.get("vix",0),s.get("change_pct",0),s.get("atr",0)
        mult = abs(vix*chg/100)/atr if atr>0 else 0
        lines += [f"{emoji} <b>VIX ANİ SPIKE</b>",
                  f"   VIX: <b>{vix:.1f}</b> ({chg:+.1f}% son 4s)"]
        if atr>0: lines.append(f"   Normal volatilitenin <b>{mult:.1f}×</b>")
        lines.append("   📌 Fonlar margin call yapıyor olabilir" if vix>=30 else
                     "   📌 Piyasa stresi artıyor")

    elif tk == "btc_crash":
        p,chg,atr = s.get("btc_price",0),s.get("change_pct",0),s.get("atr",0)
        mult = abs(p*chg/100)/atr if atr>0 else 0
        lines += [f"{emoji} <b>BTC ANİ DÜŞÜŞ</b>",
                  f"   BTC: <b>${p:,.0f}</b> ({chg:.1f}% son 4s)"]
        if atr>0: lines.append(f"   Normal volatilitenin <b>{mult:.1f}×</b>")
        lines.append("   📌 Cascade liquidation riski" if abs(chg)>=8 else
                     "   📌 Altcoinler daha sert düşebilir")

    elif tk == "usdtry_spike":
        rate,chg = s.get("usdtry",0),s.get("change_pct",0)
        lines += [f"{emoji} <b>USD/TRY ANİ ÇIKIŞ</b>",
                  f"   Kur: <b>{rate:.2f}</b> (+{chg:.2f}% son 4s)",
                  "   📌 TEFAS dolar bazlı değeri eriyor"]

    elif tk == "stablecoin_depeg":
        dep = s.get("depegged",[])
        sys = s.get("systemic",False)
        if sys:
            lines += ["🚨 <b>SİSTEMİK KRİZ — STABLECOIN ÇÖKÜŞÜ</b>",
                      "   Birden fazla stablecoin de-peg!",
                      "   📌 2022 Terra/LUNA senaryosu"]
        else:
            d=dep[0] if dep else {}
            lines += [f"{emoji} <b>STABLECOIN DE-PEG: {d.get('name','')}",
                      f"   ${d.get('price',0):.4f} (eşik: $0.995)",
                      "   📌 Piyasa likiditesi sıkışıyor"]

    elif tk == "yield_curve_bull_steepener":
        sp,pr = s.get("current_spread",0),s.get("prev_spread",0)
        lines += [f"{emoji} <b>YIELD CURVE BULL STEEPENER</b>",
                  f"   Spread: {pr:+.2f}% → <b>{sp:+.2f}%</b> ({(sp-pr)*100:+.0f} bps)",
                  "   📌 Ters eğri normalleşiyor + uzun faiz düşüyor",
                  "   📌 <b>Tarihsel resesyon tescil sinyali — 2007/2019</b>"]

    elif tk == "yield_curve_reinversion":
        sp = s.get("current_spread",0)
        lines += [f"{emoji} <b>YIELD CURVE YENİDEN İNVERSİYON</b>",
                  f"   Spread: <b>{sp*100:+.0f} bps</b>",
                  "   📌 Fed tekrar sıkılaştırıyor — Mali Dominans ön sinyali",
                  "   📌 Emtia + kısa tahvil zamanı, hisse değil"]

    elif tk == "funding_rate_hot":
        f = s.get("funding",0)
        lines += [f"{emoji} <b>FUNDING RATE AŞIRI ISINDI</b>",
                  f"   %{f*100:.3f}/8s (eşik: %0.08)",
                  "   📌 Long kaldıraç birikti — dump riski yüksek"]

    elif tk == "funding_rate_cold":
        f = s.get("funding",0)
        lines += [f"{emoji} <b>FUNDING NEGATİF — DİP FIRSATI</b>",
                  f"   %{f*100:.3f}/8s (eşik: -%0.05)",
                  "   📌 Short baskısı dorukta — squeeze / dip alım fırsatı"]

    elif tk == "open_interest":
        oi,bc = s.get("oi_change_pct",0),s.get("btc_change",0)
        lines += [f"{emoji} <b>AÇIK POZİSYON AŞIRI BİRİKİYOR</b>",
                  f"   OI: +{oi:.1f}% (4s) | BTC: {bc:+.1f}%",
                  "   📌 Cascade liquidation riski — zincirleme tasfiye olabilir"]

    elif tk == "vix_normalization":
        v,pr = s.get("vix_avg_3d",0),s.get("prior_max",0)
        lines += [f"{emoji} <b>VIX NORMALLEŞTI — RISK-ON AÇILIYOR</b>",
                  f"   3g ort VIX: <b>{v:.1f}</b> (önceki zirve: {pr:.1f})",
                  "   📌 Panik geçiyor — büyüme varlıklarına rotasyon zamanı"]

    elif tk == "btc_dominance_cycle":
        br,er = s.get("btc_return",0),s.get("eth_return",0)
        lines += [f"{emoji} <b>ALTCOIN ROTASYONU BAŞLIYOR</b>",
                  f"   ETH {er:+.1f}% / BTC {br:+.1f}% (48s)",
                  "   📌 BTC dominansı kırılıyor — majör altcoin sezonu açılıyor"]

    elif tk == "turkey_cds_drop":
        tur,try_ = s.get("tur_weekly",0),s.get("try_weekly",0)
        lines += [f"{emoji} <b>TÜRKİYE MAKRO İYİLEŞME — YABANCI GİRİYOR</b>",
                  f"   TUR ETF {tur:+.1f}% | TL {abs(try_):.1f}% güçlendi (haftalık)",
                  "   📌 CDS düşüyor — dolar bazlı BIST rallisi yaklaşıyor"]

    elif tk == "altcoin_btc_divergence":
        bc,ac,cnt = s.get("btc_change",0),s.get("altcoin_avg_change",0),s.get("altcoin_count",0)
        lines += [f"{emoji} <b>ALTCOIN/BTC AYRIŞMASI — LİKİDİTE ŞOKU UYARISI</b>",
                  f"   BTC {bc:+.1f}% | {cnt} altcoin ort {ac:.1f}%",
                  "   📌 Fonlar önce altcoinlerden çıkıyor — erken savunma sinyali"]
    else:
        lines += [f"{emoji} <b>{tk.replace('_',' ').upper()}</b>",
                  f"   {s.get('reason','')[:200]}"]

    return "\n".join(lines)


def _portfolio_impact(signals: list, portfolio: list, usd_try: float) -> str:
    if not portfolio: return ""
    lines = ["\n💼 <b>PORTFÖYİNİZE ETKİSİ:</b>"]
    triggers = {s["trigger"] for s in signals}
    class_vals = {}
    for p in portfolio:
        ac  = p.get("asset_class","us_equity")
        shr = float(p.get("shares",0))
        avg = float(p.get("avg_cost",0))
        cur = p.get("currency","USD")
        val = shr*avg/usd_try if cur=="TRY" else shr*avg
        class_vals[ac] = class_vals.get(ac,0)+val

    total = sum(class_vals.values())
    labels = {"us_equity":"🇺🇸 ABD Hisse","crypto":"₿ Kripto",
              "commodity":"🥇 Emtia","tefas":"🇹🇷 TEFAS"}

    # Etkilenen sınıflar
    risk_map = {
        "crypto":    {"btc_crash","stablecoin_depeg","altcoin_btc_divergence",
                      "funding_rate_hot","open_interest"},
        "tefas":     {"vix_spike","yield_curve_bull_steepener","usdtry_spike"},
        "us_equity": {"vix_spike","yield_curve_bull_steepener"},
    }
    positive_map = {
        "tefas":     {"turkey_cds_drop","vix_normalization"},
        "crypto":    {"funding_rate_cold","btc_dominance_cycle","vix_normalization"},
        "us_equity": {"vix_normalization"},
    }

    shown = False
    for ac, val in sorted(class_vals.items(), key=lambda x:-x[1]):
        if val <= 0: continue
        pct = val/total*100 if total>0 else 0
        is_risk     = bool(risk_map.get(ac,set()) & triggers)
        is_positive = bool(positive_map.get(ac,set()) & triggers)
        if is_risk or is_positive:
            note = "🟢 Yukarı potansiyel" if is_positive else "🔴 Risk altında"
            lines.append(f"   {labels.get(ac,ac)}: <b>${val:,.0f}</b> (%{pct:.0f}) — {note}")
            shown = True

    if not shown:
        for ac,val in sorted(class_vals.items(),key=lambda x:-x[1]):
            if val>0:
                lines.append(f"   {labels.get(ac,ac)}: ${val:,.0f}")

    return "\n".join(lines)


def _format_director_block(dr: str, ammo: dict) -> str:
    if not dr: return "\n⚠️ Direktör analizi alınamadı."
    try:
        clean = dr.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"): clean=clean[4:]
        data = json.loads(clean.strip().rstrip("`"))
    except Exception:
        return f"\n🧠 <b>DİREKTÖR:</b>\n<i>{dr[:600]}</i>"

    lines = ["\n🧠 <b>DİREKTÖR:</b>"]
    if data.get("ozet"): lines.append(f"<i>{data['ozet']}</i>")

    p_map = {"ACIL":"🔴 <b>ACİL — Bugün işlem yap</b>",
             "BUGUN":"🟡 <b>Bugün değerlendir</b>",
             "BU_HAFTA":"🟢 <b>Bu hafta pozisyon al</b>"}
    onc = data.get("oncelik","")
    if onc in p_map: lines.append(p_map[onc])

    aks = data.get("aksiyonlar",[])
    if aks:
        lines.append("\n🎯 <b>AKSİYONLAR:</b>")
        for a in aks[:8]:
            e = EYLEM_EMOJI.get(a.get("eylem",""),"•")
            lines.append(
                f"{e} <b>#{a.get('sira','?')} {a.get('eylem','')} — {a.get('varlik','')}</b>"
                + (f" ({a.get('miktar','')})" if a.get("miktar") else ""))
            if a.get("neden"): lines.append(f"   <i>{a['neden'][:120]}</i>")

    if data.get("finansman"):
        lines.append(f"\n💰 <b>Finansman:</b> <i>{data['finansman'][:150]}</i>")
    if data.get("senaryo"):
        lines.append(f"📋 Senaryo: {data['senaryo']}")

    lines.append(
        f"\n🏦 <b>Cephane:</b> ${ammo.get('cash_usd',0):,.0f} "
        f"(%{ammo.get('cash_pct',0):.1f})"
        + (f" | Defansif: ${ammo.get('defensive_value',0):,.0f}"
           if ammo.get("defensive_value",0)>0 else ""))
    if ammo.get("needs_rotation"):
        lines.append("⚡ <i>Alım için önce rotasyon gerekiyor</i>")

    return "\n".join(lines)


def format_and_send_alert(signals: list, director_response: str,
                          ammo: dict, usd_try: float,
                          portfolio: list = None) -> bool:
    if not signals: return False

    severity_order = {"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1}
    top   = max(signals,key=lambda s:severity_order.get(s["severity"],0))
    emoji = SEVERITY_EMOJI.get(top["severity"],"⚠️")
    cats  = {s["category"] for s in signals}
    layer = signals[0].get("layer",1)
    cat   = ("KARMA SİNYAL" if len(cats)>1
             else "SAVUNMA ALARMI" if "SAVUNMA" in cats
             else "HÜCUM — ROTASYON FIRSATI")

    parts = [f"{emoji} <b>KATMAN {layer} — {cat}</b>",
             "━"*32, f"📅 {_tr_now()}", ""]

    for s in signals:
        parts.append(_format_trigger_block(s))
        parts.append("")

    if portfolio:
        impact = _portfolio_impact(signals, portfolio, usd_try)
        if impact: parts += [impact, ""]

    parts.append(_format_director_block(director_response, ammo))
    parts += [f"\n{'━'*32}",
              f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>",
              "✅ /onayla | ❌ /reddet | 🔇 /sessiz"]

    msg = "\n".join(parts)
    logger.info("Alarm: %d karakter, %d sinyal",len(msg),len(signals))
    return _send(msg)


def send_morning_summary(summary_text: str) -> bool:
    return _send(
        f"🌅 <b>Günlük Piyasa Özeti</b>\n{'━'*30}\n"
        f"{summary_text}\n{'━'*30}\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>")


def send_test_message() -> bool:
    return _send("🟢 <b>Test OK</b>\nTelegram aktif.\n"
                 f"📊 <a href='{DASHBOARD_URL}'>Dashboard</a>")


if __name__ == "__main__":
    ok = send_test_message()
    print("✅" if ok else "❌")
