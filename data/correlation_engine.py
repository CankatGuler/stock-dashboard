# correlation_engine.py — Varlıklar Arası Korelasyon Motoru
#
# Cross-asset korelasyonlar Claude'un strateji üretmesi için kritik bağlam.
# "BTC al" derken BTC'nin tech hisselerinle %0.75 korelasyonlu olduğunu
# bilmek, gerçek anlamda çeşitlendirme yapılıp yapılmadığını gösterir.
#
# Hesaplanan korelasyonlar:
#   BTC / Tech hisseleri (QQQ proxy)
#   BTC / Altın
#   BTC / S&P 500
#   BTC / M2 (Global likidite proxy)
#   Altın / S&P 500
#   Altın / DXY (ters korelasyon beklenir)
#   Altın / Reel faiz (ters korelasyon beklenir)
#   Petrol / Enflasyon proxy
#   BIST / DXY (TL üzerinden)
#   Portföy içi korelasyon matrisi (kullanıcının hisseleri)
#
# Periyot: 90 gün (kısa vade) + 365 gün (uzun vade) — ikisi farklı anlatır

import logging
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── Sabit varlık çiftleri ────────────────────────────────────────────────────

CROSS_ASSET_PAIRS = [
    # (isim, ticker_A, ticker_B, beklenen_yön, açıklama)
    ("BTC / Tech (QQQ)",   "BTC-USD",   "QQQ",       "pozitif",
     "BTC ve tech hisseleri risk-off dönemlerinde birlikte düşer. Yüksek korelasyon = çeşitlendirme yanılgısı."),

    ("BTC / Altın",        "BTC-USD",   "GC=F",      "değişken",
     "BTC dijital altın mı yoksa risk varlığı mı? Korelasyon dönemlere göre değişir."),

    ("BTC / S&P 500",      "BTC-USD",   "^GSPC",     "pozitif",
     "Risk-off dönemlerinde BTC S&P ile yüksek korelasyon gösterir."),

    ("BTC / Global Likidite", "BTC-USD", "TLT",      "negatif",
     "Global M2 proxy: tahvil fiyatı düştükçe (faiz arttıkça) BTC genellikle baskılanır."),

    ("Altın / S&P 500",    "GC=F",      "^GSPC",     "negatif",
     "Klasik hedge: piyasa düşerken altın yükselir. Korelasyon negatif olmalı."),

    ("Altın / DXY",        "GC=F",      "DX-Y.NYB",  "negatif",
     "Dolar güçlenince altın genellikle düşer. Güçlü negatif korelasyon normaldir."),

    ("Altın / Reel Faiz",  "GC=F",      "TIP",       "pozitif",
     "TIP ETF reel faizi proxy eder. TIP yükselince (reel faiz düşünce) altın yükselir."),

    ("Petrol / Enflasyon", "CL=F",      "TIP",       "pozitif",
     "Petrol yükselince enflasyon beklentisi artar — TIP ile pozitif korelasyon."),

    ("Tech / Faiz",        "QQQ",       "TLT",       "pozitif",
     "Tech büyüme hisseleri faize duyarlı: tahvil fiyatı yükselince (faiz düşünce) tech toparlanır."),

    ("Altın / BTC (Uzun)", "GC=F",      "BTC-USD",   "değişken",
     "Uzun vadede bakıldığında ikisi de para arzı genişlemesinden faydalanır."),
]


# ─── Korelasyon Hesaplama ────────────────────────────────────────────────────

