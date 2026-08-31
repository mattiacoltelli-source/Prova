"""Fondamentali/trimestrali, con fallback a cascata.

Per un'azione (es. AAPL): SEC EDGAR (XBRL company facts, nessuna key,
richiede solo un contatto nell'User-Agent) come primaria, Alpha Vantage
come fallback. Per un ETF (es. SPY) SEC EDGAR non pubblica XBRL company
facts standard: si usa direttamente il profilo ETF di Alpha Vantage.
"""
from __future__ import annotations

import os

import requests

from .. import config

TIMEOUT = 15
SEC_HEADERS = {"User-Agent": f"predictive-agent research ({config.SEC_EDGAR_CONTACT_EMAIL})"}

_US_GAAP_TAGS = ["Revenues", "NetIncomeLoss", "Assets", "Liabilities", "EarningsPerShareDiluted"]


class FundamentalsUnavailableError(RuntimeError):
    pass


def _sec_cik_for_ticker(ticker: str) -> str:
    resp = requests.get(
        "https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=TIMEOUT
    )
    resp.raise_for_status()
    for entry in resp.json().values():
        if entry.get("ticker", "").upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    raise FundamentalsUnavailableError(f"CIK non trovato per {ticker}")


def _sec_edgar_fundamentals(ticker: str) -> dict:
    cik = _sec_cik_for_ticker(ticker)
    resp = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        headers=SEC_HEADERS,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    facts = resp.json().get("facts", {}).get("us-gaap", {})
    out: dict = {}
    for tag in _US_GAAP_TAGS:
        tag_data = facts.get(tag)
        if not tag_data:
            continue
        units = tag_data.get("units", {})
        series = units.get("USD") or units.get("USD/shares") or next(iter(units.values()), [])
        quarterly = [v for v in series if v.get("form") in ("10-Q", "10-K")]
        if not quarterly:
            continue
        latest = sorted(quarterly, key=lambda v: v.get("end", ""))[-1]
        out[tag] = {"value": latest.get("val"), "period_end": latest.get("end"), "form": latest.get("form")}
    if not out:
        raise FundamentalsUnavailableError(f"SEC EDGAR: nessun dato utile per {ticker}")
    return {"source": "sec_edgar", "metrics": out}


def _alphavantage_overview(ticker: str) -> dict:
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        raise FundamentalsUnavailableError("ALPHA_VANTAGE_KEY non impostata")
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "OVERVIEW", "symbol": ticker, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload or "Symbol" not in payload:
        raise FundamentalsUnavailableError(f"Alpha Vantage OVERVIEW vuoto per {ticker}")
    keys = ["PERatio", "EPS", "RevenueTTM", "ProfitMargin", "QuarterlyEarningsGrowthYOY"]
    metrics = {k: payload.get(k) for k in keys if payload.get(k) not in (None, "None")}
    return {"source": "alphavantage_overview", "metrics": metrics}


def _alphavantage_etf_profile(ticker: str) -> dict:
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        raise FundamentalsUnavailableError("ALPHA_VANTAGE_KEY non impostata")
    resp = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "ETF_PROFILE", "symbol": ticker, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload or "net_assets" not in payload:
        raise FundamentalsUnavailableError(f"Alpha Vantage ETF_PROFILE vuoto per {ticker}")
    metrics = {
        "net_assets": payload.get("net_assets"),
        "net_expense_ratio": payload.get("net_expense_ratio"),
        "dividend_yield": payload.get("dividend_yield"),
    }
    top_holdings = payload.get("holdings", [])[:5]
    return {"source": "alphavantage_etf_profile", "metrics": metrics, "top_holdings": top_holdings}


def fetch_fundamentals(ticker: str) -> dict | None:
    """Ritorna un dict compatto di fondamentali, o None se nessuna fonte
    disponibile ha dati (i fondamentali sono un segnale opzionale)."""
    asset_type = config.ASSET_TYPE.get(ticker, "stock")
    candidates = (
        (_alphavantage_etf_profile,) if asset_type == "etf" else (_sec_edgar_fundamentals, _alphavantage_overview)
    )
    for fn in candidates:
        try:
            return fn(ticker)
        except Exception:  # noqa: BLE001 - passa alla fonte successiva
            continue
    return None
