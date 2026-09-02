"""Test unitari per src/data_sources/http.py: il retry deve scattare solo
sui veri errori di rete, mai su una risposta HTTP arrivata a destinazione
(anche se è un errore) — quella è già un esito definitivo per chi chiama."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from src.data_sources import http


def test_get_nessun_errore_una_sola_chiamata():
    with patch("src.data_sources.http.requests.get", return_value="ok") as mock_get:
        assert http.get("https://example.com") == "ok"
        assert mock_get.call_count == 1


def test_get_riprova_una_volta_su_errore_di_rete_poi_riesce():
    with patch(
        "src.data_sources.http.requests.get",
        side_effect=[requests.exceptions.ConnectionError("dns fail"), "ok"],
    ) as mock_get:
        assert http.get("https://example.com") == "ok"
        assert mock_get.call_count == 2


def test_get_rilancia_dopo_il_retry_se_fallisce_ancora():
    err = requests.exceptions.Timeout("timeout")
    with patch("src.data_sources.http.requests.get", side_effect=[err, err]) as mock_get:
        with pytest.raises(requests.exceptions.Timeout):
            http.get("https://example.com")
        assert mock_get.call_count == 2


def test_get_non_intercetta_una_risposta_http_di_errore():
    # Una risposta arrivata (anche 500) non è un'eccezione di rete: get()
    # la ritorna così com'è, senza retry — sta a chi chiama valutarla
    # (es. .raise_for_status()).
    class FakeResponse:
        status_code = 500

    with patch("src.data_sources.http.requests.get", return_value=FakeResponse()) as mock_get:
        resp = http.get("https://example.com")
        assert resp.status_code == 500
        assert mock_get.call_count == 1
