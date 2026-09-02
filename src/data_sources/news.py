"""News recenti sull'asset, con fallback a cascata.

Primaria: Finnhub company-news. Fallback: Alpha Vantage News & Sentiment,
poi GDELT (nessuna key richiesta).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import TypedDict

from . import http

TIMEOUT = 15


class NewsUnavailableError(RuntimeError):
    pass


class NewsItem(TypedDict):
    headline: str
    source: str
    published_at: str
    sentiment: float | None  # -1..1 se disponibile, altrimenti None


def _finnhub_news(ticker: str, lookback_days: int, limit: int) -> list[NewsItem]:
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        raise NewsUnavailableError("FINNHUB_KEY non impostata")
    today = dt.date.today()
    since = today - dt.timedelta(days=lookback_days)
    resp = http.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": ticker, "from": since.isoformat(), "to": today.isoformat(), "token": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json()
    if not isinstance(items, list) or not items:
        raise NewsUnavailableError(f"Finnhub: nessuna news per {ticker}")
    out: list[NewsItem] = []
    for it in items[:limit]:
        out.append(
            {
                "headline": it.get("headline", ""),
                "source": it.get("source", "finnhub"),
                "published_at": dt.datetime.fromtimestamp(
                    it["datetime"], tz=dt.timezone.utc
                ).isoformat(),
                "sentiment": None,
            }
        )
    return out


def _alphavantage_news(ticker: str, lookback_days: int, limit: int) -> list[NewsItem]:
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        raise NewsUnavailableError("ALPHA_VANTAGE_KEY non impostata")
    resp = http.get(
        "https://www.alphavantage.co/query",
        params={"function": "NEWS_SENTIMENT", "tickers": ticker, "limit": limit, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    feed = payload.get("feed")
    if not feed:
        raise NewsUnavailableError(f"Alpha Vantage: {payload.get('Information') or payload.get('Note') or 'nessuna news'}")
    out: list[NewsItem] = []
    for it in feed[:limit]:
        score = None
        for ts in it.get("ticker_sentiment", []):
            if ts.get("ticker") == ticker:
                score = float(ts.get("ticker_sentiment_score", 0))
                break
        out.append(
            {
                "headline": it.get("title", ""),
                "source": it.get("source", "alphavantage"),
                "published_at": it.get("time_published", ""),
                "sentiment": score,
            }
        )
    return out


def _gdelt_news(ticker: str, lookback_days: int, limit: int) -> list[NewsItem]:
    resp = http.get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": ticker,
            "mode": "artlist",
            "format": "json",
            "maxrecords": limit,
            "timespan": f"{lookback_days}d",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    articles = payload.get("articles")
    if not articles:
        raise NewsUnavailableError(f"GDELT: nessuna news per {ticker}")
    out: list[NewsItem] = []
    for it in articles[:limit]:
        out.append(
            {
                "headline": it.get("title", ""),
                "source": it.get("domain", "gdelt"),
                "published_at": it.get("seendate", ""),
                "sentiment": None,
            }
        )
    return out


def average_sentiment(news_items: list[NewsItem]) -> float | None:
    """Media dei punteggi di sentiment (-1..1) delle news che ne hanno uno
    (solo Alpha Vantage lo fornisce, Finnhub/GDELT restituiscono None).
    Dato già raccolto, mai buttato via: nessuna chiamata aggiuntiva."""
    scores = [n["sentiment"] for n in news_items if n.get("sentiment") is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 3)


def fetch_recent_news(ticker: str, lookback_days: int = 7, limit: int = 8) -> list[NewsItem]:
    """Ritorna una lista di news recenti, vuota se tutte le fonti falliscono
    (le news sono un segnale opzionale, non bloccante per la previsione)."""
    for fn in (_finnhub_news, _alphavantage_news, _gdelt_news):
        try:
            return fn(ticker, lookback_days, limit)
        except Exception:  # noqa: BLE001 - passa alla fonte successiva
            continue
    return []
