# watchlist_analyzer.py — Günlük Watchlist Akıllı Analiz Motoru
#
# 6 Tetikleyici:
#   T1: Fiyat hareketi > %5
#   T2: 52H yakınlığı > %90 + Hacim 2x (ikili koşul)
#   T3: Insider alımı (son 7 gün)
#   T4: Sinyal haberi (FDA, sözleşme, patent...)
#   T5: Hacim patlaması > 2x ortalama
#   T6: RSI < 35 (aşırı satım)
#
# Kural: En az 2 tetikleyici gerekli → Claude analizi tetiklenir
# İstisna: T3 (insider) tek başına tetiklemez — 2 şart

import time
import logging
import os
from datetime import datetime, timezone, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

# ─── Faz tanımları ───────────────────────────────────────────────────────────

PHASE_1 = "phase1"   # 11:00 TR — Erken uyarı, sadece T1+T4, Claude YOK
PHASE_2 = "phase2"   # 23:30 TR — Tam analiz, 6 tetikleyici, Claude AKTİF

# ─── Tetikleyici eşikleri ────────────────────────────────────────────────────

PRICE_MOVE_THRESHOLD   = 5.0    # T1: %5 fiyat hareketi (her iki faz)
PREMARKET_THRESHOLD    = 3.0    # T1 Faz-1: pre-market %3+ hareket (daha hassas)
W52H_THRESHOLD         = 90.0   # T2: 52H pozisyon %90+
VOLUME_RATIO_THRESHOLD = 2.0    # T2+T5: Hacim 2x ortalama
RSI_OVERSOLD           = 35.0   # T6: RSI < 35
MIN_TRIGGERS           = 2      # Minimum tetikleyici sayısı (Faz-2)


def _safe(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except Exception:
        return default


def calculate_rsi(ticker: str, period: int = 14) -> float:
    """yfinance'ten günlük kapanış verisiyle RSI hesapla."""
    try:
        hist = yf.Ticker(ticker).history(period="3mo", interval="1d")
        if hist.empty or len(hist) < period + 1:
            return 50.0  # Veri yoksa nötr dön

        closes = hist["Close"].values
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

        gains  = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs  = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 1)
    except Exception as e:
        logger.debug("RSI hesaplama hatası %s: %s", ticker, e)
        return 50.0


