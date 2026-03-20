# crisis_comparator.py — Tarihsel Kriz Karşılaştırma Motoru
#
# Temel fikir: Bugünkü makro gösterge vektörünü 1929, 1987, 2000 ve 2008
# krizlerinden önce gözlemlenen gösterge vektörleriyle matematiksel olarak
# karşılaştır. Kosinüs benzerliği ve Öklid mesafesiyle "şu anki durum
# en çok hangi kriz öncesine benziyor?" sorusunu yanıtla.
#
# Metodoloji notu: Tarihsel göstergeler normalize edilmiş z-score olarak
# saklanıyor çünkü mutlak değerler dönemler arası karşılaştırılamaz.
# Örneğin 1929'da VIX yoktu — ancak volatilite proxy'si olarak Dow
# günlük değişim standart sapması kullanılıyor.

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ─── Tarihsel Kriz Profilleri ─────────────────────────────────────────────────
# Her krizden 6-12 ay ÖNCE gözlemlenen göstergeler.
# Değerler normalize edilmiş (z-score, tarihsel ortalamaya göre).
# Pozitif = ortalamanın üzerinde tehlike, negatif = altında.
#
# Kaynak: NBER, Robert Shiller (Yale), BIS, FRED tarihsel serileri
# Bunu anlatan akademik literatür: Reinhart & Rogoff "This Time Is Different"

CRISIS_PROFILES = {
    "1929_büyük_buhran": {
        "label":       "1929 Büyük Buhran",
        "peak_date":   "Ekim 1929",
        "drawdown":    -89,   # % Dow Jones düşüşü (3 yılda)
        "trigger":     "Teminat borcu çöküşü + banka panikları",
        "lesson":      "Kaldıraç sarmalı ne kadar hızlı tersine döner",
        # Normalize edilmiş göstergeler (z-score)
        "indicators": {
            "buffett_ratio":     +3.2,  # Piyasa değeri/GSYİH çok yüksek
            "margin_debt_gdp":   +4.1,  # Teminat borcu/GSYİH rekor (%12)
            "pe_ratio":          +2.8,  # P/E tarihi ortalamanın 3σ üzerinde
            "yield_curve":       +0.8,  # Normal ama kriz öncesi henüz normal
            "credit_spread":     -0.5,  # Kriz öncesi sıkışmış (dar)
            "housing_activity":  +2.1,  # 1926-29 Florida+ulusal konut balonu
            "consumer_debt":     +2.9,  # Tüketici borcu GSYİH'ya oranla yüksek
            "corporate_debt":    +1.8,  # Kurumsal borçlanma artmış
            "vix_proxy":         -0.3,  # Düşük volatilite = sahte güven
            "momentum":          +1.5,  # Güçlü piyasa momentumu (rally devam)
        }
    },
    "1987_kara_pazartesi": {
        "label":       "1987 Kara Pazartesi",
        "peak_date":   "Ekim 1987",
        "drawdown":    -22,   # % tek günde S&P 500
        "trigger":     "Program trading + portfolio insurance tetiklemesi",
        "lesson":      "Tek gün şokları mümkün — carry pozisyonları da bunu hızlandırır",
        "indicators": {
            "buffett_ratio":     +1.8,  # Yüksek ama 1929 kadar değil
            "margin_debt_gdp":   +1.2,
            "pe_ratio":          +2.2,  # Yüksek değerleme
            "yield_curve":       +0.3,  # Normal
            "credit_spread":     -0.3,
            "housing_activity":  +0.5,
            "consumer_debt":     +0.8,
            "corporate_debt":    +0.6,
            "vix_proxy":         -0.8,  # Çok düşük volatilite — risk anlaşılmamış
            "momentum":          +2.8,  # 1987 başında %35+ ralli
        }
    },
    "2000_dotcom": {
        "label":       "2000 Dotcom Balonu",
        "peak_date":   "Mart 2000",
        "drawdown":    -78,   # % NASDAQ
        "trigger":     "Değerleme gerçeklikle buluştu + Fed faiz artışı",
        "lesson":      "Narrative > fundamentals dönemleri ancak geriye bakınca görülür",
        "indicators": {
            "buffett_ratio":     +3.8,  # %148 — dotcom zirvesi rekoru
            "margin_debt_gdp":   +3.5,  # %2.7 GSYİH — o dönem rekoru
            "pe_ratio":          +4.2,  # Teknoloji hisseleri kazancın 100 katı
            "yield_curve":       +1.2,  # Tersine dönüyor (resesyon sinyali)
            "credit_spread":     +0.5,  # Kurumsal borç artmış
            "housing_activity":  +0.3,  # Henüz konut balonu yok
            "consumer_debt":     +1.5,
            "corporate_debt":    +2.1,
            "vix_proxy":         +1.8,  # VIX artmıştı ama görmezden gelindi
            "momentum":          +3.2,  # Spekülatif momentum çok yüksek
        }
    },
    "2007_mortgage_krizi": {
        "label":       "2007-08 Mortgage Krizi (GFC)",
        "peak_date":   "Ekim 2007",
        "drawdown":    -57,   # % S&P 500
        "trigger":     "Subprime mortgage temerrütleri → CDO çöküşü",
        "lesson":      "Görünmez kaldıraç (off-balance sheet) en tehlikeli olandır",
        "indicators": {
            "buffett_ratio":     +1.2,  # Yüksek ama 2000 kadar değil (%105)
            "margin_debt_gdp":   +2.8,  # Rekor seviyede
            "pe_ratio":          +1.5,
            "yield_curve":       +2.1,  # Tersine dönmüştü — en güçlü resesyon sinyali
            "credit_spread":     +2.5,  # Subprime spread'leri açılıyordu
            "housing_activity":  +3.8,  # Konut balonu patlamak üzere
            "consumer_debt":     +2.8,  # Subprime borçlanma rekordu
            "corporate_debt":    +1.9,
            "vix_proxy":         +1.1,
            "momentum":          +0.8,
        }
    },
}


