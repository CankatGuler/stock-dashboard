# chat_director.py — İnteraktif Direktör: Telegram Sohbet Modu
#
# Bu modül, strategy_director.py'deki tam analizden farklıdır.
# Oradaki direktör 5 analist raporunu sentezleyen ağır bir analiz makinesi.
# Buradaki direktör seninle konuşan, sorularını anlık yanıtlayan bir stratejist.
#
# Temel farklar:
#   - Tam analiz yerine sohbet formatında yanıt
#   - Konuşma geçmişini hafızada tutar (bağlamı kaybetmez)
#   - Portföy verisini her mesajda arka plana enjekte eder
#   - Master Prompt'un kısa versiyonunu kullanır (token tasarrufu)

import os
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CHAT_HISTORY_FILE = Path(__file__).parent / "chat_history.json"
MAX_HISTORY_TURNS = 20

# GitHub'daki geçmiş dosyası yolu
GITHUB_HISTORY_PATH = "chat_history.json"


# ─── GitHub Geçmiş Yönetimi ──────────────────────────────────────────────────

def _github_read_history() -> tuple[list, str]:
    """GitHub'dan chat geçmişini oku. (data, sha) döndürür."""
    try:
        import requests, base64
        token = os.getenv("GH_PAT", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return [], ""
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_HISTORY_PATH}"
        resp = requests.get(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }, timeout=10)
        if resp.status_code == 404:
            return [], ""
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data.get("sha", "")
    except Exception as e:
        logger.debug("GitHub geçmiş okuma: %s", e)
    return [], ""


def _github_write_history(history: list, sha: str = "") -> bool:
    """Chat geçmişini GitHub'a yaz."""
    try:
        import requests, base64
        token = os.getenv("GH_PAT", "")
        repo  = os.getenv("GITHUB_REPO", "")
        if not token or not repo:
            return False
        content = base64.b64encode(
            json.dumps(history, ensure_ascii=False, indent=2).encode()
        ).decode()
        url  = f"https://api.github.com/repos/{repo}/contents/{GITHUB_HISTORY_PATH}"
        body = {
            "message": "chore: direktör sohbet geçmişi güncellendi",
            "content": content,
        }
        if sha:
            body["sha"] = sha
        # Mevcut sha'yı al
        if not sha:
            r = requests.get(url, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }, timeout=8)
            if r.status_code == 200:
                body["sha"] = r.json().get("sha", "")
        resp = requests.put(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }, json=body, timeout=15)
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.debug("GitHub geçmiş yazma: %s", e)
    return False


# ─── Konuşma Geçmişi Yönetimi ────────────────────────────────────────────────

def _load_history() -> list[dict]:
    """
    Konuşma geçmişini yükle.
    Önce lokal dosya, yoksa GitHub'dan çek.
    """
    # Lokal dosya varsa kullan (hız için)
    if CHAT_HISTORY_FILE.exists():
        try:
            return json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # GitHub'dan yükle
    history, _ = _github_read_history()
    if history:
        # Lokal'e cache'le
        try:
            CHAT_HISTORY_FILE.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
    return history


def _save_history(history: list[dict]) -> None:
    """
    Konuşma geçmişini kaydet.
    Hem lokal dosyaya hem GitHub'a yaz.
    """
    trimmed = history[-MAX_HISTORY_TURNS * 2:]
    # Lokal kaydet
    try:
        CHAT_HISTORY_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error("Lokal geçmiş kaydedilemedi: %s", e)
    # GitHub'a kaydet (arka planda, deploy'dan sonra da korunsun)
    try:
        _github_write_history(trimmed)
    except Exception as e:
        logger.warning("GitHub geçmiş kaydedilemedi: %s", e)


def get_history_summary() -> str:
    """
    Konuşma geçmişinin kısa özetini döndürür.
    /durum komutu veya dashboard için kullanılabilir.
    """
    history = _load_history()
    if not history:
        return "Henüz sohbet geçmişi yok."
    turns = len([h for h in history if h["role"] == "user"])
    return f"{turns} soru soruldu. Son mesaj: {history[-1]['content'][:80]}..."


def clear_history() -> None:
    """Sohbet geçmişini temizle — /sifirla komutu için."""
    if CHAT_HISTORY_FILE.exists():
        CHAT_HISTORY_FILE.unlink()
    logger.info("Sohbet geçmişi temizlendi.")


