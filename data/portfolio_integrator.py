# portfolio_integrator.py — Çok Varlıklı Portföy Bütünleştirici
#
# Görev: Tüm varlık sınıflarını (ABD hisse, kripto, emtia, TEFAS) dolar
# bazında birleştirip tek bir bütünleşik portföy görünümü üretmek.
#
# Bu modül Faz 4 (direktör) için ham portföy verisini hazırlar.
# Direktör bu çıktıyı alır ve "toplam servet ne durumda?" sorusunu yanıtlar.

import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ─── Varlık Sınıfı Etiketleri ────────────────────────────────────────────────

ASSET_CLASS_LABELS = {
    "us_equity": "ABD Hisse",
    "crypto":    "Kripto",
    "commodity": "Emtia",
    "tefas":     "TEFAS",
    "other":     "Diğer",
}


# ─── USD/TRY Kuru ────────────────────────────────────────────────────────────

def get_usd_try() -> float:
    """Güncel USD/TRY kurunu çek."""
    try:
        import yfinance as yf
        rate = float(yf.Ticker("USDTRY=X").fast_info.last_price or 32.0)
        return rate if rate > 0 else 32.0
    except Exception:
        return 32.0


# ─── Tüm Pozisyonları Dolar Bazında Değerle ──────────────────────────────────

def enrich_all_positions(positions: list, usd_try: float = None) -> list:
    """
    Portföydeki tüm pozisyonları (her varlık sınıfından) dolar bazında değerle.
    
    TEFAS pozisyonları TL fiyatla gelir → USD'ye çevrilir.
    Kripto ve emtia yfinance'ten çekilir.
    ABD hisseleri normal yfinance akışıyla gelir.
    
    Her pozisyon şu alanlarla döner:
    - current_price_usd: güncel dolar fiyatı
    - value_usd: toplam değer (dolar)
    - pnl_usd: kâr/zarar (dolar)
    - pnl_pct: kâr/zarar yüzdesi
    - weight_pct: portföy içi ağırlık (sonradan hesaplanır)
    """
    if usd_try is None:
        usd_try = get_usd_try()

    import yfinance as yf
    enriched = []

    for pos in positions:
        ticker     = pos.get("ticker", "")
        shares     = float(pos.get("shares", 0))
        avg_cost   = float(pos.get("avg_cost", 0))
        asset_class= pos.get("asset_class", "us_equity")
        currency   = pos.get("currency", "USD")

        if shares <= 0:
            continue

        # Mevcut fiyatı çek
        current_price_usd = 0.0
        current_price_raw = 0.0  # Orijinal para birimi

        try:
            if asset_class == "tefas":
                # TEFAS: TL fiyat → USD
                from turkey_fetcher import fetch_tefas_fund
                fund = fetch_tefas_fund(ticker)
                if fund and fund.get("price", 0) > 0:
                    current_price_raw = float(fund["price"])
                    current_price_usd = current_price_raw / usd_try
                else:
                    current_price_raw = avg_cost
                    current_price_usd = avg_cost / usd_try
            else:
                # yfinance: kripto, emtia, ABD hisse hepsi USD
                fi = yf.Ticker(ticker).fast_info
                current_price_raw = float(getattr(fi, "last_price", 0) or avg_cost)
                if currency == "TRY":
                    current_price_usd = current_price_raw / usd_try
                else:
                    current_price_usd = current_price_raw

        except Exception as e:
            logger.debug("Price fetch failed for %s: %s", ticker, e)
            current_price_raw = avg_cost
            current_price_usd = avg_cost / usd_try if currency == "TRY" else avg_cost

        # Maliyet bazını USD'ye çevir
        avg_cost_usd = avg_cost / usd_try if currency == "TRY" else avg_cost

        # Hesaplamalar
        value_usd   = shares * current_price_usd
        cost_usd    = shares * avg_cost_usd
        pnl_usd     = value_usd - cost_usd
        pnl_pct     = (pnl_usd / cost_usd * 100) if cost_usd > 0 else 0

        enriched.append({
            **pos,
            "current_price_usd": round(current_price_usd, 6),
            "current_price_raw": round(current_price_raw, 6),
            "value_usd":         round(value_usd, 2),
            "cost_usd":          round(cost_usd,  2),
            "pnl_usd":           round(pnl_usd,   2),
            "pnl_pct":           round(pnl_pct,   2),
            "weight_pct":        0.0,  # Sonradan doldurulacak
        })

    # Ağırlıkları hesapla
    total_value = sum(p["value_usd"] for p in enriched)
    if total_value > 0:
        for p in enriched:
            p["weight_pct"] = round(p["value_usd"] / total_value * 100, 1)

    return enriched


