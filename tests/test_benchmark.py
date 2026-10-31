"""Test unitari per src/benchmark.py (le due righe di confronto del grafico
Trading AI: Buy & Hold SPY e Momentum a regole fisse).

Nessuna chiamata di rete reale: requests.get è sempre mockata (stesso
spirito di FakeResponse in test_market_scanner.py per Yahoo Finance)."""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from src import benchmark, config, storage


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _closes_payload(closes):
    return {
        "chart": {
            "result": [
                {"indicators": {"quote": [{"close": closes}]}}
            ]
        }
    }


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AI_TRADER_BUYHOLD_FILE", str(tmp_path / "buyhold.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_FILE", str(tmp_path / "momentum.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_BENCHMARK_SYMBOL", "SPY")
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_LOOKBACK_DAYS", 2)
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_TOP_N", 2)
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(config, "AI_TRADER_EXCLUDED_TICKERS", [])


_EXPERIMENT = {"start_equity_usd": 100000.0}


# ─── update_buy_hold ────────────────────────────────────────────────────────


def test_buy_hold_primo_giorno_usa_equity_di_partenza_come_ancora(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    payload = _closes_payload([100.0, 100.0, 105.0])
    with patch("src.benchmark.http.get", return_value=FakeResponse(json_data=payload)):
        benchmark.update_buy_hold(dt.date(2026, 10, 31), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_BUYHOLD_FILE)
    assert len(records) == 1
    assert records[0]["anchor_price"] == 105.0
    assert records[0]["equity_usd"] == 100000.0


def test_buy_hold_secondo_giorno_scala_proporzionalmente_al_prezzo(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_BUYHOLD_FILE, {
        "date": "2026-10-31", "anchor_price": 100.0, "equity_usd": 100000.0,
    })
    payload = _closes_payload([100.0, 105.0, 110.0])  # +10% rispetto all'ancora
    with patch("src.benchmark.http.get", return_value=FakeResponse(json_data=payload)):
        benchmark.update_buy_hold(dt.date(2026, 11, 1), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_BUYHOLD_FILE)
    assert len(records) == 2
    assert records[1]["equity_usd"] == 110000.0


def test_buy_hold_stesso_giorno_e_idempotente_nessuna_chiamata_di_rete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_BUYHOLD_FILE, {
        "date": "2026-10-31", "anchor_price": 100.0, "equity_usd": 100000.0,
    })

    def boom(*a, **k):
        raise AssertionError("non deve fare nessuna richiesta di rete: oggi è già registrato")

    with patch("src.benchmark.http.get", side_effect=boom):
        benchmark.update_buy_hold(dt.date(2026, 10, 31), _EXPERIMENT)

    assert len(storage.read_all(config.AI_TRADER_BUYHOLD_FILE)) == 1


# ─── update_momentum ────────────────────────────────────────────────────────


def _momentum_fake_get(closes_by_symbol, bad_symbols=()):
    def fake_get(url, **kwargs):
        for symbol in bad_symbols:
            if f"/{symbol}" in url:
                return FakeResponse(json_data={"chart": {"result": []}})
        for symbol, closes in closes_by_symbol.items():
            if f"/{symbol}" in url:
                return FakeResponse(json_data=_closes_payload(closes))
        raise AssertionError(f"URL inatteso in test: {url}")
    return fake_get


def test_momentum_primo_giorno_sceglie_i_migliori_top_n_senza_perdita_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # Lookback=2: serve closes[-1]/closes[-1-2] -> almeno 3 barre.
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],  # momentum +10%
        "BBB": [100.0, 100.0, 90.0],   # momentum -10% (escluso: negativo)
        "CCC": [100.0, 100.0, 105.0],  # momentum +5%
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)
    assert len(records) == 1
    rec = records[0]
    # Giorno 1: nessun paniere precedente da segnare a mercato, equity invariata.
    assert rec["equity_usd"] == 100000.0
    assert rec["holdings"] == {"AAA": 0.5, "CCC": 0.5}
    assert rec["prices"] == {"AAA": 110.0, "CCC": 105.0}


def test_momentum_secondo_giorno_segna_a_mercato_il_paniere_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31",
        "equity_usd": 100000.0,
        "holdings": {"AAA": 0.5, "CCC": 0.5},
        "prices": {"AAA": 110.0, "CCC": 105.0},
    })
    closes_by_symbol = {
        "AAA": [100.0, 110.0, 121.0],  # +10% rispetto a ieri (110 -> 121)
        "BBB": [100.0, 90.0, 81.0],
        "CCC": [100.0, 105.0, 105.0],  # invariato rispetto a ieri
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 1), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)
    assert len(records) == 2
    rec = records[1]
    # 0.5*(121/110-1) + 0.5*(105/105-1) = 0.05 -> 100000 * 1.05
    assert rec["equity_usd"] == 105000.0
    assert rec["holdings"] == {"AAA": 0.5, "CCC": 0.5}


def test_momentum_nessun_titolo_con_momentum_positivo_va_tutto_in_contanti(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 95.0],
        "BBB": [100.0, 100.0, 90.0],
        "CCC": [100.0, 100.0, 99.0],
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    assert rec["holdings"] == {}
    assert rec["prices"] == {}


def test_momentum_un_titolo_senza_dati_non_blocca_gli_altri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],
        "CCC": [100.0, 100.0, 105.0],
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol, bad_symbols=["BBB"])):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    assert rec["holdings"] == {"AAA": 0.5, "CCC": 0.5}


def test_momentum_stesso_giorno_e_idempotente_nessuna_chiamata_di_rete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0, "holdings": {}, "prices": {},
    })

    def boom(*a, **k):
        raise AssertionError("non deve fare nessuna richiesta di rete: oggi è già registrato")

    with patch("src.benchmark.http.get", side_effect=boom):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    assert len(storage.read_all(config.AI_TRADER_MOMENTUM_FILE)) == 1
