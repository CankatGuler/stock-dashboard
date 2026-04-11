# core/models.py — Veritabanı Tabloları (SQLAlchemy ORM Modelleri)
#
# Bu dosya sistemin tüm veri modellerini tanımlar.
# Her model bir PostgreSQL tablosuna karşılık gelir.
#
# Tablolar:
#   Transaction  — Her alım/satım işleminin kalıcı kaydı (Ledger)
#   Portfolio    — Anlık pozisyon durumu (aggregated)
#   SystemLog    — Alarm ve sistem event logları (Direktör hafızası)

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


# ─── Yardımcı: Zaman damgası ──────────────────────────────────────────────────

def _now_utc() -> datetime:
    """UTC şimdiki zamanı döndürür."""
    return datetime.now(timezone.utc)


# ─── 1. Transaction — İşlem Defteri (Ledger) ──────────────────────────────────

class Transaction(Base):
    """
    Her alım veya satım işleminin kalıcı kaydı.

    Bu tablo hiçbir zaman güncellenmez — her işlem yeni bir satır olarak eklenir.
    Silinen pozisyonların geçmişi burada kalır.

    Realized P&L hesabı bu tablodan yapılır:
      - Bir varlık satıldığında: (satış fiyatı - FIFO maliyet) × adet = realized_pnl

    Örnekler:
      BUY  | AAPL  | 10 adet | $150 | USD
      BUY  | BTC   | 0.5 adet| $65000| USD
      SELL | AAPL  | 5 adet  | $185 | USD  → realized_pnl = (185-150) × 5 = +$175
      BUY  | IIH   | 100 adet| ₺200 | TRY  → usd_try_rate ile USD'ye çevrilir
    """

    __tablename__ = "transactions"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # ── İşlem Bilgileri ───────────────────────────────────────────────────────
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        comment="İşlem tarihi ve saati (UTC)",
    )

    asset_symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Varlık sembolü. Örn: AAPL, BTC, IIH, GLD",
    )

    asset_class: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="us_equity",
        comment="Varlık sınıfı: us_equity | crypto | tefas | commodity | cash",
    )

    transaction_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="İşlem tipi: BUY veya SELL",
    )

    quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Alınan veya satılan miktar (adet)",
    )

    price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Birim fiyat (currency cinsinden)",
    )

    currency: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="USD",
        comment="Para birimi: USD veya TRY",
    )

    usd_try_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        comment="İşlem anındaki USD/TRY kuru. TRY işlemleri için kritik.",
    )

    commission: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Ödenen komisyon (currency cinsinden)",
    )

    # ── Hesaplanan Alanlar ────────────────────────────────────────────────────
    total_cost_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="İşlemin toplam USD maliyeti: (quantity × price + commission) / usd_try_rate",
    )

    realized_pnl_usd: Mapped[float] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="Sadece SELL işlemlerinde: Bu satıştan elde edilen USD kar/zarar",
    )

    # ── Notlar ────────────────────────────────────────────────────────────────
    notes: Mapped[str] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Opsiyonel not. Örn: 'Tarifelere karşı hedge', 'Stop-loss tetiklendi'",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="Kayıt oluşturulma zamanı",
    )

    # ── Index'ler (sorgu hızı için) ───────────────────────────────────────────
    __table_args__ = (
        Index("ix_transactions_asset_symbol", "asset_symbol"),
        Index("ix_transactions_date", "date"),
        Index("ix_transactions_type", "transaction_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction {self.transaction_type} {self.quantity}x"
            f"{self.asset_symbol} @ {self.price} {self.currency}>"
        )


# ─── 2. Portfolio — Anlık Pozisyon Durumu ─────────────────────────────────────

class Portfolio(Base):
    """
    Her varlık için anlık pozisyon durumu.

    Bu tablo her alım/satım işleminden sonra güncellenir.
    Kural: Her asset_symbol için yalnızca 1 satır bulunur (UNIQUE).

    Unrealized P&L burada tutulmaz — her sorgu anında anlık fiyat ile hesaplanır.
    Realized P&L ise Transaction tablosundan aggregated olarak gelir.

    NOT: realized_pnl alanı o varlıktan yapılan tüm satışların toplamıdır.
    """

    __tablename__ = "portfolio"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # ── Pozisyon Bilgileri ────────────────────────────────────────────────────
    asset_symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        comment="Varlık sembolü. Unique — her varlık için tek satır.",
    )

    asset_class: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="us_equity",
        comment="Varlık sınıfı: us_equity | crypto | tefas | commodity | cash",
    )

    total_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Mevcut toplam adet. Sıfıra düşünce pozisyon kapalı sayılır.",
    )

    average_cost: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Ortalama maliyet (currency cinsinden). FIFO veya weighted average.",
    )

    average_cost_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Ortalama maliyet USD cinsinden. TRY varlıklar için kur normalize edilir.",
    )

    currency: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        default="USD",
        comment="Ana işlem para birimi: USD veya TRY",
    )

    # ── Kar/Zarar ─────────────────────────────────────────────────────────────
    realized_pnl_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        comment="Bu varlıktan yapılan tüm satışlardan gerçekleşen toplam USD kar/zarar",
    )

    # ── Zaman Damgaları ───────────────────────────────────────────────────────
    first_buy_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="İlk alım tarihi",
    )

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        onupdate=_now_utc,
        comment="Son güncelleme zamanı",
    )

    # ── Kısıtlar ve Index'ler ──────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint("asset_symbol", name="uq_portfolio_asset_symbol"),
        Index("ix_portfolio_asset_class", "asset_class"),
    )

    def __repr__(self) -> str:
        return (
            f"<Portfolio {self.asset_symbol} qty={self.total_quantity}"
            f" avg_cost={self.average_cost} {self.currency}>"
        )


