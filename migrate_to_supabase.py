#!/usr/bin/env python3
# migrate_to_supabase.py — Tek Seferlik Göç Scripti
#
# Bu script mevcut GitHub/JSON tabanlı portföyü okur ve
# Supabase veritabanına taşır.
#
# ÇALIŞTIRMA: python migrate_to_supabase.py
# NOT: Sadece bir kere çalıştır. Tekrar çalıştırırsan duplicate kayıt oluşur.

import os
import sys
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def migrate():
    logger.info("=" * 60)
    logger.info("Supabase Migration Başlıyor...")
    logger.info("=" * 60)

    # ── 1. Eski portföyü GitHub'dan oku ──────────────────────────────
    logger.info("1/3 — GitHub'dan portföy okunuyor...")
    try:
        from portfolio_manager import load_portfolio
        positions = load_portfolio()
        logger.info("  %d pozisyon bulundu.", len(positions))
    except Exception as e:
        logger.error("GitHub portföy okunamadı: %s", e)
        sys.exit(1)

    if not positions:
        logger.warning("Portföy boş, migration tamamlandı (yapılacak bir şey yok).")
        return

    # ── 2. Supabase bağlantısını kontrol et ──────────────────────────
    logger.info("2/3 — Supabase bağlantısı kontrol ediliyor...")
    try:
        from core.database import check_connection, create_tables, SessionLocal
        from core import crud

        if not check_connection():
            logger.error("Supabase bağlantısı başarısız. DATABASE_URL'yi kontrol et.")
            sys.exit(1)

        create_tables()
        logger.info("  Bağlantı ve tablolar hazır.")
    except Exception as e:
        logger.error("Supabase hazırlık hatası: %s", e)
        sys.exit(1)

    # ── 3. Her pozisyonu Supabase'e yaz ──────────────────────────────
    logger.info("3/3 — Pozisyonlar Supabase'e aktarılıyor...")

    success_count = 0
    error_count   = 0

    # USD/TRY kurunu bir kere çek
    usd_try_rate = 44.0
    try:
        from strategy_data import fetch_usd_try_rate
        usd_try_rate = fetch_usd_try_rate()
        logger.info("  USD/TRY kuru: %.2f", usd_try_rate)
    except Exception:
        logger.warning("  USD/TRY alınamadı, varsayılan 44.0 kullanılıyor.")

    with SessionLocal() as db:
        for pos in positions:
            ticker     = pos.get("ticker", "").upper().strip()
            shares     = float(pos.get("shares", 0))
            avg_cost   = float(pos.get("avg_cost", 0))
            currency   = pos.get("currency", "USD")
            asset_class = pos.get("asset_class", "us_equity")

            if not ticker or shares <= 0 or avg_cost <= 0:
                logger.warning("  Atlandı (geçersiz veri): %s", pos)
                continue

            # asset_class normalize et
            if asset_class in ("other", "", None):
                asset_class = "us_equity"

            try:
                # Mevcut portföy verisi "alım" olarak kaydediliyor
                # Not: Migration'da alım tarihi bilinmiyor, şimdi kullanılıyor
                crud.buy_asset(
                    db          = db,
                    symbol      = ticker,
                    quantity    = shares,
                    price       = avg_cost,
                    currency    = currency,
                    usd_try_rate= usd_try_rate if currency == "TRY" else 1.0,
                    commission  = 0.0,
                    asset_class = asset_class,
                    notes       = "Migration: GitHub'dan aktarıldı",
                )
                logger.info(
                    "  ✅ %s: %g adet @ %g %s (%s)",
                    ticker, shares, avg_cost, currency, asset_class,
                )
                success_count += 1

            except Exception as e:
                logger.error("  ❌ %s aktarılamadı: %s", ticker, e)
                error_count += 1

        # Migration log'u kaydet
        crud.log_event(
            db         = db,
            source     = "SYSTEM",
            event_type = "MIGRATION",
            message    = (
                f"GitHub → Supabase migration tamamlandı. "
                f"Başarılı: {success_count}, Hatalı: {error_count}"
            ),
            severity   = "INFO",
        )

    # ── Özet ─────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Migration Tamamlandı!")
    logger.info("  Başarılı: %d pozisyon", success_count)
    if error_count:
        logger.warning("  Hatalı:   %d pozisyon (logları kontrol et)", error_count)
    logger.info("=" * 60)
    logger.info(
        "Sonraki adım: Supabase'de tabloları kontrol et, "
        "ardından bot.py değişikliklerini deploy et."
    )


if __name__ == "__main__":
    migrate()