def check_triggers(ticker: str, news_articles: list = None) -> dict:
    """
    Bir hisse için tüm tetikleyicileri kontrol et.
    Returns: {ticker, triggers, trigger_count, data}
    """
    triggers   = []
    trigger_details = {}
    data = {}

    try:
        # ── Fiyat + Hacim verisi (fast_info) ─────────────────────────────
        fi = yf.Ticker(ticker).fast_info
        price     = _safe(getattr(fi, "last_price", 0))
        prev      = _safe(getattr(fi, "previous_close", price) or price)
        w52h      = _safe(getattr(fi, "year_high", 0))
        w52l      = _safe(getattr(fi, "year_low", 0))
        volume    = _safe(getattr(fi, "last_volume", 0))
        avg_vol   = _safe(getattr(fi, "three_month_average_volume", 0))

        change_pct = ((price - prev) / prev * 100) if prev > 0 else 0
        vol_ratio  = (volume / avg_vol) if avg_vol > 0 else 1.0

        # 52H pozisyon yüzdesi
        w52h_pos = 0.0
        if w52h > 0 and w52l > 0 and (w52h - w52l) > 0:
            w52h_pos = (price - w52l) / (w52h - w52l) * 100

        data = {
            "price":      price,
            "change_pct": round(change_pct, 2),
            "w52h":       w52h,
            "w52l":       w52l,
            "w52h_pos":   round(w52h_pos, 1),
            "volume":     int(volume),
            "avg_vol":    int(avg_vol),
            "vol_ratio":  round(vol_ratio, 2),
        }

        # ── T1: Fiyat hareketi > %5 ───────────────────────────────────────
        if abs(change_pct) >= PRICE_MOVE_THRESHOLD:
            direction = "yukarı" if change_pct > 0 else "aşağı"
            triggers.append("T1")
            trigger_details["T1"] = f"Fiyat {direction} %{abs(change_pct):.1f} hareket etti"

        # ── T2: 52H > %90 + Hacim 2x (ikili koşul) ──────────────────────
        if w52h_pos >= W52H_THRESHOLD and vol_ratio >= VOLUME_RATIO_THRESHOLD:
            triggers.append("T2")
            trigger_details["T2"] = (
                f"52H pozisyon %{w52h_pos:.0f} + Hacim {vol_ratio:.1f}x ort. "
                f"→ Kırılım potansiyeli yüksek"
            )

        # ── T5: Hacim patlaması > 2x (tek başına) ────────────────────────
        if vol_ratio >= VOLUME_RATIO_THRESHOLD and "T2" not in triggers:
            triggers.append("T5")
            trigger_details["T5"] = f"Hacim {vol_ratio:.1f}x ortalama → Kurumsal hareket"

        # ── T6: RSI < 35 (aşırı satım) ───────────────────────────────────
        rsi = calculate_rsi(ticker)
        data["rsi"] = rsi
        if rsi < RSI_OVERSOLD:
            triggers.append("T6")
            trigger_details["T6"] = f"RSI {rsi:.0f} — Aşırı satım bölgesi, dip fırsatı?"

    except Exception as e:
        logger.warning("Trigger check failed for %s: %s", ticker, e)

    # ── T3: Insider alımı (son 7 gün) ────────────────────────────────────
    try:
        from insider_tracker import fetch_insider_transactions, score_transactions
        txs    = fetch_insider_transactions(ticker, days=7)
        scored = score_transactions(txs)
        data["insider"] = scored

        if scored["buy_count"] > 0 and scored["score"] >= 2:
            triggers.append("T3")
            ceo_str = " (CEO/CFO dahil)" if scored["ceo_involved"] else ""
            cluster_str = " — KÜME ALIMI ⚡" if scored["cluster_buy"] else ""
            trigger_details["T3"] = (
                f"{scored['buy_count']} insider alımı "
                f"${scored['buy_value']/1000:.0f}K{ceo_str}{cluster_str}"
            )
    except Exception as e:
        logger.debug("Insider trigger failed for %s: %s", ticker, e)
        data["insider"] = {}

    # ── T4: Sinyal haberi ────────────────────────────────────────────────
    if news_articles:
        signal_news = [a for a in news_articles if a.get("is_signal")]
        if signal_news:
            triggers.append("T4")
            trigger_details["T4"] = f"{len(signal_news)} sinyal haber: {signal_news[0].get('title','')[:60]}..."

    return {
        "ticker":          ticker,
        "triggers":        triggers,
        "trigger_details": trigger_details,
        "trigger_count":   len(triggers),
        "data":            data,
    }


