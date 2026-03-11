# news_fetcher.py — News retrieval (NewsAPI + RSS fallback) with noise filter
#
# Strategy:
#   1. Try NewsAPI "everything" endpoint (requires paid plan for full history).
#   2. Fall back to curated RSS feeds (always free) if NewsAPI fails or quota
#      is exhausted.
#   3. Apply signal keyword filter + blocked domain filter from utils.py.

import os
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
import feedparser

from utils import is_signal_news, is_blocked_domain, today_minus

logger = logging.getLogger(__name__)

NEWS_BASE   = "https://newsapi.org/v2/everything"
_SESSION    = requests.Session()
_SESSION.headers.update({"User-Agent": "StockDashboard/1.0"})

# Curated RSS sources per ticker (supplementary / fallback)
RSS_FEEDS: list[str] = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    "https://www.marketwatch.com/rss/realtimeheadlines",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.bloomberg.com/markets/news.rss",
]


# ---------------------------------------------------------------------------
# NewsAPI
# ---------------------------------------------------------------------------

def _newsapi_fetch(ticker: str, company: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch up to 10 articles from NewsAPI for a ticker + company name combo."""
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        logger.warning("NEWS_API_KEY not set; skipping NewsAPI.")
        return []

    query = f'"{ticker}" OR "{company}"'
    params = {
        "q":        query,
        "from":     from_date,
        "to":       to_date,
        "language": "en",
        "sortBy":   "relevancy",
        "pageSize": 10,
        "apiKey":   api_key,
    }
    try:
        resp = _SESSION.get(NEWS_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            logger.warning("NewsAPI returned status=%s: %s", data.get("status"), data.get("message"))
            return []
        return data.get("articles", [])
    except Exception as exc:
        logger.warning("NewsAPI request failed for %s: %s", ticker, exc)
        return []


def _parse_newsapi_article(article: dict) -> dict:
    return {
        "title":       article.get("title", ""),
        "description": article.get("description", "") or "",
        "url":         article.get("url", ""),
        "source":      (article.get("source") or {}).get("name", ""),
        "published":   article.get("publishedAt", ""),
        "content":     (article.get("content", "") or "")[:500],
    }


# ---------------------------------------------------------------------------
# RSS fallback
# ---------------------------------------------------------------------------

def _rss_fetch(ticker: str) -> list[dict]:
    """Parse the Yahoo Finance RSS feed for the given ticker."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(url)
        results = []
        for entry in feed.entries[:15]:
            results.append({
                "title":       entry.get("title", ""),
                "description": entry.get("summary", "") or "",
                "url":         entry.get("link", ""),
                "source":      "Yahoo Finance RSS",
                "published":   entry.get("published", ""),
                "content":     "",
            })
        return results
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", ticker, exc)
        return []


# ---------------------------------------------------------------------------
# Noise filter
# ---------------------------------------------------------------------------

def _apply_filters(articles: list[dict]) -> list[dict]:
    """
    Keep only articles that:
      - Are NOT from a blocked (Tier-3) domain
      - Contain at least one signal keyword
    """
    filtered = []
    for art in articles:
        url   = art.get("url", "")
        title = art.get("title", "")
        desc  = art.get("description", "")

        if is_blocked_domain(url):
            continue
        if not is_signal_news(title, desc):
            continue
        filtered.append(art)
    return filtered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_news_for_ticker(
    ticker: str,
    company: str = "",
    days_back: int = 7,
    apply_filter: bool = True,
) -> list[dict]:
    """
    Fetch and filter news for a single ticker.

    Returns a list of article dicts (max ~10 per ticker after filtering).
    """
    from_date = today_minus(days_back)
    to_date   = today_minus(0)

    # 1. Try NewsAPI
    articles = _newsapi_fetch(ticker, company, from_date, to_date)

    # 2. Fallback to RSS if NewsAPI returned nothing
    if not articles:
        logger.info("Falling back to RSS for %s", ticker)
        articles = _rss_fetch(ticker)

    # 3. Apply noise filter
    if apply_filter:
        filtered = _apply_filters(articles)
        # If filter removes everything, return raw articles with a flag
        if not filtered and articles:
            logger.info(
                "All %d articles for %s were filtered out; returning raw.",
                len(articles), ticker
            )
            return articles[:5]
        return filtered

    return articles


def fetch_news_batch(
    tickers_meta: list[dict],
    days_back: int = 7,
    delay: float = 0.5,
) -> dict[str, list[dict]]:
    """
    Fetch news for multiple tickers.

    Parameters
    ----------
    tickers_meta : list of dicts with 'ticker' and 'companyName' keys
    days_back    : look-back window
    delay        : seconds between API calls to avoid rate limiting

    Returns
    -------
    dict mapping ticker → list of filtered article dicts
    """
    news_map: dict[str, list[dict]] = {}
    for meta in tickers_meta:
        ticker  = meta.get("ticker", "")
        company = meta.get("companyName", "")
        if not ticker:
            continue
        news_map[ticker] = fetch_news_for_ticker(ticker, company, days_back)
        time.sleep(delay)
    return news_map


def format_news_for_prompt(articles: list[dict], max_articles: int = 5) -> str:
    """
    Format a list of articles into a concise string suitable for an LLM prompt.
    Keeps only the most relevant fields to stay within token budgets.
    """
    lines = []
    for i, art in enumerate(articles[:max_articles], 1):
        title  = art.get("title", "")
        source = art.get("source", "")
        desc   = (art.get("description", "") or "")[:200]
        pub    = art.get("published", "")
        lines.append(
            f"[{i}] [{source}] ({pub[:10]}) {title}\n    ↳ {desc}"
        )
    return "\n".join(lines) if lines else "No filtered news available."
