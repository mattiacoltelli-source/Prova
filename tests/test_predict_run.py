"""Test unitari per la cache di src/predict_run.py._get_analyst_outlook.

Un dry-run non deve mai consumare la quota gratuita di Alpha Vantage (25
richieste/giorno, condivisa con fondamentali/news di riserva) che serve ai
run reali: niente fetch, niente cache scritta, per lasciare intatta la
possibilità di un fetch vero più tardi nello stesso giorno.

La cache copre anche piu' giorni (ANALYST_OUTLOOK_CACHE_DAYS): un outlook
riuscito resta valido per una settimana, un fallimento (es. quota
esaurita quel giorno) no — vedi _cached_analyst_outlook.
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


# Regressione (2026-09-04): analyst_outlook costa 2 chiamate Alpha Vantage
# per asset sul tetto gratuito condiviso di 25/giorno, spesso già esaurito
# da solo un giorno di uso normale — la primissima chiamata della giornata
# ha trovato la quota già a zero. Un outlook riuscito qualche giorno fa
# resta valido (le stime di consenso non cambiano da un giorno all'altro),
# quindi non va rifatto ogni giorno.
def test_outlook_riuscito_qualche_giorno_fa_viene_riusato(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    outlook = {"next_report_date": "2026-10-30"}
    predict_run._save_analyst_outlook_cache("AAPL", dt.date(2026, 8, 30), outlook)
    with patch("src.predict_run.fundamentals.fetch_analyst_outlook") as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=False)
    assert result == outlook
    mock_fetch.assert_not_called()


# Un fallimento vecchio (es. quota esaurita quel giorno) non deve invece
# bloccare i tentativi successivi per una settimana intera: solo un
# outlook REALE resta valido a lungo, un None viene sempre ritentato.
def test_fallimento_vecchio_non_blocca_un_nuovo_tentativo(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    predict_run._save_analyst_outlook_cache("AAPL", dt.date(2026, 9, 1), None)
    outlook = {"next_report_date": "2026-10-30"}
    with patch(
        "src.predict_run.fundamentals.fetch_analyst_outlook", return_value=outlook
    ) as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=False)
    assert result == outlook
    mock_fetch.assert_called_once()


# Oltre la finestra di cache (ANALYST_OUTLOOK_CACHE_DAYS), anche un
# outlook riuscito va ricontrollato: le stime possono nel frattempo essere
# state riviste.
def test_outlook_oltre_la_finestra_di_cache_viene_riprovato(tmp_path, monkeypatch):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    old_outlook = {"next_report_date": "2026-07-30"}
    old_day = dt.date(2026, 9, 2) - dt.timedelta(days=predict_run.ANALYST_OUTLOOK_CACHE_DAYS)
    predict_run._save_analyst_outlook_cache("AAPL", old_day, old_outlook)
    fresh_outlook = {"next_report_date": "2026-10-30"}
    with patch(
        "src.predict_run.fundamentals.fetch_analyst_outlook", return_value=fresh_outlook
    ) as mock_fetch:
        result = predict_run._get_analyst_outlook("AAPL", dt.date(2026, 9, 2), dry_run=False)
    assert result == fresh_outlook
    mock_fetch.assert_called_once()


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


# Regressione: --force ignorava anche il controllo "slot già fatto oggi",
# non solo il vincolo di orario — un secondo run manuale (o un run manuale
# lanciato dopo che lo slot schedulato era già scattato con successo, es.
# per un tap ripetuto su "Run workflow" nell'app GitHub) rigenerava un
# secondo giro di previsioni reali duplicate per NVDA/MSFT/AAPL. Ora
# --force salta solo il vincolo di orario, mai il controllo "già fatto".
def test_force_non_rigenera_se_lo_slot_di_oggi_e_gia_fatto(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(predict_run.config, "STATE_DIR", str(tmp_path))
    now_et = dt.datetime.now(predict_run.config.EASTERN)
    for hour, minute in predict_run.config.PREDICTION_SLOTS_ET:
        predict_run._mark_slot_done(now_et.date(), predict_run._slot_label(hour, minute))

    with patch("src.predict_run.prices.fetch_daily_history") as mock_fetch:
        predict_run.run(dry_run=True, force=True)

    mock_fetch.assert_not_called()
    assert "già fatto" in capsys.readouterr().out


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


# Regressione trovata da revisione del codice il 2026-09-04, stessa famiglia
# del bug già corretto in evaluate_run.py (MARKET_CLOSE_ET lì): bars/
# benchmark_bars/sector_bars venivano passate INTERE (barra di oggi, ancora
# in aggiornamento a mercato aperto, inclusa) a tutti gli indicatori
# tecnici — non solo a _reference_price(), che già la escludeva.
def test_completed_bars_esclude_la_barra_di_oggi_a_mercato_aperto():
    now_et = dt.datetime(2026, 9, 4, 10, 0, tzinfo=predict_run.config.EASTERN)
    bars = [
        {"date": "2026-09-02", "close": 224.0},
        {"date": "2026-09-03", "close": 228.45},
        {"date": "2026-09-04", "close": 233.78},  # barra di oggi, live/parziale
    ]
    result = predict_run._completed_bars(bars, now_et)
    assert result == bars[:2]


def test_completed_bars_include_la_barra_di_oggi_dopo_la_chiusura():
    now_et = dt.datetime(2026, 9, 4, 20, 0, tzinfo=predict_run.config.EASTERN)  # dopo le 16:00 ET
    bars = [
        {"date": "2026-09-03", "close": 228.45},
        {"date": "2026-09-04", "close": 230.10},  # ormai definitiva
    ]
    assert predict_run._completed_bars(bars, now_et) == bars