def inject_system_message(text: str, label: str = "SİSTEM ALARMI") -> None:
    """
    Otomatik sistem mesajlarını (Katman 1/2/3, haftalık tarama vs.)
    sohbet geçmişine 'assistant' rolüyle ekle.
    Böylece direktör bu mesajları bağlam olarak görür.
    """
    try:
        history = _load_history()
        # Mesajı kısa tut — çok uzun alarmlar token'ı şişirir
        max_len = 1500
        truncated = text[:max_len] + ("..." if len(text) > max_len else "")
        history.append({
            "role":    "assistant",
            "content": f"[{label}]\n{truncated}"
        })
        _save_history(history)
        logger.debug("Sistem mesajı geçmişe eklendi: %s karakter", len(truncated))
    except Exception as e:
        logger.warning("inject_system_message hatası: %s", e)


# ─── Portföy Bağlamı ─────────────────────────────────────────────────────────

def _fetch_price_with_fallback(tk: str, ac: str, cur: str,
                               gold_usd: float, usd_try: float) -> tuple[float, bool]:
    """
    Anlık fiyatı çek ve doğrula.
    Adım 1: yfinance ile fiyat çek
    Adım 2: web search ile çapraz kontrol
    Fark %3'ten fazlaysa web search fiyatını kullan (daha güvenilir).
    Returns: (fiyat_usd, başarılı_mı)
    """
    import yfinance as yf

    # ── Altın gram TRY ────────────────────────────────────────────────────
    if tk in ("ALTIN_GRAM_TRY", "XAUTRY=X") and gold_usd > 0:
        return (gold_usd * usd_try / 31.1035) / usd_try, True

    # ── TEFAS fonu ────────────────────────────────────────────────────────
    if ac == "tefas":
        try:
            from data.tefas_client import get_fund_price
            price_tl = get_fund_price(tk)
            if price_tl:
                return price_tl / usd_try, True
        except Exception:
            pass
        return 0.0, False

    # ── Adım 1: yfinance ──────────────────────────────────────────────────
    yf_price = None
    try:
        h = yf.Ticker(tk).history(period="2d")
        if not h.empty:
            lp = float(h["Close"].iloc[-1])
            yf_price = lp / usd_try if cur == "TRY" else lp
    except Exception:
        pass

    # ── Adım 2: web search ile doğrula ───────────────────────────────────
    ws_price = _fetch_price_web_search(tk)

    # Her ikisi de başarısız
    if yf_price is None and ws_price is None:
        logger.warning("Fiyat alınamadı: %s (yfinance ve web search başarısız)", tk)
        return 0.0, False

    # Sadece biri başarılı
    if yf_price is None:
        logger.info("%s: yfinance başarısız, web search kullanılıyor: $%.4f", tk, ws_price)
        return ws_price, True

    if ws_price is None:
        logger.info("%s: web search başarısız, yfinance kullanılıyor: $%.4f", tk, yf_price)
        return yf_price, True

    # İkisi de başarılı — fark kontrolü
    fark_pct = abs(yf_price - ws_price) / ws_price * 100
    if fark_pct > 3.0:
        logger.warning(
            "%s: Fiyat uyumsuzluğu! yfinance=$%.4f | web=$%.4f | fark=%%%.1f → web search kullanılıyor",
            tk, yf_price, ws_price, fark_pct
        )
        return ws_price, True
    else:
        logger.info("%s: Fiyat doğrulandı: $%.4f (fark: %%%.2f)", tk, yf_price, fark_pct)
        return yf_price, True


