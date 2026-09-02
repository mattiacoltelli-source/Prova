"""Test unitari per src/data_sources/insider.py: filtro sulle transazioni
discrezionali sul mercato aperto (P/S) e aggregazione, senza rete reale
(risposte HTTP mockate)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data_sources import insider

_FORM4_SAMPLE = b"""<?xml version="1.0"?>
<ownershipDocument>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionCoding>
                <transactionCode>S</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>1000</value></transactionShares>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <transactionCoding>
                <transactionCode>A</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>500</value></transactionShares>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeTransaction>
            <transactionCoding>
                <transactionCode>P</transactionCode>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>200</value></transactionShares>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


def _fake_response(content: bytes | None = None, json_data=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if content is not None:
        resp.content = content
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


def test_fetch_open_market_transactions_ignora_i_codici_non_p_s():
    with patch("src.data_sources.insider.http.get", return_value=_fake_response(content=_FORM4_SAMPLE)):
        transactions = insider._fetch_open_market_transactions("0000320193", "0001-26-000001")
    # Solo S (vendita) e P (acquisto): il grant "A" con codice non P/S è escluso.
    assert len(transactions) == 2
    codes = {tx["code"] for tx in transactions}
    assert codes == {"S", "P"}


def test_fetch_insider_summary_aggrega_acquisti_e_vendite():
    filings_payload = {
        "filings": {
            "recent": {
                "form": ["4", "10-K"],
                "filingDate": ["2026-08-15", "2026-08-01"],
                "accessionNumber": ["0001-26-000001", "0002-26-000002"],
            }
        }
    }
    with patch("src.data_sources.insider.sec_cik_for_ticker", return_value="0000320193"), patch(
        "src.data_sources.insider.http.get"
    ) as mock_get:
        mock_get.side_effect = [
            _fake_response(json_data=filings_payload),  # submissions
            _fake_response(content=_FORM4_SAMPLE),  # form4.xml del filing "4"
        ]
        result = insider.fetch_insider_summary("AAPL", lookback_days=30)

    assert result == {
        "lookback_days": 30,
        "buy_transactions": 1,
        "sell_transactions": 1,
        "net_shares": 200 - 1000,
    }


def test_fetch_insider_summary_none_se_nessun_filing_form4():
    filings_payload = {"filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-08-01"], "accessionNumber": ["0002"]}}}
    with patch("src.data_sources.insider.sec_cik_for_ticker", return_value="0000320193"), patch(
        "src.data_sources.insider.http.get", return_value=_fake_response(json_data=filings_payload)
    ):
        assert insider.fetch_insider_summary("AAPL") is None


def test_fetch_insider_summary_none_se_cik_non_trovato():
    with patch("src.data_sources.insider.sec_cik_for_ticker", side_effect=Exception("non trovato")):
        assert insider.fetch_insider_summary("XYZ") is None
