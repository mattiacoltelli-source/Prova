from __future__ import annotations

import json
import os
from unittest.mock import patch

from src import config, snapshot_run


def _isolate(tmp_path, monkeypatch, assets=None):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "_state"))
    if assets is not None:
        monkeypatch.setattr(config, "ASSETS", assets)


def test_run_reale_scrive_snapshot_per_ogni_asset(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, ["NVDA", "AAPL"])

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
    _isolate(tmp_path, monkeypatch, ["NVDA"])

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", return_value=(224.92, "2026-09-03T20:00:00+00:00", "yahoo")
    ):
        snapshot_run.run(dry_run=True)

    assert not os.path.exists(config.snapshot_file("NVDA"))


def test_una_fonte_fallita_non_blocca_gli_altri_asset(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, ["NVDA", "AAPL"])

    def fake_fetch(asset):
        if asset == "NVDA":
            raise Exception("fonte prezzo non disponibile")
        return (326.09, "2026-09-03T20:00:01+00:00", "yahoo")

    with patch("src.snapshot_run.prices.fetch_latest_price", side_effect=fake_fetch):
        snapshot_run.run(dry_run=False)

    assert not os.path.exists(config.snapshot_file("NVDA"))
    with open(config.snapshot_file("AAPL"), encoding="utf-8") as fh:
        aapl = json.load(fh)
    assert aapl["price"] == 326.09


# Regressione: la richiesta dell'utente era un modo sicuro per recuperare a
# mano un'istantanea saltata (i 3 tick schedulati "spesso non si attivano"),
# senza rischiare di finire con più di 3 istantanee nello stesso giorno se
# uno scheduled tick arriva comunque più tardi. Il tetto è condiviso tra
# tick schedulati e run manuali: qui simuliamo 3 round reali di fila (come
# se tutti e 3 i tick fossero scattati, o 2 automatici + 1 manuale di
# recupero) e verifichiamo che un quarto tentativo sia un no-op esplicito.
def test_oltre_il_tetto_giornaliero_non_scrive_piu_nulla(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, ["NVDA"])
    monkeypatch.setattr(config, "SNAPSHOT_MAX_PER_DAY", 3)

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", return_value=(224.92, "2026-09-03T20:00:00+00:00", "yahoo")
    ) as mock_fetch:
        for _ in range(3):
            snapshot_run.run(dry_run=False)
        assert mock_fetch.call_count == 3

        # Quarto tentativo (es. un click manuale dopo che i 3 round del
        # giorno sono già stati fatti): nessuna chiamata di rete, nessuna
        # riscrittura.
        mock_fetch.reset_mock()
        snapshot_run.run(dry_run=False)
        mock_fetch.assert_not_called()


def test_dry_run_non_consuma_il_tetto_giornaliero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, ["NVDA"])
    monkeypatch.setattr(config, "SNAPSHOT_MAX_PER_DAY", 3)

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", return_value=(224.92, "2026-09-03T20:00:00+00:00", "yahoo")
    ) as mock_fetch:
        for _ in range(5):
            snapshot_run.run(dry_run=True)
        assert mock_fetch.call_count == 5  # nessuna delle 5 è bloccata dal tetto

        # Il tetto reale (3) resta comunque intatto per il primo run vero.
        snapshot_run.run(dry_run=False)
    assert os.path.exists(config.snapshot_file("NVDA"))


def test_un_round_totalmente_fallito_non_consuma_il_tetto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, ["NVDA"])
    monkeypatch.setattr(config, "SNAPSHOT_MAX_PER_DAY", 1)

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", side_effect=Exception("fonte non disponibile")
    ):
        snapshot_run.run(dry_run=False)  # fallisce, nessuna scrittura

    with patch(
        "src.snapshot_run.prices.fetch_latest_price", return_value=(224.92, "2026-09-03T20:00:00+00:00", "yahoo")
    ):
        snapshot_run.run(dry_run=False)  # il tetto non era stato consumato, questo riesce

    assert os.path.exists(config.snapshot_file("NVDA"))