def run_watchlist_analysis(
    extra_tickers: list[str] = None,
    min_triggers: int = MIN_TRIGGERS,
) -> dict:
    """
    Watchlist + portföy hisselerini tara.
    En az min_triggers tetikleyicisi olan hisseler için Claude analizi yap.

    Returns:
        {
          "triggered": [analiz sonuçları],
          "screened":  [tetiklenmeyen hisseler özeti],
          "total":     int,
          "analyzed":  int,
          "timestamp": str,
        }
    """
    # Portföy + watchlist tickerları topla
    tickers = list(extra_tickers or [])
    try:
        from breakout_scanner import load_watchlist
        tickers += load_watchlist()
    except Exception:
        pass
    try:
        from portfolio_manager import load_portfolio
        port = load_portfolio()
        tickers += [p["ticker"] for p in port if p.get("ticker")]
    except Exception:
        pass

    tickers = list(dict.fromkeys(tickers))  # Tekrar kaldır
    if not tickers:
        return {"triggered": [], "screened": [], "total": 0, "analyzed": 0, "timestamp": ""}

    logger.info("Watchlist taraması: %d hisse", len(tickers))

    triggered  = []
    screened   = []

    for ticker in tickers:
        try:
            # Haber çek
            news_articles = []
            try:
                from news_fetcher import fetch_news_for_ticker
                news_articles = fetch_news_for_ticker(ticker, days=2)
            except Exception:
                pass

            # Tetikleyici kontrolü
            result = check_triggers(ticker, news_articles)

            if result["trigger_count"] >= min_triggers:
                logger.info("✅ %s — %d tetikleyici: %s",
                            ticker, result["trigger_count"], result["triggers"])
                triggered.append(result)
            else:
                screened.append({
                    "ticker":  ticker,
                    "price":   result["data"].get("price", 0),
                    "chg":     result["data"].get("change_pct", 0),
                    "w52h_pos": result["data"].get("w52h_pos", 0),
                    "trigger_count": result["trigger_count"],
                    "triggers": result["triggers"],
                })

            time.sleep(0.4)
        except Exception as e:
            logger.warning("Watchlist check failed for %s: %s", ticker, e)

    # Tetiklenen hisseler için Claude analizi yap
    analyzed_results = []
    if triggered:
        logger.info("%d hisse Claude analizine alınıyor...", len(triggered))
        try:
            from data_fetcher import enrich_ticker
            from news_fetcher import fetch_news_for_ticker, format_news_for_prompt
            from claude_analyzer import analyse_stock

            for t in triggered:
                try:
                    ticker = t["ticker"]
                    stock  = enrich_ticker(ticker)
                    if not stock.get("price"):
                        continue

                    articles  = fetch_news_for_ticker(ticker, days=3)
                    news_text = format_news_for_prompt(articles)
                    analysis  = analyse_stock(stock, news_text)

                    if analysis:
                        analysis["_stock_meta"]       = stock
                        analysis["_triggers"]         = t["triggers"]
                        analysis["_trigger_details"]  = t["trigger_details"]
                        analysis["_trigger_data"]     = t["data"]
                        analyzed_results.append(analysis)

                    time.sleep(0.5)
                except Exception as e:
                    logger.warning("Claude analizi başarısız %s: %s", t["ticker"], e)
        except Exception as e:
            logger.error("Toplu analiz hatası: %s", e)

    # Skora göre sırala
    analyzed_results.sort(
        key=lambda x: x.get("nihai_guven_skoru", 0), reverse=True
    )

    now_tr = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    return {
        "triggered": analyzed_results,
        "screened":  sorted(screened, key=lambda x: x["trigger_count"], reverse=True),
        "total":     len(tickers),
        "analyzed":  len(analyzed_results),
        "timestamp": now_tr,
    }


# ─── Telegram Formatı ────────────────────────────────────────────────────────