def compute_correlation(ticker_a: str, ticker_b: str,
                        period_days: int = 90) -> float | None:
    """
    İki varlık arasındaki Pearson korelasyonunu hesapla.
    Returns: -1.0 ile +1.0 arası float, veri yoksa None
    """
    try:
        import yfinance as yf
        import statistics

        end   = datetime.now()
        start = end - timedelta(days=period_days + 10)

        hist_a = yf.Ticker(ticker_a).history(start=start, end=end)["Close"]
        hist_b = yf.Ticker(ticker_b).history(start=start, end=end)["Close"]

        # Ortak tarihlere hizala
        common = hist_a.index.intersection(hist_b.index)
        if len(common) < 20:
            return None

        a_vals = [float(hist_a[d]) for d in common]
        b_vals = [float(hist_b[d]) for d in common]

        # Günlük getiriler üzerinden korelasyon hesapla (fiyat değil)
        a_rets = [(a_vals[i] - a_vals[i-1]) / a_vals[i-1]
                  for i in range(1, len(a_vals)) if a_vals[i-1] > 0]
        b_rets = [(b_vals[i] - b_vals[i-1]) / b_vals[i-1]
                  for i in range(1, len(b_vals)) if b_vals[i-1] > 0]

        n = min(len(a_rets), len(b_rets))
        if n < 15:
            return None

        a_rets = a_rets[:n]
        b_rets = b_rets[:n]

        # Pearson korelasyon
        mean_a = sum(a_rets) / n
        mean_b = sum(b_rets) / n
        cov    = sum((a_rets[i] - mean_a) * (b_rets[i] - mean_b) for i in range(n)) / n
        std_a  = statistics.stdev(a_rets)
        std_b  = statistics.stdev(b_rets)

        if std_a == 0 or std_b == 0:
            return None

        corr = round(cov / (std_a * std_b), 3)
        return max(-1.0, min(1.0, corr))

    except Exception as e:
        logger.debug("Correlation failed %s/%s: %s", ticker_a, ticker_b, e)
        return None


def interpret_correlation(corr: float, expected: str,
                          label: str, description: str) -> dict:
    """
    Korelasyon değerini yorumla.
    expected: "pozitif" | "negatif" | "değişken"
    """
    if corr is None:
        return {
            "correlation": None,
            "signal":      "neutral",
            "label":       label,
            "note":        f"{label}: Veri yetersiz",
        }

    # Gücü belirle
    abs_c = abs(corr)
    if abs_c >= 0.7:
        strength = "Çok Yüksek"
    elif abs_c >= 0.5:
        strength = "Yüksek"
    elif abs_c >= 0.3:
        strength = "Orta"
    elif abs_c >= 0.1:
        strength = "Zayıf"
    else:
        strength = "Yok"

    direction = "Pozitif" if corr > 0 else "Negatif"

    # Beklenenle karşılaştır
    if expected == "pozitif":
        if corr >= 0.5:
            signal = "neutral"   # Beklenen — çeşitlendirme sınırlı
            warn   = "Birlikte hareket ediyor — gerçek çeşitlendirme sağlamıyor."
        elif corr >= 0.3:
            signal = "green"
            warn   = "Orta korelasyon — kısmi çeşitlendirme mümkün."
        else:
            signal = "green"
            warn   = "Düşük korelasyon — iyi çeşitlendirme!"
    elif expected == "negatif":
        if corr <= -0.5:
            signal = "green"     # Beklenen — güçlü hedge
            warn   = "Güçlü negatif korelasyon — hedge görevi yapıyor."
        elif corr <= -0.3:
            signal = "green"
            warn   = "Orta hedge etkisi var."
        elif corr >= 0.3:
            signal = "red"       # Beklenmedik — hedge bozuldu
            warn   = "⚠️ Beklenmedik pozitif korelasyon! Hedge etkisi kayboldu."
        else:
            signal = "amber"
            warn   = "Zayıf negatif korelasyon — hedge kısmen çalışıyor."
    else:  # değişken
        signal = "neutral"
        warn   = "Korelasyon dönemlere göre değişir."

    note = (f"{label}: {corr:+.2f} ({strength} {direction}). "
            f"{warn} — {description[:60]}")

    return {
        "correlation": corr,
        "strength":    strength,
        "direction":   direction,
        "signal":      signal,
        "label":       label,
        "note":        note,
        "warn":        warn,
    }


# ─── Cross-Asset Korelasyon Analizi ──────────────────────────────────────────

def fetch_cross_asset_correlations(period_days: int = 90) -> dict:
    """
    Tüm varlık çiftleri için korelasyon hesapla.
    90 gün = kısa vadeli ilişki
    """
    results = {}
    logger.info("Cross-asset korelasyon hesaplanıyor (%d gün)...", period_days)

    for label, ticker_a, ticker_b, expected, desc in CROSS_ASSET_PAIRS:
        corr = compute_correlation(ticker_a, ticker_b, period_days)
        results[label] = interpret_correlation(corr, expected, label, desc)
        time.sleep(0.2)

    logger.info("Korelasyon hesaplandı: %d çift", len(results))
    return results


