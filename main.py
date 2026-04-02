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
        loop = asyncio.get_event_loop()
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
        import anthropic
        import yfinance as yf
        from strategy_data import fetch_usd_try_rate

        # Anlık veriler
        vix = 0.0
        spy_chg = 0.0
        btc = 0.0
        try:
            vix     = float(yf.Ticker("^VIX").fast_info.last_price or 0)
            spy_h   = yf.Ticker("SPY").history(period="5d")
            if len(spy_h) >= 2:
                spy_chg = (float(spy_h["Close"].iloc[-1]) -
                           float(spy_h["Close"].iloc[-5])) / float(spy_h["Close"].iloc[-5]) * 100
            btc     = float(yf.Ticker("BTC-USD").fast_info.last_price or 0)
        except Exception:
            pass
        usd_try = fetch_usd_try_rate()

        # Portföy durumu özeti
        port_resp = await get_portfolio_detail()
        port_summary = ""
        if port_resp.get("status") == "ok":
            pnl_pct = port_resp.get("total_pnl_pct", 0)
            port_summary = f"Portföy toplam K/Z: %{pnl_pct:+.1f}"

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
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
        text = response.content[0].text.strip()
        cache_file.write_text(json.dumps({"text": text, "ts": time.time()}))
        return {"status": "ok", "briefing": text, "cached": False}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/news")
async def get_news():
    """Piyasayı etkileyen önemli haberler — portföy bazlı filtrelenmiş."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content":
                "Bugün global finansal piyasaları etkileyen en önemli 3-4 haberi bul. "
                "Kriter: Fed/merkez bankası kararları, jeopolitik şoklar, "
                "kripto/BTC gelişmeleri, Türkiye/TL haberleri veya büyük şirket haberleri. "
                "Her haber için: başlık (max 10 kelime), tek cümle özet, etki yönü "
                "(pozitif/negatif/nötr) ve etkilenen varlık sınıfı. "
                "JSON formatında döndür: [{title, summary, impact, asset_class}]"
            }],
        )
        import json, re
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text
        # JSON çıkar
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            news = json.loads(match.group())
            return {"status": "ok", "news": news[:4]}
        return {"status": "ok", "news": []}
    except Exception as e:
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
        loop   = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, ask_director, message)
        return {"status": "ok", "response": answer}
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
    """Portföy durumunu döndürür. Reflex dashboard bu endpoint'i okuyacak."""
    try:
        from portfolio_manager import load_portfolio
        portfolio = load_portfolio()
        return {"status": "ok", "positions": portfolio}
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
