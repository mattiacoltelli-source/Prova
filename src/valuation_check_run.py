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

from .data_sources import fundamentals


def check(tickers: list[str]) -> dict:
    results = {}
    for ticker in tickers:
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
