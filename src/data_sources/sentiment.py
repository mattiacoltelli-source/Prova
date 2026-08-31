"""Calcolo del News & Social Sentiment Score (-1.0 a +1.0) per un asset.

Combina punteggi di sentiment forniti direttamente dalle fonti news (es. Alpha Vantage)
o calcola una polarità euristica/NLP sulle notizie e sui titoli recenti se il punteggio nativo non è presente.
"""
from __future__ import annotations

import re
from typing import TypedDict
from .news import NewsItem, fetch_recent_news

# Parole chiave positive e negative ad alto impatto per mercati ed equity
BULLISH_KEYWORDS = [
    r"\bsurge\b", r"\bjump\b", r"\brally\b", r"\bbeat\b", r"\boutperform\b",
    r"\bgrowth\b", r"\bprofit\b", r"\bupgrade\b", r"\bstrong\b", r"\brecord\b",
    r"\bbullish\b", r"\bexpansion\b", r"\bgain\b", r"\bhighs?\b", r"\bbreakout\b"
]

BEARISH_KEYWORDS = [
    r"\bplunge\b", r"\bdrop\b", r"\bslump\b", r"\bmiss\b", r"\bunderperform\b",
    r"\bloss\b", r"\bdown-?grade\b", r"\bweak\b", r"\blawsuit\b", r"\bearnings miss\b",
    r"\bbearish\b", r"\brecession\b", r"\bfall\b", r"\blows?\b", r"\bcrash\b", r"\bcrisis\b"
]

class SentimentAnalysisResult(TypedDict):
    ticker: str
    sentiment_score: float  # -1.0 a +1.0
    sentiment_label: str    # Bullish, Neutral, Bearish
    news_count: int
    bullish_signals: int
    bearish_signals: int


def analyze_headline_sentiment(headline: str) -> float:
    """Calcola la polarità di una singola notizia tra -1.0 e +1.0."""
    text = headline.lower()
    bull_count = sum(1 for kw in BULLISH_KEYWORDS if re.search(kw, text))
    bear_count = sum(1 for kw in BEARISH_KEYWORDS if re.search(kw, text))

    total = bull_count + bear_count
    if total == 0:
        return 0.0
    return (bull_count - bear_count) / total


def compute_sentiment_score(ticker: str, news_items: list[NewsItem] | None = None) -> SentimentAnalysisResult:
    """Calcola lo score ponderato di sentiment (-1.0 a +1.0) da notizie e social sentiment."""
    if news_items is None:
        news_items = fetch_recent_news(ticker, lookback_days=5, limit=10)

    if not news_items:
        return {
            "ticker": ticker,
            "sentiment_score": 0.0,
            "sentiment_label": "Neutrale",
            "news_count": 0,
            "bullish_signals": 0,
            "bearish_signals": 0,
        }

    scores: list[float] = []
    bullish_count = 0
    bearish_count = 0

    for item in news_items:
        # Se la fonte fornisce già un sentiment nativo tra -1 e +1
        if item.get("sentiment") is not None:
            score = float(item["sentiment"])
        else:
            score = analyze_headline_sentiment(item.get("headline", ""))

        scores.append(score)
        if score > 0.1:
            bullish_count += 1
        elif score < -0.1:
            bearish_count += 1

    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_score = max(-1.0, min(1.0, round(avg_score, 2)))

    if avg_score >= 0.15:
        label = "Bullish (Positivo)"
    elif avg_score <= -0.15:
        label = "Bearish (Negativo)"
    else:
        label = "Neutrale"

    return {
        "ticker": ticker,
        "sentiment_score": avg_score,
        "sentiment_label": label,
        "news_count": len(news_items),
        "bullish_signals": bullish_count,
        "bearish_signals": bearish_count,
    }
