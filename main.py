# main.py — Sistemin Kalbi: FastAPI Uygulaması
#
# Bu dosya üç rolü tek çatı altında birleştiriyor:
#   1. Telegram bot webhook'unu dinliyor (kullanıcı mesajları)
#   2. Arka plan görevlerini zamanlıyor (VIX izleme, sabah özeti vs.)
#   3. İleride Reflex dashboard'a veri sağlayacak API endpoint'leri sunuyor
#
# Railway bu dosyayı `uvicorn main:app` komutuyla çalıştırır.

import os
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# Loglama ayarı — Railway'de tüm loglar konsola gider, oradan izleyebilirsin
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Bot'u ve Zamanlayıcıyı Başlat ───────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI'nin yaşam döngüsü yöneticisi.
    Uygulama başlarken bot ve zamanlayıcıyı başlatır,
    kapanırken düzgünce durdurur.
    """
    logger.info("🚀 Sistem başlatılıyor...")

    # Telegram bot'unu başlat
    from bot import start_bot, stop_bot
    await start_bot()
    logger.info("✅ Telegram bot aktif")

    # Arka plan görevlerini zamanla
    _schedule_jobs()
    scheduler.start()
    logger.info("✅ Zamanlayıcı aktif — %d görev planlandı", len(scheduler.get_jobs()))

    yield  # Uygulama burada çalışır

    # Kapatma
    logger.info("Sistem kapatılıyor...")
    scheduler.shutdown(wait=False)
    await stop_bot()
    logger.info("Sistem güvenle kapatıldı.")


app = FastAPI(
    title="Strateji Direktörü API",
    description="Otonom portföy izleme ve interaktif direktör sistemi",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — dashboard'un API çağrıları yapabilmesi için
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static dosyaları sun — dashboard HTML, CSS, JS burada
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard")
async def dashboard():
    """Ana dashboard sayfasını sun."""
    return FileResponse(os.path.join(static_dir, "index.html"))


# ─── Arka Plan Görev Zamanlaması ──────────────────────────────────────────────

def _schedule_jobs():
    """
    Tüm otomatik görevleri zamanlayıcıya kaydet.
    APScheduler AsyncIOScheduler async fonksiyon bekler — lambda değil.
    """
    # Katman 1: Her 15 dakikada VIX, BTC, USD/TRY, stablecoin
    scheduler.add_job(
        _run_layer1,
        trigger="interval",
        minutes=15,
        id="layer1",
        name="Katman 1 — Acil Alarmlar",
        misfire_grace_time=120,
    )

    # Katman 2: Her saat başı
    scheduler.add_job(
        _run_layer2,
        trigger="interval",
        hours=1,
        id="layer2",
        name="Katman 2 — Önemli Sinyaller",
        misfire_grace_time=300,
    )

    # Katman 3: Her sabah 07:30 TR — her zaman sabah özeti gönderir
    scheduler.add_job(
        _run_layer3,
        trigger="cron",
        hour=7,
        minute=30,
        id="layer3",
        name="Katman 3 — Sabah Özeti",
    )

    # Performans takibi: Her Pazar 23:00 TR
    scheduler.add_job(
        _run_performance_tracker,
        trigger="cron",
        day_of_week="sun",
        hour=23,
        minute=0,
        id="performance",
        name="Haftalık Performans Takibi",
    )

    # Hisse sağlık taraması: Her Pazartesi 09:00 TR
    scheduler.add_job(
        _run_portfolio_scanner,
        trigger="cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="scanner",
        name="Haftalık Hisse Taraması",
    )


async def _run_in_executor(fn, *args):
    """
    Senkron (blocking) fonksiyonu thread pool'da çalıştırır.
    Event loop'u bloke etmez.
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, fn, *args)
    except Exception as e:
        logger.error("Arka plan görevi hatası [%s]: %s", fn.__name__, e)


# APScheduler'a geçirilen async fonksiyonlar — her katman için ayrı

async def _run_layer1():
    from trigger_monitor import run as run_trigger
    logger.info("Katman 1 başlatılıyor...")
    await _run_in_executor(run_trigger, 1, False)


