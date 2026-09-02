"""Test unitari per src/data_sources/fundamentals.py: solo la logica pura
(select_next_quarter_estimate), nessuna chiamata di rete."""
from __future__ import annotations

import datetime as dt

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
