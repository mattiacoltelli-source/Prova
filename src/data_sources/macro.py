"""Snapshot di indicatori macro/di mercato da FRED (API ufficiale gratuita)."""
from __future__ import annotations

import os

import requests

TIMEOUT = 15

# id serie FRED -> etichetta leggibile
SERIES = {
    "DGS10": "treasury_yield_10y",
    "DGS2": "treasury_yield_2y",
    "FEDFUNDS": "fed_funds_rate",
    "CPIAUCSL": "cpi",
    "UNRATE": "unemployment_rate",
    "VIXCLS": "vix",
    "DTWEXBGS": "dollar_index",
}


class MacroUnavailableError(RuntimeError):
    pass


def _fetch_series_latest(series_id: str, api_key: str) -> dict | None:
    resp = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs or obs[0].get("value") in (None, "."):
        return None
    return {"value": float(obs[0]["value"]), "date": obs[0]["date"]}


def fetch_macro_snapshot() -> dict:
    """Ritorna gli indicatori macro disponibili; salta silenziosamente
    quelli che falliscono (segnale opzionale, non bloccante)."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise MacroUnavailableError("FRED_API_KEY non impostata")
    snapshot: dict = {}
    for series_id, label in SERIES.items():
        try:
            value = _fetch_series_latest(series_id, key)
            if value is not None:
                snapshot[label] = value
        except Exception:  # noqa: BLE001 - salta la singola serie
            continue

    # Spread 10Y-2Y: negativo = curva invertita, segnale classico di
    # rallentamento/recessione attesa. Derivato, non una serie FRED a sé.
    if "treasury_yield_10y" in snapshot and "treasury_yield_2y" in snapshot:
        spread = snapshot["treasury_yield_10y"]["value"] - snapshot["treasury_yield_2y"]["value"]
        snapshot["yield_curve_10y_2y"] = {
            "value": round(spread, 3),
            "date": snapshot["treasury_yield_10y"]["date"],
        }

    return snapshot