def _fetch_price_web_search(tk: str) -> float | None:
    """
    Claude web_search ile hisse fiyatını çek.
    Returns: fiyat (float) veya None
    """
    try:
        import os, requests, re
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5-20251001",
                "max_tokens": 150,
                "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                "messages":   [{
                    "role":    "user",
                    "content": (
                        f"Current stock price of {tk} in USD right now? "
                        f"Reply ONLY with JSON: {{\"price\": <number>}}. No text."
                    )
                }],
            },
            timeout=20,
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", [])
                       if b.get("type") == "text" and b.get("text")]
        if not text_blocks:
            return None

        text = text_blocks[-1].strip()
        text = re.sub(r"```json\s*|\s*```", "", text).strip()
        match = re.search(r'"price"\s*:\s*([\d.]+)', text)
        if match:
            price = float(match.group(1))
            if price > 0:
                return price
    except Exception as e:
        logger.debug("Web search fiyat hatası [%s]: %s", tk, e)

    return None



    """
    Supabase'den taze portföy verisi çek.
    TÜM matematik (ağırlık, K/Z oranı) Python'da hesaplanır.
    Direktöre sadece hazır, yoruma kapalı sayılar gönderilir.
    """
    try:
        import yfinance as yf
        from core.database import SessionLocal
        from core import crud

        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)

        positions = [p for p in summary["positions"] if p["is_open"] and p["quantity"] > 0]
        if not positions:
            return "Portföy boş veya yüklenemedi."

        # Altın fiyatı
        gold_usd = 0.0
        try:
            h = yf.Ticker("GC=F").history(period="2d")
            if not h.empty:
                gold_usd = float(h["Close"].iloc[-1])
        except Exception:
            pass

        ac_labels = {
            "us_equity": "ABD Hisse",
            "crypto":    "Kripto",
            "commodity": "Emtia",
            "tefas":     "TEFAS Fonu",
            "cash":      "Nakit",
        }

        # ── ADIM 1: Tüm anlık değerleri Python'da hesapla ─────────────────
        enriched = []
        for p in positions:
            tk   = p["symbol"]
            shr  = float(p["quantity"])
            avg  = float(p["avg_cost_usd"])
            cur  = p.get("currency", "USD")
            ac   = p.get("asset_class", "us_equity") or "us_equity"
            cost_usd = shr * avg

            live_price_usd, price_ok = _fetch_price_with_fallback(
                tk, ac, cur, gold_usd, usd_try
            )
            if not price_ok:
                live_price_usd = avg  # son çare fallback

            live_usd = shr * live_price_usd
            pnl      = live_usd - cost_usd
            pnl_pct  = pnl / cost_usd * 100 if cost_usd > 0 else 0

            enriched.append({
                "symbol":     tk,
                "ac":         ac,
                "shr":        shr,
                "avg":        avg,
                "cost_usd":   cost_usd,
                "live_price": live_price_usd,
                "live_usd":   live_usd,
                "pnl":        pnl,
                "pnl_pct":    pnl_pct,
                "price_ok":   price_ok,
            })

        # ── ADIM 2: Toplam ve kategori toplamlarını hesapla ───────────────
        total_cur  = sum(p["live_usd"]  for p in enriched)
        total_cost = sum(p["cost_usd"]  for p in enriched)
        total_pnl  = total_cur - total_cost
        total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0

        cat_totals: dict[str, float] = {}
        for p in enriched:
            cat_totals[p["ac"]] = cat_totals.get(p["ac"], 0.0) + p["live_usd"]

        # ── ADIM 3: Direktöre gidecek metni oluştur ───────────────────────
        lines = [
            f"MEVCUT PORTFÖY — CANLI VERİ (Supabase | USD/TRY: {usd_try:.2f})",
            f"Toplam Portföy Değeri: ${total_cur:,.0f} | "
            f"Toplam Yatırılan: ${total_cost:,.0f} | "
            f"Net K/Z: ${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)",
            "",
            "NOT: Tüm ağırlıklar ve K/Z oranları Python tarafından hesaplanmıştır.",
            "Matematiksel hesaplama YAPMA — aşağıdaki hazır verileri OKU ve YORUMLA.",
            "",
        ]

        # Kategoriye göre grupla
        class_groups: dict[str, list] = {}
        for p in enriched:
            class_groups.setdefault(p["ac"], []).append(p)

        for ac, pos_list in class_groups.items():
            cat_total = cat_totals.get(ac, 0)
            cat_pct   = cat_total / total_cur * 100 if total_cur > 0 else 0
            lines.append(
                f"── {ac_labels.get(ac, ac)}: "
                f"Kategori Toplamı ${cat_total:,.0f} "
                f"(Portföy Ağırlığı: %{cat_pct:.1f}) ──"
            )

            for p in pos_list:
                sign       = "+" if p["pnl"] >= 0 else ""
                cat_weight = p["live_usd"] / cat_total * 100 if cat_total > 0 else 0
                tot_weight = p["live_usd"] / total_cur * 100 if total_cur > 0 else 0

                if p["price_ok"]:
                    kz_str = (
                        f"K/Z: {sign}${p['pnl']:,.0f} ({sign}{p['pnl_pct']:.1f}%) | "
                        f"Kategori İçi Ağırlık: %{cat_weight:.1f} | "
                        f"Toplam Portföy Ağırlığı: %{tot_weight:.1f}"
                    )
                    if p["ac"] == "tefas":
                        # TEFAS için TL değerini de göster
                        live_tl = p["live_usd"] * usd_try
                        cost_tl = p["cost_usd"] * usd_try
                        fiyat_str = (
                            f"Anlık Birim Fiyat: ₺{p['live_price'] * usd_try:,.4f} "
                            f"(${p['live_price']:,.4f}) | "
                            f"Varlık Değeri: ₺{live_tl:,.0f} (${p['live_usd']:,.0f})"
                        )
                    else:
                        fiyat_str = (
                            f"Anlık Birim Fiyat: ${p['live_price']:,.2f} | "
                            f"Varlık Değeri: ${p['live_usd']:,.0f}"
                        )
                else:
                    # Fiyat alınamadı ama pozisyonu yine de göster
                    cost_tl = p["cost_usd"] * usd_try
                    if p["ac"] == "tefas":
                        avg_tl = p["avg"] * usd_try
                        fiyat_str = (
                            f"Anlık Birim Fiyat: [Çekilemedi] | "
                            f"Toplam Yatırılan: ₺{cost_tl:,.0f} (${p['cost_usd']:,.0f})"
                        )
                    else:
                        fiyat_str = f"Anlık Birim Fiyat: [Çekilemedi] | Varlık Değeri: [Bilinmiyor]"
                    kz_str = "K/Z: [Fiyat çekilemedi — K/Z yorumu yapma, pozisyon mevcut]"

                lines.append(
                    f"  {p['symbol']}: "
                    f"Miktar: {p['shr']:,g} adet | "
                    f"Ort. Birim Maliyet: ${p['avg']:,.2f} | "
                    f"Toplam Yatırılan: ${p['cost_usd']:,.0f} | "
                    f"{fiyat_str} | "
                    f"{kz_str}"
                )
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error("_build_portfolio_context hatası: %s", e)
        return f"Portföy alınamadı: {e}"





