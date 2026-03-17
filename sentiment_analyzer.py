# sentiment_analyzer.py — Haber Duygu Skoru Analizi
#
# Her haber için -1 (çok negatif) ile +1 (çok pozitif) arasında skor üretir.
# Kural tabanlı (hızlı) + Claude tabanlı (derin) iki mod desteklenir.
#
# Kural tabanlı mod: anahtar kelime eşleştirme, API gerektirmez
# Claude modu:       derin bağlamsal analiz, Claude API kullanır

import re
import logging

logger = logging.getLogger(__name__)

# ─── Anahtar kelime sözlükleri ────────────────────────────────────────────────

POSITIVE_KEYWORDS = [
    # Kazanç / Büyüme
    "beat", "beats", "exceeded", "surpassed", "record", "record high",
    "revenue growth", "profit", "earnings beat", "strong results",
    "raised guidance", "upgraded", "upgrade", "buy rating", "outperform",
    "strong buy", "price target raised", "target raised",
    # Ürün / Sözleşme
    "fda approved", "fda approval", "contract won", "major contract",
    "partnership", "acquisition", "merger", "deal closed",
    "patent granted", "breakthrough", "launch", "new product",
    # Piyasa
    "rally", "surge", "soar", "jump", "gain", "bullish",
    "all-time high", "52-week high", "outperform",
    # Insider
    "insider buying", "ceo bought", "director bought",
]

NEGATIVE_KEYWORDS = [
    # Kayıp / Düşüş
    "miss", "missed", "below expectations", "disappointing", "weak",
    "revenue decline", "loss", "earnings miss", "lowered guidance",
    "downgraded", "downgrade", "sell rating", "underperform",
    "price target cut", "target lowered",
    # Risk
    "fda rejected", "fda rejection", "lawsuit", "investigation",
    "sec probe", "fraud", "accounting irregularities",
    "ceo resigned", "ceo fired", "layoffs", "restructuring",
    # Piyasa
    "crash", "plunge", "tumble", "fall", "drop", "decline", "bearish",
    "52-week low", "all-time low",
    # Makro
    "recession", "default", "bankruptcy", "delisted",
]

STRONG_POSITIVE = ["fda approved", "record high", "all-time high", "major contract", "acquisition"]
STRONG_NEGATIVE = ["fda rejected", "bankruptcy", "fraud", "sec probe", "delisted", "crash"]


# ─── Kural tabanlı sentiment ─────────────────────────────────────────────────

def score_text_rule_based(text: str) -> float:
    """
    Anahtar kelime tabanlı hızlı sentiment skoru.
    Returns: -1.0 ile +1.0 arası float
    """
    if not text:
        return 0.0

    text_lower = text.lower()
    score = 0.0
    count = 0

    # Güçlü pozitif/negatif önce kontrol et (2x ağırlık)
    for kw in STRONG_POSITIVE:
        if kw in text_lower:
            score += 2.0
            count += 2

    for kw in STRONG_NEGATIVE:
        if kw in text_lower:
            score -= 2.0
            count += 2

    # Normal anahtar kelimeler
    for kw in POSITIVE_KEYWORDS:
        if kw in text_lower:
            score += 1.0
            count += 1

    for kw in NEGATIVE_KEYWORDS:
        if kw in text_lower:
            score -= 1.0
            count += 1

    if count == 0:
        return 0.0

    # -1 ile +1 arasına normalize et
    raw = score / count
    return round(max(-1.0, min(1.0, raw)), 3)


def get_sentiment_label(score: float) -> tuple[str, str]:
    """
    Skor → (etiket, renk) dönüştür.
    """
    if score >= 0.5:
        return "Çok Pozitif", "#00c48c"
    elif score >= 0.15:
        return "Pozitif", "#4fc3f7"
    elif score >= -0.15:
        return "Nötr", "#8a9ab0"
    elif score >= -0.5:
        return "Negatif", "#ffb300"
    else:
        return "Çok Negatif", "#e74c3c"


# ─── Hisse haberleri toplu sentiment ─────────────────────────────────────────

def score_articles(articles: list[dict]) -> dict:
    """
    Haber listesi için toplu sentiment skoru hesapla.

    Returns:
    {
      "avg_score":     float (-1 ile +1),
      "label":         str,
      "color":         str,
      "positive_count": int,
      "negative_count": int,
      "neutral_count":  int,
      "article_scores": [(title, score, label), ...]
    }
    """
    if not articles:
        return {
            "avg_score": 0.0, "label": "Veri Yok", "color": "#8a9ab0",
            "positive_count": 0, "negative_count": 0, "neutral_count": 0,
            "article_scores": [],
        }

    article_scores = []
    total = 0.0

    for art in articles:
        title   = art.get("title", "")
        summary = art.get("summary", "")
        combined = f"{title} {summary}"

        score = score_text_rule_based(combined)
        label, color = get_sentiment_label(score)
        article_scores.append((title[:80], score, label, color))
        total += score

    avg = total / len(articles)
    avg = round(max(-1.0, min(1.0, avg)), 3)
    label, color = get_sentiment_label(avg)

    pos = sum(1 for _, s, _, _ in article_scores if s > 0.15)
    neg = sum(1 for _, s, _, _ in article_scores if s < -0.15)
    neu = len(article_scores) - pos - neg

    return {
        "avg_score":      avg,
        "label":          label,
        "color":          color,
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count":  neu,
        "article_scores": article_scores,
    }


# ─── Radar entegrasyonu ───────────────────────────────────────────────────────

def get_sentiment_bonus(articles: list[dict]) -> float:
    """
    Radar puanına eklenecek sentiment bonusu (-10 ile +10 arası).
    Pozitif haberler bonus, negatif haberler ceza verir.
    """
    result = score_articles(articles)
    avg    = result["avg_score"]

    # Doğrusal ölçekleme: -1.0 → -10, 0 → 0, +1.0 → +10
    bonus = round(avg * 10, 1)
    return bonus


def format_sentiment_badge(score: float) -> str:
    """
    HTML badge formatında sentiment göster.
    """
    label, color = get_sentiment_label(score)
    return (
        f'<span style="background:{color}22;color:{color};'
        f'border:1px solid {color}44;padding:1px 7px;'
        f'border-radius:10px;font-size:11px;font-weight:600;">'
        f'{label} ({score:+.2f})</span>'
    )
