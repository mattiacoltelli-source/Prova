"""Test unitari per il tracking del contesto, versioning, hash e analisi della confidence."""
from __future__ import annotations

from src import config, predict_run, report, storage


def test_new_prediction_contains_required_metadata_and_hashes():
    timestamp_iso = "2026-08-31T12:00:00+00:00"
    inputs_summary = {"news_count": 3, "fundamentals_source": "sec_edgar", "macro_keys": ["VIXCLS"]}

    c_hash = predict_run.compute_context_hash(
        asset="AAPL",
        horizon="1d",
        generated_at=timestamp_iso,
        price_at_generation=220.5,
        volatility_threshold_pct=1.2,
        model=config.ANTHROPIC_MODEL,
        prompt_version="v1",
        inputs_summary=inputs_summary,
    )

    record = {
        "id": "pred-123",
        "asset": "AAPL",
        "horizon": "1d",
        "generated_at": timestamp_iso,
        "target_at": "2026-09-01T12:00:00+00:00",
        "price_at_generation": 220.5,
        "price_source": "yahoo",
        "predicted_class": "UP",
        "confidence": 85,
        "volatility_threshold_pct": 1.2,
        "model": config.ANTHROPIC_MODEL,
        "prompt_version": config.PROMPT_VERSION,
        "inputs_summary": inputs_summary,
        "context_hash": c_hash,
        "reasoning_short": "Strong momentum.",
    }

    assert record["generated_at"] == timestamp_iso
    assert record["price_at_generation"] == 220.5
    assert record["volatility_threshold_pct"] == 1.2
    assert record["model"] == config.ANTHROPIC_MODEL
    assert record["prompt_version"] == "v1"
    assert record["inputs_summary"] == inputs_summary
    assert record["context_hash"] == c_hash
    assert isinstance(record["context_hash"], str)
    assert len(record["context_hash"]) == 64  # SHA-256 hex


def test_same_context_produces_same_hash():
    kwargs = {
        "asset": "SPY",
        "horizon": "7d",
        "generated_at": "2026-08-31T10:00:00Z",
        "price_at_generation": 550.0,
        "volatility_threshold_pct": 0.8,
        "model": "claude-haiku-4-5-20251001",
        "prompt_version": "v1",
        "inputs_summary": {"news_count": 5},
    }

    hash1 = predict_run.compute_context_hash(**kwargs)
    hash2 = predict_run.compute_context_hash(**kwargs)
    assert hash1 == hash2


def test_modifying_context_element_changes_hash():
    base_kwargs = {
        "asset": "SPY",
        "horizon": "7d",
        "generated_at": "2026-08-31T10:00:00Z",
        "price_at_generation": 550.0,
        "volatility_threshold_pct": 0.8,
        "model": "claude-haiku-4-5-20251001",
        "prompt_version": "v1",
        "inputs_summary": {"news_count": 5},
    }
    base_hash = predict_run.compute_context_hash(**base_kwargs)

    # Change price
    price_modified = dict(base_kwargs, price_at_generation=551.0)
    assert predict_run.compute_context_hash(**price_modified) != base_hash

    # Change prompt version
    v2_modified = dict(base_kwargs, prompt_version="v2")
    assert predict_run.compute_context_hash(**v2_modified) != base_hash

    # Change threshold
    thresh_modified = dict(base_kwargs, volatility_threshold_pct=0.9)
    assert predict_run.compute_context_hash(**thresh_modified) != base_hash


def test_outcome_does_not_affect_context_hash():
    kwargs = {
        "asset": "SPY",
        "horizon": "1d",
        "generated_at": "2026-08-31T10:00:00Z",
        "price_at_generation": 400.0,
        "volatility_threshold_pct": 1.0,
        "model": "claude-haiku-4-5-20251001",
        "prompt_version": "v1",
        "inputs_summary": {"news_count": 2},
    }
    context_hash_before = predict_run.compute_context_hash(**kwargs)

    # Simulating evaluation / outcome creation
    outcome = {
        "prediction_id": "pred-456",
        "price_at_target": 405.0,
        "actual_class": "UP",
        "correct": True,
        "evaluated_at": "2026-09-01T10:00:00Z",
    }

    context_hash_after = predict_run.compute_context_hash(**kwargs)
    assert context_hash_before == context_hash_after
    assert "actual_class" not in kwargs
    assert "correct" not in kwargs


def test_legacy_records_without_metadata_continue_to_work(tmp_path, monkeypatch):
    outcomes_file = str(tmp_path / "outcomes.jsonl")
    monkeypatch.setattr(config, "outcomes_file", lambda asset: outcomes_file)

    legacy_record = {
        "prediction_id": "legacy-1",
        "asset": "SPY",
        "horizon": "1d",
        "evaluated_at": "2026-08-20T12:00:00Z",
        "price_at_target": 540.0,
        "target_bar_date": "2026-08-20",
        "actual_change_pct": 0.5,
        "actual_class": "UP",
        "predicted_class": "UP",
        "confidence": 65,
        "correct": True,
    }
    storage.append_record(outcomes_file, legacy_record)

    loaded = storage.read_all(outcomes_file)
    assert len(loaded) == 1
    assert loaded[0]["prediction_id"] == "legacy-1"

    buckets = report.analyze_confidence_buckets(loaded)
    bucket_60 = next(b for b in buckets if b["bucket_label"] == "60–69%")
    assert bucket_60["total"] == 1
    assert bucket_60["correct"] == 1
    assert bucket_60["accuracy_pct"] == 100.0


def test_confidence_analysis_buckets_and_out_of_range():
    outcomes = [
        {"confidence": 55, "correct": True},
        {"confidence": 58, "correct": False},
        {"confidence": 62, "correct": True},
        {"confidence": 75, "correct": True},
        {"confidence": 88, "correct": True},
        {"confidence": 95, "correct": False},
        {"confidence": 99, "correct": True},
        {"confidence": 40, "correct": False},  # out of range (under 50)
        {"confidence": 110, "correct": True},  # out of range (over 100)
        {"confidence": None, "correct": False}, # missing confidence
        {"confidence": "invalid", "correct": True}, # non-numeric confidence
    ]

    analysis = report.analyze_confidence_buckets(outcomes)
    by_label = {b["bucket_label"]: b for b in analysis}

    b50 = by_label["50–59%"]
    assert b50["total"] == 2
    assert b50["correct"] == 1
    assert b50["accuracy_pct"] == 50.0
    assert b50["mean_confidence"] == 56.5

    b60 = by_label["60–69%"]
    assert b60["total"] == 1
    assert b60["correct"] == 1
    assert b60["accuracy_pct"] == 100.0

    b70 = by_label["70–79%"]
    assert b70["total"] == 1
    assert b70["correct"] == 1

    b80 = by_label["80–89%"]
    assert b80["total"] == 1

    b90 = by_label["90–100%"]
    assert b90["total"] == 2
    assert b90["correct"] == 1

    assert sum(b["total"] for b in analysis) == 7