def _extract_tickers_from_message(message: str) -> list[str]:
    """
    Kullanıcı mesajından hisse/kripto sembollerini tespit et.
    Büyük harfli 1-5 karakter kelimeler potansiyel ticker.
    Bilinen kripto ve yaygın kısaltmaları filtrele.
    """
    import re
    # Büyük harfli 2-6 karakter kelimeler (ticker formatı)
    candidates = re.findall(r'\b([A-Z]{2,6}(?:-USD)?)\b', message.upper())

    # Filtrele — Türkçe büyük harf kısaltmalar ve stopword'ler
    stopwords = {
        "VIX", "DXY", "ETF", "ABD", "USD", "TRY",
        "TL", "FED", "GDP", "CPI", "PCE", "AI", "API", "EPS", "FCF",
        "ROE", "ROA", "PE", "PEG", "YOY", "QOQ", "TTM", "EBITDA",
        "OK", "TR", "EN", "DE", "KI", "BI", "NE", "BU", "DA",
    }

    tickers = []
    for c in candidates:
        if c not in stopwords and len(c) >= 2:
            tickers.append(c)

    return list(dict.fromkeys(tickers))[:5]  # max 5, tekrarsız


def _fetch_live_prices(tickers: list[str]) -> str:
    """
    Verilen ticker listesi için anlık fiyat ve temel metrikleri çek.
    Direktörün sistem promptuna enjekte edilecek.
    """
    if not tickers:
        return ""

    import yfinance as yf

    lines = ["\nANLIK FİYAT VERİSİ (otomatik çekildi):"]
    found_any = False

    for tk in tickers:
        try:
            ticker_obj = yf.Ticker(tk)
            hist = ticker_obj.history(period="5d")
            if hist.empty:
                continue

            price     = float(hist["Close"].iloc[-1])
            prev      = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
            chg_pct   = (price - prev) / prev * 100 if prev > 0 else 0
            price_5d  = float(hist["Close"].iloc[0])
            chg_5d    = (price - price_5d) / price_5d * 100 if price_5d > 0 else 0

            # Temel metrikler (hızlı — sadece fast_info)
            fi = ticker_obj.fast_info
            mkt_cap = getattr(fi, "market_cap", None)
            mc_str  = ""
            if mkt_cap:
                if mkt_cap >= 1e12:
                    mc_str = f" | Piyasa Değeri: ${mkt_cap/1e12:.2f}T"
                elif mkt_cap >= 1e9:
                    mc_str = f" | Piyasa Değeri: ${mkt_cap/1e9:.1f}B"

            chg_sign  = "+" if chg_pct >= 0 else ""
            chg5_sign = "+" if chg_5d  >= 0 else ""
            lines.append(
                f"  {tk}: ${price:,.2f} "
                f"(günlük {chg_sign}{chg_pct:.2f}%, "
                f"5g {chg5_sign}{chg_5d:.2f}%)"
                f"{mc_str}"
            )
            found_any = True
        except Exception:
            continue  # Geçersiz ticker, sessizce atla

    if not found_any:
        return ""

    lines.append("(Kaynak: yfinance — gerçek zamanlı veri)")
    return "\n".join(lines)


