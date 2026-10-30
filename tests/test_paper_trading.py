"""Test unitari per src/paper_trading.py e src/paper_order_run.py.

Nessuna chiamata di rete reale: requests.get/post sono sempre mockati.
Verifica soprattutto le tre cose che contano di più per un modulo che
invia ordini veri (anche se su un conto paper): le chiavi mancanti non
passano silenziose, un ordine mal formato non parte, e il record salvato
riporta esattamente quello che Alpaca ha risposto, senza reinterpretarlo.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src import config, paper_order_run, paper_trading, storage


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PAPER_ORDERS_FILE", str(tmp_path / "orders.jsonl"))
    monkeypatch.setattr(config, "PAPER_ACCOUNT_FILE", str(tmp_path / "account.json"))


# ─── Chiavi mancanti ────────────────────────────────────────────────────────


def test_get_account_senza_chiavi_solleva_errore_chiaro(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(paper_trading.AlpacaError, match="ALPACA_API_KEY"):
        paper_trading.get_account()


# ─── Validazione ordine (prima ancora di chiamare la rete) ─────────────────


def test_place_order_side_non_valido_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="side"):
            paper_trading.place_order("NVDA", side="hold", qty=1)
        mock_post.assert_not_called()


def test_place_order_limit_senza_prezzo_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="limit_price"):
            paper_trading.place_order("NVDA", side="buy", qty=1, order_type="limit")
        mock_post.assert_not_called()


def test_place_order_qty_e_notional_insieme_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="qty e notional"):
            paper_trading.place_order("NVDA", side="buy", qty=1, notional=100)
        mock_post.assert_not_called()


def test_place_order_ne_qty_ne_notional_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="qty e notional"):
            paper_trading.place_order("NVDA", side="buy")
        mock_post.assert_not_called()


# ─── Ordine inviato con successo ────────────────────────────────────────────


def test_place_order_successo_manda_il_payload_atteso(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, {"id": "ord-1", "symbol": "NVDA", "status": "accepted"})
    with patch("src.paper_trading.requests.post", return_value=fake_resp) as mock_post:
        result = paper_trading.place_order("nvda", side="buy", qty=2.5)
    assert result["id"] == "ord-1"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["symbol"] == "NVDA"  # normalizzato maiuscolo
    assert kwargs["json"]["qty"] == "2.5"
    assert "notional" not in kwargs["json"]
    assert kwargs["headers"]["APCA-API-KEY-ID"] == "x"


def test_place_order_errore_http_solleva_alpaca_error_con_corpo(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(403, text="insufficient buying power")
    with patch("src.paper_trading.requests.post", return_value=fake_resp):
        with pytest.raises(paper_trading.AlpacaError, match="insufficient buying power"):
            paper_trading.place_order("NVDA", side="buy", qty=1000000)


def test_place_order_errore_di_rete_non_viene_ritentato(monkeypatch):
    """Punto di sicurezza: a differenza di una GET, una POST /v2/orders non
    va mai ritentata alla cieca su un errore di rete (rischio di doppio
    ordine) — qui verifichiamo solo che requests.post sia chiamata una
    volta sola, mai con retry automatico."""
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    import requests as requests_module

    with patch(
        "src.paper_trading.requests.post", side_effect=requests_module.exceptions.ConnectionError("dns fail")
    ) as mock_post:
        with pytest.raises(requests_module.exceptions.ConnectionError):
            paper_trading.place_order("NVDA", side="buy", qty=1)
        assert mock_post.call_count == 1


# ─── record_order: riporta alla lettera, non reinterpreta ──────────────────


def test_record_order_salva_esattamente_i_campi_della_risposta(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    order_response = {
        "id": "ord-42",
        "symbol": "NVDA",
        "side": "buy",
        "type": "market",
        "qty": "2.5",
        "notional": None,
        "limit_price": None,
        "time_in_force": "day",
        "status": "accepted",
        "submitted_at": "2026-10-31T10:00:00Z",
        "filled_at": None,
        "filled_qty": "0",
        "filled_avg_price": None,
    }
    saved = paper_trading.record_order(order_response)
    assert saved["alpaca_order_id"] == "ord-42"
    assert saved["status"] == "accepted"

    rows = storage.read_all(config.PAPER_ORDERS_FILE)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NVDA"
    ok, err = storage.verify_chain(config.PAPER_ORDERS_FILE)
    assert ok, err


def test_record_order_due_ordini_restano_in_catena(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    paper_trading.record_order({"id": "ord-1", "symbol": "NVDA", "status": "accepted"})
    paper_trading.record_order({"id": "ord-2", "symbol": "AAPL", "status": "accepted"})
    rows = storage.read_all(config.PAPER_ORDERS_FILE)
    assert len(rows) == 2
    assert rows[1]["prev_hash"] == rows[0]["record_hash"]


# ─── snapshot_account ───────────────────────────────────────────────────────


def test_snapshot_account_scrive_i_campi_attesi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    account = {"equity": "99500", "cash": "80000", "buying_power": "160000",
               "portfolio_value": "99500", "account_number": "PA123", "status": "ACTIVE"}
    positions = [{"symbol": "NVDA", "qty": "2.5", "avg_entry_price": "215.38",
                  "current_price": "194.23", "market_value": "485.57",
                  "unrealized_pl": "-52.87", "unrealized_plpc": "-0.098"}]
    paper_trading.snapshot_account(account, positions)

    import json
    with open(config.PAPER_ACCOUNT_FILE, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    assert snapshot["equity"] == "99500"
    assert len(snapshot["positions"]) == 1
    assert snapshot["positions"][0]["symbol"] == "NVDA"


# ─── paper_order_run.run(): dry-run non tocca la rete né il disco ──────────


def test_dry_run_non_chiama_place_order_ne_scrive(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.paper_trading.place_order") as mock_place:
        paper_order_run.run(
            symbol="NVDA", side="buy", qty=1, notional=None,
            order_type="market", limit_price=None, dry_run=True,
        )
    mock_place.assert_not_called()
    assert storage.read_all(config.PAPER_ORDERS_FILE) == []


def test_run_reale_invia_registra_e_fa_snapshot(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    order_response = {"id": "ord-9", "symbol": "NVDA", "side": "buy", "status": "accepted",
                       "qty": "1", "notional": None}
    account = {"equity": "100000"}
    with patch("src.paper_order_run.paper_trading.place_order", return_value=order_response) as mock_place, \
         patch("src.paper_order_run.paper_trading.get_account", return_value=account), \
         patch("src.paper_order_run.paper_trading.get_positions", return_value=[]):
        paper_order_run.run(
            symbol="NVDA", side="buy", qty=1, notional=None,
            order_type="market", limit_price=None, dry_run=False,
        )
    mock_place.assert_called_once()
    rows = storage.read_all(config.PAPER_ORDERS_FILE)
    assert len(rows) == 1
    assert rows[0]["alpaca_order_id"] == "ord-9"