# ─── Varlık Sınıfı Bazında Özet ──────────────────────────────────────────────

def compute_class_breakdown(enriched_positions: list, cash_usd: float) -> dict:
    """
    Varlık sınıfı bazında toplam değer, ağırlık ve P&L hesapla.
    Nakit de dahil edilir.
    """
    breakdown = {}
    total_portfolio = sum(p["value_usd"] for p in enriched_positions) + cash_usd

    for ac_key, ac_label in ASSET_CLASS_LABELS.items():
        class_positions = [p for p in enriched_positions if p.get("asset_class") == ac_key]
        if not class_positions:
            continue

        class_value = sum(p["value_usd"] for p in class_positions)
        class_cost  = sum(p["cost_usd"]  for p in class_positions)
        class_pnl   = class_value - class_cost
        class_pnl_pct = (class_pnl / class_cost * 100) if class_cost > 0 else 0

        breakdown[ac_key] = {
            "label":     ac_label,
            "value_usd": round(class_value,   2),
            "cost_usd":  round(class_cost,    2),
            "pnl_usd":   round(class_pnl,     2),
            "pnl_pct":   round(class_pnl_pct, 2),
            "weight_pct":round(class_value / total_portfolio * 100, 1) if total_portfolio > 0 else 0,
            "count":     len(class_positions),
        }

    # Nakit
    if cash_usd > 0:
        breakdown["cash"] = {
            "label":     "Nakit",
            "value_usd": round(cash_usd, 2),
            "cost_usd":  round(cash_usd, 2),
            "pnl_usd":   0,
            "pnl_pct":   0,
            "weight_pct":round(cash_usd / total_portfolio * 100, 1) if total_portfolio > 0 else 0,
            "count":     0,
        }

    return breakdown


# ─── Portföy Beta Hesabı ──────────────────────────────────────────────────────

def compute_portfolio_beta(enriched_positions: list) -> float:
    """
    Portföyün ağırlıklı ortalama beta değerini hesapla.
    Beta > 1: piyasadan daha volatil (agresif)
    Beta < 1: piyasadan daha az volatil (defansif)
    
    Kripto için beta = 1.5 (yüksek volatilite proxy)
    Emtia için beta = 0.3 (düşük korelasyon)
    TEFAS için beta = 0.6 (gelişen piyasa, kısmi korelasyon)
    """
    # Varlık sınıfı beta tahmini — yfinance'ten gerçek beta çekilemezse
    ASSET_CLASS_BETA = {
        "crypto":    1.8,
        "commodity": 0.3,
        "tefas":     0.6,
        "us_equity": None,  # yfinance'ten çekilecek
        "other":     1.0,
    }

    total_value  = sum(p["value_usd"] for p in enriched_positions)
    if total_value <= 0:
        return 1.0

    weighted_beta = 0.0

    try:
        import yfinance as yf
        for pos in enriched_positions:
            weight  = pos.get("weight_pct", 0) / 100
            ac      = pos.get("asset_class", "us_equity")
            beta_val= ASSET_CLASS_BETA.get(ac)

            if beta_val is None and ac == "us_equity":
                # yfinance'ten gerçek beta çek
                try:
                    info     = yf.Ticker(pos["ticker"]).info
                    beta_val = float(info.get("beta") or 1.0)
                except Exception:
                    beta_val = 1.0

            if beta_val is None:
                beta_val = 1.0

            weighted_beta += weight * beta_val
    except Exception as e:
        logger.debug("Beta calculation failed: %s", e)
        return 1.0

    return round(weighted_beta, 2)


# ─── Likidite Skoru ───────────────────────────────────────────────────────────