async def _run_layer2():
    from trigger_monitor import run as run_trigger
    logger.info("Katman 2 başlatılıyor...")
    await _run_in_executor(run_trigger, 2, False)


async def _run_layer3():
    from trigger_monitor import run as run_trigger
    logger.info("Katman 3 başlatılıyor...")
    await _run_in_executor(run_trigger, 3, True)


async def _run_performance_tracker():
    from performance_tracker import run as run_perf
    logger.info("Performans takibi başlatılıyor...")
    await _run_in_executor(run_perf)


async def _run_portfolio_scanner():
    from portfolio_scanner import run as run_scanner
    logger.info("Hisse taraması başlatılıyor...")
    await _run_in_executor(run_scanner)


# Eski _run_sync — bot.py'deki cmd_tetikle hâlâ kullanıyor, koru
async def _run_sync(fn, *args):
    await _run_in_executor(fn, *args)


# ─── API Endpoint'leri ────────────────────────────────────────────────────────

@app.get("/")
async def health_check():
    """Railway'in sağlık kontrolü için. 200 dönerse sistem ayakta."""
    jobs = scheduler.get_jobs()
    return {
        "status": "online",
        "version": "2.0.0",
        "scheduled_jobs": len(jobs),
        "jobs": [{"id": j.id, "name": j.name,
                  "next_run": str(j.next_run_time)} for j in jobs],
    }


