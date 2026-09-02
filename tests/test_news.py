"""Test unitari per src/data_sources/news.py: solo la logica pura
(average_sentiment), nessuna chiamata di rete."""
from __future__ import annotations

from src.data_sources import news


def _item(sentiment=None):
    return {"headline": "x", "source": "s", "published_at": "2026-01-01", "sentiment": sentiment}


def test_average_sentiment_valore_atteso():
    items = [_item(0.5), _item(-0.1), _item(None)]
    assert news.average_sentiment(items) == round((0.5 - 0.1) / 2, 3)


def test_average_sentiment_none_se_nessun_punteggio():
    items = [_item(None), _item(None)]
    assert news.average_sentiment(items) is None


def test_average_sentiment_none_se_lista_vuota():
    assert news.average_sentiment([]) is None