@dataclass
class CrisisComparison:
    """Tek bir krizle karşılaştırma sonucu."""
    crisis_key:     str
    label:          str
    similarity_pct: float        # Kosinüs benzerliği → 0-100 arası
    distance:       float        # Öklid mesafesi (düşük = daha benzer)
    matched_signals: List[str]   # En güçlü örtüşen göstergeler
    divergent:      List[str]    # En büyük farklılıklar
    peak_date:      str
    drawdown:       int
    trigger:        str
    lesson:         str
    risk_level:     str          # "YÜKSEK" / "ORTA" / "DÜŞÜK"


def _normalize_current(current_raw: dict) -> dict:
    """
    Mevcut göstergeleri tarihsel profillerle karşılaştırılabilir z-score'lara dönüştür.

    Sezgisel normalizasyon kuralları — her gösterge için "ne kadar tehlikeli?"
    sorusunu 0 (nötr) ile ±4 arası bir skalaya çevirir.
    """
    normalized = {}

    # Buffett Göstergesi
    buffett = current_raw.get("buffett_ratio", 0)
    if buffett > 0:
        # Tarihsel ortalama ~%100, std ~40pp
        normalized["buffett_ratio"] = (buffett - 100) / 40

    # P/E Oranı (S&P 500 Forward P/E)
    pe = current_raw.get("sp500_pe", 0)
    if pe > 0:
        # Tarihsel ortalama ~16x, std ~4
        normalized["pe_ratio"] = (pe - 16) / 4

    # Yield Curve (10Y - 2Y)
    yc = current_raw.get("yield_curve_spread", 999)
    if yc != 999:
        # Tersine döndükçe daha tehlikeli; -0.5 = inversiyon
        # Normalize: inversiyon = +2.0, pozitif = negatif z-score
        normalized["yield_curve"] = -yc / 0.5  # -0.5 inversiyonu → z=+1

    # Kredi Spread (High Yield - Investment Grade)
    cs = current_raw.get("credit_spread", 0)
    if cs > 0:
        # Tarihsel ortalama ~350bp, std ~150bp
        # Geniş spread = tehlikeli = pozitif z
        normalized["credit_spread"] = (cs - 350) / 150

    # VIX — düşük VIX tehlikeli (sahte güven)
    vix = current_raw.get("vix", 0)
    if vix > 0:
        # VIX 12-15 = tehlikeli düşük, 25-30 = yüksek ama tepki veriliyor
        # Düşük VIX → pozitif risk (sahte güven) → ters normalize
        normalized["vix_proxy"] = -(vix - 20) / 8  # VIX 12 → +1, VIX 28 → -1

    # Teminat Borcu / Spekülatif Aktivite
    spec = current_raw.get("spec_activity_pct", 0)
    if spec > 0:
        # 80%+ zirve yakın = tehlikeli, 40% = nötr
        normalized["margin_debt_gdp"] = (spec - 50) / 20

    # Konut Aktivitesi
    new_home = current_raw.get("new_home_sales", 0)
    if new_home > 0:
        # 700K+ normal, 600K altı sorunlu, 400K altı kriz
        normalized["housing_activity"] = (new_home - 650) / 100

    # Kurumsal Borç / GSYİH
    corp_debt_ratio = current_raw.get("corporate_debt_gdp", 0)
    if corp_debt_ratio > 0:
        # Tarihsel ortalama ~%35, std ~%10
        normalized["corporate_debt"] = (corp_debt_ratio - 35) / 10

    # Piyasa Momentumu (12M getiri)
    sp500_mom = current_raw.get("sp500_12m_return", 0)
    if sp500_mom > 0:
        # Güçlü yükseliş öncesi momentum her krizde yüksekti
        normalized["momentum"] = (sp500_mom - 10) / 15  # %10 ortalama, %15 std

    return normalized