def _build_memory_context() -> str:
    """Hafıza sisteminden güncel direktör bağlamını getir."""
    try:
        from memory.director_memory import memory
        regime, days = memory.get_current_regime()
        locks        = memory.get_active_locks()
        recent       = memory.get_recent_decisions(n=3)

        lines = []
        if regime and regime != "Bilinmiyor":
            lines.append(f"MEVCUT REJİM: {regime} ({days} gündür)")
        if locks:
            lines.append(f"KİLİTLİ VARLIKLAR: {', '.join(locks.keys())}")
        if recent:
            son = recent[-1]
            lines.append(
                f"SON KARAR ({son.get('tarih','?')}): {son.get('ozet','')[:100]}"
            )
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _build_tefas_context() -> str:
    """Portföydeki TEFAS fonlarının içerik profillerini döndür."""
    try:
        from memory.knowledge_library import get_all_tefas_profiles_text
        return get_all_tefas_profiles_text()
    except Exception:
        return ""


def _build_portfolio_context(usd_try: float) -> str:
    """
    Supabase'den taze portföy verisi çek.
    TÜM matematik (ağırlık, K/Z oranı) Python'da hesaplanır.
    Direktöre sadece hazır, yoruma kapalı sayılar gönderilir.
    """
    try:
        import yfinance as yf
        from core.database import SessionLocal
        from core import crud

        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)

        positions = [p for p in summary["positions"] if p["is_open"] and p["quantity"] > 0]
        if not positions:
            return "Portföy boş veya yüklenemedi."

        # Altın fiyatı
        gold_usd = 0.0
        try:
            h = yf.Ticker("GC=F").history(period="2d")
            if not h.empty:
                gold_usd = float(h["Close"].iloc[-1])
        except Exception:
            pass

        ac_labels = {
            "us_equity": "ABD Hisse",
            "crypto":    "Kripto",
            "commodity": "Emtia",
            "tefas":     "TEFAS Fonu",
            "cash":      "Nakit",
        }

        # ── ADIM 1: Tüm anlık değerleri Python'da hesapla ─────────────────
        enriched = []
        for p in positions:
            tk       = p["symbol"]
            shr      = float(p["quantity"])
            avg      = float(p["avg_cost_usd"])
            cur      = p.get("currency", "USD")
            ac       = p.get("asset_class", "us_equity") or "us_equity"
            cost_usd = shr * avg

            live_price_usd, price_ok = _fetch_price_with_fallback(
                tk, ac, cur, gold_usd, usd_try
            )
            if not price_ok:
                live_price_usd = avg  # son çare fallback

            live_usd = shr * live_price_usd
            pnl      = live_usd - cost_usd
            pnl_pct  = pnl / cost_usd * 100 if cost_usd > 0 else 0

            enriched.append({
                "symbol":     tk,
                "ac":         ac,
                "shr":        shr,
                "avg":        avg,
                "cost_usd":   cost_usd,
                "live_price": live_price_usd,
                "live_usd":   live_usd,
                "pnl":        pnl,
                "pnl_pct":    pnl_pct,
                "price_ok":   price_ok,
            })

        # ── ADIM 2: Toplam ve kategori toplamlarını hesapla ───────────────
        total_cur  = sum(p["live_usd"]  for p in enriched)
        total_cost = sum(p["cost_usd"]  for p in enriched)
        total_pnl  = total_cur - total_cost
        total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0

        cat_totals: dict[str, float] = {}
        for p in enriched:
            cat_totals[p["ac"]] = cat_totals.get(p["ac"], 0.0) + p["live_usd"]

        # ── ADIM 3: Direktöre gidecek metni oluştur ───────────────────────
        lines = [
            f"MEVCUT PORTFÖY — CANLI VERİ (Supabase | USD/TRY: {usd_try:.2f})",
            f"Toplam Portföy Değeri: ${total_cur:,.0f} | "
            f"Toplam Yatırılan: ${total_cost:,.0f} | "
            f"Net K/Z: ${total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)",
            "",
            "NOT: Tüm ağırlıklar ve K/Z oranları Python tarafından hesaplanmıştır.",
            "Matematiksel hesaplama YAPMA — aşağıdaki hazır verileri OKU ve YORUMLA.",
            "",
        ]

        # Kategoriye göre grupla
        class_groups: dict[str, list] = {}
        for p in enriched:
            class_groups.setdefault(p["ac"], []).append(p)

        for ac, pos_list in class_groups.items():
            cat_total = cat_totals.get(ac, 0)
            cat_pct   = cat_total / total_cur * 100 if total_cur > 0 else 0
            lines.append(
                f"── {ac_labels.get(ac, ac)}: "
                f"Kategori Toplamı ${cat_total:,.0f} "
                f"(Portföy Ağırlığı: %{cat_pct:.1f}) ──"
            )

            for p in pos_list:
                sign       = "+" if p["pnl"] >= 0 else ""
                cat_weight = p["live_usd"] / cat_total * 100 if cat_total > 0 else 0
                tot_weight = p["live_usd"] / total_cur * 100 if total_cur > 0 else 0

                if p["price_ok"]:
                    kz_str = (
                        f"K/Z: {sign}${p['pnl']:,.0f} ({sign}{p['pnl_pct']:.1f}%) | "
                        f"Kategori İçi Ağırlık: %{cat_weight:.1f} | "
                        f"Toplam Portföy Ağırlığı: %{tot_weight:.1f}"
                    )
                    if p["ac"] == "tefas":
                        live_tl = p["live_usd"] * usd_try
                        fiyat_str = (
                            f"Anlık Birim Fiyat: ₺{p['live_price'] * usd_try:,.4f} "
                            f"(${p['live_price']:,.4f}) | "
                            f"Varlık Değeri: ₺{live_tl:,.0f} (${p['live_usd']:,.0f})"
                        )
                    else:
                        fiyat_str = (
                            f"Anlık Birim Fiyat: ${p['live_price']:,.2f} | "
                            f"Varlık Değeri: ${p['live_usd']:,.0f}"
                        )
                else:
                    if p["ac"] == "tefas":
                        avg_tl    = p["avg"] * usd_try
                        cost_tl   = p["cost_usd"] * usd_try
                        fiyat_str = (
                            f"Anlık Birim Fiyat: [Çekilemedi] | "
                            f"Toplam Yatırılan: ₺{cost_tl:,.0f} (${p['cost_usd']:,.0f})"
                        )
                    else:
                        fiyat_str = "Anlık Birim Fiyat: [Çekilemedi] | Varlık Değeri: [Bilinmiyor]"
                    kz_str = "K/Z: [Fiyat çekilemedi — K/Z yorumu yapma, pozisyon mevcut]"

                lines.append(
                    f"  {p['symbol']}: "
                    f"Miktar: {p['shr']:,g} adet | "
                    f"Ort. Birim Maliyet: ${p['avg']:,.2f} | "
                    f"Toplam Yatırılan: ${p['cost_usd']:,.0f} | "
                    f"{fiyat_str} | "
                    f"{kz_str}"
                )
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error("_build_portfolio_context hatası: %s", e)
        return f"Portföy alınamadı: {e}"




