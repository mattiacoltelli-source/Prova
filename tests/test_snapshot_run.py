from __future__ import annotations

import json
from unittest.mock import patch

from src import config, snapshot_run


def test_run_reale_scrive_snapshot_per_ogni_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ASSETS", ["NVDA", "AAPL"])

    prices_by_asset = {
        "NVDA": (224.92, "2026-09-03T20:00:00+00:00", "yahoo"),
        "AAPL": (326.09, "2026-09-03T20:00:01+00:00", "yahoo"),
    }
    with patch(
        "src.snapshot_run.prices.fetch_latest_price",
        side_effect=lambda asset: prices_by_asset[asset],
    ):
        snapshot_run.run(dry_run=False)

    with open(config.snapshot_file("NVDA"), encoding="utf-8") as fh:
        nvda = json.load(fh)
    assert nvda["asset"] == "NVDA"
    assert nvda["price"] == 224.92
    assert nvda["price_source"] == "yahoo"
    assert "snapshot_at" in nvda

    with open(config.snapshot_file("AAPL"), encoding="utf-8") as fh:
        aapl = json.load(fh)
    assert aapl["price"] == 326.09


def test_dry_run_non_scrive_nulla(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ASSETS", ["NVDA"])

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", return_value=(224.92, "2026-09-03T20:00:00+00:00", "yahoo")
    ):
        snapshot_run.run(dry_run=True)

    import os

    assert not os.path.exists(config.snapshot_file("NVDA"))


def test_una_fonte_fallita_non_blocca_gli_altri_asset(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ASSETS", ["NVDA", "AAPL"])

    def fake_fetch(asset):
        if asset == "NVDA":
            raise Exception("fonte prezzo non disponibile")
        return (326.09, "2026-09-03T20:00:01+00:00", "yahoo")

    with patch("src.snapshot_run.prices.fetch_latest_price", side_effect=fake_fetch):
        snapshot_run.run(dry_run=False)

    import os

    assert not os.path.exists(config.snapshot_file("NVDA"))
    with open(config.snapshot_file("AAPL"), encoding="utf-8") as fh:
        aapl = json.load(fh)
    assert aapl["price"] == 326.09
