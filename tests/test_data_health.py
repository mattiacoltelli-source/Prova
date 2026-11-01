"""Test unitari per src/data_health.py — stato di salute delle fonti prezzi
(Yahoo Finance via market_scanner.py e benchmark.py), richiesto dall'utente
il 2026-11-02 dopo il bug reale (già corretto) di un formato cambiato senza
errore esplicito."""
from __future__ import annotations

import json

import pytest

from src import config, data_health


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "_state"))
    monkeypatch.setattr(config, "DATA_HEALTH_FAILURE_RATE_ALERT_THRESHOLD", 0.20)


def _read_health(source):
    with open(f"{config.STATE_DIR}/data_health_{source}.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_record_fetch_health_nessun_fallimento_nessun_allarme(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    data_health.record_fetch_health("scanner", total=10, failed_symbols=[])
    rec = _read_health("scanner")
    assert rec["total"] == 10
    assert rec["failed_count"] == 0
    assert rec["failure_rate"] == 0.0
    assert rec["alert"] is False


def test_record_fetch_health_sotto_soglia_nessun_allarme(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # 1/10 = 10%, sotto la soglia del 20%: un singolo ticker illiquido,
    # non un segnale di fonte rotta.
    data_health.record_fetch_health("scanner", total=10, failed_symbols=["BAD"])
    rec = _read_health("scanner")
    assert rec["failure_rate"] == 0.1
    assert rec["alert"] is False


def test_record_fetch_health_sopra_soglia_scatta_allarme(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # 3/10 = 30%, sopra la soglia del 20%.
    data_health.record_fetch_health("scanner", total=10, failed_symbols=["A", "B", "C"])
    rec = _read_health("scanner")
    assert rec["failure_rate"] == 0.3
    assert rec["alert"] is True
    assert rec["failed_symbols"] == ["A", "B", "C"]


def test_record_fetch_health_soglia_esatta_non_scatta(tmp_path, monkeypatch):
    """">" non ">=": esattamente alla soglia non è ancora un allarme, solo
    il superamento lo è."""
    _isolate(tmp_path, monkeypatch)
    data_health.record_fetch_health("scanner", total=10, failed_symbols=["A", "B"])  # 20%
    rec = _read_health("scanner")
    assert rec["failure_rate"] == 0.2
    assert rec["alert"] is False


def test_record_fetch_health_sovrascrive_non_accumula(tmp_path, monkeypatch):
    """Stato del giorno, non uno storico: una seconda chiamata lo stesso
    giorno sovrascrive, non somma ai fallimenti precedenti."""
    _isolate(tmp_path, monkeypatch)
    data_health.record_fetch_health("scanner", total=10, failed_symbols=["A", "B", "C"])
    data_health.record_fetch_health("scanner", total=10, failed_symbols=[])
    rec = _read_health("scanner")
    assert rec["failed_count"] == 0
    assert rec["alert"] is False


def test_record_fetch_health_fonti_diverse_file_diversi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    data_health.record_fetch_health("scanner", total=10, failed_symbols=["A"])
    data_health.record_fetch_health("benchmark", total=5, failed_symbols=["X", "Y"])
    assert _read_health("scanner")["failed_count"] == 1
    assert _read_health("benchmark")["failed_count"] == 2


def test_record_fetch_health_universo_vuoto_non_crasha(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    data_health.record_fetch_health("scanner", total=0, failed_symbols=[])
    rec = _read_health("scanner")
    assert rec["failure_rate"] == 0.0
    assert rec["alert"] is False