def _get_recent_news_context() -> str:
    """Son haberleri ve on-chain verileri direktöre bağlam olarak hazırla."""
    ctx_parts = []
    try:
        from core.database import SessionLocal
        from core import crud
        with SessionLocal() as db:
            summary = crud.get_portfolio_summary(db)
        crypto_pos = [p for p in summary["positions"]
                      if p["is_open"] and p.get("asset_class") == "crypto"]
        if crypto_pos:
            from data.onchain_client import get_crypto_onchain_data
            btc_data = get_crypto_onchain_data("BTC")
            if btc_data.get("metrics"):
                m = btc_data["metrics"]
                lines = ["ON-CHAIN DURUMU (BTC):"]
                for key, label in [("mvrv_zscore","MVRV Z-Score"),("nupl","NUPL"),("sth_sopr","STH-SOPR")]:
                    if key in m:
                        lines.append(f"  {label}: {m[key]['value']} — {m[key]['note']}")
                lines.append(f"  Genel: {btc_data['summary']}")
                ctx_parts.append("\n".join(lines))
    except Exception as e:
        logger.debug("On-chain baglam: %s", e)
    try:
        from data.news_client import get_global_macro_news
        news = get_global_macro_news()
        if news:
            lines = ["GÜNCEL MAKRO HABERLER (son 3):"]
            for n in news[:3]:
                lines.append(f"  • {n.get('title','')[:100]} [{n.get('source','')}]")
            ctx_parts.append("\n".join(lines))
    except Exception as e:
        logger.debug("Haber baglam: %s", e)
    return "\n\n".join(ctx_parts) if ctx_parts else ""


