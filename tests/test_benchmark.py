"""Test unitari per src/benchmark.py (la strategia di confronto Momentum a
regole fisse per la pagina Trading AI).

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
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_FILE", str(tmp_path / "momentum.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_LOOKBACK_DAYS", 2)
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_TOP_N", 2)
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(config, "AI_TRADER_EXCLUDED_TICKERS", [])


_EXPERIMENT = {"start_equity_usd": 100000.0}


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
    assert rec["entry_prices"] == {"AAA": 110.0, "CCC": 105.0}
    assert rec["mark_prices"] == {"AAA": 110.0, "CCC": 105.0}
    assert rec["exit_prices"] == {}


def test_momentum_secondo_giorno_segna_a_mercato_il_paniere_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31",
        "equity_usd": 100000.0,
        "holdings": {"AAA": 0.5, "CCC": 0.5},
        "entry_prices": {"AAA": 110.0, "CCC": 105.0},
        "mark_prices": {"AAA": 110.0, "CCC": 105.0},
        "exit_prices": {},
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
    # Nessuno dei due è entrato oggi: entry_prices resta quello originale di ieri.
    assert rec["entry_prices"] == {"AAA": 110.0, "CCC": 105.0}
    # mark_prices invece è sempre quello di OGGI.
    assert rec["mark_prices"] == {"AAA": 121.0, "CCC": 105.0}


def test_momentum_entry_price_resta_invariato_su_piu_giorni_di_possesso(tmp_path, monkeypatch):
    """Bug reale corretto il 2026-11-02: un unico campo 'prices' veniva
    sovrascritto ogni giorno, quindi per un titolo tenuto da più giorni non
    c'era più modo di sapere a quanto era stato comprato all'origine."""
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 1.0}, "entry_prices": {"AAA": 100.0},
        "mark_prices": {"AAA": 100.0}, "exit_prices": {},
    })
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-11-01", "equity_usd": 105000.0,
        "holdings": {"AAA": 1.0}, "entry_prices": {"AAA": 100.0},
        "mark_prices": {"AAA": 105.0}, "exit_prices": {},
    })
    # Terzo giorno: AAA ha ancora il momentum migliore, resta l'unica in portafoglio.
    closes_by_symbol = {
        "AAA": [100.0, 105.0, 112.0],
        "BBB": [100.0, 90.0, 80.0],
        "CCC": [100.0, 95.0, 90.0],
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 2), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[2]
    assert rec["entry_prices"]["AAA"] == 100.0  # invariato dal giorno 1
    assert rec["mark_prices"]["AAA"] == 112.0   # aggiornato a oggi


def test_momentum_salva_il_prezzo_di_uscita_di_un_titolo_venduto(tmp_path, monkeypatch):
    """Il prezzo di vendita di un titolo che esce dal paniere deve essere
    salvato nello stesso giorno in cui esce — altrimenti il frontend non
    potrebbe mai mostrare 'a quanto ha venduto' (richiesto dall'utente)."""
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 0.5, "BBB": 0.5},
        "entry_prices": {"AAA": 100.0, "BBB": 100.0},
        "mark_prices": {"AAA": 100.0, "BBB": 100.0}, "exit_prices": {},
    })
    closes_by_symbol = {
        "AAA": [100.0, 110.0, 121.0],  # momentum +21%, resta
        "BBB": [100.0, 50.0, 40.0],    # momentum -60%, esce dal paniere
        "CCC": [100.0, 100.0, 110.0],  # momentum +10%, entra nel paniere
    }
    with patch("src.benchmark.http.get", side_effect=_momentum_fake_get(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 1), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[1]
    assert rec["holdings"] == {"AAA": 0.5, "CCC": 0.5}  # BBB non c'è più
    assert rec["exit_prices"] == {"BBB": 40.0}  # solo lei è uscita oggi
    assert rec["entry_prices"]["CCC"] == 110.0  # appena entrata: ingresso = oggi


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
    assert rec["entry_prices"] == {}


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
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {}, "entry_prices": {}, "mark_prices": {}, "exit_prices": {},
    })

    def boom(*a, **k):
        raise AssertionError("non deve fare nessuna richiesta di rete: oggi è già registrato")

    with patch("src.benchmark.http.get", side_effect=boom):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    assert len(storage.read_all(config.AI_TRADER_MOMENTUM_FILE)) == 1


# ─── derive_momentum_trades ─────────────────────────────────────────────────


def test_derive_momentum_trades_operazione_chiusa_ha_rendimento_corretto():
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {},
         "entry_prices": {}, "mark_prices": {}, "exit_prices": {"AAA": 110.0}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert result["open"] == []
    assert len(result["closed"]) == 1
    trade = result["closed"][0]
    assert trade == {
        "symbol": "AAA", "entry_date": "2026-10-31", "entry_price": 100.0,
        "exit_date": "2026-11-01", "exit_price": 110.0, "return_pct": 10.0,
    }


def test_derive_momentum_trades_posizione_ancora_aperta_usa_mark_price_piu_recente():
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 108.0}, "exit_prices": {}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert result["closed"] == []
    assert len(result["open"]) == 1
    open_trade = result["open"][0]
    assert open_trade["entry_date"] == "2026-10-31"
    assert open_trade["entry_price"] == 100.0
    assert open_trade["mark_price"] == 108.0
    assert open_trade["return_pct"] == 8.0


def test_derive_momentum_trades_entry_price_non_cambia_tra_chiusura_e_riapertura():
    """Se un titolo esce e poi rientra più tardi, la seconda apertura deve
    avere il SUO prezzo d'ingresso, non quello della volta precedente."""
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {},
         "entry_prices": {}, "mark_prices": {}, "exit_prices": {"AAA": 90.0}},
        {"date": "2026-11-03", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 95.0}, "mark_prices": {"AAA": 95.0}, "exit_prices": {}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert len(result["closed"]) == 1
    assert result["closed"][0]["entry_price"] == 100.0
    assert result["closed"][0]["exit_price"] == 90.0
    assert len(result["open"]) == 1
    assert result["open"][0]["entry_date"] == "2026-11-03"
    assert result["open"][0]["entry_price"] == 95.0


def test_derive_momentum_trades_storico_vuoto_non_crasha():
    assert benchmark.derive_momentum_trades([]) == {"closed": [], "open": []}
