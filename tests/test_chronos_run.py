"""Test unitari per src/chronos_run.py: la logica di orchestrazione
(quali previsioni di oggi vanno "ombrate", idempotenza, matching del
contesto storico) isolata dal modello vero e proprio — _load_pipeline e
_median_forecast sono mockati apposta, questi test NON richiedono
torch/chronos-forecasting installati (vedi il commento su _load_pipeline
in chronos_run.py)."""
from __future__ import annotations

from unittest.mock import patch

from src import chronos_run, config, storage


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))


def _seed_ai_prediction(asset: str, pred_id: str, generated_at: str, **overrides) -> dict:
    record = {
        "id": pred_id,
        "asset": asset,
        "horizon": "1d",
        "generated_at": generated_at,
        "target_at": "2026-09-05T00:00:00+00:00",
        "price_at_generation": 100.0,
        "predicted_class": "UP",
        "volatility_threshold_pct": 1.0,
    }
    record.update(overrides)
    storage.append_record(config.predictions_file(asset), record)
    return record


def test_salta_se_nessuna_previsione_ai_oggi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_ai_prediction("NVDA", "pred-1", "2026-09-03T11:00:00+00:00")  # ieri, non oggi

    with patch("src.chronos_run._load_pipeline") as mock_load:
        chronos_run.run(today_et=__import__("datetime").date(2026, 9, 4))

    mock_load.assert_not_called()
    assert storage.read_all(config.chronos_predictions_file("NVDA")) == []


def test_genera_previsione_ombra_per_previsione_ai_di_oggi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_ai_prediction("NVDA", "pred-1", "2026-09-04T11:00:00+00:00", price_at_generation=100.0)

    # Almeno MIN_CONTEXT_BARS barre, l'ultima con close==100.0 e date "2026-09-04".
    bars = [{"date": f"2026-0{m}-{i:02d}", "close": 90.0 + i * 0.1} for m in (1, 2, 3, 4, 5, 6, 7) for i in range(1, 29)] + \
           [{"date": f"2026-08-{i:02d}", "close": 90.0 + i * 0.1} for i in range(1, 32)] + \
           [{"date": f"2026-09-{i:02d}", "close": 95.0 + i * 0.1} for i in range(1, 4)] + \
           [{"date": "2026-09-04", "close": 100.0}]

    with patch("src.chronos_run._load_pipeline", return_value="fake-pipeline") as mock_load, \
         patch("src.chronos_run._median_forecast", return_value=102.0) as mock_forecast, \
         patch("src.chronos_run.prices.fetch_daily_history", return_value=bars):
        chronos_run.run(today_et=__import__("datetime").date(2026, 9, 4))

    mock_load.assert_called_once()
    mock_forecast.assert_called_once()
    records = storage.read_all(config.chronos_predictions_file("NVDA"))
    assert len(records) == 1
    rec = records[0]
    assert rec["prediction_id"] == "pred-1"
    assert rec["model"] == chronos_run.MODEL_ID
    assert rec["forecast_price"] == 102.0
    # +2% > soglia 1.0% -> UP
    assert rec["predicted_class"] == "UP"


def test_idempotente_non_duplica_se_gia_ombrata(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_ai_prediction("NVDA", "pred-1", "2026-09-04T11:00:00+00:00")
    storage.append_record(
        config.chronos_predictions_file("NVDA"),
        {"id": "shadow-1", "prediction_id": "pred-1", "asset": "NVDA", "horizon": "1d"},
    )

    with patch("src.chronos_run._load_pipeline") as mock_load:
        chronos_run.run(today_et=__import__("datetime").date(2026, 9, 4))

    mock_load.assert_not_called()
    assert len(storage.read_all(config.chronos_predictions_file("NVDA"))) == 1


def test_salta_se_contesto_storico_insufficiente(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_ai_prediction("NVDA", "pred-1", "2026-09-04T11:00:00+00:00", price_at_generation=100.0)
    bars = [{"date": "2026-09-04", "close": 100.0}]  # una sola barra, ben sotto MIN_CONTEXT_BARS

    with patch("src.chronos_run._load_pipeline", return_value="fake-pipeline") as mock_load, \
         patch("src.chronos_run.prices.fetch_daily_history", return_value=bars):
        chronos_run.run(today_et=__import__("datetime").date(2026, 9, 4))

    # pipeline caricata (c'era una previsione da processare) ma nessun
    # record scritto: contesto troppo corto.
    mock_load.assert_called_once()
    assert storage.read_all(config.chronos_predictions_file("NVDA")) == []


def test_find_context_end_trova_ultima_barra_combaciante():
    dates = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
    closes = [98.0, 99.0, 100.0, 101.0]
    idx = chronos_run._find_context_end(dates, closes, 100.0, "2026-09-03")
    assert idx == 2


def test_find_context_end_nessun_match():
    dates = ["2026-09-01", "2026-09-02"]
    closes = [98.0, 99.0]
    assert chronos_run._find_context_end(dates, closes, 123.45, "2026-09-02") is None