# ─── Portföy İçi Korelasyon ──────────────────────────────────────────────────

def fetch_portfolio_correlations(tickers: list,
                                  period_days: int = 90) -> dict:
    """
    Kullanıcının portföyündeki hisseler arasındaki korelasyon matrisi.
    En yüksek korelasyonlu çiftleri tespit et — gerçek çeşitlendirmeyi ölç.
    """
    if len(tickers) < 2:
        return {}

    try:
        import yfinance as yf
        from datetime import timedelta

        end   = datetime.now()
        start = end - timedelta(days=period_days + 10)

        # Tüm hisse tarihlerini çek
        price_data = {}
        for ticker in tickers[:15]:  # Max 15 hisse
            try:
                hist = yf.Ticker(ticker).history(start=start, end=end)["Close"]
                if len(hist) >= 20:
                    price_data[ticker] = hist
                time.sleep(0.1)
            except Exception:
                pass

        if len(price_data) < 2:
            return {}

        # Korelasyon matrisi
        pairs    = []
        tickers_ = list(price_data.keys())

        for i in range(len(tickers_)):
            for j in range(i + 1, len(tickers_)):
                a, b  = tickers_[i], tickers_[j]
                corr  = compute_correlation(a, b, period_days)
                if corr is not None:
                    pairs.append({
                        "pair":        f"{a}/{b}",
                        "ticker_a":    a,
                        "ticker_b":    b,
                        "correlation": corr,
                    })

        if not pairs:
            return {}

        # En yüksek korelasyonlu çiftler (risk konsantrasyonu)
        high_corr = [p for p in pairs if p["correlation"] >= 0.7]
        high_corr.sort(key=lambda x: x["correlation"], reverse=True)

        # Ortalama korelasyon
        avg_corr  = round(sum(p["correlation"] for p in pairs) / len(pairs), 3)

        # Diversification score: 1 - avg_corr (0=tamamen ilişkili, 1=tamamen bağımsız)
        div_score = round((1 - avg_corr) * 100, 1)

        if div_score >= 70:
            signal = "green"
            note   = f"Portföy çeşitlendirmesi İYİ (%{div_score:.0f} skor). Düşük korelasyon."
        elif div_score >= 50:
            signal = "amber"
            note   = (f"Portföy çeşitlendirmesi ORTA (%{div_score:.0f} skor). "
                     f"Bazı hisseler birlikte hareket ediyor.")
        else:
            signal = "red"
            note   = (f"Portföy çeşitlendirmesi ZAYIF (%{div_score:.0f} skor). "
                     f"Çoğu hisse yüksek korelasyonlu — risk konsantrasyonu var!")

        if high_corr:
            top_pairs = ", ".join(p["pair"] for p in high_corr[:3])
            note += f" En yüksek korelasyonlu çiftler: {top_pairs}"

        return {
            "pairs":        pairs,
            "high_corr":    high_corr,
            "avg_corr":     avg_corr,
            "div_score":    div_score,
            "signal":       signal,
            "note":         note,
        }

    except Exception as e:
        logger.warning("Portfolio correlations failed: %s", e)
        return {}


# ─── Yapısal Rejim Değişimi Tespiti ─────────────────────────────────────────

