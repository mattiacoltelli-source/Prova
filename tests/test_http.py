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


# ─── Retry sul 429 (opt-in) ────────────────────────────────────────────────
# Un 429 è una risposta HTTP arrivata a destinazione, quindi per default
# resta un esito definitivo come sopra. Con retry_on_rate_limit=True viene
# invece riprovata dopo un'attesa: serve a GDELT, che limita per IP e gira
# da runner con IP condivisi. time.sleep è sempre patchato, altrimenti i
# test unitari aspetterebbero davvero i 15 secondi.


def _resp(status, headers=None):
    class FakeResponse:
        status_code = status

        def __init__(self):
            self.headers = headers or {}

    return FakeResponse()


def test_get_non_riprova_sul_429_se_non_richiesto():
    with patch("src.data_sources.http.requests.get", return_value=_resp(429)) as mock_get:
        assert http.get("https://example.com").status_code == 429
        assert mock_get.call_count == 1


def test_get_riprova_sul_429_e_ritorna_la_risposta_buona():
    with patch("src.data_sources.http.time.sleep") as mock_sleep:
        with patch(
            "src.data_sources.http.requests.get",
            side_effect=[_resp(429), _resp(200)],
        ) as mock_get:
            assert http.get("https://example.com", retry_on_rate_limit=True).status_code == 200
            assert mock_get.call_count == 2
            assert mock_sleep.call_count == 1


def test_get_si_arrende_dopo_i_retry_sul_429():
    # Dopo i tentativi previsti il 429 viene restituito così com'è: chi
    # chiama lo tratta come fonte non disponibile, senza che il rate limit
    # resti nascosto.
    with patch("src.data_sources.http.time.sleep"):
        with patch(
            "src.data_sources.http.requests.get", return_value=_resp(429)
        ) as mock_get:
            assert http.get("https://example.com", retry_on_rate_limit=True).status_code == 429
            assert mock_get.call_count == 1 + http.RATE_LIMIT_MAX_RETRIES


def test_get_rispetta_retry_after_del_server():
    with patch("src.data_sources.http.time.sleep") as mock_sleep:
        with patch(
            "src.data_sources.http.requests.get",
            side_effect=[_resp(429, {"Retry-After": "3"}), _resp(200)],
        ):
            http.get("https://example.com", retry_on_rate_limit=True)
            mock_sleep.assert_called_once_with(3.0)


def test_get_ignora_un_retry_after_non_numerico():
    # Retry-After può essere una data HTTP invece di secondi: si ricade
    # sull'attesa fissa invece di lanciare.
    with patch("src.data_sources.http.time.sleep") as mock_sleep:
        with patch(
            "src.data_sources.http.requests.get",
            side_effect=[_resp(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), _resp(200)],
        ):
            http.get("https://example.com", retry_on_rate_limit=True)
            mock_sleep.assert_called_once_with(http.RATE_LIMIT_WAITS_S[0])


def test_get_tetta_un_retry_after_enorme():
    with patch("src.data_sources.http.time.sleep") as mock_sleep:
        with patch(
            "src.data_sources.http.requests.get",
            side_effect=[_resp(429, {"Retry-After": "600"}), _resp(200)],
        ):
            http.get("https://example.com", retry_on_rate_limit=True)
            mock_sleep.assert_called_once_with(float(http.RATE_LIMIT_MAX_WAIT_S))
