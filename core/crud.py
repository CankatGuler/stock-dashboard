# core/crud.py — Finansal İş Mantığı (Business Logic)
#
# Bu modül veritabanı tablolarıyla etkileşimi yönetir.
# Tüm finansal hesaplamalar (ortalama maliyet, realized P&L) burada yapılır.
#
# Kullanım:
#   from core.database import SessionLocal
#   from core import crud
#
#   with SessionLocal() as db:
#       crud.buy_asset(db, symbol="AAPL", quantity=10, price=150.0, currency="USD")

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from core.models import Portfolio, SystemLog, Transaction

logger = logging.getLogger(__name__)


# ─── Yardımcı ─────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_usd(amount: float, currency: str, usd_try_rate: float) -> float:
    """Tutarı USD'ye normalize et."""
    if currency == "TRY" and usd_try_rate > 0:
        return amount / usd_try_rate
    return amount


# ─── 1. ALIM — buy_asset ──────────────────────────────────────────────────────

def buy_asset(
    db: Session,
    symbol: str,
    quantity: float,
    price: float,
    currency: str = "USD",
    usd_try_rate: float = 1.0,
    commission: float = 0.0,
    asset_class: str = "us_equity",
    notes: Optional[str] = None,
) -> Transaction:
    """
    Varlık alımını kaydet ve portföyü güncelle.

    İşlem adımları:
    1. Transaction tablosuna BUY kaydı ekle
    2. Portfolio tablosunda varlık varsa ortalama maliyeti güncelle
       Formül: (eski_miktar * eski_maliyet + yeni_miktar * yeni_fiyat) / toplam_miktar
    3. Portfolio tablosunda varlık yoksa yeni kayıt oluştur
    4. Commit et

    Args:
        db:            SQLAlchemy Session
        symbol:        Varlık sembolü (AAPL, BTC, IIH)
        quantity:      Alınan adet
        price:         Birim fiyat (currency cinsinden)
        currency:      USD veya TRY
        usd_try_rate:  İşlem anındaki USD/TRY kuru
        commission:    Ödenen komisyon (currency cinsinden)
        asset_class:   us_equity | crypto | tefas | commodity | cash
        notes:         Opsiyonel not

    Returns:
        Oluşturulan Transaction nesnesi
    """
    try:
        # ── Toplam maliyet hesapla ─────────────────────────────────────────
        gross_cost    = quantity * price
        total_cost    = gross_cost + commission           # currency cinsinden
        total_cost_usd = _to_usd(total_cost, currency, usd_try_rate)
        price_usd      = _to_usd(price, currency, usd_try_rate)

        # ── 1. Transaction kaydı ──────────────────────────────────────────
        txn = Transaction(
            date             = _now_utc(),
            asset_symbol     = symbol.upper(),
            asset_class      = asset_class,
            transaction_type = "BUY",
            quantity         = quantity,
            price            = price,
            currency         = currency,
            usd_try_rate     = usd_try_rate,
            commission       = commission,
            total_cost_usd   = total_cost_usd,
            realized_pnl_usd = None,   # Alımda P&L yok
            notes            = notes,
        )
        db.add(txn)

        # ── 2. Portfolio güncelle veya oluştur ────────────────────────────
        position = (
            db.query(Portfolio)
            .filter(Portfolio.asset_symbol == symbol.upper())
            .first()
        )

        if position is None:
            # Yeni pozisyon
            position = Portfolio(
                asset_symbol     = symbol.upper(),
                asset_class      = asset_class,
                total_quantity   = quantity,
                average_cost     = price,
                average_cost_usd = price_usd,
                currency         = currency,
                realized_pnl_usd = 0.0,
                first_buy_date   = _now_utc(),
                last_updated     = _now_utc(),
            )
            db.add(position)
            logger.info("Yeni pozisyon açıldı: %s x%g @ %g %s", symbol, quantity, price, currency)

        else:
            # Mevcut pozisyon — ortalama maliyet güncelle (Weighted Average)
            old_qty      = position.total_quantity
            old_cost     = position.average_cost
            old_cost_usd = position.average_cost_usd

            new_qty      = old_qty + quantity
            # Ortalama maliyet formülü
            new_avg_cost     = (old_qty * old_cost     + quantity * price    ) / new_qty
            new_avg_cost_usd = (old_qty * old_cost_usd + quantity * price_usd) / new_qty

            position.total_quantity   = new_qty
            position.average_cost     = new_avg_cost
            position.average_cost_usd = new_avg_cost_usd
            position.last_updated     = _now_utc()

            logger.info(
                "Pozisyon güncellendi: %s | Yeni miktar: %g | Yeni ort. maliyet: %g %s",
                symbol, new_qty, new_avg_cost, currency,
            )

        db.commit()
        db.refresh(txn)
        return txn

    except Exception as e:
        db.rollback()
        logger.error("buy_asset hatası [%s]: %s", symbol, e)
        raise


# ─── 2. SATIM — sell_asset ────────────────────────────────────────────────────