def ask_director(user_message: str, deep_analysis: bool = False) -> str:
    """
    Kullanıcının mesajına direktörden yanıt al.
    deep_analysis=True: /sor komutuyla tetiklenir, XML düşünce odaları kullanır.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "❌ API anahtarı eksik."

    try:
        from strategy_data import fetch_usd_try_rate
        usd_try = fetch_usd_try_rate()
    except Exception:
        usd_try = 44.0

    portfolio_ctx    = _build_portfolio_context(usd_try)
    memory_ctx       = _build_memory_context()
    tefas_ctx        = _build_tefas_context()
    tr_time          = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d %B %Y, %H:%M")
    detected_tickers = _extract_tickers_from_message(user_message)
    live_price_ctx   = _fetch_live_prices(detected_tickers)

    news_onchain_ctx = ""
    if deep_analysis:
        try:
            news_onchain_ctx = _get_recent_news_context()
        except Exception as e:
            logger.debug("Derin analiz baglam: %s", e)

    if deep_analysis:
        system_prompt = f"""Sen bir Strateji Mentörüsün — yatırım botu değil.
Cankat'ın kişisel baş yatırım direktörü ve risk yönetimi danışmanısın.

{portfolio_ctx}

{memory_ctx}
{live_price_ctx}

{tefas_ctx}

{news_onchain_ctx}

TARİH/SAAT: {tr_time} | USD/TRY: {usd_try:.2f}

─── DÜŞÜNCE ODALARI SİSTEMİ ───────────────────────────────────────────────
Her soruyu şu XML etiketleriyle adım adım analiz et:

<makro_analiz>
Küresel atmosfere bak: DXY, VIX, tahvil faizleri, jeopolitik riskler.
Güncel haberler piyasayı destekliyor mu, sabote mi ediyor?
"Veriler X diyor ama haberler Y riski taşıyor" formatında yaz.
</makro_analiz>

<mikro_analiz>
İlgili varlığın temel verilerini değerlendir.
Hisse ise: F/K, büyüme, insider. Kripto ise: MVRV, SOPR, on-chain.
Emtia/fon ise: Sektör dinamikleri, talep/arz dengesi.
</mikro_analiz>

<uyumsuzluk_analizi>
KRİTİK ADIM: Veriler ile haberler/makro arasında ÇATIŞMA var mı?
ÖRNEK: "On-chain MVRV dip bölgesinde (alım sinyali) AMA DXY güçleniyor
ve jeopolitik gerilim tırmanıyor (risk-off) → Koruma moduna geç."
Çatışma varsa: korumacı öner. Uyum varsa: sinyali güçlü say.
</uyumsuzluk_analizi>

<risk_degerlendirmesi>
Portföydeki mevcut durumu kontrol et:
Nakit oranı yeterli mi? Konsantrasyon riski var mı?
</risk_degerlendirmesi>

<nihai_muhakeme>
"Evet ama..." veya "Hayır çünkü..." formatında konuş.
Asla sadece "Al" veya "Sat" deme. Mantık zincirini göster.
</nihai_muhakeme>

─── VERİ BİLİNCİ & MATEMATİK KURALI ──────────────────────────────────────
Sana sağlanan portföy verisi Supabase'den, fiyat verisi yfinance'den anlık çekilir.
"Erişimim yok", "Bağlantım yok" DEME — bu bağlam senin CANLI veri kaynağındır.

PORTFÖY KAYNAĞI KURALI — KESİN:
Portföy analizi için YALNIZCA yukarıdaki "MEVCUT PORTFÖY — CANLI VERİ" bölümünü
baz al. Sohbet geçmişinde adı geçen varlıkları (ZIL, HONEY vb.) portföyde varmış
gibi değerlendirme. O listede olmayan hiçbir varlığı analize dahil etme.
Geçmiş konuşmalar referans için kullanılabilir ama portföy durumu için değil.

TEFAS FONU YORUMU:
"TEFAS Fonu" kategorisindeki varlıklar (IIH, AOY, TTE, URA, TI1, TSI vb.)
Türk yatırım fonlarıdır. Portföy listesinde görüyorsan kesinlikle VAR demektir.
"TEFAS fonlarına ait veri göremiyorum" DEME — listede yazıyorsa oradadır.
Fon içeriğini bilemezsin ama: toplam TL değerini yorumla, portföy ağırlığını söyle,
kullanıcı sorarsa "/fon [KOD]" komutunu öner.

KESİN KURAL — MATEMATİK VE GEÇMİŞ VERİ YASAĞI:
Her varlığın K/Z Yüzdesi yukarıdaki "MEVCUT PORTFÖY" bölümünde HAZIR verilmiştir.
KESİNLİKLE kendi kendine hesaplama yapma. Sohbet geçmişinde geçen HİÇBİR yüzde,
fiyat veya K/Z rakamını kullanma — o veriler eskimiş olabilir.
SADECE yukarıdaki portföy bölümündeki güncel rakamları kullan.
Örnek: Geçmişte "IREN -%91" yazmışsa bunu unutu; portföy bölümündeki güncel değeri kullan.
Bir varlık için "K/Z: [Fiyat çekilemedi]" yazıyorsa o varlık için K/Z yorumu YAPMA.

