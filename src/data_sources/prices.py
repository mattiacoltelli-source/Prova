"""Prezzo storico e realtime-ish (delayed), con fallback a cascata.

Primaria: endpoint pubblico Yahoo Finance (nessuna key richiesta).
Fallback: Twelve Data, poi Finnhub (solo quote: il candle storico di
Finnhub richiede un piano a pagamento).
"""
from __future__ import annotations

import datetime as dt
import os
from typing import TypedDict

import requests

YAHOO_UA = {"User-Agent": "Mozilla/5.0 (predictive-agent research script)"}
TIMEOUT = 15


class DataUnavailableError(RuntimeError):
    pass


class DailyBar(TypedDict):
    date: str  # YYYY-MM-DD
    close: float


def _yahoo_daily_history(ticker: str, range_: str = "1y") -> list[DailyBar]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    resp = requests.get(
        url, params={"range": range_, "interval": "1d"}, headers=YAHOO_UA, timeout=TIMEOUT
    )
    resp.raise_for_status()
    payload = resp.json()["chart"]["result"][0]
    timestamps = payload["timestamp"]
    closes = payload["indicators"]["quote"][0]["close"]
    bars: list[DailyBar] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        date = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        bars.append({"date": date, "close": round(float(close), 4)})
    if not bars:
        raise DataUnavailableError(f"Yahoo: nessuna barra per {ticker}")
    return bars


def _yahoo_latest_price(ticker: str) -> tuple[float, str]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    resp = requests.get(
        url, params={"range": "1d", "interval": "1m"}, headers=YAHOO_UA, timeout=TIMEOUT
    )
    resp.raise_for_status()
    meta = resp.json()["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")
    if price is None:
        raise DataUnavailableError(f"Yahoo: nessun prezzo realtime per {ticker}")
    asof = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat() if ts else _now_iso()
    return float(price), asof


def _twelvedata_daily_history(ticker: str, outputsize: int = 260) -> list[DailyBar]:
    key = os.environ.get("TWELVE_DATA_KEY")
    if not key:
        raise DataUnavailableError("TWELVE_DATA_KEY non impostata")
    url = "https://api.twelvedata.com/time_series"
    resp = requests.get(
        url,
        params={"symbol": ticker, "interval": "1day", "outputsize": outputsize, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    values = payload.get("values")
    if not values:
        raise DataUnavailableError(f"Twelve Data: {payload.get('message', 'nessun dato')}")
    bars = [{"date": v["datetime"][:10], "close": round(float(v["close"]), 4)} for v in values]
    return sorted(bars, key=lambda b: b["date"])


def _twelvedata_latest_price(ticker: str) -> tuple[float, str]:
    key = os.environ.get("TWELVE_DATA_KEY")
    if not key:
        raise DataUnavailableError("TWELVE_DATA_KEY non impostata")
    resp = requests.get(
        "https://api.twelvedata.com/quote",
        params={"symbol": ticker, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    price = payload.get("close")
    if price is None:
        raise DataUnavailableError(f"Twelve Data quote fallita: {payload}")
    return float(price), _now_iso()


def _finnhub_latest_price(ticker: str) -> tuple[float, str]:
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        raise DataUnavailableError("FINNHUB_KEY non impostata")
    resp = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": ticker, "token": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    price = payload.get("c")
    if not price:
        raise DataUnavailableError(f"Finnhub quote fallita: {payload}")
    return float(price), _now_iso()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def fetch_daily_history(ticker: str, range_: str = "1y") -> list[DailyBar]:
    """Storico daily con fallback a cascata. Ordinato per data crescente."""
    errors = []
    for fn, label in ((_yahoo_daily_history, "yahoo"), (_twelvedata_daily_history, "twelvedata")):
        try:
            return fn(ticker)
        except Exception as exc:  # noqa: BLE001 - vogliamo continuare sulla fonte successiva
            errors.append(f"{label}: {exc}")
    raise DataUnavailableError(f"Storico prezzo non disponibile per {ticker}: {errors}")


def fetch_latest_price(ticker: str) -> tuple[float, str, str]:
    """Ritorna (prezzo, timestamp ISO, fonte usata)."""
    errors = []
    for fn, label in (
        (_yahoo_latest_price, "yahoo"),
        (_twelvedata_latest_price, "twelvedata"),
        (_finnhub_latest_price, "finnhub"),
    ):
        try:
            price, asof = fn(ticker)
            return price, asof, label
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    raise DataUnavailableError(f"Prezzo realtime non disponibile per {ticker}: {errors}")


def price_on_or_after(ticker: str, target_date: str, range_: str = "2y") -> DailyBar:
    """Prima barra daily con date >= target_date (gestisce weekend/festivi)."""
    bars = fetch_daily_history(ticker, range_=range_)
    for bar in bars:
        if bar["date"] >= target_date:
            return bar
    raise DataUnavailableError(
        f"Nessuna barra disponibile per {ticker} a partire da {target_date}"
    )