def sell_asset(
    db: Session,
    symbol: str,
    quantity: float,
    price: float,
    currency: str = "USD",
    usd_try_rate: float = 1.0,
    commission: float = 0.0,
    notes: Optional[str] = None,
) -> tuple[Transaction, float]:
    """
    Varlık satışını kaydet, realized P&L hesapla ve portföyü güncelle.

    P&L Formülü (USD normalize):
      realized_pnl = (satış_fiyatı_usd - ortalama_maliyet_usd) × miktar - komisyon_usd

    Miktar sıfıra düşse bile Portfolio kaydını SİLME.
    realized_pnl geçmişi ve average_cost bilgisi korunur.

    Args:
        db:            SQLAlchemy Session
        symbol:        Varlık sembolü
        quantity:      Satılan adet
        price:         Satış birim fiyatı (currency cinsinden)
        currency:      USD veya TRY
        usd_try_rate:  İşlem anındaki USD/TRY kuru
        commission:    Ödenen komisyon (currency cinsinden)
        notes:         Opsiyonel not

    Returns:
        (Transaction, realized_pnl_usd) tuple'ı

    Raises:
        ValueError: Portföyde yeterli miktar yoksa
    """
    try:
        # ── Pozisyonu kontrol et ──────────────────────────────────────────
        position = (
            db.query(Portfolio)
            .filter(Portfolio.asset_symbol == symbol.upper())
            .first()
        )

        if position is None:
            raise ValueError(f"{symbol} portföyde bulunamadı.")

        if position.total_quantity < quantity:
            raise ValueError(
                f"Yetersiz bakiye: {symbol} için {position.total_quantity:g} adet var, "
                f"{quantity:g} adet satılmak isteniyor."
            )

        # ── Realized P&L hesapla ──────────────────────────────────────────
        price_usd       = _to_usd(price, currency, usd_try_rate)
        commission_usd  = _to_usd(commission, currency, usd_try_rate)

        # (Satış fiyatı - Ortalama maliyet) × Miktar - Komisyon
        pnl_per_unit    = price_usd - position.average_cost_usd
        realized_pnl    = (pnl_per_unit * quantity) - commission_usd

        total_sale_usd  = price_usd * quantity - commission_usd

        logger.info(
            "Satış: %s x%g @ %g %s | P&L: %+.2f USD",
            symbol, quantity, price, currency, realized_pnl,
        )

        # ── Transaction kaydı ─────────────────────────────────────────────
        txn = Transaction(
            date             = _now_utc(),
            asset_symbol     = symbol.upper(),
            asset_class      = position.asset_class,
            transaction_type = "SELL",
            quantity         = quantity,
            price            = price,
            currency         = currency,
            usd_try_rate     = usd_try_rate,
            commission       = commission,
            total_cost_usd   = total_sale_usd,
            realized_pnl_usd = realized_pnl,
            notes            = notes,
        )
        db.add(txn)

        # ── Portfolio güncelle ────────────────────────────────────────────
        position.total_quantity   -= quantity
        position.realized_pnl_usd += realized_pnl
        position.last_updated      = _now_utc()

        # Miktar sıfıra düştüyse kayıt kalır (geçmiş korunur), sadece log at
        if position.total_quantity <= 0:
            position.total_quantity = 0.0
            logger.info("%s pozisyonu kapatıldı (miktar=0). P&L geçmişi korunuyor.", symbol)

        db.commit()
        db.refresh(txn)
        return txn, realized_pnl

    except ValueError:
        raise
    except Exception as e:
        db.rollback()
        logger.error("sell_asset hatası [%s]: %s", symbol, e)
        raise


# ─── 3. PORTFÖY ÖZETI — get_portfolio_summary ─────────────────────────────────

def get_portfolio_summary(db: Session) -> dict:
    """
    Tüm portföyü listele ve özet istatistikleri hesapla.

    Returns:
        {
            "positions": [...],     # Her pozisyonun detayı
            "total_cost_usd": ...,  # Toplam yatırım (USD)
            "total_realized_pnl_usd": ...,  # Toplam gerçekleşen P&L
            "open_positions": ...,  # Açık pozisyon sayısı
        }
    """
    try:
        positions = db.query(Portfolio).all()

        result_positions = []
        total_cost_usd        = 0.0
        total_realized_pnl    = 0.0
        open_count            = 0

        for pos in positions:
            cost_usd = pos.total_quantity * pos.average_cost_usd
            total_cost_usd     += cost_usd
            total_realized_pnl += pos.realized_pnl_usd

            if pos.total_quantity > 0:
                open_count += 1

            result_positions.append({
                "symbol":           pos.asset_symbol,
                "asset_class":      pos.asset_class,
                "quantity":         pos.total_quantity,
                "average_cost":     pos.average_cost,
                "average_cost_usd": pos.average_cost_usd,
                "currency":         pos.currency,
                "cost_usd":         round(cost_usd, 2),
                "realized_pnl_usd": round(pos.realized_pnl_usd, 2),
                "first_buy_date":   pos.first_buy_date.isoformat() if pos.first_buy_date else None,
                "last_updated":     pos.last_updated.isoformat() if pos.last_updated else None,
                "is_open":          pos.total_quantity > 0,
            })

        return {
            "positions":              result_positions,
            "total_cost_usd":         round(total_cost_usd, 2),
            "total_realized_pnl_usd": round(total_realized_pnl, 2),
            "open_positions":         open_count,
            "total_positions":        len(positions),
        }

    except Exception as e:
        logger.error("get_portfolio_summary hatası: %s", e)
        raise


