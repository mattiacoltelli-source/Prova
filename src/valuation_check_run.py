"""Controllo valutazione una tantum per titoli non ancora tracciati da Prova.

    python -m src.valuation_check_run --tickers PWR,NVT,ETN

Riusa _alphavantage_overview() (già usata come fallback fondamentali in
fundamentals.py) per leggere P/E, crescita YoY e margine da Alpha Vantage.
Non scrive nulla su data/: è un lookup manuale per valutare se un titolo
merita di entrare nel roster, non una fonte per le previsioni.
"""
from __future__ import annotations

import argparse
import json
import time

from .data_sources import fundamentals

# Alpha Vantage free tier: 5 chiamate/minuto. Senza pausa fra un ticker e
# l'altro, la seconda/terza chiamata dello stesso run torna vuota (risposta
# 200 con corpo "rate limit", non un 429 — _alphavantage_overview la legge
# come "nessun dato utile"). Verificato dal vivo il 2026-09-18: PWR ok,
# NVT/ETN vuoti nello stesso run senza pausa.
PAUSE_SECONDS = 15


def check(tickers: list[str]) -> dict:
    results = {}
    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(PAUSE_SECONDS)
        try:
            results[ticker] = fundamentals._alphavantage_overview(ticker)["metrics"]
        except Exception as exc:  # noqa: BLE001 - un ticker fallito non blocca gli altri
            results[ticker] = {"error": str(exc)}
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", required=True, help="Lista separata da virgole, es. PWR,NVT,ETN")
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    print(json.dumps(check(tickers), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
