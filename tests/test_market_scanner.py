"""Test unitari per src/market_scanner.py.

Nessuna chiamata di rete reale: requests.get è sempre mockata con una
risposta Yahoo Finance fabbricata (stessa forma vista dal vivo prima di
scrivere il modulo). Verifica soprattutto il bug reale trovato durante lo
sviluppo (chartPreviousClose con range="1mo" NON è la chiusura di ieri) e
che un simbolo che fallisce non blocchi l'intera scansione.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src import config, market_scanner


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _yahoo_payload(
    price=100.0,
    volume=3_000_000,
    change_pct=5.0,
    opens=None,
    highs=None,
    closes=None,
    volumes=None,
    name="Fake Corp",
    currency="USD",
    include_chart_previous_close=True,
):
    # 21 barre: le prime 20 sono storico, l'ultima è "oggi" (parziale).
    opens = opens or [10.0] * 20 + [10.5]
    highs = highs or [10.2] * 20 + [10.6]
    closes = closes or [10.0] * 19 + [9.5, 10.5]  # closes[-2] = 9.5 = chiusura di ieri
    volumes = volumes or [1_000_000] * 20 + [volume]
    meta = {
        "regularMarketPrice": price,
        "regularMarketVolume": volume,
        "regularMarketChangePercent": change_pct,
        "shortName": name,
        "currency": currency,
    }
    if include_chart_previous_close:
        # Deliberatamente un valore "sbagliato" (lontano da closes[-2]) per
        # verificare che il codice NON lo usi più per il gap — vedi
        # test_fetch_symbol_ignora_chart_previous_close_fuorviante.
        meta["chartPreviousClose"] = 999.0
    return {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "indicators": {
                        "quote": [
                            {"open": opens, "high": highs, "close": closes, "volume": volumes}
                        ]
                    },
                }
            ]
        }
    }


# ─── fetch_symbol: calcolo segnali ──────────────────────────────────────────


def test_fetch_symbol_calcola_i_segnali_attesi():
    payload = _yahoo_payload(
        price=11.0,  # prezzo "adesso" (meta), può differire dal close dell'ultima barra
        volume=4_000_000,  # 4x la media storica (1_000_000 su 20 barre)
        opens=[10.0] * 20 + [10.45],  # oggi apre a 10.45, ieri chiude a 9.5 -> gap +10%
        highs=[10.2] * 20 + [10.6],  # massimo recente (esclude oggi, ultimo elemento) = 10.2
        closes=[10.0] * 19 + [9.5, 10.5],
    )
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        row = market_scanner.fetch_symbol("FAKE")
    assert row["symbol"] == "FAKE"
    assert row["price"] == 11.0
    assert row["volume_ratio"] == 4.0
    assert row["gap_pct"] == pytest.approx(10.0, abs=0.01)  # (10.45-9.5)/9.5*100
    assert row["recent_high"] == 10.2
    assert row["breakout_pct"] == pytest.approx(7.84, abs=0.01)  # (11.0-10.2)/10.2*100


def test_fetch_symbol_ignora_chart_previous_close_fuorviante():
    """Bug reale trovato con dati veri (RIVN): meta.chartPreviousClose con
    range="1mo" è la chiusura di ~1 mese fa, non quella di ieri. closes[-2]
    nello stesso array è sempre corretto, qualunque range."""
    payload = _yahoo_payload(opens=[10.0] * 20 + [9.595], closes=[10.0] * 19 + [9.5, 10.5])
    assert payload["chart"]["result"][0]["meta"]["chartPreviousClose"] == 999.0
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        row = market_scanner.fetch_symbol("FAKE")
    # Se avesse usato chartPreviousClose=999 il gap sarebbe ~-99%, non ~+1%.
    assert row["gap_pct"] == pytest.approx(1.0, abs=0.1)


def test_fetch_symbol_nessun_risultato_solleva_errore():
    payload = {"chart": {"result": []}}
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        with pytest.raises(market_scanner.ScannerError):
            market_scanner.fetch_symbol("FAKE")


def test_fetch_symbol_riporta_la_valuta_non_usd():
    """THK/Harmonic Drive (6481.T/6324.T) quotano in yen: il frontend deve
    poter scegliere il simbolo giusto invece di assumere sempre "$"."""
    payload = _yahoo_payload(currency="JPY")
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        row = market_scanner.fetch_symbol("6481.T")
    assert row["currency"] == "JPY"


def test_fetch_symbol_valuta_default_usd_se_assente():
    payload = _yahoo_payload()
    del payload["chart"]["result"][0]["meta"]["currency"]
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        row = market_scanner.fetch_symbol("FAKE")
    assert row["currency"] == "USD"


def test_fetch_symbol_storico_troppo_corto_solleva_errore():
    payload = _yahoo_payload(opens=[10.0], highs=[10.2], closes=[10.0], volumes=[1_000_000])
    with patch("src.market_scanner.http.get", return_value=FakeResponse(json_data=payload)):
        with pytest.raises(market_scanner.ScannerError):
            market_scanner.fetch_symbol("FAKE")


# ─── is_flagged ──────────────────────────────────────────────────────────────


def test_is_flagged_su_volume_anomalo():
    row = {"volume_ratio": config.SCANNER_VOLUME_RATIO_FLAG, "gap_pct": 0.1, "breakout_pct": -50}
    assert market_scanner.is_flagged(row)


def test_is_flagged_su_gap_forte_positivo_o_negativo():
    row_up = {"volume_ratio": 1.0, "gap_pct": config.SCANNER_GAP_PCT_FLAG, "breakout_pct": -50}
    row_down = {"volume_ratio": 1.0, "gap_pct": -config.SCANNER_GAP_PCT_FLAG, "breakout_pct": -50}
    assert market_scanner.is_flagged(row_up)
    assert market_scanner.is_flagged(row_down)


def test_is_flagged_su_breakout():
    row = {"volume_ratio": 1.0, "gap_pct": 0.1, "breakout_pct": config.SCANNER_BREAKOUT_PCT_FLAG}
    assert market_scanner.is_flagged(row)


def test_is_flagged_falso_quando_nessuna_soglia_superata():
    row = {"volume_ratio": 1.1, "gap_pct": 0.5, "breakout_pct": -30.0}
    assert not market_scanner.is_flagged(row)


# ─── scan: un simbolo che fallisce non blocca gli altri ────────────────────


def test_scan_un_simbolo_fallito_non_blocca_gli_altri():
    good_payload = _yahoo_payload(price=100.0, volume=1_000_000)

    def fake_get(url, **kwargs):
        if "BAD" in url:
            return FakeResponse(json_data={"chart": {"result": []}})
        return FakeResponse(json_data=good_payload)

    with patch("src.market_scanner.http.get", side_effect=fake_get):
        result = market_scanner.scan(["GOOD1", "BAD", "GOOD2"])

    assert len(result["results"]) == 2
    assert {r["symbol"] for r in result["results"]} == {"GOOD1", "GOOD2"}
    assert len(result["errors"]) == 1
    assert result["errors"][0]["symbol"] == "BAD"


def test_scan_ordina_i_flagged_prima_per_volume_ratio_decrescente():
    def payload_for(volume_ratio):
        # price=10.0 ben sotto il massimo recente (12.0, da highs) e gap
        # piatto: niente segnala flagged tranne il volume, così la riga
        # LOW (ratio 1.0, sotto la soglia 2.0) resta davvero non-flagged.
        return _yahoo_payload(
            price=10.0,
            volume=int(1_000_000 * volume_ratio),
            opens=[10.0] * 21,
            highs=[12.0] * 20 + [12.5],
            closes=[10.0] * 21,
        )

    def fake_get(url, **kwargs):
        if "LOW" in url:
            return FakeResponse(json_data=payload_for(1.0))  # non flagged
        if "HIGH" in url:
            return FakeResponse(json_data=payload_for(5.0))  # flagged, ratio alto
        return FakeResponse(json_data=payload_for(2.5))  # flagged, ratio medio

    with patch("src.market_scanner.http.get", side_effect=fake_get):
        result = market_scanner.scan(["LOW", "MED", "HIGH"])

    symbols_in_order = [r["symbol"] for r in result["results"]]
    assert symbols_in_order == ["HIGH", "MED", "LOW"]


# ─── all_symbols ─────────────────────────────────────────────────────────────


def test_all_symbols_unisce_azioni_e_crypto_senza_duplicati():
    symbols = market_scanner.all_symbols()
    assert len(symbols) == len(config.SCANNER_STOCKS) + len(config.SCANNER_CRYPTO)
    assert len(symbols) == len(set(symbols))
    assert "BTC-USD" in symbols
