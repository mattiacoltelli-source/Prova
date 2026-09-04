from __future__ import annotations

import json
import pytest

from src import storage, config


def test_append_record_and_verify_chain(tmp_path, monkeypatch):
    test_file = tmp_path / "predictions.jsonl"

    rec1 = {"id": "1", "asset": "SPY", "horizon": "1d", "val": 100}
    saved1 = storage.append_record(str(test_file), rec1)

    assert saved1["prev_hash"] == storage.GENESIS
    assert "record_hash" in saved1

    rec2 = {"id": "2", "asset": "SPY", "horizon": "1d", "val": 102}
    saved2 = storage.append_record(str(test_file), rec2)

    assert saved2["prev_hash"] == saved1["record_hash"]

    is_valid, msg = storage.verify_chain(str(test_file))
    assert is_valid is True
    assert msg is None

    # Test chain tampering detection
    records = storage.read_all(str(test_file))
    records[0]["val"] = 999
    with open(test_file, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    is_valid, msg = storage.verify_chain(str(test_file))
    assert is_valid is False
    assert "record_hash non corrisponde" in msg


def test_pending_operations(tmp_path, monkeypatch):
    pending_file = str(tmp_path / "pending.json")
    monkeypatch.setattr(config, "PENDING_FILE", pending_file)

    assert storage.load_pending() == []

    e1 = {"id": "p1", "asset": "AAPL", "horizon": "1d", "target_at": "2026-09-01T00:00:00"}
    storage.add_pending(e1)

    loaded = storage.load_pending()
    assert len(loaded) == 1
    assert loaded[0]["id"] == "p1"

    storage.remove_pending("p1")
    assert storage.load_pending() == []


# Regressione: l'ordine di pending.json dipendeva da quando ogni entry
# veniva aggiunta/rimossa, non da un ordine stabile — pending.json è
# l'unico file riscritto per intero sia da predict_run.py che da
# evaluate_run.py, quindi un ordine variabile aumentava il rischio di
# conflitti spuri nel retry con rebase su un push concorrente.
def test_save_pending_ordina_in_modo_stabile_indipendentemente_dall_ordine_di_inserimento(
    tmp_path, monkeypatch
):
    pending_file = str(tmp_path / "pending.json")
    monkeypatch.setattr(config, "PENDING_FILE", pending_file)

    storage.add_pending({"id": "z", "asset": "NVDA", "horizon": "7d", "target_at": "x"})
    storage.add_pending({"id": "a", "asset": "AAPL", "horizon": "1d", "target_at": "x"})
    storage.add_pending({"id": "m", "asset": "MSFT", "horizon": "1m", "target_at": "x"})

    ids_in_order = [e["id"] for e in storage.load_pending()]
    assert ids_in_order == ["a", "m", "z"]  # ordinate per (asset, horizon, id), non per inserimento
