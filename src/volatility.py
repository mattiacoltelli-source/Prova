"""Soglie UP/DOWN/FLAT basate sull'Average True Range (ATR) dell'asset.

La soglia viene calcolata al momento della previsione e va sempre
riutilizzata (mai ricalcolata) in fase di valutazione, per evitare
look-ahead bias nella misura di accuratezza.
"""
from __future__ import annotations

from . import config, technicals
from .data_sources.prices import DailyBar


def compute_threshold_pct(bars: list[DailyBar], horizon: config.Horizon) -> float:
    """Ritorna la banda FLAT in punti percentuali per l'orizzonte dato,
    scalando l'ATR% a 14 giorni (già usato come indicatore tecnico, stesso
    dato, nessun calcolo duplicato) per la radice dei giorni di trading
    dell'orizzonte."""
    atr_pct = technicals.compute_atr_pct(bars)
    if atr_pct is None:
        raise ValueError("Storico insufficiente per calcolare la volatilità (ATR)")
    scaled = atr_pct * (horizon.trading_days ** 0.5)
    return round(config.VOLATILITY_K * scaled, 4)


def classify_change(change_pct: float, threshold_pct: float) -> str:
    if change_pct > threshold_pct:
        return "UP"
    if change_pct < -threshold_pct:
        return "DOWN"
    return "FLAT"