@app.get("/api/macro")
async def get_macro():
    """Makro göstergeler — dashboard ana sayfa için."""
    try:
        from macro_dashboard import fetch_macro_data
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, fetch_macro_data)
        result = {}
        for key, ind in data.items():
            result[key] = {
                "label":      ind.label,
                "value":      ind.value,
                "change_pct": ind.change_pct,
                "unit":       ind.unit,
                "group":      ind.group,
                "signal":     ind.signal,
                "note":       ind.note,
            }
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/portfolio")
async def get_portfolio_detail():
    """Portföy anlık değerler ve K/Z — dashboard için."""
    try:
        from portfolio_manager import load_portfolio
        from strategy_data import fetch_usd_try_rate
        import yfinance as yf

        portfolio = [p for p in load_portfolio() if float(p.get("shares", 0)) > 0]
        usd_try   = fetch_usd_try_rate()

        # Altın fiyatı
        gold_usd = 0.0
        try:
            h = yf.Ticker("GC=F").history(period="2d")
            if not h.empty:
                gold_usd = float(h["Close"].iloc[-1])
        except Exception:
            pass

        class_data: dict = {}
        labels = {
            "us_equity": "ABD Hisse", "crypto": "Kripto",
            "commodity": "Emtia",     "tefas":  "TEFAS",
        }

        for p in portfolio:
            ac  = (p.get("asset_class") or "us_equity").strip()
            if ac in ("other", ""):
                ac = "us_equity"
            shr = float(p.get("shares", 0))
            avg = float(p.get("avg_cost", 0))
            cur = p.get("currency", "USD")
            tk  = p.get("ticker", "")
            cost = shr * avg / usd_try if cur == "TRY" else shr * avg
            live = cost
            try:
                if tk in ("ALTIN_GRAM_TRY",) and gold_usd > 0:
                    live = shr * (gold_usd * usd_try / 31.1035) / usd_try
                elif ac == "tefas":
                    from turkey_fetcher import fetch_tefas_fund
                    fd = fetch_tefas_fund(tk)
                    if fd and fd.get("price", 0) > 0:
                        live = shr * float(fd["price"]) / usd_try
                else:
                    h = yf.Ticker(tk).history(period="2d")
                    if not h.empty:
                        lp = float(h["Close"].iloc[-1])
                        live = shr * lp / usd_try if cur == "TRY" else shr * lp
            except Exception:
                pass
            if ac not in class_data:
                class_data[ac] = {"label": labels.get(ac, ac),
                                  "value": 0.0, "cost": 0.0, "positions": []}
            class_data[ac]["value"] += live
            class_data[ac]["cost"]  += cost
            class_data[ac]["positions"].append({
                "ticker": tk, "shares": shr,
                "value": round(live, 0), "cost": round(cost, 0),
            })

        total_v = sum(d["value"] for d in class_data.values())
        total_c = sum(d["cost"]  for d in class_data.values())

        for ac, d in class_data.items():
            d["pnl"]     = round(d["value"] - d["cost"], 0)
            d["pnl_pct"] = round((d["value"] - d["cost"]) / d["cost"] * 100, 2) if d["cost"] else 0
            d["weight"]  = round(d["value"] / total_v * 100, 1) if total_v else 0
            d["value"]   = round(d["value"], 0)
            d["cost"]    = round(d["cost"], 0)

        return {
            "status":      "ok",
            "total_value": round(total_v, 0),
            "total_cost":  round(total_c, 0),
            "total_pnl":   round(total_v - total_c, 0),
            "total_pnl_pct": round((total_v - total_c) / total_c * 100, 2) if total_c else 0,
            "usd_try":     usd_try,
            "classes":     class_data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/briefing")
async def get_briefing():
    """
    Direktörün sabah brifingini üret.
    Anlık VIX, S&P trendi ve portföy durumuna göre kişiselleştirilmiş 4-5 cümle.
    Önbelleğe alınır — her çağrıda Claude tetiklenmez.
    """
    import time, json
    from pathlib import Path

    cache_file = Path(__file__).parent / "briefing_cache.json"

    # 30 dakika önbellek — sık çağrılsa bile Claude'u zorlamaz
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if time.time() - cached.get("ts", 0) < 1800:
                return {"status": "ok", "briefing": cached["text"], "cached": True}
        except Exception:
            pass

    try:
        import yfinance as yf
        from strategy_data import fetch_usd_try_rate

        # Anlık veriler — executor'da çalıştır
        def _fetch_market_data():
            _vix = 0.0
            _spy_chg = 0.0
            _btc = 0.0
            try:
                _vix = float(yf.Ticker("^VIX").fast_info.last_price or 0)
                spy_h = yf.Ticker("SPY").history(period="5d")
                if len(spy_h) >= 2:
                    _spy_chg = (float(spy_h["Close"].iloc[-1]) -
                               float(spy_h["Close"].iloc[-5])) / float(spy_h["Close"].iloc[-5]) * 100
                _btc = float(yf.Ticker("BTC-USD").fast_info.last_price or 0)
            except Exception:
                pass
            return _vix, _spy_chg, _btc

        loop = asyncio.get_running_loop()
        vix, spy_chg, btc = await loop.run_in_executor(None, _fetch_market_data)
        usd_try = await loop.run_in_executor(None, fetch_usd_try_rate)

        # Portföy durumu özeti
        port_resp = await get_portfolio_detail()
        port_summary = ""
        if port_resp.get("status") == "ok":
            pnl_pct = port_resp.get("total_pnl_pct", 0)
            port_summary = f"Portföy toplam K/Z: %{pnl_pct:+.1f}"

        def _generate_briefing():
            import anthropic as _anthropic
            _client = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
            _resp = _client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                system=(
                    "Sen bir portföy strateji direktörüsün. "
                    "Sabah brifingini yaz — 4-5 cümle, somut, eyleme dönüştürülebilir. "
                    "Türkçe. HTML tagı kullanma."
                ),
                messages=[{"role": "user", "content":
                    f"VIX: {vix:.1f} | S&P 5g: {spy_chg:+.1f}% | BTC: ${btc:,.0f} | "
                    f"USD/TRY: {usd_try:.2f} | {port_summary}\n\n"
                    "Bu verilere bakarak bugün için kısa bir sabah brifing yaz. "
                    "Piyasa tonu nedir, neye dikkat etmeli, portföy için önerisi nedir?"
                }],
            )
            return _resp.content[0].text.strip()

        text = await loop.run_in_executor(None, _generate_briefing)
        cache_file.write_text(json.dumps({"text": text, "ts": time.time()}))
        return {"status": "ok", "briefing": text, "cached": False}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/news")
