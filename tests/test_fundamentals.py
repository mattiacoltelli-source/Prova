"""Test unitari per src/data_sources/fundamentals.py: la logica pura
(select_next_quarter_estimate) e l'orchestrazione di fetch_analyst_outlook
(con le due chiamate Alpha Vantage mockate, mai rete reale)."""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from src.data_sources import fundamentals


def _estimate(date, horizon="fiscal quarter", **extra):
    return {"date": date, "horizon": horizon, **extra}


def test_select_next_quarter_estimate_sceglie_il_piu_vicino_futuro():
    estimates = [
        _estimate("2027-12-31", horizon="fiscal year"),  # ignorata: non trimestrale
        _estimate("2026-12-31"),  # futura ma più lontana
        _estimate("2026-09-30"),  # la più vicina non passata
        _estimate("2026-06-30"),  # passata rispetto a today
    ]
    today = dt.date(2026, 9, 2)
    picked = fundamentals.select_next_quarter_estimate(estimates, today)
    assert picked["date"] == "2026-09-30"


def test_select_next_quarter_estimate_include_la_data_di_oggi():
    estimates = [_estimate("2026-09-02")]
    today = dt.date(2026, 9, 2)
    assert fundamentals.select_next_quarter_estimate(estimates, today)["date"] == "2026-09-02"


def test_select_next_quarter_estimate_none_se_tutte_passate():
    estimates = [_estimate("2026-06-30"), _estimate("2026-03-31")]
    today = dt.date(2026, 9, 2)
    assert fundamentals.select_next_quarter_estimate(estimates, today) is None


def test_select_next_quarter_estimate_ignora_date_malformate():
    estimates = [_estimate("non-una-data"), _estimate("2026-09-30")]
    today = dt.date(2026, 9, 2)
    picked = fundamentals.select_next_quarter_estimate(estimates, today)
    assert picked["date"] == "2026-09-30"


def test_select_next_quarter_estimate_none_se_lista_vuota():
    assert fundamentals.select_next_quarter_estimate([], dt.date(2026, 9, 2)) is None


def test_fetch_analyst_outlook_non_chiama_earnings_calendar_se_le_stime_falliscono():
    """Bug reale osservato in produzione (feedback utente 2026-09-19: 'stime
    analisti non le ha mai') per settimane: il tetto di 25 chiamate/giorno
    di Alpha Vantage, condiviso con fondamentali/news di riserva, veniva
    esaurito proprio sulle stime. La vecchia versione chiamava SEMPRE
    earnings_calendar prima di earnings_estimates, sprecando una chiamata
    anche nei giorni in cui le stime fallivano comunque. Ora, se le stime
    falliscono, earnings_calendar non deve scattare affatto."""
    with patch.object(fundamentals, "_alphavantage_earnings_estimates", return_value=None) as mock_estimates, \
         patch.object(fundamentals, "_alphavantage_earnings_calendar") as mock_calendar:
        result = fundamentals.fetch_analyst_outlook("NVDA", today=dt.date(2026, 9, 19))

    assert result is None
    mock_estimates.assert_called_once_with("NVDA")
    mock_calendar.assert_not_called()


def test_fetch_analyst_outlook_chiama_earnings_calendar_solo_se_le_stime_riescono():
    estimates = [_estimate("2026-09-30", eps_estimate_average="1.50", eps_estimate_analyst_count="40")]
    with patch.object(fundamentals, "_alphavantage_earnings_estimates", return_value=estimates), \
         patch.object(fundamentals, "_alphavantage_earnings_calendar", return_value="2026-11-15") as mock_calendar:
        result = fundamentals.fetch_analyst_outlook("NVDA", today=dt.date(2026, 9, 19))

    mock_calendar.assert_called_once_with("NVDA")
    assert result["next_report_date"] == "2026-11-15"
    assert result["fiscal_quarter_ending"] == "2026-09-30"
    assert result["eps_estimate_average"] == "1.50"
