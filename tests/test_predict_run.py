"""Test unitari per la cache giornaliera di src/predict_run.py._get_analyst_outlook.

Un dry-run non deve mai consumare la quota gratuita di Alpha Vantage (25
richieste/giorno, condivisa con fondamentali/news di riserva) che serve ai
run reali: niente fetch, niente cache scritta, per lasciare intatta la
possibilità di un fetch vero più tardi nello stesso giorno.
"""
from __future__ import annotations

import datetime as dt
import os
from unittest.mock import patch

from src import predict_run


def test_dry_run_senza_cache_non_chiama_alpha_vantage_e_non_scrive_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    with patch(
        "src.predict_run.fundamentals.fetch_analyst_outlook"
    ) as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=True)
    assert result is None
    mock_fetch.assert_not_called()
    assert not os.path.exists(
        predict_run._analyst_outlook_state_path("AAPL", dt.date(2026, 9, 2))
    )


def test_run_reale_senza_cache_chiama_alpha_vantage_e_scrive_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    outlook = {"next_report_date": "2026-10-30"}
    with patch(
        "src.predict_run.fundamentals.fetch_analyst_outlook", return_value=outlook
    ) as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=False)
    assert result == outlook
    mock_fetch.assert_called_once()
    already_fetched, cached = predict_run._cached_analyst_outlook("AAPL", dt.date(2026, 9, 2))
    assert already_fetched is True
    assert cached == outlook


def test_con_cache_gia_presente_non_richiama_alpha_vantage_neanche_in_run_reale(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    predict_run._save_analyst_outlook_cache("AAPL", dt.date(2026, 9, 2), {"cached": True})
    with patch(
        "src.predict_run.fundamentals.fetch_analyst_outlook"
    ) as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=False)
    assert result == {"cached": True}
    mock_fetch.assert_not_called()
