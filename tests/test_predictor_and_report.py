from __future__ import annotations

import json
import pytest

from src import budget, config, predictor, report, storage


def test_budget_management(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(config, "MAX_AI_CALLS_PER_DAY", 2)

    assert budget.get_call_count() == 0
    assert budget.has_budget() is True

    assert budget.reserve_call() is True
    assert budget.get_call_count() == 1

    assert budget.reserve_call() is True
    assert budget.get_call_count() == 2

    # Budget limit reached
    assert budget.has_budget() is False
    assert budget.reserve_call() is False
    assert budget.get_call_count() == 2


def test_predictor_parse_prediction_probabilita_valide():
    valid_text = (
        '{"probability_up": 0.7, "probability_down": 0.1, "probability_flat": 0.2, '
        '"reasoning_short": "Strong earnings."}'
    )
    parsed = predictor.parse_prediction(valid_text)
    # predicted_class/confidence sono DERIVATI dalle probabilità (classe più
    # probabile, sua probabilità in punti percentuali), non più campi
    # separati auto-dichiarati dal modello.
    assert parsed["predicted_class"] == "UP"
    assert parsed["confidence"] == 70
    assert parsed["probability_up"] == 0.7
    assert parsed["probability_down"] == 0.1
    assert parsed["probability_flat"] == 0.2
    assert parsed["reasoning_short"] == "Strong earnings."


def test_predictor_parse_prediction_normalizza_arrotondamento():
    # Somma 0.99 (arrotondamento tipico del modello): entro tolleranza,
    # normalizzata a somma esatta 1 invece di rifiutata.
    text = '{"probability_up": 0.33, "probability_down": 0.33, "probability_flat": 0.33, "reasoning_short": "x"}'
    parsed = predictor.parse_prediction(text)
    total = parsed["probability_up"] + parsed["probability_down"] + parsed["probability_flat"]
    # Tolleranza legata all'arrotondamento a 4 decimali dei valori salvati
    # (parse_prediction arrotonda DOPO la normalizzazione), non alla
    # normalizzazione stessa, che è esatta prima dell'arrotondamento.
    assert abs(total - 1.0) < 1e-3


def test_predictor_parse_prediction_json_non_valido():
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction("Not a json")


def test_predictor_parse_prediction_probabilita_fuori_range():
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction(
            '{"probability_up": 1.5, "probability_down": 0.1, "probability_flat": 0.2, "reasoning_short": "x"}'
        )


def test_predictor_parse_prediction_probabilita_mancante():
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction('{"probability_up": 0.5, "probability_down": 0.5, "reasoning_short": "x"}')


def test_predictor_parse_prediction_somma_troppo_lontana_da_1():
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction(
            '{"probability_up": 0.8, "probability_down": 0.8, "probability_flat": 0.8, "reasoning_short": "x"}'
        )


def test_predictor_parse_prediction_reasoning_mancante():
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction(
            '{"probability_up": 0.5, "probability_down": 0.3, "probability_flat": 0.2, "reasoning_short": ""}'
        )


def test_report_generation(tmp_path, monkeypatch):
    report_file = str(tmp_path / "REPORT.md")
    monkeypatch.setattr(config, "REPORT_FILE", report_file)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    # Add dummy outcome for AAPL
    outcome = {
        "prediction_id": "p1",
        "asset": "AAPL",
        "horizon": "1d",
        "evaluated_at": "2026-08-30T12:00:00Z",
        "price_at_target": 225.0,
        "target_bar_date": "2026-08-30",
        "actual_change_pct": 1.5,
        "actual_class": "UP",
        "predicted_class": "UP",
        "confidence": 80,
        "correct": True,
    }
    storage.append_record(config.outcomes_file("AAPL"), outcome)

    report.generate_report()

    with open(report_file, "r", encoding="utf-8") as fh:
        content = fh.read()

    assert "# Report accuratezza" in content
    assert "Previsioni valutate: 1 — accuratezza complessiva: 100.0%" in content
    assert "| AAPL | 1d | 1 | 100.0% |" in content
