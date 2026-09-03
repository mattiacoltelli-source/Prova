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


# Regressione: un recupero manuale reale (--force, non dry-run) del
# 2026-09-02 non segnava lo slot come fatto, così un tick schedulato
# scattato più tardi lo stesso giorno lo trovava ancora libero e generava
# un secondo giro di previsioni reali duplicate per NVDA/MSFT/AAPL.
def test_slot_normale_marca_solo_quello_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    day = dt.date(2026, 9, 2)
    predict_run._mark_today_done(day, "15:45")
    assert predict_run._done_slots(day) == {"15:45"}


def test_force_reale_marca_tutti_gli_slot_configurati_del_giorno(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(predict_run.config, "PREDICTION_SLOTS_ET", [(9, 30), (15, 45)])
    day = dt.date(2026, 9, 2)
    predict_run._mark_today_done(day, "manual-force")
    assert predict_run._done_slots(day) == {"09:30", "15:45"}


def test_dopo_un_force_reale_un_tick_schedulato_lo_stesso_giorno_non_trova_altro_slot_dovuto(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    now_et = dt.datetime(2026, 9, 2, 20, 0, tzinfo=predict_run.config.EASTERN)
    predict_run._mark_today_done(now_et.date(), "manual-force")
    assert predict_run.find_due_slot(now_et) is None


# Regressione: con lo slot spostato a 8:00 ET (prima dell'apertura),
# prices.fetch_latest_price() ritorna ancora il prezzo dell'ultima
# chiusura (congelato fino alle 9:30 ET). Se target_at fosse calcolato da
# "adesso" invece che dalla data di quella chiusura, l'orizzonte "1g"
# diventerebbe silenziosamente di due giorni di trading invece di uno.
def test_target_anchor_date_prima_dell_apertura_usa_il_giorno_prima():
    now_et = dt.datetime(2026, 9, 3, 8, 0, tzinfo=predict_run.config.EASTERN)
    assert predict_run._target_anchor_date(now_et) == dt.date(2026, 9, 2)


def test_target_anchor_date_dopo_l_apertura_usa_oggi():
    now_et = dt.datetime(2026, 9, 3, 9, 30, tzinfo=predict_run.config.EASTERN)
    assert predict_run._target_anchor_date(now_et) == dt.date(2026, 9, 3)


def test_target_anchor_date_subito_prima_dell_apertura_usa_ancora_il_giorno_prima():
    now_et = dt.datetime(2026, 9, 3, 9, 29, tzinfo=predict_run.config.EASTERN)
    assert predict_run._target_anchor_date(now_et) == dt.date(2026, 9, 2)