def detect_correlation_regime_change(period_short: int = 30,
                                      period_long: int = 180) -> dict:
    """
    Korelasyon rejim değişimini tespit et.
    Kısa vadeli korelasyon uzun vadeden önemli ölçüde farklılaşıyorsa
    piyasa rejimi değişiyor olabilir.

    Örnek: BTC/Tech kısa vade korelasyonu 0.3'e düştüyse ama uzun vade 0.7 ise
    → BTC, tech'ten ayrışmaya başlıyor = potansiyel bağımsızlık sinyali.
    """
    key_pairs = [
        ("BTC / Tech (QQQ)", "BTC-USD", "QQQ"),
        ("Altın / S&P 500",  "GC=F",    "^GSPC"),
        ("BTC / Altın",      "BTC-USD", "GC=F"),
    ]

    changes = []
    for label, a, b in key_pairs:
        try:
            corr_short = compute_correlation(a, b, period_short)
            corr_long  = compute_correlation(a, b, period_long)
            time.sleep(0.15)

            if corr_short is None or corr_long is None:
                continue

            diff = round(corr_short - corr_long, 3)
            if abs(diff) >= 0.25:  # Anlamlı değişim eşiği
                direction = "DÜŞTÜ" if diff < 0 else "ARTTI"
                changes.append({
                    "label":       label,
                    "corr_short":  corr_short,
                    "corr_long":   corr_long,
                    "diff":        diff,
                    "note":        (f"{label}: Kısa vade {corr_short:+.2f} vs "
                                   f"Uzun vade {corr_long:+.2f} → "
                                   f"Korelasyon {direction} ({diff:+.2f}). "
                                   f"Rejim değişimi olabilir!")
                })
        except Exception:
            pass

    return {
        "regime_changes": changes,
        "has_changes":    len(changes) > 0,
        "note": (
            " | ".join(c["note"] for c in changes)
            if changes else
            "Korelasyon rejimleri stabil — anlamlı değişim yok."
        ),
    }


# ─── Claude için Korelasyon Özeti ─────────────────────────────────────────────

def build_correlation_prompt(cross_data: dict,
                              portfolio_data: dict,
                              regime_data: dict) -> str:
    """
    Korelasyon verilerini Claude için formatlı metne dönüştür.
    """
    lines = ["\n=== VARLIK KORELASYON ANALİZİ ==="]
    lines.append("NOT: Yüksek korelasyon = gerçek çeşitlendirme yok demektir.\n")

    # Kritik cross-asset korelasyonlar
    priority_pairs = [
        "BTC / Tech (QQQ)",
        "BTC / S&P 500",
        "BTC / Altın",
        "Altın / S&P 500",
        "Altın / DXY",
        "BTC / Global Likidite",
    ]

    for pair in priority_pairs:
        if pair in cross_data:
            d = cross_data[pair]
            corr = d.get("correlation")
            if corr is not None:
                lines.append(f"  {pair}: {corr:+.2f} ({d.get('strength','')}) — {d.get('warn','')}")

    # Portföy içi çeşitlendirme
    if portfolio_data:
        lines.append(f"\nPortföy Çeşitlendirme Skoru: {portfolio_data.get('div_score','—')}/100")
        lines.append(f"  → {portfolio_data.get('note','')}")

        high = portfolio_data.get("high_corr", [])
        if high:
            lines.append("  Yüksek korelasyonlu çiftler (risk konsantrasyonu):")
            for p in high[:5]:
                lines.append(f"    {p['pair']}: {p['correlation']:+.2f}")

    # Rejim değişimleri
    if regime_data and regime_data.get("has_changes"):
        lines.append(f"\n⚠️ Korelasyon Rejim Değişimi Tespit Edildi:")
        for c in regime_data.get("regime_changes", []):
            lines.append(f"  {c['note']}")

    lines.append(
        "\nSTRATEJİ NOTU: Korelasyon > 0.7 olan varlıklara birden pozisyon açmak "
        "çeşitlendirme yanılgısı yaratır. Her iki varlık aynı anda düşer."
    )

    return "\n".join(lines)


# ─── Ana Toplayıcı ───────────────────────────────────────────────────────────

def fetch_all_correlations(portfolio_tickers: list = None) -> dict:
    """
    Tüm korelasyon analizini tek seferde çalıştır.
    """
    logger.info("Korelasyon analizi başlıyor...")

    cross   = fetch_cross_asset_correlations(period_days=90)
    port    = fetch_portfolio_correlations(portfolio_tickers or [], period_days=90)
    regime  = detect_correlation_regime_change()

    prompt  = build_correlation_prompt(cross, port, regime)

    return {
        "cross_asset":   cross,
        "portfolio":     port,
        "regime":        regime,
        "prompt":        prompt,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }
