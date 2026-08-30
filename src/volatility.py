"""Soglie UP/DOWN/FLAT basate sulla volatilità storica dell'asset.

La soglia viene calcolata al momento della previsione e va sempre
riutilizzata (mai ricalcolata) in fase di valutazione, per evitare
look-ahead bias nella misura di accuratezza.
"""
from __future__ import annotations

import statistics

from . import config
from .data_sources.prices import DailyBar


def daily_returns_pct(bars: list[DailyBar]) -> list[float]:
    closes = [b["close"] for b in bars]
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def compute_threshold_pct(bars: list[DailyBar], horizon: config.Horizon) -> float:
    """Ritorna la banda FLAT in punti percentuali per l'orizzonte dato."""
    window = bars[-(config.VOLATILITY_LOOKBACK_DAYS + 1) :]
    returns = daily_returns_pct(window)
    if len(returns) < 5:
        raise ValueError("Storico insufficiente per calcolare la volatilità")
    daily_std = statistics.pstdev(returns)
    scaled = daily_std * (horizon.trading_days ** 0.5)
    return round(config.VOLATILITY_K * scaled, 4)


def classify_change(change_pct: float, threshold_pct: float) -> str:
    if change_pct > threshold_pct:
        return "UP"
    if change_pct < -threshold_pct:
        return "DOWN"
    return "FLAT"