async def get_news():
    """Piyasayı etkileyen önemli haberler — 1 saatlik önbellek."""
    import time, json as _json
    from pathlib import Path

    cache_file = Path(__file__).parent / "news_cache.json"

    # 1 saatlik önbellek
    if cache_file.exists():
        try:
            cached = _json.loads(cache_file.read_text())
            if time.time() - cached.get("ts", 0) < 3600:
                return {"status": "ok", "news": cached["news"], "cached": True}
        except Exception:
            pass

    def _fetch_news():
        import anthropic, json, re
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

        messages = [{"role": "user", "content":
            "Bugün global finansal piyasaları etkileyen en önemli 3-4 haberi ara ve bul. "
            "Kriter: Fed/merkez bankası kararları, jeopolitik gelişmeler, "
            "kripto/BTC haberleri, Türkiye/TL gelişmeleri, büyük şirket haberleri. "
            "Bulduğun haberleri şu JSON formatında döndür (başka hiçbir şey yazma): "
            '[{"title":"max 10 kelime başlık","summary":"tek cümle özet",'
            '"impact":"pozitif veya negatif veya nötr","asset_class":"etkilenen varlık"}]'
        }]

        # web_search tool döngüsü — Claude arama yapıp sonuç döndürene kadar
        for _ in range(5):  # max 5 tur
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=messages,
            )

            # Tool kullanıldı mı?
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            text_blocks = [b for b in resp.content if hasattr(b, "text")]

            if resp.stop_reason == "end_turn" or not tool_uses:
                # Son yanıt — JSON'u çıkar
                text = " ".join(b.text for b in text_blocks)
                match = re.search(r'\[.*?\]', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except Exception:
                        pass
                return []

            # Tool sonuçlarını conversation'a ekle
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for tu in tool_uses:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": getattr(tu, "output", "") or "",
                })
            messages.append({"role": "user", "content": tool_results})

        return []

    try:
        loop = asyncio.get_running_loop()
        news = await loop.run_in_executor(None, _fetch_news)
        news = news[:4] if news else []

        # Önbelleğe yaz
        try:
            cache_file.write_text(_json.dumps({"news": news, "ts": time.time()}))
        except Exception:
            pass

        return {"status": "ok", "news": news}
    except Exception as e:
        logger.error("Haber çekme hatası: %s", e)
        return {"status": "error", "message": str(e), "news": []}


@app.post("/api/chat")
async def chat_with_director(request: Request):
    """Dashboard direktör chat endpoint'i."""
    try:
        body    = await request.json()
        message = body.get("message", "").strip()
        if not message:
            return {"status": "error", "message": "Mesaj boş"}
        from chat_director import ask_director
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(None, ask_director, message)
        return {"status": "ok", "response": answer}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/crypto")
