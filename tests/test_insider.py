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
        transactions = insider._fetch_open_market_transactions(
            "0000320193", "0001-26-000001", "xslF345X06/form4.xml"
        )
    # Solo S (vendita) e P (acquisto): il grant "A" con codice non P/S è escluso.
    assert len(transactions) == 2
    codes = {tx["code"] for tx in transactions}
    assert codes == {"S", "P"}


# Regressione reale trovata il 2026-09-04: il nome del documento XML
# primario di un Form 4 NON è sempre "form4.xml" (dipende dall'agente di
# deposito del filer, es. per NVDA è "wk-form4_<id>.xml") — l'URL fisso
# a "form4.xml" dava 404 su ogni filing NVDA, e "nessuna transazione
# insider" (esito silenzioso, nessun log) era in realtà un fetch fallito,
# non un dato vero. Verificato con SEC EDGAR live prima del fix.
def test_fetch_open_market_transactions_usa_il_vero_nome_del_documento():
    with patch(
        "src.data_sources.insider.http.get", return_value=_fake_response(content=_FORM4_SAMPLE)
    ) as mock_get:
        insider._fetch_open_market_transactions(
            "1045810", "0001199039-26-000012", "xslF345X06/wk-form4_1788387031.xml"
        )
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith("/wk-form4_1788387031.xml")
    assert "xslF345X06" not in called_url


def test_fetch_open_market_transactions_fallback_form4_xml_se_primary_document_assente():
    with patch(
        "src.data_sources.insider.http.get", return_value=_fake_response(content=_FORM4_SAMPLE)
    ) as mock_get:
        insider._fetch_open_market_transactions("0000320193", "0001-26-000001", None)
    assert mock_get.call_args[0][0].endswith("/form4.xml")


def test_fetch_insider_summary_aggrega_acquisti_e_vendite():
    filings_payload = {
        "filings": {
            "recent": {
                "form": ["4", "10-K"],
                "filingDate": ["2026-08-15", "2026-08-01"],
                "accessionNumber": ["0001-26-000001", "0002-26-000002"],
                "primaryDocument": ["xslF345X06/form4.xml", "10-k.htm"],
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


# Regressione: un fallimento sistematico nel recuperare l'elenco dei filing
# (CIK non trovato, SEC EDGAR giù, un campo rinominato) era completamente
# silenzioso — indistinguibile da "nessuna transazione questo mese", lo
# stesso tipo di fallimento silenzioso che ha nascosto in produzione il bug
# del nome file Form 4 sbagliato per NVDA.
def test_fetch_insider_summary_logga_se_il_fetch_dell_elenco_filing_fallisce(capsys):
    with patch("src.data_sources.insider.sec_cik_for_ticker", side_effect=Exception("SEC EDGAR non raggiungibile")):
        result = insider.fetch_insider_summary("XYZ")
    assert result is None
    assert "XYZ" in capsys.readouterr().out
