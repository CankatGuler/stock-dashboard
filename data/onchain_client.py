# data/onchain_client.py — Kripto On-Chain Veri İstemcisi (Alphractal API)
#
# Alphractal API endpoint'leri:
#   Base URL : https://api.alphractal.com
#   Auth     : X-Api-Key header
#   Format   : GET /{asset}/{kategori}/{metrik}?startDate=...
#   Response : [{time, değer}, ...] — en son eleman alınır
#
# Desteklenen metrikler:
#   Market   : Mvrv_zscore, CapMVRVCur, Nupl, NVTAdj90
#   Lifespan : Lth_mvrv, Sth_sopr, Lth_sopr, Sopr
#   Derivatives: Long_short_ratio, Funding_Rate, Open_Interest
#   Exchange : Netflow (BTC giriş/çıkış)
#   Addresses: AdrActCnt (aktif adres sayısı)

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

ALPHRACTAL_BASE = "https://api.alphractal.com"
_TIMEOUT        = 12


# ─── Temel API İstemcisi ──────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.getenv("ALPHRACTAL_API_KEY", "")
    if not key:
        raise ValueError("ALPHRACTAL_API_KEY eksik — .env veya Railway Variables'a ekleyin")
    return key


def _alphractal_fetch(path: str, asset: str = "btc", days: int = 5) -> list:
    """
    Alphractal API'den ham veri çek.
    İki format desteklenir:
      1. /{asset}/market/Mvrv_zscore  (path tabanlı)
      2. /api/GetMvrvZscore           (query param tabanlı)
    """
    try:
        api_key = _get_api_key()
        start   = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        url  = f"{ALPHRACTAL_BASE}{path.replace('{asset}', asset.lower())}"
        resp = requests.get(
            url,
            headers={"X-Api-Key": api_key},
            params={"startDate": start, "asset": asset.lower()},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                logger.info("Alphractal OK: %s → %d kayıt", path, len(data))
                return data
            logger.warning("Alphractal boş veri: %s", path)
            return []
        logger.warning("Alphractal HTTP %s: %s | %s", resp.status_code, path, resp.text[:150])
        return []
    except ValueError as e:
        logger.error("Alphractal config: %s", e)
        return []
    except requests.Timeout:
        logger.warning("Alphractal timeout: %s", path)
        return []
    except Exception as e:
        logger.warning("Alphractal hata [%s]: %s", path, e)
        return []


def _alphractal_api(endpoint: str, asset: str = "btc", days: int = 5) -> list:
    """
    /api/GetXxx formatındaki endpoint'leri çek.
    Bu format bazı planlarda daha geniş erişim sağlıyor.
    """
    try:
        api_key = _get_api_key()
        start   = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        url  = f"{ALPHRACTAL_BASE}/api/{endpoint}"
        resp = requests.get(
            url,
            headers={"X-Api-Key": api_key},
            params={"startDate": start, "asset": asset.lower()},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                logger.info("Alphractal /api OK: %s → %d kayıt", endpoint, len(data))
                return data
            return []
        logger.warning("Alphractal /api HTTP %s: %s", resp.status_code, endpoint)
        return []
    except Exception as e:
        logger.warning("Alphractal /api hata [%s]: %s", endpoint, e)
        return []


def _latest(path: str, field: str, asset: str = "btc",
            api_endpoint: str = None, api_field: str = None) -> Optional[float]:
    """
    Belirtilen metriğin en son değerini döndür.
    Önce path formatını dener, başarısız olursa /api/Get... formatını dener.
    """
    # Format 1: /{asset}/market/Mvrv_zscore
    data = _alphractal_fetch(path, asset=asset)
    if data:
        val = data[-1].get(field)
        if val is not None:
            return float(val)

    # Format 2: /api/GetMvrvZscore (eğer belirtilmişse)
    if api_endpoint:
        data2 = _alphractal_api(api_endpoint, asset=asset)
        if data2:
            f = api_field or field
            val = data2[-1].get(f)
            if val is not None:
                return float(val)
    return None


# ─── Metrik Fonksiyonları ─────────────────────────────────────────────────────

def get_mvrv_zscore(asset: str = "btc") -> Optional[float]:
    """MVRV Z-Score — piyasanın aşırı ısınma/soğuma durumu."""
    return _latest("/{asset}/market/Mvrv_zscore", "mvrv_zscore", asset,
                   api_endpoint="GetMvrvZscore", api_field="mvrv_zscore")


def get_mvrv_ratio(asset: str = "btc") -> Optional[float]:
    """MVRV Ratio — piyasa değeri / realize edilmiş değer."""
    return _latest("/{asset}/market/CapMVRVCur", "capMVRVCur", asset,
                   api_endpoint="GetCapMVRVCur", api_field="capMVRVCur")


def get_nupl(asset: str = "btc") -> Optional[float]:
    """NUPL — Net Unrealized Profit/Loss."""
    return _latest("/{asset}/market/Nupl", "nupl", asset,
                   api_endpoint="GetNupl", api_field="nupl")


def get_lth_mvrv(asset: str = "btc") -> Optional[float]:
    """LTH-MVRV — Uzun vadeli tutucuların MVRV'si."""
    return _latest("/{asset}/lifespan/Lth_mvrv", "lth_mvrv", asset,
                   api_endpoint="GetLth_mvrv", api_field="lth_mvrv")


def get_sopr(asset: str = "btc") -> Optional[float]:
    """SOPR — Harcanan çıktıların kar/zarar oranı."""
    return _latest("/{asset}/lifespan/Sopr", "sopr", asset,
                   api_endpoint="GetSopr", api_field="sopr")


def get_sth_sopr(asset: str = "btc") -> Optional[float]:
    """STH-SOPR — Kısa vadeli tutucuların SOPR'u."""
    return _latest("/{asset}/lifespan/Sth_sopr", "sth_sopr", asset,
                   api_endpoint="GetSth_sopr", api_field="sth_sopr")


def get_exchange_netflow(asset: str = "btc") -> Optional[float]:
    """Exchange Net Flow — Borsalara BTC giriş/çıkışı."""
    return _latest("/{asset}/exchange_flow/Netflow", "netflow", asset,
                   api_endpoint="GetExchangeNetflow", api_field="netflow")


def get_long_short_ratio(asset: str = "btc") -> Optional[float]:
    """Long/Short Oranı — Türev piyasasındaki pozisyon dağılımı."""
    return _latest("/{asset}/derivatives/Long_short_ratio", "long_short_ratio", asset,
                   api_endpoint="GetLongShortRatio", api_field="long_short_ratio")


def get_nvt(asset: str = "btc") -> Optional[float]:
    """NVT Signal (90g) — Piyasa değeri / işlem hacmi oranı."""
    val = _latest("/{asset}/market/NVTAdj90", "nVTAdj90", asset,
                  api_endpoint="GetNVTAdj90", api_field="nVTAdj90")
    if val is None:
        val = _latest("/{asset}/market/NVTAdj", "nVTAdj", asset,
                      api_endpoint="GetNVTAdj", api_field="nVTAdj")
    return val


def get_active_addresses(asset: str = "btc") -> Optional[float]:
    """Aktif Adres Sayısı — Ağ kullanım yoğunluğu."""
    return _latest("/{asset}/addresses/AdrActCnt", "adrActCnt", asset,
                   api_endpoint="GetAdrActCnt", api_field="adrActCnt")


def get_funding_rate(asset: str = "btc") -> Optional[float]:
    """Funding Rate — Vadeli piyasada long/short maliyeti."""
    return _latest("/{asset}/derivatives/Funding_Rate", "value", asset)


# ─── Ana Fonksiyon: Tam On-Chain Özeti ───────────────────────────────────────

def get_crypto_onchain_data(symbol: str) -> dict:
    """
    Verilen kripto sembolü için tüm kritik on-chain metrikleri çek.

    Args:
        symbol: Kripto sembolü (BTC, ETH, SOL vb.)

    Returns:
        {
            "symbol": "BTC",
            "metrics": {
                "mvrv_zscore":       {"value": 2.1, "signal": "neutral", "note": "..."},
                "nupl":              {"value": 0.45, ...},
                "sth_sopr":          {"value": 1.02, ...},
                "exchange_netflow":  {"value": -3200.0, ...},
                "long_short_ratio":  {"value": 1.15, ...},
                "nvt":               {"value": 42.0, ...},
                "active_addresses":  {"value": 850000, ...},
                "funding_rate":      {"value": 0.012, ...},
            },
            "overall_signal": "green" | "neutral" | "amber" | "red",
            "summary": "Kısa özet metni",
            "error": None | "hata mesajı"
        }
    """
    asset = symbol.upper().replace("-USD", "").replace("USD", "").lower()

    result = {
        "symbol":          symbol.upper(),
        "metrics":         {},
        "overall_signal":  "neutral",
        "summary":         "",
        "error":           None,
    }

    try:
        _get_api_key()
    except ValueError as e:
        result["error"] = str(e)
        return result

    # ── Metrikleri çek ────────────────────────────────────────────────────────
    signals = []

    # MVRV Z-Score
    mvrv_z = get_mvrv_zscore(asset)
    if mvrv_z is not None:
        if mvrv_z >= 7:
            sig, note = "red",     f"Aşırı ısınmış — Tarihsel zirve bölgesi"
        elif mvrv_z >= 4:
            sig, note = "amber",   f"Yüksek bölge — Risk artıyor"
        elif mvrv_z >= 1:
            sig, note = "neutral", f"Normal boğa bölgesi"
        elif mvrv_z >= -0.5:
            sig, note = "green",   f"Adil değer — İyi alım bölgesi"
        else:
            sig, note = "green",   f"Dip bölgesi — Güçlü alım sinyali"
        result["metrics"]["mvrv_zscore"] = {"value": round(mvrv_z, 2), "signal": sig, "note": note}
        signals.append(sig)

    # NUPL
    nupl = get_nupl(asset)
    if nupl is not None:
        if nupl >= 0.75:
            sig, note = "red",     "Euphoria — Zirve riski yüksek"
        elif nupl >= 0.5:
            sig, note = "amber",   "Açgözlülük bölgesi — Dikkatli ol"
        elif nupl >= 0:
            sig, note = "neutral", "Umut bölgesi — Sağlıklı"
        elif nupl >= -0.25:
            sig, note = "green",   "Korku bölgesi — Alım fırsatı"
        else:
            sig, note = "green",   "Kapitülasyon — Güçlü alım sinyali"
        result["metrics"]["nupl"] = {"value": round(nupl, 3), "signal": sig, "note": note}
        signals.append(sig)

    # STH-SOPR
    sth_sopr = get_sth_sopr(asset)
    if sth_sopr is not None:
        if sth_sopr < 0.95:
            sig, note = "green",   "1'in altı — Kısa vadeliler zarar satıyor — Dip sinyali"
        elif sth_sopr < 1.0:
            sig, note = "green",   "Hafif zarar bölgesi — Zayıf eller temizleniyor"
        elif sth_sopr < 1.05:
            sig, note = "neutral", "1 civarı — Kar/zarar dengeli"
        elif sth_sopr < 1.15:
            sig, note = "amber",   "Kar realizasyonu var — Satış baskısı"
        else:
            sig, note = "red",     "Yüksek kar satışı — Tepe yakın olabilir"
        result["metrics"]["sth_sopr"] = {"value": round(sth_sopr, 3), "signal": sig, "note": note}
        signals.append(sig)

    # Exchange Net Flow
    netflow = get_exchange_netflow(asset)
    if netflow is not None:
        if netflow > 5000:
            sig, note = "red",     f"Borsalara YÜKSEK giriş — Satış baskısı"
        elif netflow > 0:
            sig, note = "amber",   f"Borsalara net giriş — Dikkat"
        elif netflow > -5000:
            sig, note = "green",   f"Borsalardan çıkış — HODLing artıyor"
        else:
            sig, note = "green",   f"Güçlü çıkış — Kurumsal birikim sinyali"
        result["metrics"]["exchange_netflow"] = {
            "value": round(netflow, 0), "signal": sig, "note": note
        }
        signals.append(sig)

    # Long/Short Ratio
    ls_ratio = get_long_short_ratio(asset)
    if ls_ratio is not None:
        if ls_ratio > 2.0:
            sig, note = "red",     "Aşırı long — Long squeeze riski"
        elif ls_ratio > 1.2:
            sig, note = "amber",   "Long ağırlıklı — Dikkat"
        elif ls_ratio < 0.5:
            sig, note = "green",   "Short ağırlıklı — Short squeeze fırsatı"
        else:
            sig, note = "neutral", "Dengeli — Normal piyasa"
        result["metrics"]["long_short_ratio"] = {
            "value": round(ls_ratio, 2), "signal": sig, "note": note
        }
        signals.append(sig)

    # NVT Signal (NVTAdj90) — 90 günlük hareketli ortalama bazlı
    nvt = get_nvt(asset)
    if nvt is not None:
        if nvt >= 150:
            sig, note = "red",     "Aşırı yüksek — Fiyat on-chain aktivitesinden kopuk, balon riski"
        elif nvt >= 100:
            sig, note = "amber",   "Yüksek — Dikkat, spekülasyon arttı"
        elif nvt >= 50:
            sig, note = "neutral", "Normal aralık — Sağlıklı"
        else:
            sig, note = "green",   "Düşük — Ağ yoğun kullanılıyor, fiyat destekli"
        result["metrics"]["nvt"] = {"value": round(nvt, 1), "signal": sig, "note": note}
        signals.append(sig)

    # Aktif Adres
    addr = get_active_addresses(asset)
    if addr is not None:
        addr_k = round(addr / 1000)
        if addr >= 1_200_000:
            sig, note = "green",   "Yüksek ağ aktivitesi"
        elif addr >= 600_000:
            sig, note = "neutral", "Normal aktivite"
        else:
            sig, note = "amber",   "Düşük aktivite — İlgi azalıyor"
        result["metrics"]["active_addresses"] = {
            "value": int(addr), "signal": sig, "note": f"~{addr_k}K aktif adres/gün — {note}"
        }
        signals.append(sig)

    # Funding Rate
    funding = get_funding_rate(asset)
    if funding is not None:
        funding_pct = round(funding * 100, 4)
        if funding > 0.03:
            sig, note = "red",     "Çok yüksek — Longlar aşırı ücret ödüyor"
        elif funding > 0.01:
            sig, note = "amber",   "Yüksek — Long ağırlıklı piyasa"
        elif funding < -0.01:
            sig, note = "green",   "Negatif — Short ağırlıklı, bounce olabilir"
        else:
            sig, note = "neutral", "Normal"
        result["metrics"]["funding_rate"] = {
            "value": funding_pct, "signal": sig, "note": f"%{funding_pct}/8s — {note}"
        }
        signals.append(sig)

    # ── Genel sinyal: ağırlıklı çoğunluk ────────────────────────────────────
    if signals:
        counts   = {"green": signals.count("green"), "amber": signals.count("amber"),
                    "red": signals.count("red"), "neutral": signals.count("neutral")}
        total    = len(signals)
        red_pct  = counts["red"]   / total
        grn_pct  = counts["green"] / total

        if red_pct >= 0.5:
            overall = "red"       # Çoğunluk kırmızı → dikkatli
        elif red_pct >= 0.34:
            overall = "amber"     # 1/3'ten fazla kırmızı → temkinli
        elif grn_pct >= 0.5:
            overall = "green"     # Çoğunluk yeşil → olumlu
        elif counts["amber"] > counts["green"]:
            overall = "amber"
        else:
            overall = "neutral"
        result["overall_signal"] = overall

    # ── Özet metin ────────────────────────────────────────────────────────────
    filled = len(result["metrics"])
    if filled == 0:
        result["error"]   = "Alphractal'dan veri alınamadı. API key ve plan erişimini kontrol et."
        result["summary"] = "On-chain verisi mevcut değil."
    else:
        green_count = signals.count("green")
        red_count   = signals.count("red")
        amber_count = signals.count("amber")
        overall     = result["overall_signal"]

        if overall == "green":
            durum = "olumlu — Birikim fırsatı sinyalleri var"
        elif overall == "red":
            durum = "dikkatli — Yüksek değerleme veya satış baskısı"
        elif overall == "amber":
            durum = "nötr-dikkatli — Karma sinyaller"
        else:
            durum = "nötr — Bekleme modunda"

        result["summary"] = (
            f"{symbol.upper()} on-chain durumu {durum}. "
            f"{filled} metrik: {green_count} yeşil, {amber_count} sarı, {red_count} kırmızı."
        )

    return result
