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


def test_predictor_parse_prediction():
    valid_text = '{"predicted_class": "UP", "confidence": 85, "reasoning_short": "Strong earnings."}'
    parsed = predictor.parse_prediction(valid_text)
    assert parsed["predicted_class"] == "UP"
    assert parsed["confidence"] == 85
    assert parsed["reasoning_short"] == "Strong earnings."

    # Invalid JSON
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction("Not a json")

    # Invalid class
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction('{"predicted_class": "INVALID", "confidence": 50, "reasoning_short": "x"}')

    # Invalid confidence
    with pytest.raises(predictor.PredictionParseError):
        predictor.parse_prediction('{"predicted_class": "UP", "confidence": 150, "reasoning_short": "x"}')


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
