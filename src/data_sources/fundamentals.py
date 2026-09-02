"""Fondamentali/trimestrali, con fallback a cascata.

Per un'azione (es. AAPL): SEC EDGAR (XBRL company facts, nessuna key,
richiede solo un contatto nell'User-Agent) come primaria, Alpha Vantage
come fallback. Per un ETF (es. SPY) SEC EDGAR non pubblica XBRL company
facts standard: si usa direttamente il profilo ETF di Alpha Vantage.

In più, fetch_analyst_outlook() dà consenso analisti (stima EPS, numero di
analisti, revisioni) e prossima data di bilancio via Alpha Vantage
(EARNINGS_ESTIMATES + EARNINGS_CALENDAR) — stessa key già usata sopra,
nessuna fonte nuova.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os

from .. import config
from . import http

TIMEOUT = 15
SEC_HEADERS = {"User-Agent": f"predictive-agent research ({config.SEC_EDGAR_CONTACT_EMAIL})"}

_US_GAAP_TAGS = ["Revenues", "NetIncomeLoss", "Assets", "Liabilities", "EarningsPerShareDiluted"]


class FundamentalsUnavailableError(RuntimeError):
    pass


def _sec_cik_for_ticker(ticker: str) -> str:
    resp = http.get(
        "https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS, timeout=TIMEOUT
    )
    resp.raise_for_status()
    for entry in resp.json().values():
        if entry.get("ticker", "").upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    raise FundamentalsUnavailableError(f"CIK non trovato per {ticker}")


def _sec_edgar_fundamentals(ticker: str) -> dict:
    cik = _sec_cik_for_ticker(ticker)
    resp = http.get(
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
    resp = http.get(
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
    resp = http.get(
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


def _alphavantage_earnings_calendar(ticker: str) -> str | None:
    """Prossima data di uscita del bilancio (function=EARNINGS_CALENDAR,
    unica risposta CSV di Alpha Vantage, orizzonte 3 mesi). None se non
    programmata entro 3 mesi o se la fonte fallisce."""
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        return None
    resp = http.get(
        "https://www.alphavantage.co/query",
        params={"function": "EARNINGS_CALENDAR", "symbol": ticker, "horizon": "3month", "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = [row for row in reader if row.get("symbol") == ticker and row.get("reportDate")]
    if not rows:
        # Log informativo, non un errore: "nessun bilancio nei prossimi 3
        # mesi" e "tetto di 25 chiamate/giorno di Alpha Vantage esaurito"
        # producono entrambi 0 righe utili qui — utile poter distinguere i
        # due casi guardando il corpo grezzo nei log del run.
        print(f"[info] EARNINGS_CALENDAR {ticker}: 0 righe utili, corpo grezzo: {resp.text[:300]!r}")
        return None
    return min(row["reportDate"] for row in rows)


def _alphavantage_earnings_estimates(ticker: str) -> list[dict] | None:
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        return None
    resp = http.get(
        "https://www.alphavantage.co/query",
        params={"function": "EARNINGS_ESTIMATES", "symbol": ticker, "apikey": key},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    estimates = payload.get("estimates")
    if not estimates:
        # Log informativo, stessa ragione del commento sopra.
        print(f"[info] EARNINGS_ESTIMATES {ticker}: nessuna stima, corpo grezzo: {json.dumps(payload)[:300]}")
        return None
    return estimates


def select_next_quarter_estimate(estimates: list[dict], today: dt.date) -> dict | None:
    """Tra le stime trimestrali (escluse quelle annuali), sceglie quella col
    fiscalDateEnding più vicino ma non passato rispetto a `today` — le stime
    Alpha Vantage non sono ordinate per data, solo raggruppate per orizzonte.
    None se non ce n'è nessuna futura (tutte le trimestrali sono già passate)."""
    upcoming = []
    for e in estimates:
        if e.get("horizon") != "fiscal quarter":
            continue
        try:
            period_end = dt.date.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        if period_end >= today:
            upcoming.append((period_end, e))
    if not upcoming:
        return None
    return min(upcoming, key=lambda pair: pair[0])[1]


def fetch_analyst_outlook(ticker: str, today: dt.date | None = None) -> dict | None:
    """Prossima data di bilancio + consenso analisti (stima EPS media, numero
    di analisti, revisioni al rialzo/ribasso negli ultimi 30gg) per il
    trimestre fiscale più vicino. None se Alpha Vantage non ha nulla di
    utile (fonte opzionale, mai bloccante). 2 chiamate Alpha Vantage per
    ticker: va richiamata al più una volta al giorno per asset (vedi la
    cache in predict_run.py), non ad ogni previsione — il tetto gratuito è
    di 25 chiamate/giorno in totale, condiviso con fondamentali/news di
    riserva."""
    today = today or dt.date.today()
    next_report_date = _alphavantage_earnings_calendar(ticker)
    estimates = _alphavantage_earnings_estimates(ticker)
    if estimates is None:
        return None
    picked = select_next_quarter_estimate(estimates, today)
    if picked is None:
        return None
    return {
        "next_report_date": next_report_date,
        "fiscal_quarter_ending": picked["date"],
        "eps_estimate_average": picked.get("eps_estimate_average"),
        "eps_estimate_analyst_count": picked.get("eps_estimate_analyst_count"),
        "eps_revisions_up_30d": picked.get("eps_estimate_revision_up_trailing_30_days"),
        "eps_revisions_down_30d": picked.get("eps_estimate_revision_down_trailing_30_days"),
    }


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
