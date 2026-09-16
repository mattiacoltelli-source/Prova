"""News recenti sull'asset, con fallback a cascata.

Primaria: Finnhub company-news. Fallback: Alpha Vantage News & Sentiment,
poi GDELT (nessuna key richiesta).

In più (non un fallback della cascata sopra, ma unita ai suoi risultati):
RSS ufficiale del feed newsroom aziendale, dove esiste (RSS_FEEDS) — cattura
comunicati diretti dalla fonte, spesso prima che gli aggregatori di mercato
li indicizzino. Verificato manualmente il 2026-09-17 quali aziende
espongono davvero un feed pubblico raggiungibile (AAPL/MSFT/NVDA); THK e
Harmonic Drive Systems non ne hanno uno accessibile, quindi restano solo
sulla cascata sopra.

Nota sul feed MSFT: osservato intermittente dietro protezione Cloudflare
(risposta 200 con Content-Type RSS corretto, ma corpo che mescola contenuto
del feed con un frammento HTML del footer anti-bot di Cloudflare, che rompe
il parsing XML) — non un bug del parser, un blocco lato server sull'IP di
chi chiama. _rss_news lo gestisce già come ogni altro fallimento: eccezione
catturata, si torna silenziosamente alla sola cascata per quell'asset, mai
un crash. Lasciato comunque nella lista: potrebbe funzionare da IP diversi
(es. i runner di GitHub Actions) anche quando fallisce da questo sandbox."""
from __future__ import annotations

import datetime as dt
import os
from typing import TypedDict

import feedparser

from . import http

TIMEOUT = 15

RSS_FEEDS = {
    "AAPL": "https://www.apple.com/newsroom/rss-feed.rss",
    "MSFT": "https://news.microsoft.com/feed/",
    "NVDA": "https://nvidianews.nvidia.com/rss.xml",
}


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


def _rss_news(feed_url: str, lookback_days: int, limit: int) -> list[NewsItem]:
    # feedparser.parse(url) farebbe il proprio fetch di rete (urllib),
    # bypassando http.get (retry su singolo blip di rete, stessa gestione
    # del proxy delle altre fonti in questo modulo) — si passa invece il
    # contenuto già scaricato, coerente con _finnhub_news/_alphavantage_news.
    resp = http.get(feed_url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0 (predictive-agent research script)"})
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise NewsUnavailableError(f"RSS: feed non valido ({feed_url})")

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    out: list[NewsItem] = []
    for entry in parsed.entries:
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if struct:
            published_dt = dt.datetime(*struct[:6], tzinfo=dt.timezone.utc)
            if published_dt < cutoff:
                continue
            published_at = published_dt.isoformat()
        else:
            published_at = entry.get("published") or entry.get("updated") or ""
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        out.append({"headline": title, "source": feed_url, "published_at": published_at, "sentiment": None})
        if len(out) >= limit:
            break
    if not out:
        raise NewsUnavailableError(f"RSS: nessuna news recente nel feed ({feed_url})")
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
    (le news sono un segnale opzionale, non bloccante per la previsione).

    RSS_FEEDS non è un ulteriore livello della cascata sopra (Finnhub ->
    Alpha Vantage -> GDELT, si ferma al primo che risponde): è unita ai
    risultati della cascata quando esiste un feed per questo ticker, perché
    è un comunicato ufficiale diretto dalla fonte, non un sostituto delle
    news di mercato/sentiment che la cascata fornisce."""
    cascade_items: list[NewsItem] = []
    for fn in (_finnhub_news, _alphavantage_news, _gdelt_news):
        try:
            cascade_items = fn(ticker, lookback_days, limit)
            break
        except Exception:  # noqa: BLE001 - passa alla fonte successiva
            continue

    feed_url = RSS_FEEDS.get(ticker)
    if not feed_url:
        return cascade_items

    try:
        rss_items = _rss_news(feed_url, lookback_days, limit)
    except Exception:  # noqa: BLE001 - RSS è un segnale opzionale, mai bloccante
        return cascade_items

    # RSS prima (fonte ufficiale/primaria), poi il resto della cascata;
    # dedup per headline — la stessa notizia può comparire sia sul feed
    # ufficiale sia su un aggregatore di mercato.
    seen: set[str] = set()
    merged: list[NewsItem] = []
    for item in rss_items + cascade_items:
        key = item["headline"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(item)
    return merged[:limit]