def compute_liquidity_score(enriched_positions: list) -> dict:
    """
    Portföyün likidite skorunu hesapla.
    Kriz anında ne kadarını hızlıca nakde çevirebilirsin?
    
    Likidite seviyeleri:
    - T+0 (Anlık): BTC, ETH, büyük cap ABD hisseleri
    - T+1 (1 gün): Küçük cap ABD hisseleri, altcoinler
    - T+3 (3 gün): Emtia ETF'leri
    - T+5+ (Yavaş): TEFAS fonları (NAV bazlı, 1-2 gün gecikme)
    """
    total_value = sum(p["value_usd"] for p in enriched_positions)
    if total_value <= 0:
        return {"score": 100, "note": "Portföy boş"}

    liquidity_map = {
        "us_equity": {"tier": "T+0", "days": 0,  "score": 100},
        "crypto":    {"tier": "T+0", "days": 0,  "score": 95},
        "commodity": {"tier": "T+1", "days": 1,  "score": 80},
        "tefas":     {"tier": "T+2", "days": 2,  "score": 60},
        "other":     {"tier": "T+1", "days": 1,  "score": 75},
    }

    weighted_score = 0.0
    tier_breakdown = {"T+0": 0.0, "T+1": 0.0, "T+2": 0.0, "T+5+": 0.0}

    for pos in enriched_positions:
        weight = pos.get("weight_pct", 0) / 100
        ac     = pos.get("asset_class", "us_equity")
        liq    = liquidity_map.get(ac, liquidity_map["other"])

        weighted_score += weight * liq["score"]
        tier = liq["tier"]
        tier_breakdown[tier] = tier_breakdown.get(tier, 0.0) + weight * 100

    score = round(weighted_score, 1)

    if score >= 90:
        note = f"Yüksek likidite (%{score:.0f}) — portföyün büyük bölümü anlık nakde çevrilebilir."
    elif score >= 70:
        note = f"Orta likidite (%{score:.0f}) — 1-2 gün içinde büyük bölüm nakde çevrilebilir."
    else:
        note = f"Düşük likidite (%{score:.0f}) — TEFAS ağırlığı yüksek, kriz anında hızlı çıkış sınırlı."

    return {
        "score":     score,
        "note":      note,
        "breakdown": {k: round(v, 1) for k, v in tier_breakdown.items() if v > 0},
    }


# ─── Dinamik Yıl Sonu Hedefi ──────────────────────────────────────────────────

