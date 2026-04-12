# data/fmp_client.py — Financial Modeling Prep API İstemcisi
#
# FMP, yfinance'in sağlayamadığı derinlikte temel analiz verisi sunar:
# F/K oranı, piyasa değeri, sektör, şirket profili, gelir tablosu vb.
#
# API Key: .env dosyasında FMP_API_KEY olarak tanımlanmalı.
# Ücretsiz plan: 250 istek/gün (temel veriler için yeterli)
# Site: https://financialmodelingprep.com

import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"
_TIMEOUT = 10


def _get_api_key() -> str:
    key = os.getenv("FMP_API_KEY", "")
    if not key:
        raise ValueError(
            "FMP_API_KEY tanımlı değil. "
            ".env dosyasına veya Railway Variables'a ekleyin."
        )
    return key


def _get(endpoint: str, params: dict = None) -> Optional[dict | list]:
    """FMP API'ye GET isteği gönder."""
    try:
        api_key = _get_api_key()
        p = {"apikey": api_key}
        if params:
            p.update(params)
        resp = requests.get(
            f"{FMP_BASE}/{endpoint}",
            params=p,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 401:
            logger.error("FMP API: Geçersiz API key")
            return None
        if resp.status_code == 429:
            logger.warning("FMP API: Rate limit aşıldı (250 istek/gün)")
            return None
        resp.raise_for_status()
        data = resp.json()
        # FMP hata mesajı döndürebilir
        if isinstance(data, dict) and data.get("Error Message"):
            logger.warning("FMP hata: %s", data["Error Message"])
            return None
        return data
    except ValueError as e:
        logger.error("FMP config hatası: %s", e)
        return None
    except requests.Timeout:
        logger.warning("FMP API zaman aşımı: %s", endpoint)
        return None
    except Exception as e:
        logger.warning("FMP API hatası [%s]: %s", endpoint, e)
        return None


# ─── 1. Anlık Hisse Fiyatı ────────────────────────────────────────────────────

def get_stock_quote(symbol: str) -> Optional[dict]:
    """
    Anlık hisse fiyatı ve değişim bilgisi.

    Returns:
        {
            "symbol": "AAPL",
            "price": 185.50,
            "change": 2.30,
            "change_pct": 1.25,
            "volume": 52_000_000,
            "market_cap": 2_850_000_000_000,
            "pe_ratio": 28.5,
            "52w_high": 199.62,
            "52w_low": 124.17,
            "avg_volume": 58_000_000,
            "eps": 6.43,
        }
        None — hata durumunda
    """
    data = _get(f"quote/{symbol.upper()}")
    if not data or not isinstance(data, list) or len(data) == 0:
        logger.warning("FMP: %s için fiyat verisi bulunamadı", symbol)
        return None

    q = data[0]
    return {
        "symbol":     q.get("symbol", symbol),
        "price":      q.get("price", 0.0),
        "change":     q.get("change", 0.0),
        "change_pct": q.get("changesPercentage", 0.0),
        "volume":     q.get("volume", 0),
        "market_cap": q.get("marketCap", 0),
        "pe_ratio":   q.get("pe", None),
        "52w_high":   q.get("yearHigh", None),
        "52w_low":    q.get("yearLow", None),
        "avg_volume": q.get("avgVolume", None),
        "eps":        q.get("eps", None),
        "name":       q.get("name", ""),
    }


# ─── 2. Şirket Profili ────────────────────────────────────────────────────────

def get_company_profile(symbol: str) -> Optional[dict]:
    """
    Şirket temel bilgileri ve değerleme metrikleri.

    Returns:
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "description": "Apple Inc. designs...",
            "pe_ratio": 28.5,
            "market_cap": 2_850_000_000_000,
            "beta": 1.23,
            "dividend_yield": 0.52,
            "price_to_book": 45.2,
            "price_to_sales": 7.8,
            "roe": 1.73,
            "debt_to_equity": 1.76,
            "revenue_growth": 0.085,
            "employees": 164_000,
            "ceo": "Tim Cook",
            "website": "https://www.apple.com",
            "exchange": "NASDAQ",
            "currency": "USD",
        }
    """
    data = _get(f"profile/{symbol.upper()}")
    if not data or not isinstance(data, list) or len(data) == 0:
        logger.warning("FMP: %s için şirket profili bulunamadı", symbol)
        return None

    p = data[0]
    return {
        "symbol":         p.get("symbol", symbol),
        "name":           p.get("companyName", ""),
        "sector":         p.get("sector", ""),
        "industry":       p.get("industry", ""),
        "description":    p.get("description", "")[:500],  # İlk 500 karakter
        "pe_ratio":       p.get("pe", None),
        "market_cap":     p.get("mktCap", 0),
        "beta":           p.get("beta", None),
        "dividend_yield": p.get("lastDiv", None),
        "price_to_book":  p.get("priceToBookRatio", None),
        "price_to_sales": p.get("priceToSalesRatio", None),
        "roe":            p.get("roe", None),
        "debt_to_equity": p.get("debtToEquity", None),
        "revenue_growth": p.get("revenueGrowth", None),
        "employees":      p.get("fullTimeEmployees", None),
        "ceo":            p.get("ceo", ""),
        "website":        p.get("website", ""),
        "exchange":       p.get("exchangeShortName", ""),
        "currency":       p.get("currency", "USD"),
        "country":        p.get("country", ""),
    }


# ─── 3. Birleşik Analiz (quote + profile) ────────────────────────────────────

def get_full_analysis(symbol: str) -> Optional[dict]:
    """
    Fiyat ve şirket profilini tek seferde birleştir.
    /hisse komutu için kullanılır.
    """
    quote   = get_stock_quote(symbol)
    profile = get_company_profile(symbol)

    if not quote and not profile:
        return None

    result = {}
    if quote:
        result.update(quote)
    if profile:
        # Profil verisini ekle (fiyat verisinin üzerine yazmadan)
        for k, v in profile.items():
            if k not in result or result[k] is None:
                result[k] = v

    return result


# ─── 4. Toplu Hisse Fiyatları ─────────────────────────────────────────────────

def get_batch_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Birden fazla hisse için tek istekte fiyat çek.
    Portföy endpoint'i için kullanılır.

    Returns:
        {"AAPL": {...}, "NVDA": {...}, ...}
    """
    if not symbols:
        return {}

    symbols_str = ",".join(s.upper() for s in symbols)
    data = _get(f"quote/{symbols_str}")
    if not data or not isinstance(data, list):
        return {}

    result = {}
    for q in data:
        sym = q.get("symbol", "")
        if sym:
            result[sym] = {
                "price":      q.get("price", 0.0),
                "change_pct": q.get("changesPercentage", 0.0),
                "pe_ratio":   q.get("pe", None),
                "market_cap": q.get("marketCap", 0),
                "name":       q.get("name", ""),
            }
    return result