K/Z KURALI:
Bir varlık için "K/Z: [Anlık fiyat alınamadı]" yazıyorsa o varlık için kesinlikle
K/Z yorumu yapma. Sadece maliyet bilgisini ver, güncel değeri bilinmiyor de.

─── ÜSLUP ──────────────────────────────────────────────────────────────────
- Türkçe, temkinli, çok yönlü mentor üslubu.
- Balık vermek yerine balık tutmayı öğret.
- Telegram formatı: başlıklar için <b>bold</b>.
- 400-600 kelime arası yanıt.
"""
    else:
        system_prompt = f"""Sen deneyimli bir portföy strateji direktörüsün.
Cankat'ın kişisel yatırım direktörüsün.

{portfolio_ctx}
{memory_ctx}
{live_price_ctx}

{tefas_ctx}

TARİH/SAAT: {tr_time} | USD/TRY: {usd_try:.2f}

VERİ BİLİNCİ: Sağlanan portföy verisi Supabase'den anlık çekilmektedir.
"Erişimim yok" DEME — bu bağlam senin canlı veri kaynağındır.
PORTFÖY KAYNAĞI KURALI: Portföy analizi için YALNIZCA "MEVCUT PORTFÖY — CANLI VERİ"
bölümünü baz al. Sohbet geçmişinde geçen eski varlıkları (satılmış olanlar dahil)
portföyde varmış gibi değerlendirme. O listede olmayan hiçbir varlığı analize dahil etme.
TEFAS FONU KURALI: "TEFAS Fonu" kategorisinde görünen varlıklar (IIH, AOY, TTE vb.)
listede varsa portföyde kesinlikle VAR demektir. "Göremiyorum" DEME.
MATEMATİK KURALI: Varlık ağırlıkları ve K/Z oranları "MEVCUT PORTFÖY" bölümünde
hazır verilmiştir. Kendi başına hesaplama yapma. Sohbet geçmişindeki eski fiyat ve
K/Z rakamlarını kullanma — sadece yukarıdaki güncel portföy verisini kullan.

KURALLAR: Türkçe, somut, sorumluluktan kaçma. Geçmiş konuşmaya atıfta bulunabilirsin.
Telegram formatı için <b>bold</b> ve <i>italic</i> kullanabilirsin.
"""

    history = _load_history()
    history.append({"role": "user", "content": user_message})

    client     = anthropic.Anthropic(api_key=api_key)
    last_error = None
    max_tokens = 2500 if deep_analysis else 1500

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system_prompt,
                messages=history[-MAX_HISTORY_TURNS * 2:],
            )
            answer = response.content[0].text.strip()
            history.append({"role": "assistant", "content": answer})
            _save_history(history)
            logger.info("Direktör yanıtladı (%d karakter, derin=%s).", len(answer), deep_analysis)

            # ── Karar Günlüğü Hook ────────────────────────────────────────
            # Direktörün yanıtını arka planda analiz et.
            # Bu işlem asenkron değil ama try/except ile izole edilmiş —
            # hata verirse direktörün yanıtı zaten kullanıcıya gönderilmiş.
            try:
                from memory.decision_logger import log_decision
                trigger = "sor" if deep_analysis else "sohbet"
                # Ayrı thread'de çalıştır, yanıtı geciktirmesin
                import threading
                threading.Thread(
                    target=log_decision,
                    args=(answer, user_message, trigger),
                    daemon=True
                ).start()
            except Exception as _log_err:
                logger.warning("Karar günlüğü başlatılamadı: %s", _log_err)
            # ─────────────────────────────────────────────────────────────

            return answer

        except anthropic.APIError as e:
            last_error = e
            if "529" in str(e) or "overloaded" in str(e).lower():
                if attempt < 2:
                    wait = (attempt + 1) * 3
                    logger.warning("Claude API yüklü, %ds bekleniyor...", wait)
                    import time as _time
                    _time.sleep(wait)
                    continue
            logger.error("Claude API hatası: %s", e)
            break
        except Exception as e:
            last_error = e
            logger.error("Beklenmeyen hata: %s", e)
            break

    if last_error and ("529" in str(last_error) or "overloaded" in str(last_error).lower()):
        return "⚠️ Claude API şu an yoğun. 1-2 dakika sonra tekrar dene."
    return f"⚠️ Direktör yanıt veremedi: {last_error}"
