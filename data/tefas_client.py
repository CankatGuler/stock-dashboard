# data/tefas_client.py — TEFAS Fon Veri İstemcisi
#
# Türkiye Elektronik Fon Alım Satım Platformu (TEFAS) verilerini çeker.
# Resmi kaynak: tefas.gov.tr
#
# Kullanılan kütüphane: tefas-crawler (pip install tefas-crawler)
# GitHub: https://github.com/burakyilmaz321/tefas-crawler
#
# Veri güncellenme saati: Her iş günü ~18:30'da TEFAS günceller.
# T+1 valör: Bugün verilen emir yarın işleme girer.

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def get_fund_price(fund_code: str) -> Optional[float]:
    """
    TEFAS'tan fon birim fiyatını çek.

    Args:
        fund_code: Fon kodu (örn: IIH, NNF, TI1, MAC)

    Returns:
        Birim fiyat (float, TL cinsinden)
        None — hata veya fon bulunamadı
    """
    try:
        from tefas import Crawler
        crawler = Crawler()

        today     = date.today()
        yesterday = today - timedelta(days=1)

        # Önce bugünü dene, boşsa dünü dene (hafta sonu / tatil)
        for d in [today, yesterday, today - timedelta(days=3)]:
            date_str = d.strftime("%Y-%m-%d")
            try:
                data = crawler.fetch(
                    start=date_str,
                    end=date_str,
                    name=fund_code.upper(),
                    columns=["code", "date", "price"],
                )
                if data is not None and not data.empty:
                    price = float(data["price"].iloc[-1])
                    logger.info("TEFAS %s: %.4f TL (%s)", fund_code, price, date_str)
                    return price
            except Exception:
                continue

        logger.warning("TEFAS: %s için fiyat bulunamadı", fund_code)
        return None

    except ImportError:
        logger.error("tefas-crawler kurulu değil: pip install tefas-crawler")
        return None
    except Exception as e:
        logger.error("TEFAS hatası [%s]: %s", fund_code, e)
        return None


def get_fund_info(fund_code: str, days: int = 5) -> Optional[dict]:
    """
    Fon hakkında detaylı bilgi çek (son N günlük veri).

    Args:
        fund_code: Fon kodu
        days:      Kaç günlük geçmiş veri

    Returns:
        {
            "code": "IIH",
            "price": 14.52,
            "price_1w_ago": 14.10,
            "change_1w_pct": 2.98,
            "date": "2026-04-10",
        }
    """
    try:
        from tefas import Crawler
        crawler = Crawler()

        end_date   = date.today()
        start_date = end_date - timedelta(days=days + 5)  # Hafta sonu payı

        data = crawler.fetch(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            name=fund_code.upper(),
            columns=["code", "date", "price"],
        )

        if data is None or data.empty:
            return None

        data = data.sort_values("date")
        latest = data.iloc[-1]
        price  = float(latest["price"])

        result = {
            "code":  fund_code.upper(),
            "price": price,
            "date":  str(latest["date"])[:10],
            "price_1w_ago":   None,
            "change_1w_pct":  None,
        }

        if len(data) >= 2:
            old_price = float(data.iloc[0]["price"])
            result["price_1w_ago"]  = old_price
            result["change_1w_pct"] = round((price - old_price) / old_price * 100, 2)

        return result

    except ImportError:
        logger.error("tefas-crawler kurulu değil")
        return None
    except Exception as e:
        logger.error("TEFAS detay hatası [%s]: %s", fund_code, e)
        return None


def get_batch_fund_prices(fund_codes: list[str]) -> dict[str, Optional[float]]:
    """
    Birden fazla fon için fiyat çek.
    Portföy değerleme için kullanılır.

    Returns:
        {"IIH": 14.52, "NNF": 8.23, "TI1": None (hata)}
    """
    results = {}
    for code in fund_codes:
        results[code.upper()] = get_fund_price(code)
    return results