async def get_crypto_dashboard():
    """
    BTC kripto dashboard metrikleri:
    - Fear & Greed Index
    - BTC Dominansı
    - Funding Rate proxy
    - Open Interest proxy
    - Long/Short oranı
    - On-chain proxies (MVRV, RSI, hacim)
    - Stablecoin dominansı
    """
    def _fetch():
        from crypto_fetcher import (
            fetch_crypto_fear_greed,
            fetch_bitcoin_dominance,
            fetch_long_short_ratio,
            fetch_onchain_proxies,
            fetch_stablecoin_dominance,
        )
        import yfinance as yf

        result = {}

        # Fear & Greed
        try:
            fg = fetch_crypto_fear_greed()
            result["fear_greed"] = fg
        except Exception as e:
            result["fear_greed"] = {"error": str(e)}

        # BTC Dominansı
        try:
            dom = fetch_bitcoin_dominance()
            result["dominance"] = dom
        except Exception as e:
            result["dominance"] = {"error": str(e)}

        # Long/Short oranı (funding rate proxy içerir)
        try:
            ls = fetch_long_short_ratio()
            result["long_short"] = ls
        except Exception as e:
            result["long_short"] = {"error": str(e)}

        # On-chain proxies (MVRV, RSI, hacim trendi)
        try:
            onchain = fetch_onchain_proxies()
            result["onchain"] = onchain
        except Exception as e:
            result["onchain"] = {}

        # Exchange Net Flow / Madenci Baskısı
        try:
            from crypto_fetcher import fetch_exchange_net_flow
            result["exchange_flow"] = fetch_exchange_net_flow()
        except Exception as e:
            result["exchange_flow"] = {"error": str(e)}

        # NVT Signal
        try:
            from crypto_fetcher import fetch_nvt_signal
            result["nvt"] = fetch_nvt_signal()
        except Exception as e:
            result["nvt"] = {"error": str(e)}

        # Active Addresses
        try:
            from crypto_fetcher import fetch_active_addresses_proxy
            result["active_addresses"] = fetch_active_addresses_proxy()
        except Exception as e:
            result["active_addresses"] = {"error": str(e)}

        # SOPR Proxy
        try:
            from crypto_fetcher import fetch_sopr_proxy
            result["sopr"] = fetch_sopr_proxy()
        except Exception as e:
            result["sopr"] = {"error": str(e)}

        # Stablecoin dominansı
        try:
            stable = fetch_stablecoin_dominance()
            result["stablecoin"] = stable
        except Exception as e:
            result["stablecoin"] = {"error": str(e)}

        # Spot vs Futures hacim proxy (BTC-USD spot vs BITO ETF)
        try:
            btc_hist  = yf.Ticker("BTC-USD").history(period="2d")
            bito_hist = yf.Ticker("BITO").history(period="2d")
            if not btc_hist.empty and not bito_hist.empty:
                spot_vol    = float(btc_hist["Volume"].iloc[-1])
                futures_vol = float(bito_hist["Volume"].iloc[-1]) * 10  # normalize
                ratio = spot_vol / (spot_vol + futures_vol) if (spot_vol + futures_vol) > 0 else 0.5
                if ratio > 0.65:
                    sv_signal = "green"
                    sv_note   = f"Spot hacmi baskın (%{ratio*100:.0f}) — gerçek alım satım, spekülatif değil"
                elif ratio < 0.35:
                    sv_signal = "amber"
                    sv_note   = f"Futures hacmi baskın (%{(1-ratio)*100:.0f}) — spekülatif hareket olabilir"
                else:
                    sv_signal = "neutral"
                    sv_note   = f"Spot/Futures dengeli — sağlıklı piyasa yapısı"
                result["spot_vs_futures"] = {
                    "spot_pct": round(ratio * 100, 1),
                    "signal":   sv_signal,
                    "note":     sv_note,
                }
        except Exception:
            pass

        return result

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _fetch)
        return {"status": "ok", "data": data}
    except Exception as e:
        logger.error("Crypto endpoint hatası: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


@app.get("/api/library")
async def get_library():
    """Finansal terimler kütüphanesi."""
    try:
        from knowledge_library import TERMS, CATEGORIES
        return {"status": "ok", "terms": TERMS, "categories": CATEGORIES}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/archive")
async def get_archive():
    """Direktör karar arşivi."""
    try:
        from director_memory import memory
        decisions = memory.get_recent_decisions(n=30)
        return {"status": "ok", "decisions": decisions}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/memory")
async def get_memory():
    """Direktör hafıza durumunu döndürür."""
    try:
        from director_memory import memory
        regime, days = memory.get_current_regime()
        locks = memory.get_active_locks()
        recent = memory.get_recent_decisions(n=5)
        return {
            "status": "ok",
            "current_regime": regime,
            "regime_days": days,
            "active_locks": locks,
            "recent_decisions": recent,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/trigger/{layer}")
async def manual_trigger(layer: int):
    """
    Telegram dışından manuel tetikleme için.
    Örnek: POST /trigger/3 → sabah özetini şimdi gönder.
    """
    if layer not in (1, 2, 3):
        return {"status": "error", "message": "Geçerli katman: 1, 2 veya 3"}
    from trigger_monitor import run as run_trigger
    asyncio.create_task(_run_sync(run_trigger, layer))
    return {"status": "ok", "message": f"Katman {layer} tetiklendi"}