def _cosine_similarity(vec_a: dict, vec_b: dict) -> float:
    """
    İki gösterge vektörü arasındaki kosinüs benzerliği.
    Ortak anahtarlar üzerinden hesaplanır.
    Sonuç: -1 (tam zıt) ile +1 (tam aynı) arası.
    """
    keys = set(vec_a.keys()) & set(vec_b.keys())
    if not keys:
        return 0.0

    dot   = sum(vec_a[k] * vec_b[k] for k in keys)
    mag_a = math.sqrt(sum(vec_a[k]**2 for k in keys))
    mag_b = math.sqrt(sum(vec_b[k]**2 for k in keys))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _euclidean_distance(vec_a: dict, vec_b: dict) -> float:
    """Öklid mesafesi — düşük değer = daha benzer."""
    keys = set(vec_a.keys()) & set(vec_b.keys())
    if not keys:
        return float('inf')
    return math.sqrt(sum((vec_a[k] - vec_b[k])**2 for k in keys))


def compare_to_historical_crises(current_indicators: dict) -> List[CrisisComparison]:
    """
    Mevcut göstergeleri tüm kriz profilleriyle karşılaştır.
    Benzerlik sırasına göre döndür (en benzer ilk).

    current_indicators formatı:
    {
        "buffett_ratio":      230.0,   # Buffett Göstergesi %
        "sp500_pe":           22.0,    # Forward P/E
        "yield_curve_spread": 0.77,    # 10Y-2Y farkı
        "credit_spread":      320.0,   # HY-IG bp
        "vix":                25.0,
        "spec_activity_pct":  70.0,    # TQQQ pozisyon %
        "new_home_sales":     587.0,   # K adet
        "corporate_debt_gdp": 50.0,    # %
        "sp500_12m_return":   18.0,    # %
    }
    """
    current_norm = _normalize_current(current_indicators)

    if not current_norm:
        logger.warning("Karşılaştırma için yeterli gösterge yok")
        return []

    results = []
    for key, profile in CRISIS_PROFILES.items():
        crisis_vec = profile["indicators"]

        similarity = _cosine_similarity(current_norm, crisis_vec)
        distance   = _euclidean_distance(current_norm, crisis_vec)

        # Benzerliği 0-100 arasına dönüştür
        similarity_pct = (similarity + 1) / 2 * 100

        # Hangi göstergeler en çok örtüşüyor?
        common_keys = set(current_norm.keys()) & set(crisis_vec.keys())
        agreement = {}
        for k in common_keys:
            c_sign = 1 if current_norm[k] > 0 else -1
            h_sign = 1 if crisis_vec[k]   > 0 else -1
            agreement[k] = (c_sign == h_sign, abs(current_norm[k]) + abs(crisis_vec[k]))

        matched   = [k for k, (ag, mag) in sorted(agreement.items(), key=lambda x: -x[1][1]) if ag][:3]
        divergent = [k for k, (ag, mag) in sorted(agreement.items(), key=lambda x: -x[1][1]) if not ag][:2]

        # Risk seviyesi — benzerlik yüksekse ve drawdown büyükse yüksek risk
        if similarity_pct > 65 and abs(profile["drawdown"]) > 50:
            risk = "YÜKSEK"
        elif similarity_pct > 50:
            risk = "ORTA"
        else:
            risk = "DÜŞÜK"

        # Gösterge isimlerini Türkçeye çevir
        label_map = {
            "buffett_ratio":     "Buffett Göstergesi",
            "margin_debt_gdp":   "Teminat Borcu/Spekülatif Aktivite",
            "pe_ratio":          "P/E Değerleme",
            "yield_curve":       "Getiri Eğrisi",
            "credit_spread":     "Kredi Spread'i",
            "housing_activity":  "Konut Aktivitesi",
            "consumer_debt":     "Tüketici Borcu",
            "corporate_debt":    "Kurumsal Borç",
            "vix_proxy":         "Volatilite/VIX",
            "momentum":          "Piyasa Momentumu",
        }

        results.append(CrisisComparison(
            crisis_key      = key,
            label           = profile["label"],
            similarity_pct  = round(similarity_pct, 1),
            distance        = round(distance, 2),
            matched_signals = [label_map.get(k, k) for k in matched],
            divergent       = [label_map.get(k, k) for k in divergent],
            peak_date       = profile["peak_date"],
            drawdown        = profile["drawdown"],
            trigger         = profile["trigger"],
            lesson          = profile["lesson"],
            risk_level      = risk,
        ))

    # En benzer kriz en üstte
    results.sort(key=lambda x: -x.similarity_pct)
    return results


