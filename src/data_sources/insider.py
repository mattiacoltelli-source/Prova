"""Transazioni insider (Form 4) da SEC EDGAR, nessuna key richiesta.

Acquisti/vendite sul mercato aperto di dirigenti, amministratori e
azionisti >10% sono filing pubblici obbligatori (Form 4) entro 2 giorni
lavorativi dall'operazione — un segnale di sentiment "informato" gratuito.

Contano solo le transazioni discrezionali sul mercato aperto (codice P =
acquisto, S = vendita). Escluse deliberatamente vesting di RSU, esercizio
di opzioni, ritenute fiscali, donazioni e conversioni (codici A/F/M/G/C):
avvengono su calendari predeterminati o sono automatiche, non riflettono
una scelta dell'insider sul titolo.
"""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

from . import http
from .fundamentals import SEC_HEADERS, sec_cik_for_ticker

TIMEOUT = 15

_OPEN_MARKET_CODES = {"P", "S"}

# Limite di sicurezza sul numero di filing Form 4 da scaricare per run:
# evita di scaricare decine di documenti se un titolo ha avuto un'ondata
# insolita di filing nella finestra di lookback.
_MAX_FILINGS_PER_RUN = 20


def _recent_form4_filings(cik: str, lookback_days: int) -> list[dict]:
    resp = http.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_HEADERS, timeout=TIMEOUT
    )
    resp.raise_for_status()
    recent = resp.json().get("filings", {}).get("recent", {})
    cutoff = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    out = []
    for form, date, accession in zip(
        recent.get("form", []), recent.get("filingDate", []), recent.get("accessionNumber", [])
    ):
        if form == "4" and date >= cutoff:
            out.append({"accession": accession, "date": date})
    return out


def _fetch_open_market_transactions(cik: str, accession: str) -> list[dict]:
    accession_nodash = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/form4.xml"
    resp = http.get(url, headers=SEC_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    out = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        code = tx.findtext("./transactionCoding/transactionCode")
        if code not in _OPEN_MARKET_CODES:
            continue
        shares = tx.findtext("./transactionAmounts/transactionShares/value")
        acquired_disposed = tx.findtext("./transactionAmounts/transactionAcquiredDisposedCode/value")
        if shares is None or acquired_disposed is None:
            continue
        out.append({"code": code, "acquired_disposed": acquired_disposed, "shares": float(shares)})
    return out


def fetch_insider_summary(ticker: str, lookback_days: int = 30) -> dict | None:
    """Riepilogo delle compravendite insider sul mercato aperto negli
    ultimi `lookback_days` giorni. None se non ci sono transazioni
    rilevanti nella finestra o la fonte non è disponibile (segnale
    opzionale, mai bloccante per la previsione)."""
    try:
        cik = sec_cik_for_ticker(ticker)
        filings = _recent_form4_filings(cik, lookback_days)
    except Exception:  # noqa: BLE001
        return None
    if not filings:
        return None

    buy_transactions = sell_transactions = 0
    buy_shares = sell_shares = 0.0
    for filing in filings[:_MAX_FILINGS_PER_RUN]:
        try:
            transactions = _fetch_open_market_transactions(cik, filing["accession"])
        except Exception:  # noqa: BLE001 - salta il singolo filing
            continue
        for tx in transactions:
            if tx["acquired_disposed"] == "A":
                buy_transactions += 1
                buy_shares += tx["shares"]
            elif tx["acquired_disposed"] == "D":
                sell_transactions += 1
                sell_shares += tx["shares"]

    if buy_transactions == 0 and sell_transactions == 0:
        return None
    return {
        "lookback_days": lookback_days,
        "buy_transactions": buy_transactions,
        "sell_transactions": sell_transactions,
        "net_shares": round(buy_shares - sell_shares),
    }