def format_watchlist_telegram(result: dict) -> list[str]:
    """Watchlist analiz sonucunu Telegram mesaj listesine çevir."""
    messages   = []
    triggered  = result["triggered"]
    screened   = result["screened"]
    total      = result["total"]
    analyzed   = result["analyzed"]
    ts         = result["timestamp"]

    # ── Başlık mesajı ─────────────────────────────────────────────────────
    trigger_emoji = "🔥" if analyzed >= 3 else ("⚡" if analyzed >= 1 else "😴")
    header = (
        f"{trigger_emoji} <b>TAKİP LİSTESİ GÜNLÜK RAPORU</b>\n"
        f"<i>{ts} TR — ABD Piyasa Açılışı Öncesi</i>\n\n"
        f"📊 {total} hisse tarandı\n"
        f"✅ {analyzed} hisse tetiklendi ve analiz edildi\n"
        f"💤 {total - analyzed} hisse: Tetikleyici yok\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    messages.append(header)

    # ── Tetiklenen hisseler ───────────────────────────────────────────────
    if not triggered:
        messages.append(
            "😴 <b>Bugün tetikleyici yok</b>\n\n"
            "<i>Tüm hisseler sakin. Fırsat beklenmiyor.</i>"
        )
    else:
        chunk = []
        for i, r in enumerate(triggered, 1):
            ticker   = r.get("hisse_sembolu", r.get("_stock_meta", {}).get("ticker", ""))
            score    = r.get("nihai_guven_skoru", 0)
            tavsiye  = r.get("tavsiye", "Tut")
            ozet     = r.get("analiz_ozeti", "")[:120]
            triggers = r.get("_triggers", [])
            tdetails = r.get("_trigger_details", {})
            tdata    = r.get("_trigger_data", {})

            price    = tdata.get("price", 0)
            chg      = tdata.get("change_pct", 0)
            w52h_pos = tdata.get("w52h_pos", 0)
            rsi      = tdata.get("rsi", 0)
            vol_r    = tdata.get("vol_ratio", 0)

            score_emoji = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
            tav_emoji   = {"Ağırlık Artır": "⬆️", "Tut": "➡️", "Azalt": "⬇️"}.get(tavsiye, "➡️")
            chg_str     = f"{chg:+.1f}%"

            # Tetikleyici listesi
            trigger_strs = []
            for t in triggers:
                detail = tdetails.get(t, "")[:50]
                trigger_strs.append(f"  • {t}: {detail}")

            entry = (
                f"\n{score_emoji} <b>#{i} {ticker}</b> — {score} puan\n"
                f"   💰 ${price:.2f} ({chg_str}) | 52H: %{w52h_pos:.0f}"
                + (f" | RSI: {rsi:.0f}" if rsi and rsi != 50 else "")
                + (f" | Hacim: {vol_r:.1f}x" if vol_r >= 1.5 else "")
                + f"\n   {tav_emoji} <b>{tavsiye}</b>\n"
                + "\n".join(trigger_strs) + "\n"
                + f"   💬 <i>{ozet}</i>"
            )
            chunk.append(entry)

            if len(chunk) == 4 or i == len(triggered):
                messages.append("\n".join(chunk))
                chunk = []

    # ── Sakin hisseler özeti (sadece en çok tetiklenenleri) ──────────────
    if screened:
        near_miss = [s for s in screened if s["trigger_count"] == 1][:5]
        if near_miss:
            nm_lines = ["📡 <b>Yakın Kaçanlar (1 tetikleyici):</b>"]
            for s in near_miss:
                t_str = ", ".join(s["triggers"]) if s["triggers"] else "—"
                nm_lines.append(
                    f"  • {s['ticker']}: ${s['price']:.2f} ({s['chg']:+.1f}%) "
                    f"| 52H:%{s['w52h_pos']:.0f} | {t_str}"
                )
            messages.append("\n".join(nm_lines))

    # ── Footer ────────────────────────────────────────────────────────────
    messages.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Bu analiz yatırım tavsiyesi değildir. DYOR.</i>\n"
        "<i>Bir sonraki rapor: Yarın 15:00 TR</i>"
    )

    return messages


# ─────────────────────────────────────────────────────────────────────────────
# FAZ 1 — Erken Uyarı (11:00 TR)
# ─────────────────────────────────────────────────────────────────────────────

