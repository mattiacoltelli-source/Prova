"""Test unitari per src/data_sources/macro.py: fetch_series_history()
(storico FRED usato per il percentile VIX), con la chiamata HTTP mockata."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data_sources import macro


def _fred_response(observations: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"observations": observations})
    return resp


def test_fetch_series_history_ordina_cronologicamente_crescente():
    # FRED risponde sort_order=desc: la funzione deve ritornare crescente.
    observations = [
        {"date": "2026-01-03", "value": "22.0"},
        {"date": "2026-01-02", "value": "20.0"},
        {"date": "2026-01-01", "value": "18.0"},
    ]
    with patch("src.data_sources.macro.http.get", return_value=_fred_response(observations)):
        history = macro.fetch_series_history("VIXCLS", "fake-key")
    assert [h["date"] for h in history] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert [h["value"] for h in history] == [18.0, 20.0, 22.0]


def test_fetch_series_history_scarta_valori_mancanti():
    observations = [
        {"date": "2026-01-02", "value": "."},  # FRED usa "." per un buco
        {"date": "2026-01-01", "value": "18.0"},
    ]
    with patch("src.data_sources.macro.http.get", return_value=_fred_response(observations)):
        history = macro.fetch_series_history("VIXCLS", "fake-key")
    assert len(history) == 1
    assert history[0]["date"] == "2026-01-01"


def test_fetch_series_history_lista_vuota_se_la_fonte_fallisce():
    with patch("src.data_sources.macro.http.get", side_effect=RuntimeError("rete giù")):
        history = macro.fetch_series_history("VIXCLS", "fake-key")
    assert history == []
