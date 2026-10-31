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


def test_place_order_crypto_con_day_non_chiama_la_rete(monkeypatch):
    """Alpaca rifiuta time_in_force='day' per un ordine crypto (il mercato
    non chiude mai): validato qui prima della rete, non lasciato tornare
    come un 422 poco chiaro da Alpaca."""
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="gtc.*ioc"):
            paper_trading.place_order("BTC/USD", side="buy", qty=0.01)
        mock_post.assert_not_called()


def test_place_order_crypto_con_gtc_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, {"id": "ord-btc", "symbol": "BTC/USD", "status": "accepted"})
    with patch("src.paper_trading.requests.post", return_value=fake_resp) as mock_post:
        result = paper_trading.place_order("btc/usd", side="buy", qty=0.0833333, time_in_force="gtc")
    assert result["id"] == "ord-btc"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["symbol"] == "BTC/USD"
    assert kwargs["json"]["time_in_force"] == "gtc"


def test_place_order_azione_con_day_resta_valido(monkeypatch):
    """Il controllo è specifico per i simboli crypto (contengono '/'): un
    titolo azionario con time_in_force='day' (il default) non deve rompersi."""
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, {"id": "ord-x", "symbol": "NVDA", "status": "accepted"})
    with patch("src.paper_trading.requests.post", return_value=fake_resp):
        result = paper_trading.place_order("NVDA", side="buy", qty=1)
    assert result["id"] == "ord-x"


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


# ─── place_order: order_type="stop" (stop nativo, src/ai_trader_run.py) ────


def test_place_order_stop_senza_stop_price_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="stop_price"):
            paper_trading.place_order("NVDA", side="sell", qty=1, order_type="stop")
        mock_post.assert_not_called()


def test_place_order_stop_successo_manda_stop_price(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, {"id": "ord-stop", "symbol": "NVDA", "status": "accepted"})
    with patch("src.paper_trading.requests.post", return_value=fake_resp) as mock_post:
        result = paper_trading.place_order("NVDA", side="sell", qty=2, order_type="stop", stop_price=180.5)
    assert result["id"] == "ord-stop"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["type"] == "stop"
    assert kwargs["json"]["stop_price"] == "180.5"
    assert "limit_price" not in kwargs["json"]


def test_place_order_order_type_non_valido_non_chiama_la_rete(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.post") as mock_post:
        with pytest.raises(ValueError, match="order_type"):
            paper_trading.place_order("NVDA", side="sell", qty=1, order_type="trailing_stop")
        mock_post.assert_not_called()


# ─── get_open_orders ────────────────────────────────────────────────────────


def test_get_open_orders_senza_filtro(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, [{"id": "ord-1", "symbol": "NVDA"}])
    with patch("src.paper_trading.requests.get", return_value=fake_resp) as mock_get:
        result = paper_trading.get_open_orders()
    assert result == [{"id": "ord-1", "symbol": "NVDA"}]
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"status": "open"}


def test_get_open_orders_con_filtro_simbolo(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(200, [])
    with patch("src.paper_trading.requests.get", return_value=fake_resp) as mock_get:
        paper_trading.get_open_orders(symbol="nvda")
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"status": "open", "symbols": "NVDA"}


def test_get_open_orders_errore_http_solleva_alpaca_error(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(500, text="server error")
    with patch("src.paper_trading.requests.get", return_value=fake_resp):
        with pytest.raises(paper_trading.AlpacaError, match="server error"):
            paper_trading.get_open_orders()


# ─── cancel_order ────────────────────────────────────────────────────────────


def test_cancel_order_successo(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(204)
    with patch("src.paper_trading.requests.delete", return_value=fake_resp) as mock_delete:
        paper_trading.cancel_order("ord-1")
    mock_delete.assert_called_once()


def test_cancel_order_404_non_solleva_errore(monkeypatch):
    """Un 404 (ordine già eseguito o già annullato) non è un errore: chi
    chiama voleva solo che l'ordine non fosse più lì, ed è già così."""
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(404, text="order not found")
    with patch("src.paper_trading.requests.delete", return_value=fake_resp):
        paper_trading.cancel_order("ord-1")  # non deve sollevare


def test_cancel_order_altro_errore_solleva(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(500, text="server error")
    with patch("src.paper_trading.requests.delete", return_value=fake_resp):
        with pytest.raises(paper_trading.AlpacaError, match="server error"):
            paper_trading.cancel_order("ord-1")


# ─── get_portfolio_history ───────────────────────────────────────────────────


def test_get_portfolio_history_successo(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_data = {"timestamp": [1, 2], "equity": [100000.0, 100050.0], "timeframe": "1D"}
    fake_resp = FakeResponse(200, fake_data)
    with patch("src.paper_trading.requests.get", return_value=fake_resp) as mock_get:
        result = paper_trading.get_portfolio_history(start="2026-10-31")
    assert result == fake_data
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"start": "2026-10-31", "timeframe": "1D"}


def test_get_portfolio_history_errore_http_solleva_alpaca_error(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fake_resp = FakeResponse(422, text="bad request")
    with patch("src.paper_trading.requests.get", return_value=fake_resp):
        with pytest.raises(paper_trading.AlpacaError, match="bad request"):
            paper_trading.get_portfolio_history(start="2026-10-31")


# ─── get_activities (fill reali, fonte autorevole del prezzo) ──────────────


def test_get_activities_una_sola_pagina(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    fills = [{"id": "a1", "symbol": "NVDA", "side": "buy", "price": "123.45", "qty": "10"}]
    with patch("src.paper_trading.requests.get", return_value=FakeResponse(200, fills)) as mock_get:
        result = paper_trading.get_activities(after="2026-10-31")
    assert result == fills
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["activity_types"] == "FILL"
    assert kwargs["params"]["after"] == "2026-10-31"
    assert "page_token" not in kwargs["params"]


def test_get_activities_segue_la_paginazione(monkeypatch):
    """Una pagina piena (page_size=100) deve far ripartire una seconda
    richiesta con page_token = id dell'ultima attività — senza questo, le
    attività oltre la prima pagina andrebbero perse silenziosamente."""
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    page_1 = [{"id": f"a{i}", "symbol": "NVDA"} for i in range(100)]
    page_2 = [{"id": "a100", "symbol": "AAPL"}]

    responses = [FakeResponse(200, page_1), FakeResponse(200, page_2)]
    with patch("src.paper_trading.requests.get", side_effect=responses) as mock_get:
        result = paper_trading.get_activities(after="2026-10-31")

    assert len(result) == 101
    assert mock_get.call_count == 2
    second_call_params = mock_get.call_args_list[1].kwargs["params"]
    assert second_call_params["page_token"] == "a99"


def test_get_activities_errore_http_solleva_alpaca_error(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "x")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "y")
    with patch("src.paper_trading.requests.get", return_value=FakeResponse(500, text="boom")):
        with pytest.raises(paper_trading.AlpacaError, match="boom"):
            paper_trading.get_activities(after="2026-10-31")
