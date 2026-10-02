"""Controllo cascata news ad-hoc, per verificare una chiave API appena
aggiornata senza aspettare il prossimo slot di predict.yml (che nei giorni
feriali gira una volta sola — vedi config.PREDICTION_SLOTS_ET).

    python -m src.news_check_run --tickers NVDA,MSFT,AAPL,AMD

Riusa data_sources.news.fetch_recent_news() così com'è: stessi log
diagnostici "[info] ..." già aggiunti il 2026-10-01 (commit 3f06ebe),
nessuna scrittura su data/.
"""
from __future__ import annotations

import argparse

from .data_sources import news


def check(tickers: list[str]) -> dict:
    results = {}
    for ticker in tickers:
        items = news.fetch_recent_news(ticker)
        results[ticker] = len(items)
        print(f"{ticker}: {len(items)} articoli")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True, help="Ticker separati da virgola, es. NVDA,MSFT,AAPL,AMD")
    args = parser.parse_args()
    check([t.strip().upper() for t in args.tickers.split(",") if t.strip()])