def run_phase1_scan(extra_tickers: list[str] = None) -> dict:
    """
    Faz 1: Pre-market erken uyarı taraması.
    Sadece T1 (pre-market fiyat hareketi) ve T4 (sinyal haberi) kontrol eder.
    Claude analizi yok — sadece alarm üretir.
    """
    tickers = _collect_tickers(extra_tickers)
    if not tickers:
        return {"alerts": [], "total": 0, "phase": PHASE_1}

    logger.info("FAZ 1 taraması: %d hisse (pre-market)", len(tickers))
    alerts = []

    for ticker in tickers:
        try:
            fi    = yf.Ticker(ticker).fast_info
            price = _safe(getattr(fi, "last_price", 0))
            prev  = _safe(getattr(fi, "previous_close", price) or price)
            chg   = ((price - prev) / prev * 100) if prev > 0 else 0

            triggered  = []
            details    = {}

            # T1 — Pre-market fiyat hareketi (eşik daha düşük: %3)
            if abs(chg) >= PREMARKET_THRESHOLD:
                direction = "yukarı ▲" if chg > 0 else "aşağı ▼"
                triggered.append("T1")
                details["T1"] = f"Pre-market %{abs(chg):.1f} {direction}"

            # T4 — Sinyal haberi (son 18 saat — dün kapanışından bu yana)
            try:
                from news_fetcher import fetch_news_for_ticker_for_ticker
                articles = fetch_news_for_ticker(ticker, days=1)
                signal_news = [a for a in articles if a.get("is_signal")]
                if signal_news:
                    triggered.append("T4")
                    details["T4"] = f"{len(signal_news)} sinyal haber: {signal_news[0].get('title','')[:55]}..."
            except Exception:
                pass

            if triggered:
                alerts.append({
                    "ticker":   ticker,
                    "price":    price,
                    "chg":      round(chg, 2),
                    "triggers": triggered,
                    "details":  details,
                    "note":     "Faz 2 (23:30 TR) tam analizini bekle",
                })

            time.sleep(0.25)
        except Exception as e:
            logger.warning("Faz1 check hatası %s: %s", ticker, e)

    alerts.sort(key=lambda x: abs(x["chg"]), reverse=True)
    logger.info("Faz 1 tamamlandı: %d alarm", len(alerts))
    return {"alerts": alerts, "total": len(tickers), "phase": PHASE_1}


def format_phase1_telegram(result: dict) -> str:
    """Faz 1 Telegram mesajı — kısa, aksiyon yok, sadece radar."""
    from datetime import timezone
    now_tr = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%H:%M")

    alerts = result["alerts"]
    total  = result["total"]

    if not alerts:
        return (
            f"📡 <b>Sabah Radarı {now_tr} TR</b>\n"
            f"<i>{total} hisse tarandı — pre-market sakin</i>\n"
            f"💤 Dikkat çeken hareket yok. Piyasa açılışını normal izle."
        )

    lines = [
        f"📡 <b>Sabah Radarı — {now_tr} TR</b>",
        f"<i>Pre-market erken uyarı · {total} hisse · Claude analizi YOK</i>",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"",
    ]

    for a in alerts:
        chg    = a["chg"]
        emoji  = "🔥" if abs(chg) >= 5 else "⚡"
        arrow  = "▲" if chg > 0 else "▼"
        t_list = " + ".join(a["triggers"])

        lines.append(
            f"{emoji} <b>{a['ticker']}</b>  "
            f"{arrow} %{abs(chg):.1f}  ·  ${a['price']:.2f}"
        )
        for k, v in a["details"].items():
            lines.append(f"   <i>{v}</i>")
        lines.append(f"   📌 Tetikleyici: {t_list}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "⏳ <i>Gece 23:30 TR tam analiz raporu geliyor.</i>",
        "<i>Bu alarm sadece dikkat için — henüz işlem yapma.</i>",
    ])

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# FAZ 2 — Tam Analiz (23:30 TR)
# ─────────────────────────────────────────────────────────────────────────────

def run_phase2_analysis(extra_tickers: list[str] = None) -> dict:
    """
    Faz 2: Kapanış sonrası tam analiz.
    Tüm 6 tetikleyici çalışır. En az 2 tetikleyici → Claude analizi.
    """
    result = run_watchlist_analysis(extra_tickers=extra_tickers, min_triggers=MIN_TRIGGERS)
    result["phase"] = PHASE_2
    return result