def compute_dynamic_target(
    total_value_usd: float,
    cash_usd:        float,
    year_target_pct: float = 40.0,
    year_start_value: float = 0.0,
) -> dict:
    """
    Yıl sonu hedefine ne kadar yakınsın ve ne kadar risk almanı gerektiriyor?
    
    3 aylık periyodik güncelleme mantığı:
    Gerçekçi hedef = piyasa koşullarına göre revize edilir.
    Fırsatçı hedef = piyasa %60 fırsat sunuyorsa o da yakalanabilir.
    """
    now   = datetime.now()
    year_end = datetime(now.year, 12, 31)
    months_remaining = max(1, (year_end - now).days / 30)
    months_elapsed   = 12 - months_remaining

    # Yılın başındaki değeri tahmin et
    if year_start_value <= 0:
        # Bilmiyorsak mevcut değerden geriye çalış
        year_start_value = total_value_usd * 0.92  # Yaklaşık %8 büyüme varsayımı

    total_with_cash = total_value_usd + cash_usd

    # Şimdiye kadarki getiri
    current_return_pct = (
        (total_with_cash - year_start_value) / year_start_value * 100
        if year_start_value > 0 else 0
    )

    # Hedefe kalan
    remaining_pct     = year_target_pct - current_return_pct
    target_value_usd  = year_start_value * (1 + year_target_pct / 100)
    gap_usd           = target_value_usd - total_with_cash

    # Kalan sürede gerekli aylık büyüme
    required_monthly  = (
        ((target_value_usd / total_with_cash) ** (1 / months_remaining) - 1) * 100
        if months_remaining > 0 and total_with_cash > 0 else 0
    )

    # Risk değerlendirmesi
    if required_monthly <= 1.5:
        risk_level = "Düşük"
        risk_note  = f"Aylık %{required_monthly:.1f} büyüme gerekiyor — makul, temkinli strateji yeterli."
    elif required_monthly <= 3.0:
        risk_level = "Orta"
        risk_note  = f"Aylık %{required_monthly:.1f} büyüme gerekiyor — orta risk gerekli, seçici alımlar yap."
    elif required_monthly <= 5.0:
        risk_level = "Yüksek"
        risk_note  = f"Aylık %{required_monthly:.1f} büyüme gerekiyor — yüksek risk gerekli, dikkatli ol."
    else:
        risk_level = "Çok Yüksek"
        risk_note  = (f"Aylık %{required_monthly:.1f} büyüme gerekiyor — GERÇEKÇI DEĞİL. "
                     f"Hedefi %{max(current_return_pct + 10, 20):.0f}'ye revize etmeyi düşün.")

    # Üç aylık periyodik güncelleme önerisi
    quarterly_checkpoint = None
    q_month = ((now.month - 1) // 3 + 1) * 3  # Sonraki çeyrek sonu
    if q_month > 12:
        q_month = 3
        q_year  = now.year + 1
    else:
        q_year  = now.year
    quarterly_checkpoint = datetime(q_year, q_month, 28).strftime("%Y-%m-%d")

    return {
        "year_target_pct":    year_target_pct,
        "year_start_value":   round(year_start_value, 2),
        "current_value":      round(total_with_cash, 2),
        "target_value":       round(target_value_usd, 2),
        "current_return_pct": round(current_return_pct, 1),
        "remaining_pct":      round(remaining_pct, 1),
        "gap_usd":            round(gap_usd, 2),
        "months_remaining":   round(months_remaining, 1),
        "required_monthly":   round(required_monthly, 2),
        "risk_level":         risk_level,
        "risk_note":          risk_note,
        "quarterly_checkpoint": quarterly_checkpoint,
    }


# ─── Ana Bütünleştirici ───────────────────────────────────────────────────────

def build_integrated_portfolio(
    positions:        list,
    cash_usd:         float,
    year_target_pct:  float = 40.0,
    year_start_value: float = 0.0,
) -> dict:
    """
    Tüm portföy verilerini birleştir.
    Direktör için tek, kapsamlı bir portföy paketi üret.
    """
    logger.info("Bütünleşik portföy hesaplanıyor...")

    usd_try   = get_usd_try()
    enriched  = enrich_all_positions(positions, usd_try)
    total_val = sum(p["value_usd"] for p in enriched)
    total_inc_cash = total_val + cash_usd

    breakdown  = compute_class_breakdown(enriched, cash_usd)
    beta       = compute_portfolio_beta(enriched)
    liquidity  = compute_liquidity_score(enriched)
    target     = compute_dynamic_target(total_val, cash_usd, year_target_pct, year_start_value)

    # Konsantrasyon riski
    max_weight = max((p.get("weight_pct", 0) for p in enriched), default=0)
    if max_weight >= 30:
        concentration_risk = "Yüksek"
        conc_note = f"En büyük pozisyon portföyün %{max_weight:.0f}'ini oluşturuyor — yüksek konsantrasyon riski."
    elif max_weight >= 20:
        concentration_risk = "Orta"
        conc_note = f"En büyük pozisyon %{max_weight:.0f} — orta konsantrasyon."
    else:
        concentration_risk = "Düşük"
        conc_note = f"İyi dağılım — en büyük pozisyon %{max_weight:.0f}."

    # Toplam P&L
    total_pnl     = sum(p["pnl_usd"] for p in enriched)
    total_cost    = sum(p["cost_usd"] for p in enriched)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return {
        "positions":            enriched,
        "cash":                 round(cash_usd, 2),
        "usd_try":              round(usd_try, 2),
        "total_value":          round(total_val, 2),
        "total_with_cash":      round(total_inc_cash, 2),
        "total_pnl":            round(total_pnl, 2),
        "total_pnl_pct":        round(total_pnl_pct, 1),
        "class_breakdown":      breakdown,
        "beta":                 beta,
        "liquidity":            liquidity,
        "concentration_risk":   concentration_risk,
        "concentration_note":   conc_note,
        "dynamic_target":       target,
        "analytics": {
            "total_value":    round(total_val, 2),
            "total_cost":     round(total_cost, 2),
            "total_pnl":      round(total_pnl, 2),
            "total_pnl_pct":  round(total_pnl_pct, 1),
            "concentration_risk": concentration_risk,
            "top_positions": sorted(
                [{"ticker": p["ticker"], "weight": p.get("weight_pct", 0),
                  "pnl_pct": p.get("pnl_pct", 0), "asset_class": p.get("asset_class","us_equity")}
                 for p in enriched],
                key=lambda x: x["weight"], reverse=True
            )[:8],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
