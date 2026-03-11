# claude_analyzer.py — Anthropic Claude API integration
#
# Sends enriched stock data + filtered news to Claude and parses the
# mandatory JSON response into a structured Python dict.

import os
import json
import logging
import re
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Sen acımasız ve tamamen objektif bir Kantitatif Analistsin.
Duygusal yorum yapma. Sadece verilerle konuş.

PUANLAMA KURALLARI:
- Eğer hisse A Tipi ise nakit akışını ve tekel gücünü artıran haberlere
  (ihale, sözleşme, ortaklık, hükümet sözleşmesi) yüksek puan ver (75-100).
- Eğer B Tipi ise yıkıcı inovasyon, patent, FDA/FAA onayı ve içeriden
  hisse alımlarına (Form 4) yüksek puan ver (70-95).
- Clickbait, spekülatif blog yazıları ve belirsiz makro yorumlar
  acımadan düşük puanla (0-50).
- Makro riskler (faiz artışı, jeopolitik, ambargo) skoru aşağı çeker.
- Nötr ya da olumsuz haberler varsa skoru düşür.

ÇIKTI KURALI (KESİNLİKLE UYULACAK):
Yanıtın SADECE ve SADECE aşağıdaki JSON formatında olmalıdır.
JSON dışında hiçbir şey yazma; açıklama, markdown veya ```json fence kullanma.

{
  "hisse_sembolu": "TICKER",
  "kategori": "A Tipi veya B Tipi",
  "nihai_guven_skoru": <0-100 arası tam sayı>,
  "analiz_ozeti": "<haber ve makro katalizörlerin net, tek cümlelik yorumu>",
  "kritik_riskler": {
    "global_makro": "<dışsal riskler: faiz, jeopolitik, ambargo vb.>",
    "finansal_sirket_ozel": "<içsel riskler: borçluluk, Ar-Ge yükü vb.>"
  },
  "tavsiye": "<Ağırlık Artır | Tut | Azalt>"
}"""


def _build_user_message(stock: dict, news_text: str) -> str:
    """Construct the user-turn message with all relevant stock context."""

    mkt_cap_b = (stock.get("mktCap", 0) or 0) / 1e9
    revenue_m = (stock.get("revenue", 0) or 0) / 1e6
    fcf_m     = (stock.get("freeCashFlow", 0) or 0) / 1e6
    rd_m      = (stock.get("researchAndDevelopmentExpenses", 0) or 0) / 1e6

    return f"""
ANALİZ EDİLECEK HİSSE: {stock.get("ticker", "N/A")}
Şirket Adı   : {stock.get("companyName", "N/A")}
Sektör       : {stock.get("sector", "N/A")} — {stock.get("industry", "N/A")}
Kategori     : {stock.get("kategori", "Bilinmiyor")}
Fiyat        : ${stock.get("price", 0):.2f}  ({stock.get("change_pct", 0):+.2f}%)
Piyasa Değeri: ${mkt_cap_b:.2f}B
Beta         : {stock.get("beta", 0):.2f}
Gelir        : ${revenue_m:.1f}M
Serbest N.A. : ${fcf_m:.1f}M
Ar-Ge Gideri : ${rd_m:.1f}M
P/E Oranı    : {stock.get("peRatio", 0):.1f}
Borç/Özsermaye: {stock.get("debtToEquity", 0):.2f}
ROIC         : {stock.get("roic", 0):.2%}
---
ŞİRKET AÇIKLAMASI (özet):
{stock.get("description", "Bilgi yok.")[:300]}
---
FILTRELENMIŞ SON HABERLER (son 7 gün):
{news_text}
---
Yukarıdaki verilere ve haberlere dayanarak JSON formatında analiz yap.
""".strip()


# ---------------------------------------------------------------------------
# Core analyser
# ---------------------------------------------------------------------------

def analyse_stock(stock: dict, news_text: str, model: str = "claude-opus-4-5") -> dict | None:
    """
    Send stock data + news to Claude and return parsed JSON dict.

    Returns None if the API call fails or JSON cannot be parsed.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set.")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    user_message = _build_user_message(stock, news_text)

    try:
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = message.content[0].text if message.content else ""
        return _parse_claude_json(raw_text, fallback_ticker=stock.get("ticker", ""))

    except anthropic.APIConnectionError as exc:
        logger.error("Claude connection error for %s: %s", stock.get("ticker"), exc)
    except anthropic.RateLimitError as exc:
        logger.error("Claude rate limit hit for %s: %s", stock.get("ticker"), exc)
    except anthropic.APIStatusError as exc:
        logger.error("Claude API status error for %s: %s %s", stock.get("ticker"), exc.status_code, exc.message)
    except Exception as exc:
        logger.error("Unexpected error analysing %s: %s", stock.get("ticker"), exc)

    return None


def _parse_claude_json(raw: str, fallback_ticker: str = "") -> dict | None:
    """
    Robustly parse Claude's raw text into a validated dict.
    Handles cases where the model accidentally wraps JSON in markdown fences.
    """
    # Strip markdown fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object with regex as last resort
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            logger.error("Could not parse Claude JSON for %s. Raw: %s", fallback_ticker, raw[:200])
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            logger.error("JSON extraction failed for %s.", fallback_ticker)
            return None

    # Validate and coerce required fields
    if not isinstance(data, dict):
        return None

    data.setdefault("hisse_sembolu",      fallback_ticker)
    data.setdefault("kategori",           "Bilinmiyor")
    data.setdefault("nihai_guven_skoru",  0)
    data.setdefault("analiz_ozeti",       "Analiz mevcut değil.")
    data.setdefault("kritik_riskler",     {
        "global_makro":          "N/A",
        "finansal_sirket_ozel":  "N/A",
    })
    data.setdefault("tavsiye",            "Tut")

    # Clamp score to 0-100
    try:
        data["nihai_guven_skoru"] = max(0, min(100, int(data["nihai_guven_skoru"])))
    except (ValueError, TypeError):
        data["nihai_guven_skoru"] = 0

    return data


# ---------------------------------------------------------------------------
# Batch analyser
# ---------------------------------------------------------------------------

def analyse_batch(
    stocks: list[dict],
    news_map: dict[str, list[dict]],
    model: str = "claude-opus-4-5",
    progress_callback=None,
) -> list[dict]:
    """
    Analyse a batch of enriched stock dicts.

    Parameters
    ----------
    stocks            : list of enriched stock dicts (from data_fetcher)
    news_map          : dict ticker → list[article dict]
    model             : Claude model ID
    progress_callback : optional callable(ticker, index, total)

    Returns
    -------
    list of Claude result dicts, sorted by nihai_guven_skoru descending
    """
    from news_fetcher import format_news_for_prompt

    results = []
    total   = len(stocks)

    for idx, stock in enumerate(stocks):
        ticker     = stock.get("ticker", "")
        articles   = news_map.get(ticker, [])
        news_text  = format_news_for_prompt(articles)

        if progress_callback:
            progress_callback(ticker, idx + 1, total)

        result = analyse_stock(stock, news_text, model=model)
        if result:
            # Attach original stock metadata for display purposes
            result["_stock_meta"] = stock
            results.append(result)

    results.sort(key=lambda r: r.get("nihai_guven_skoru", 0), reverse=True)
    return results