# ─── 3. SystemLog — Sistem ve Uyarı Hafızası ──────────────────────────────────

class SystemLog(Base):
    """
    Tüm sistem eventlerinin kalıcı kaydı.

    Direktör bu tabloyu okuyarak geçmiş alarmları ve sistem durumunu anlayabilir.
    "Bugün sabah VIX alarmı vermiştim, o yüzden yeni pozisyon açma" gibi.

    Kaynaklar (source):
      - ALARM_ENGINE   → Katman 1/2/3 tetikleyicileri
      - DIRECTOR       → Direktör sohbet özetleri
      - TELEGRAM_BOT   → Kullanıcı komutları (ekle, sat vs.)
      - PORTFOLIO      → Portföy güncellemeleri
      - SYSTEM         → Uygulama başlangıç/kapanış, hata logları

    Event tipleri örnekleri:
      - VIX_ALERT, BTC_CRASH, USDTRY_SPIKE   → Alarm eventleri
      - PORTFOLIO_BUY, PORTFOLIO_SELL         → İşlem eventleri
      - CHAT_SUMMARY                          → Sohbet özeti
      - STARTUP, SHUTDOWN, ERROR              → Sistem eventleri
    """

    __tablename__ = "system_logs"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # ── Event Bilgileri ───────────────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now_utc,
        comment="Event zamanı (UTC)",
    )

    source: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Kaynağı: ALARM_ENGINE | DIRECTOR | TELEGRAM_BOT | PORTFOLIO | SYSTEM",
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Event tipi. Örn: VIX_ALERT, PORTFOLIO_BUY, CHAT_SUMMARY",
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Event mesajı veya özeti. Direktör bu metni okuyacak.",
    )

    # ── Ek Metadata ───────────────────────────────────────────────────────────
    severity: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="INFO",
        comment="Önem seviyesi: INFO | WARNING | CRITICAL",
    )

    asset_symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="İlgili varlık sembolü (varsa). Örn: BTC, AAPL",
    )

    metric_value: Mapped[float] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="İlgili metrik değeri (varsa). Örn: VIX=32.5, BTC_CHANGE=-7.2",
    )

    # ── Index'ler ─────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_system_logs_timestamp", "timestamp"),
        Index("ix_system_logs_source", "source"),
        Index("ix_system_logs_event_type", "event_type"),
        Index("ix_system_logs_severity", "severity"),
    )

    def __repr__(self) -> str:
        return (
            f"<SystemLog [{self.severity}] {self.source}:{self.event_type}"
            f" @ {self.timestamp}>"
        )
