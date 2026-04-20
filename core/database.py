# core/database.py — Veritabanı Bağlantı Altyapısı
#
# Bu modül SQLAlchemy kullanarak PostgreSQL (Supabase) bağlantısını kurar.
# Tüm modeller ve CRUD operasyonları bu modülü import eder.
#
# Kullanım:
#   from core.database import get_db, engine
#   from core.models import Base
#
# .env dosyasında şu değişken tanımlı olmalı:
#   DATABASE_URL=postgresql://user:password@host:port/dbname

import logging
import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

# ─── Bağlantı URL'si ──────────────────────────────────────────────────────────

def _get_database_url() -> str:
    """
    DATABASE_URL'yi environment'tan oku.
    Supabase bağlantı string formatı:
      postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres
    """
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError(
            "DATABASE_URL environment variable tanımlı değil. "
            ".env dosyasına veya Railway Variables'a ekleyin."
        )

    # SQLAlchemy, 'postgres://' prefix'ini kabul etmiyor — 'postgresql://' olmalı.
    # Supabase bazı durumlarda eski prefix döndürebilir.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    return url


# ─── Engine ───────────────────────────────────────────────────────────────────

def _create_engine():
    """
    SQLAlchemy engine oluştur.
    - pool_pre_ping: Her bağlantıdan önce canlılık kontrolü yapar,
      kopuk bağlantıları otomatik yeniler (Railway restart'larına karşı kritik).
    - pool_size / max_overflow: Supabase Free Tier için konservatif ayarlar.
    """
    url = _get_database_url()

    engine = create_engine(
        url,
        pool_pre_ping=True,       # Bağlantı kopukluğunu otomatik yakala
        pool_size=5,              # Eş zamanlı bağlantı havuzu
        max_overflow=10,          # Havuz dolunca en fazla +10 geçici bağlantı
        pool_recycle=1800,        # 30 dakikada bir bağlantıyı yenile
        echo=False,               # SQL sorgularını loglamak için True yapılabilir
    )

    logger.info("PostgreSQL engine oluşturuldu: %s", url.split("@")[-1])
    return engine


engine = _create_engine()

# ─── Session Factory ──────────────────────────────────────────────────────────

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,   # Manuel commit zorunlu — veri tutarlılığı için
    autoflush=False,    # Sorgular arası otomatik flush kapalı
    expire_on_commit=False,  # Commit sonrası objeye erişim için
)

# ─── Declarative Base ─────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """
    Tüm SQLAlchemy modelleri bu class'tan türeyecek.
    core/models.py bu Base'i import eder.
    """
    pass


# ─── Dependency: FastAPI ve senkron kullanım için session yönetimi ────────────

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI endpoint'lerinde dependency injection için kullanılır.

    Kullanım (FastAPI):
        @app.get("/ornek")
        def ornek(db: Session = Depends(get_db)):
            ...

    Senkron kullanım için `with_db()` fonksiyonunu tercih edin.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def with_db(func):
    """
    Decorator: Senkron fonksiyonlara otomatik DB session ekler.

    Kullanım:
        @with_db
        def portfoy_guncelle(db: Session, ticker: str):
            ...
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with SessionLocal() as db:
            return func(db, *args, **kwargs)

    return wrapper


# ─── Tablo Oluşturma ──────────────────────────────────────────────────────────

def create_tables() -> None:
    """
    Tüm tabloları veritabanında oluştur (yoksa).
    main.py lifespan başlangıcında çağrılır.
    """
    from core.models import Base as ModelBase  # noqa: F401

    try:
        ModelBase.metadata.create_all(bind=engine)
        logger.info("✅ Veritabanı tabloları hazır.")
    except Exception as e:
        logger.error("❌ Tablo oluşturma hatası: %s", e)
        raise

    # director_decisions tablosunu raw SQL ile oluştur
    # (SQLAlchemy ORM dışında, migration gerektirmeden)
    try:
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS director_decisions (
                    id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
                    created_at            TIMESTAMPTZ DEFAULT NOW(),
                    asset_symbol          TEXT NOT NULL,
                    asset_class           TEXT,
                    trigger_type          TEXT,
                    question_summary      TEXT,
                    recommendation        TEXT,
                    confidence            TEXT,
                    reasoning_summary     TEXT,
                    price_at_decision     FLOAT,
                    portfolio_weight_pct  FLOAT,
                    vix_at_decision       FLOAT,
                    evaluation_date       DATE,
                    price_at_evaluation   FLOAT,
                    actual_return_pct     FLOAT,
                    outcome               TEXT,
                    postmortem_note       TEXT,
                    is_evaluated          BOOLEAN DEFAULT FALSE
                );
            """))
            db.commit()
        logger.info("✅ director_decisions tablosu hazır.")
    except Exception as e:
        logger.warning("director_decisions tablo oluşturma: %s", e)


def check_connection() -> bool:
    """
    Veritabanı bağlantısını test et.
    main.py startup'ta çağrılabilir.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Supabase bağlantısı başarılı.")
        return True
    except Exception as e:
        logger.error("❌ Supabase bağlantı hatası: %s", e)
        return False
