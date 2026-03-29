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


# ─── Arka Plan Görev Zamanlaması ──────────────────────────────────────────────

def _schedule_jobs():
    """
    Tüm otomatik görevleri zamanlayıcıya kaydet.
    GitHub Actions cron'larının yerini alıyor — artık her şey tek serviste.
    """
    from trigger_monitor import run as run_trigger

    # Katman 1: Her 15 dakikada VIX, BTC, USD/TRY, stablecoin kontrolü
    scheduler.add_job(
        lambda: asyncio.create_task(_run_sync(run_trigger, 1)),
        trigger="interval",
        minutes=15,
        id="layer1",
        name="Katman 1 — Acil Alarmlar",
        misfire_grace_time=120,  # 2 dakika gecikmeye tolerans
    )

    # Katman 2: Her saat başı yield curve, funding rate vs.
    scheduler.add_job(
        lambda: asyncio.create_task(_run_sync(run_trigger, 2)),
        trigger="interval",
        hours=1,
        id="layer2",
        name="Katman 2 — Önemli Sinyaller",
        misfire_grace_time=300,
    )

    # Katman 3: Her sabah 07:30 TR saatiyle sabah özeti
    scheduler.add_job(
        lambda: asyncio.create_task(_run_sync(run_trigger, 3)),
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


async def _run_sync(fn, *args):
    """
    Senkron bir fonksiyonu async event loop'u bloke etmeden çalıştırır.
    trigger_monitor.run() gibi eski senkron fonksiyonlarla uyumluluk için.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, fn, *args)


async def _run_performance_tracker():
    from performance_tracker import run as run_perf
    await _run_sync(run_perf)


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


@app.get("/portfolio")
async def get_portfolio():
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
