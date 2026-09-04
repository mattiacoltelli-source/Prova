"""Test unitari per src/evaluate_run.py: soprattutto il gate a chiusura
mercato prima di valutare un orizzonte scaduto oggi.

Regressione reale del 2026-09-04: fetch_daily_history() include una barra
per la sessione di OGGI anche a mercato ancora aperto (verificato dal vivo:
due chiamate a pochi secondi di distanza a mercato aperto ritornavano
close/volume diversi per la stessa data — una barra ancora in
aggiornamento, non la chiusura definitiva). Senza questo gate, un run
manuale di recupero lanciato durante l'orario di mercato avrebbe valutato
la previsione contro un prezzo non definitivo, scrivendolo per sempre
nella catena hash.
"""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

from src import config, evaluate_run, storage


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(config, "REPORT_FILE", str(tmp_path / "REPORT.md"))


def _seed_prediction_and_pending(asset: str, prediction_id: str, target_at: str):
    prediction = {
        "id": prediction_id,
        "asset": asset,
        "horizon": "1d",
        "generated_at": "2026-09-03T11:00:00+00:00",
        "target_at": target_at,
        "price_at_generation": 100.0,
        "predicted_class": "UP",
        "confidence": 72,
        "volatility_threshold_pct": 1.0,
        "prev_hash": "GENESIS",
    }
    storage.append_record(config.predictions_file(asset), prediction)
    storage.save_pending([{"asset": asset, "horizon": "1d", "id": prediction_id, "target_at": target_at}])


def test_orizzonte_scaduto_oggi_a_mercato_aperto_viene_rimandato(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_prediction_and_pending("NVDA", "pred-1", "2026-09-04T00:00:00+00:00")

    # 10:00 ET (mercato aperto, chiude alle 16:00 ET) = 14:00 UTC.
    now_utc = dt.datetime(2026, 9, 4, 14, 0, tzinfo=dt.timezone.utc)
    with patch("src.evaluate_run.prices.price_on_or_after") as mock_price:
        evaluate_run.run(dry_run=False, now_utc=now_utc)

    mock_price.assert_not_called()
    # La previsione resta ancora in pending, non valutata.
    with open(config.PENDING_FILE, encoding="utf-8") as fh:
        assert len(json.load(fh)) == 1
    assert not storage.read_all(config.outcomes_file("NVDA"))


def test_orizzonte_scaduto_oggi_dopo_la_chiusura_viene_valutato(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_prediction_and_pending("NVDA", "pred-1", "2026-09-04T00:00:00+00:00")

    # 21:00 ET, ben dopo la chiusura delle 16:00 ET = 01:00 UTC del 5/9.
    now_utc = dt.datetime(2026, 9, 5, 1, 0, tzinfo=dt.timezone.utc)
    with patch(
        "src.evaluate_run.prices.price_on_or_after",
        return_value={"date": "2026-09-04", "close": 102.0},
    ) as mock_price:
        evaluate_run.run(dry_run=False, now_utc=now_utc)

    mock_price.assert_called_once_with("NVDA", "2026-09-04")
    outcomes = storage.read_all(config.outcomes_file("NVDA"))
    assert len(outcomes) == 1
    assert outcomes[0]["correct"] is True  # +2% > soglia 1% -> UP, previsto UP


def test_orizzonte_scaduto_un_giorno_fa_viene_valutato_anche_a_mercato_aperto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _seed_prediction_and_pending("NVDA", "pred-1", "2026-09-03T00:00:00+00:00")

    # 10:00 ET del 4/9 (mercato aperto OGGI), ma l'orizzonte era di ieri:
    # il gate non si applica, la barra di ieri è già sicuramente definitiva.
    now_utc = dt.datetime(2026, 9, 4, 14, 0, tzinfo=dt.timezone.utc)
    with patch(
        "src.evaluate_run.prices.price_on_or_after",
        return_value={"date": "2026-09-03", "close": 101.0},
    ) as mock_price:
        evaluate_run.run(dry_run=False, now_utc=now_utc)

    mock_price.assert_called_once_with("NVDA", "2026-09-03")
    assert len(storage.read_all(config.outcomes_file("NVDA"))) == 1
