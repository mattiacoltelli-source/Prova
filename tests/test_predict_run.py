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


# Regressione: con lo slot spostato a 7:00 ET (prima dell'apertura),
# prices.fetch_latest_price() ritorna ancora il prezzo dell'ultima
# chiusura (congelato fino alle 9:30 ET). Se target_at fosse calcolato da
# "adesso" invece che dalla data di quella chiusura, l'orizzonte "1g"
# diventerebbe silenziosamente di due giorni di trading invece di uno.
def test_reference_price_prima_dell_apertura_usa_il_prezzo_congelato():
    now_et = dt.datetime(2026, 9, 3, 7, 0, tzinfo=predict_run.config.EASTERN)
    bars = [
        {"date": "2026-09-01", "close": 220.0},
        {"date": "2026-09-02", "close": 224.31},
    ]
    with patch(
        "src.predict_run.prices.fetch_latest_price",
        return_value=(224.31, "2026-09-02T20:00:00+00:00", "yahoo"),
    ) as mock_fetch:
        price, asof, source, session_date = predict_run._reference_price("NVDA", bars=bars, now_et=now_et)
    mock_fetch.assert_called_once_with("NVDA")
    assert price == 224.31
    assert source == "yahoo"
    assert session_date == dt.date(2026, 9, 2)


# Regressione reale trovata da revisione del codice il 2026-09-03: il ramo
# pre-apertura calcolava la data di sessione come "oggi - 1 giorno" senza
# controllare se ieri fosse un vero giorno di borsa. Un lunedì l'ultima
# chiusura vera è venerdì, non domenica — per 7g/1m l'orizzonte finiva
# ancorato 2-3 giorni più avanti del dovuto ogni lunedì e dopo ogni
# festività, sballando silenziosamente l'accuratezza misurata su quei
# orizzonti. now_et qui è lunedì 2026-09-07 (venerdì 2026-09-04 è l'ultima
# barra storica, sabato/domenica non compaiono affatto in bars).
def test_reference_price_di_lunedi_usa_la_chiusura_di_venerdi_non_domenica():
    now_et = dt.datetime(2026, 9, 7, 7, 0, tzinfo=predict_run.config.EASTERN)
    bars = [
        {"date": "2026-09-03", "close": 226.0},
        {"date": "2026-09-04", "close": 228.9},
    ]
    with patch(
        "src.predict_run.prices.fetch_latest_price",
        return_value=(228.9, "2026-09-04T20:00:00+00:00", "yahoo"),
    ):
        _, _, _, session_date = predict_run._reference_price("NVDA", bars=bars, now_et=now_et)
    assert session_date == dt.date(2026, 9, 4)


# Regressione reale del 2026-09-03: un run manuale partito 1 minuto dopo
# l'apertura (9:31 ET) ha usato come prezzo di riferimento un prezzo
# intraday di oggi, ma l'orizzonte "1g" restava ancorato a "oggi + 1
# giorno" calcolato dall'orario di esecuzione — la previsione ha finito
# per coprire il resto della sessione di oggi PIÙ l'intera sessione di
# domani, quasi due giorni di trading invece di uno. Dopo l'apertura
# _reference_price() usa invece l'ultima chiusura storica reale (mai la
# barra di oggi, anche se già presente e ancora parziale).
def test_reference_price_dopo_l_apertura_usa_ultima_chiusura_storica_non_quella_di_oggi():
    now_et = dt.datetime(2026, 9, 3, 9, 31, tzinfo=predict_run.config.EASTERN)
    bars = [
        {"date": "2026-09-01", "close": 220.0},
        {"date": "2026-09-02", "close": 224.31},
        {"date": "2026-09-03", "close": 227.0},  # barra di oggi: mai usata
    ]
    price, asof, source, session_date = predict_run._reference_price("NVDA", bars=bars, now_et=now_et)
    assert price == 224.31
    assert source == "historical_bar"
    assert session_date == dt.date(2026, 9, 2)


def test_target_at_un_giorno_dopo_la_sessione_di_riferimento():
    target = predict_run._target_at(dt.date(2026, 9, 2), horizon_days=1)
    assert target == dt.datetime(2026, 9, 3, tzinfo=dt.timezone.utc)