# ─── 4. LOG KAYDI — log_event ─────────────────────────────────────────────────

def log_event(
    db: Session,
    source: str,
    event_type: str,
    message: str,
    severity: str = "INFO",
    asset_symbol: Optional[str] = None,
    metric_value: Optional[float] = None,
) -> SystemLog:
    """
    Sistem olayını veritabanına kaydet.

    JSON tabanlı chat_history ve trigger log'larının yerine geçer.
    Direktör bu tabloyu okuyarak geçmiş alarmları ve olayları hatırlar.

    Args:
        db:           SQLAlchemy Session
        source:       ALARM_ENGINE | DIRECTOR | TELEGRAM_BOT | PORTFOLIO | SYSTEM
        event_type:   VIX_ALERT | PORTFOLIO_BUY | CHAT_SUMMARY | vb.
        message:      Olay açıklaması (Direktör bu metni okuyacak)
        severity:     INFO | WARNING | CRITICAL
        asset_symbol: İlgili varlık (varsa)
        metric_value: İlgili sayısal değer (VIX=32.5 gibi)

    Returns:
        Oluşturulan SystemLog nesnesi
    """
    try:
        log = SystemLog(
            timestamp    = _now_utc(),
            source       = source.upper(),
            event_type   = event_type.upper(),
            message      = message,
            severity     = severity.upper(),
            asset_symbol = asset_symbol.upper() if asset_symbol else None,
            metric_value = metric_value,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    except Exception as e:
        db.rollback()
        logger.error("log_event hatası: %s", e)
        raise


# ─── 5. SON LOGLAR — get_recent_logs ──────────────────────────────────────────

def get_recent_logs(
    db: Session,
    limit: int = 10,
    source: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
) -> list[dict]:
    """
    Son N sistem olayını getir.

    Direktör bu fonksiyonu çağırarak:
    - "Bugün hangi alarmlar geldi?"
    - "Son portföy değişiklikleri ne?"
    - "VIX son ne zaman alarm verdi?"
    sorularını yanıtlayabilir.

    Args:
        db:         SQLAlchemy Session
        limit:      Kaç kayıt dönsün (default: 10)
        source:     Filtreleme — sadece bu kaynaktan (opsiyonel)
        severity:   Filtreleme — sadece bu önem seviyesi (opsiyonel)
        event_type: Filtreleme — sadece bu olay tipi (opsiyonel)

    Returns:
        Log kayıtlarının dict listesi (en yeniden eskiye)
    """
    try:
        query = db.query(SystemLog)

        if source:
            query = query.filter(SystemLog.source == source.upper())
        if severity:
            query = query.filter(SystemLog.severity == severity.upper())
        if event_type:
            query = query.filter(SystemLog.event_type == event_type.upper())

        logs = (
            query
            .order_by(SystemLog.timestamp.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id":           log.id,
                "timestamp":    log.timestamp.isoformat(),
                "source":       log.source,
                "event_type":   log.event_type,
                "severity":     log.severity,
                "message":      log.message,
                "asset_symbol": log.asset_symbol,
                "metric_value": log.metric_value,
            }
            for log in logs
        ]

    except Exception as e:
        logger.error("get_recent_logs hatası: %s", e)
        raise


# ─── 6. İŞLEM GEÇMİŞİ — get_transaction_history ─────────────────────────────

def get_transaction_history(
    db: Session,
    symbol: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    İşlem geçmişini getir.

    Args:
        db:     SQLAlchemy Session
        symbol: Sadece bu varlığın işlemleri (None ise tümü)
        limit:  Kaç kayıt dönsün

    Returns:
        Transaction kayıtlarının dict listesi (en yeniden eskiye)
    """
    try:
        query = db.query(Transaction)

        if symbol:
            query = query.filter(Transaction.asset_symbol == symbol.upper())

        transactions = (
            query
            .order_by(Transaction.date.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id":               txn.id,
                "date":             txn.date.isoformat(),
                "symbol":           txn.asset_symbol,
                "asset_class":      txn.asset_class,
                "type":             txn.transaction_type,
                "quantity":         txn.quantity,
                "price":            txn.price,
                "currency":         txn.currency,
                "usd_try_rate":     txn.usd_try_rate,
                "commission":       txn.commission,
                "total_cost_usd":   txn.total_cost_usd,
                "realized_pnl_usd": txn.realized_pnl_usd,
                "notes":            txn.notes,
            }
            for txn in transactions
        ]

    except Exception as e:
        logger.error("get_transaction_history hatası: %s", e)
        raise
