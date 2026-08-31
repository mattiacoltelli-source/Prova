import pytest
from src.data_sources.sentiment import (
    analyze_headline_sentiment,
    compute_sentiment_score,
)

def test_analyze_headline_sentiment():
    headline_bull = "NVIDIA shares surge and beat earnings expectations with strong profit growth"
    score_bull = analyze_headline_sentiment(headline_bull)
    assert score_bull > 0

    headline_bear = "Apple shares drop and slump after lawsuit and earnings miss"
    score_bear = analyze_headline_sentiment(headline_bear)
    assert score_bear < 0

    headline_neutral = "Company announces routine annual general meeting date"
    score_neutral = analyze_headline_sentiment(headline_neutral)
    assert score_neutral == 0.0

def test_compute_sentiment_score():
    news_items = [
        {"headline": "NVIDIA stock surges to new record high", "source": "finnhub", "published_at": "2025-01-01T00:00:00Z", "sentiment": None},
        {"headline": "Analysts upgrade tech sector forecast", "source": "finnhub", "published_at": "2025-01-01T00:00:00Z", "sentiment": None},
        {"headline": "Market stays steady", "source": "gdelt", "published_at": "2025-01-01T00:00:00Z", "sentiment": None},
    ]

    result = compute_sentiment_score("NVDA", news_items)
    assert result["ticker"] == "NVDA"
    assert result["news_count"] == 3
    assert result["sentiment_score"] > 0
    assert "Bullish" in result["sentiment_label"]
    assert result["bullish_signals"] >= 1

def test_compute_sentiment_score_empty():
    result = compute_sentiment_score("SPY", [])
    assert result["news_count"] == 0
    assert result["sentiment_score"] == 0.0
    assert result["sentiment_label"] == "Neutrale"