def format_phase2_telegram(result: dict) -> list[str]:
    """
    Faz 2 Telegram mesajları — tam analiz formatı.
    Mevcut format_watchlist_telegram'ı kullanır ama başlık farklı.
    """
    from datetime import timezone
    now_tr = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    messages  = []
    triggered = result["triggered"]
    screened  = result["screened"]
    total     = result["total"]
    analyzed  = result["analyzed"]

    # Başlık
    trigger_emoji = "🔥" if analyzed >= 3 else ("⚡" if analyzed >= 1 else "😴")
    header = (
        f"{trigger_emoji} <b>GECE RAPORU — TAM ANALİZ</b>\n"
        f"<i>{now_tr} TR · Piyasa kapandıktan sonra · Claude analizi aktif</i>\n\n"
        f"📊 {total} hisse tarandı · "
        f"✅ {analyzed} tetiklendi · "
        f"💤 {total - analyzed} sakin\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    messages.append(header)

    if not triggered:
        messages.append(
            "😴 <b>Bugün tetikleyici eşiği aşılmadı</b>\n\n"
            "<i>Tüm hisseler sakin. Yarın tekrar kontrol edilecek.</i>"
        )
    else:
        chunk = []
        for i, r in enumerate(triggered, 1):
            ticker   = r.get("hisse_sembolu", r.get("_stock_meta", {}).get("ticker", ""))
            score    = r.get("nihai_guven_skoru", 0)
            tavsiye  = r.get("tavsiye", "Tut")
            ozet     = r.get("analiz_ozeti", "")[:130]
            triggers = r.get("_triggers", [])
            tdetails = r.get("_trigger_details", {})
            tdata    = r.get("_trigger_data", {})

            price    = tdata.get("price", 0)
            chg      = tdata.get("change_pct", 0)
            w52h_pos = tdata.get("w52h_pos", 0)
            rsi      = tdata.get("rsi", 0)
            vol_r    = tdata.get("vol_ratio", 0)

            score_emoji = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
            tav_emoji   = {"Ağırlık Artır": "⬆️", "Tut": "➡️", "Azalt": "⬇️"}.get(tavsiye, "➡️")

            # Tetikleyici özeti
            t_strs = []
            for t in triggers:
                detail = tdetails.get(t, "")[:45]
                t_strs.append(f"  • {t}: {detail}")

            entry = (
                f"\n{score_emoji} <b>#{i} {ticker}</b> — {score} puan\n"
                f"   💰 ${price:.2f} ({chg:+.1f}%)"
                + (f" · 52H %{w52h_pos:.0f}" if w52h_pos else "")
                + (f" · RSI {rsi:.0f}" if rsi and rsi != 50 else "")
                + (f" · Hacim {vol_r:.1f}x" if vol_r >= 1.5 else "")
                + f"\n   {tav_emoji} <b>{tavsiye}</b>\n"
                + "\n".join(t_strs) + "\n"
                + f"   💬 <i>{ozet}</i>"
            )
            chunk.append(entry)

            if len(chunk) == 4 or i == len(triggered):
                messages.append("\n".join(chunk))
                chunk = []

    # Yakın kaçanlar
    near = [s for s in screened if s["trigger_count"] == 1][:4]
    if near:
        nm = ["📡 <b>1 tetikleyici (eşiği geçemedi):</b>"]
        for s in near:
            nm.append(
                f"  • {s['ticker']}: ${s['price']:.2f} ({s['chg']:+.1f}%) "
                f"· {', '.join(s['triggers'])}"
            )
        messages.append("\n".join(nm))

    messages.append(
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Bu analiz yatırım tavsiyesi değildir. DYOR.</i>\n"
        "<i>Sonraki sabah radarı: 11:00 TR</i>"
    )

    return messages


# ─── Yardımcı: Ticker toplama ────────────────────────────────────────────────

def _collect_tickers(extra: list[str] = None) -> list[str]:
    """Portföy + watchlist + extra tickerları topla, tekrar kaldır."""
    tickers = list(extra or [])
    try:
        from breakout_scanner import load_watchlist
        tickers += load_watchlist()
    except Exception:
        pass
    try:
        from portfolio_manager import load_portfolio
        tickers += [p["ticker"] for p in load_portfolio() if p.get("ticker")]
    except Exception:
        pass
    return list(dict.fromkeys(tickers))
