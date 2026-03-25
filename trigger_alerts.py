# trigger_alerts.py — Telegram Mesaj Formatları ve Gönderimi
#
# Bu dosya, tetikleyici sinyalleri insanın anlayabileceği,
# eyleme dönüştürebileceği Telegram mesajlarına dönüştürür.
#
# İki mesaj kategorisi:
#   SAVUNMA — "Piyasada tehlike, şunları yap"
#   HÜCUM   — "Fırsat kapısı açıldı, rotasyon zamanı"

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Severity → emoji eşlemesi
SEVERITY_EMOJI = {
    "CRITICAL": "🚨",
    "HIGH":     "⚠️",
    "MEDIUM":   "⚡",
    "LOW":      "💡",
}

# Kategori → renk/emoji eşlemesi
CATEGORY_EMOJI = {
    "SAVUNMA": "🛡️",
    "HUCUM":   "⚔️",
}

DASHBOARD_URL = "https://stock-dashboard-xcssaysbnrkdrrswxq2okk.streamlit.app"


# ─── Temel Gönderim ───────────────────────────────────────────────────────────

def _send(text: str, parse_mode: str = "HTML") -> bool:
    """
    Telegram'a mesaj gönder.
    Token ve chat ID Streamlit secrets / env'den alınır.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials eksik — mesaj gönderilemedi.")
        return False

    # Telegram mesajlarının 4096 karakter limiti var, gerekirse böl
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]

    for chunk in chunks:
        try:
            resp = requests.post(
                TELEGRAM_API.format(token=token, method="sendMessage"),
                json={
                    "chat_id":    chat_id,
                    "text":       chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
            return False

    return True


# ─── Tetikleyici Mesaj Formatı ────────────────────────────────────────────────

def _format_trigger_header(signals: list[dict]) -> str:
    """
    Alarm başlığını oluştur.
    Birden fazla sinyal varsa en yüksek severity'yi öne çıkar.
    """
    # En kritik severity'yi bul
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    top_severity   = max(signals, key=lambda s: severity_order.get(s["severity"], 0))
    severity       = top_severity["severity"]
    emoji          = SEVERITY_EMOJI.get(severity, "❓")

    # Kategori belirleme
    categories = {s["category"] for s in signals}
    if "SAVUNMA" in categories and "HUCUM" in categories:
        cat_label = "🛡️⚔️ KARMA SİNYAL"
    elif "SAVUNMA" in categories:
        cat_label = "🛡️ SAVUNMA ALARMI"
    else:
        cat_label = "⚔️ HÜCUM ALARMI"

    layer = signals[0].get("layer", 1)
    return (
        f"{emoji} <b>KATMAN {layer} — {cat_label}</b>\n"
        f"{'━' * 30}"
    )


def _format_signals_block(signals: list[dict]) -> str:
    """Her tetikleyici için özet satır üret."""
    lines = []
    for s in signals:
        emoji = SEVERITY_EMOJI.get(s["severity"], "•")
        lines.append(f"{emoji} <b>{s['trigger'].replace('_', ' ').upper()}</b>")
        lines.append(f"   {s['reason'][:200]}")
    return "\n".join(lines)


def _format_director_block(director_json_str: str, ammo: dict) -> str:
    """
    Direktör çıktısını Telegram formatına dönüştür.
    Direktör JSON döndürür, biz bunu okunabilir mesaja çeviririz.
    """
    if not director_json_str:
        return "⚠️ Direktör analizi alınamadı."

    # JSON parse et
    try:
        # JSON bloğu ```json ... ``` içinde gelebilir, temizle
        clean = director_json_str.strip()
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean)
    except Exception:
        # JSON değilse ham metni göster
        return f"🧠 <b>Direktör:</b>\n{director_json_str[:500]}"

    lines = ["", "🧠 <b>DİREKTÖR ANALİZİ</b>"]

    # Özet
    if data.get("ozet"):
        lines.append(f"<i>{data['ozet']}</i>")

    # Öncelik seviyesi
    oncelik = data.get("oncelik", "")
    if oncelik == "ACIL":
        lines.append("🔴 <b>ÖNCELİK: ACİL — Bugün işlem yapılmalı</b>")
    elif oncelik == "BUGUN":
        lines.append("🟡 <b>ÖNCELİK: Bugün içinde değerlendir</b>")
    elif oncelik == "BU_HAFTA":
        lines.append("🟢 <b>ÖNCELİK: Bu hafta içinde pozisyon al</b>")

    # Aksiyonlar
    aksiyonlar = data.get("aksiyonlar", [])
    if aksiyonlar:
        lines.append("")
        lines.append("🎯 <b>AKSİYONLAR:</b>")
        eylem_emoji = {
            "SAT":   "🔴",
            "AZALT": "🔻",
            "AL":    "🟢",
            "ARTIR": "🔺",
            "BEKLE": "⏸️",
        }
        for a in aksiyonlar[:8]:  # Max 8 aksiyon göster
            e = eylem_emoji.get(a.get("eylem", ""), "•")
            lines.append(
                f"{e} <b>#{a.get('sira','?')} {a.get('eylem','')} "
                f"{a.get('varlik','')}</b> — {a.get('miktar','')}\n"
                f"   <i>{a.get('neden','')[:100]}</i>"
            )

    # Finansman / Rotasyon notu
    finansman = data.get("finansman", "")
    if finansman:
        lines.append("")
        lines.append(f"💰 <b>Finansman:</b> {finansman[:150]}")

    # Cephane özeti
    lines.append("")
    lines.append(
        f"🏦 <b>Cephane:</b> ${ammo.get('cash_usd', 0):,.0f} nakit "
        f"(%{ammo.get('cash_pct', 0):.1f}) | "
        f"Defansif: ${ammo.get('defensive_value', 0):,.0f}"
    )
    if ammo.get("needs_rotation"):
        lines.append("⚡ Alım için önce rotasyon gerekiyor")

    return "\n".join(lines)


def _format_footer() -> str:
    """Mesaj altbilgisi."""
    return (
        f"\n{'━' * 30}\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>\n"
        f"Onaylamak için: /onayla | Reddetmek için: /reddet"
    )


# ─── Ana Gönderim Fonksiyonu ──────────────────────────────────────────────────

def format_and_send_alert(signals: list[dict], director_response: str,
                          ammo: dict, usd_try: float) -> bool:
    """
    Tetikleyici sinyalleri ve direktör analizini birleştirerek
    Telegram'a güzel formatlı mesaj gönder.
    """
    if not signals:
        return False

    parts = [
        _format_trigger_header(signals),
        "",
        _format_signals_block(signals),
        _format_director_block(director_response, ammo),
        _format_footer(),
    ]

    message = "\n".join(parts)
    logger.info("Telegram mesajı hazırlandı (%d karakter)", len(message))
    return _send(message)


# ─── Sabah Özeti Gönderimi ────────────────────────────────────────────────────

def send_morning_summary(summary_text: str) -> bool:
    """Günlük sabah özetini gönder."""
    message = (
        f"🌅 <b>Günlük Piyasa Özeti</b>\n"
        f"{'━' * 30}\n"
        f"{summary_text}\n"
        f"{'━' * 30}\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>"
    )
    return _send(message)


# ─── Test Fonksiyonu ──────────────────────────────────────────────────────────

def send_test_message() -> bool:
    """Telegram bağlantısını test et."""
    return _send(
        "🟢 <b>Tetikleyici Sistem Test Mesajı</b>\n\n"
        "Sistem başarıyla kuruldu ve Telegram bağlantısı çalışıyor.\n\n"
        f"📊 <a href='{DASHBOARD_URL}'>Dashboard'u Aç</a>"
    )


if __name__ == "__main__":
    # Direkt çalıştırıldığında test mesajı gönder
    ok = send_test_message()
    print("✅ Test mesajı gönderildi" if ok else "❌ Gönderim başarısız")