def get_crisis_context_for_claude(current_indicators: dict) -> str:
    """
    Tarihsel kriz karşılaştırmasını direktör ve makro analiz için
    formatlı metin olarak üret.
    """
    comparisons = compare_to_historical_crises(current_indicators)
    if not comparisons:
        return ""

    lines = ["\n=== TARİHSEL KRİZ KARŞILAŞTIRMASI ==="]
    lines.append("Mevcut göstergeler geçmiş kriz dönemleriyle matematiksel olarak karşılaştırıldı.")
    lines.append("Yöntem: Kosinüs benzerliği (normalize edilmiş gösterge vektörleri)\n")

    for i, comp in enumerate(comparisons[:3]):  # En benzer 3 kriz
        risk_emoji = {"YÜKSEK": "🔴", "ORTA": "🟡", "DÜŞÜK": "🟢"}.get(comp.risk_level, "⚪")
        lines.append(
            f"{i+1}. {risk_emoji} {comp.label} ({comp.peak_date}) — "
            f"Benzerlik: %{comp.similarity_pct:.0f} | Risk: {comp.risk_level}"
        )
        lines.append(
            f"   Düşüş: {comp.drawdown}% | Tetikleyici: {comp.trigger}"
        )
        if comp.matched_signals:
            lines.append(f"   Örtüşen sinyaller: {', '.join(comp.matched_signals)}")
        if comp.divergent:
            lines.append(f"   Farklılaşan: {', '.join(comp.divergent)}")
        lines.append(f"   Ders: {comp.lesson}")
        lines.append("")

    # En benzer kriz için özel uyarı
    top = comparisons[0]
    if top.similarity_pct > 60:
        lines.append(
            f"⚠️ DİKKAT: Mevcut tablo {top.label} öncesiyle %{top.similarity_pct:.0f} "
            f"benzerlik gösteriyor. O dönemde piyasa zirveden {top.drawdown}% düştü. "
            f"Bu bir kesinlik değil, olasılık dağılımında ağırlık artışı anlamına gelir."
        )

    lines.append("=" * 50)
    return "\n".join(lines)
