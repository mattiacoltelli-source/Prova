"""Test unitari per src/ai_trader.py, src/ai_trader_run.py e il tetto di
spesa mensile in dollari aggiunto a src/budget.py.

Nessuna chiamata di rete/Anthropic reale: il client è sempre mockato (vedi
FakeAnthropicClient sotto, stesso spirito di FakeResponse in
test_paper_trading.py per requests)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src import ai_trader, ai_trader_run, budget, config, paper_trading, storage


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "_state"))
    monkeypatch.setattr(config, "AI_TRADER_DECISIONS_FILE", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_EXPERIMENT_FILE", str(tmp_path / "experiment.json"))
    monkeypatch.setattr(config, "AI_TRADER_EQUITY_HISTORY_FILE", str(tmp_path / "equity_history.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_PORTFOLIO_HISTORY_FILE", str(tmp_path / "portfolio_history.json"))
    monkeypatch.setattr(config, "AI_TRADER_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PAPER_ORDERS_FILE", str(tmp_path / "orders.jsonl"))
    monkeypatch.setattr(config, "PAPER_ACCOUNT_FILE", str(tmp_path / "account.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    # _update_benchmarks (src/benchmark.py) gira dopo ogni setup/daily: senza
    # questo no-op, ogni test di run_setup/run_daily farebbe una vera
    # chiamata di rete a Yahoo Finance (lenta, flaky, contro il principio
    # "nessuna chiamata di rete reale" dichiarato in cima a questo file). I
    # test dedicati all'integrazione sotto sovrascrivono di nuovo questi due
    # mock per verificare che vengano chiamati davvero.
    monkeypatch.setattr(ai_trader_run.benchmark, "update_buy_hold", lambda *a, **k: None)
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: None)


# ─── budget.py: tetto mensile in dollari ────────────────────────────────────


def test_trader_spent_usd_parte_da_zero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert budget.get_trader_spent_usd() == 0.0
    assert budget.trader_has_budget() is True


def test_record_trader_call_cost_usa_i_prezzi_configurati(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # Haiku 5.5: 0.10$/1M input, 0.50$/1M output (config.py)
    cost = budget.record_trader_call_cost(config.AI_TRADER_HAIKU_MODEL, input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(0.60)
    assert budget.get_trader_spent_usd() == pytest.approx(0.60)


def test_record_trader_call_cost_si_accumula(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    budget.record_trader_call_cost(config.AI_TRADER_HAIKU_MODEL, 500_000, 0)
    budget.record_trader_call_cost(config.AI_TRADER_HAIKU_MODEL, 500_000, 0)
    assert budget.get_trader_spent_usd() == pytest.approx(0.10)


def test_trader_has_budget_falso_oltre_il_tetto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_MONTHLY_BUDGET_USD", 1.0)
    budget.record_trader_call_cost(config.AI_TRADER_SONNET_MODEL, 100_000, 0)  # 0.20$
    assert budget.trader_has_budget() is True
    budget.record_trader_call_cost(config.AI_TRADER_SONNET_MODEL, 500_000, 0)  # +1.00$ = 1.20$
    assert budget.trader_has_budget() is False


# ─── ai_trader.tradeable_universe() ────────────────────────────────────────


def test_tradeable_universe_esclude_i_ticker_di_tokyo():
    universe = ai_trader.tradeable_universe()
    assert "6481.T" not in universe
    assert "6324.T" not in universe
    assert "NVDA" in universe  # resta dentro (è anche in ASSETS)


# ─── ai_trader.core_asset_decision() ───────────────────────────────────────


def test_core_asset_decision_buy_su_up_alta_confidenza(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(config.predictions_file("NVDA"), {"horizon": "1d", "predicted_class": "UP", "confidence": 70})
    decision = ai_trader.core_asset_decision("NVDA")
    assert decision["decision"] == "BUY"
    assert decision["cost_usd"] == 0.0
    assert decision["model_used"] == "previsione_esistente"


def test_core_asset_decision_sell_su_down_alta_confidenza(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(config.predictions_file("AAPL"), {"horizon": "1d", "predicted_class": "DOWN", "confidence": 80})
    assert ai_trader.core_asset_decision("AAPL")["decision"] == "SELL"


def test_core_asset_decision_hold_su_bassa_confidenza(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(config.predictions_file("AMD"), {"horizon": "1d", "predicted_class": "UP", "confidence": 40})
    assert ai_trader.core_asset_decision("AMD")["decision"] == "HOLD"


def test_core_asset_decision_hold_senza_previsione(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    assert ai_trader.core_asset_decision("MU")["decision"] == "HOLD"


# ─── ai_trader.parse_decision() ────────────────────────────────────────────


def test_parse_decision_valida():
    raw = '{"decision": "buy", "reasoning_short": "Volume anomalo e breakout confermato."}'
    parsed = ai_trader.parse_decision(raw)
    assert parsed["decision"] == "BUY"


def test_parse_decision_non_valida_solleva_errore():
    with pytest.raises(ai_trader.DecisionParseError):
        ai_trader.parse_decision('{"decision": "MAYBE", "reasoning_short": "boh"}')


def test_parse_decision_senza_reasoning_solleva_errore():
    with pytest.raises(ai_trader.DecisionParseError):
        ai_trader.parse_decision('{"decision": "HOLD", "reasoning_short": ""}')


# ─── ai_trader.scanner_symbol_decision() ───────────────────────────────────


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeMessage:
    def __init__(self, text, input_tokens=1000, output_tokens=200):
        self.content = [FakeBlock(text)]
        self.usage = FakeUsage(input_tokens, output_tokens)


def test_scanner_symbol_decision_budget_esaurito_non_chiama_il_modello(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_MONTHLY_BUDGET_USD", 0.0)
    with patch("src.ai_trader.anthropic.Anthropic") as mock_client_cls:
        decision = ai_trader.scanner_symbol_decision(
            "RIVN", {"price": 10, "currency": "USD"}, {}, config.AI_TRADER_HAIKU_MODEL
        )
    assert decision["decision"] == "HOLD"
    assert decision.get("skipped_budget") is True
    mock_client_cls.assert_not_called()


def test_scanner_symbol_decision_successo_registra_il_costo(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    fake_text = '{"decision": "BUY", "reasoning_short": "Breakout netto con volume forte."}'
    mock_client = type("C", (), {})()
    mock_client.messages = type("M", (), {"create": lambda self, **kw: FakeMessage(fake_text)})()
    with patch("src.ai_trader.anthropic.Anthropic", return_value=mock_client):
        decision = ai_trader.scanner_symbol_decision(
            "RIVN", {"price": 10, "currency": "USD", "flagged": True}, {}, config.AI_TRADER_HAIKU_MODEL
        )
    assert decision["decision"] == "BUY"
    assert decision["cost_usd"] > 0
    assert budget.get_trader_spent_usd() == pytest.approx(decision["cost_usd"])


def test_scanner_symbol_decision_errore_modello_torna_hold(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader.anthropic.Anthropic", side_effect=RuntimeError("rete giù")):
        decision = ai_trader.scanner_symbol_decision(
            "RIVN", {"price": 10, "currency": "USD"}, {}, config.AI_TRADER_HAIKU_MODEL
        )
    assert decision["decision"] == "HOLD"
    assert decision["cost_usd"] == 0.0


# ─── ai_trader.decide_all(): instradamento Sonnet/Haiku/previsione ────────


def test_decide_all_instrada_sonnet_su_flagged_e_rispetta_il_tetto_giornaliero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "AI_TRADER_MAX_SONNET_CALLS_PER_DAY", 1)
    monkeypatch.setattr(config, "ASSETS", ["NVDA"])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["NVDA", "RIVN", "SOFI"])

    scanner_file = tmp_path / "scanner.json"
    scanner_file.write_text(json.dumps({
        "thresholds": {"volume_ratio": 2.0},
        "results": [
            {"symbol": "RIVN", "flagged": True, "price": 10, "currency": "USD"},
            {"symbol": "SOFI", "flagged": True, "price": 8, "currency": "USD"},
        ],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))

    used_models = []

    def fake_scanner_decision(symbol, row, thresholds, model):
        used_models.append((symbol, model))
        return {"symbol": symbol, "model_used": model, "decision": "HOLD", "reasoning_short": "x", "cost_usd": 0.0}

    with patch("src.ai_trader.scanner_symbol_decision", side_effect=fake_scanner_decision):
        decisions = ai_trader.decide_all()

    symbols = [d["symbol"] for d in decisions]
    assert "NVDA" in symbols  # asset core, previsione esistente
    assert dict(used_models)["RIVN"] in (config.AI_TRADER_SONNET_MODEL, config.AI_TRADER_HAIKU_MODEL)
    # con il tetto a 1, solo UNO dei due flagged usa Sonnet
    sonnet_count = sum(1 for _, m in used_models if m == config.AI_TRADER_SONNET_MODEL)
    assert sonnet_count == 1


def test_decide_all_salta_simboli_senza_riga_scanner(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ASSETS", [])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["RIVN"])
    monkeypatch.setattr(config, "SCANNER_FILE", str(tmp_path / "nessuno.json"))  # non esiste
    assert ai_trader.decide_all() == []


# ─── ai_trader_run: setup ──────────────────────────────────────────────────


def test_setup_idempotente_se_experiment_esiste(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "status": "running"}, fh)
    with patch("src.ai_trader_run.paper_trading.get_positions") as mock_positions:
        ai_trader_run.run_setup(dry_run=False)
    mock_positions.assert_not_called()


def test_setup_dry_run_non_chiude_posizioni(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[{"symbol": "QQQ", "qty": "1"}]), \
         patch("src.ai_trader_run.paper_trading.place_order") as mock_place:
        ai_trader_run.run_setup(dry_run=True)
    mock_place.assert_not_called()
    assert ai_trader_run.load_experiment() is None


def test_setup_reale_chiude_posizioni_e_fissa_experiment(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    order_resp = {"id": "ord-1", "symbol": "QQQ", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[{"symbol": "QQQ", "qty": "1"}]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99950.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)
    mock_place.assert_called_once_with(symbol="QQQ", side="sell", qty=1.0, time_in_force="day")
    experiment = ai_trader_run.load_experiment()
    assert experiment["status"] == "running"
    assert experiment["start_equity_usd"] == 99950.0
    history = storage.read_all(config.AI_TRADER_EQUITY_HISTORY_FILE)
    assert len(history) == 1
    assert history[0]["equity_usd"] == 99950.0
    with open(config.AI_TRADER_PORTFOLIO_HISTORY_FILE, encoding="utf-8") as fh:
        assert json.load(fh) == {"timestamp": [], "equity": []}


# ─── ai_trader_run: daily ──────────────────────────────────────────────────


def test_daily_senza_esperimento_non_fa_nulla(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_positions") as mock_positions:
        ai_trader_run.run_daily(dry_run=False)
    mock_positions.assert_not_called()


def test_daily_esperimento_scaduto_lo_segna_finished(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2020-01-01", "end_date": "2020-01-02", "status": "running"}, fh)
    with patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "123456"}):
        ai_trader_run.run_daily(dry_run=False)
    experiment = ai_trader_run.load_experiment()
    assert experiment["status"] == "finished"
    assert experiment["final_equity_usd"] == 123456.0


def test_daily_dry_run_non_chiama_ai_trader_decide_all(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader.decide_all") as mock_decide:
        ai_trader_run.run_daily(dry_run=True)
    mock_decide.assert_not_called()


def test_daily_stop_loss_vende_posizione_sotto_soglia(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    losing_position = {"symbol": "GME", "qty": "5", "unrealized_plpc": "-0.12"}
    order_resp = {"id": "ord-stop", "symbol": "GME", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[losing_position]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000", "buying_power": "50000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=[]):
        ai_trader_run.run_daily(dry_run=False)
    mock_place.assert_any_call(symbol="GME", side="sell", qty=5.0, time_in_force="day")


def test_setup_chiude_posizione_crypto_con_gtc_non_day(tmp_path, monkeypatch):
    """Bug reale scoperto in due run di setup falliti di fila: Alpaca
    rifiuta time_in_force='day' (il default) per una posizione crypto, ma
    GET /v2/positions ritorna il simbolo crypto SENZA slash (es. "BTCUSD",
    non "BTC/USD" come negli ordini) — quindi il riconoscimento deve usare
    asset_class="crypto" (il campo che Alpaca fornisce), non la presenza
    dello slash nella stringa del simbolo."""
    _isolate(tmp_path, monkeypatch)
    order_resp = {"id": "ord-btc", "symbol": "BTCUSD", "status": "accepted"}
    crypto_position = {"symbol": "BTCUSD", "qty": "0.5", "asset_class": "crypto"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[crypto_position]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99950.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)
    mock_place.assert_called_once_with(symbol="BTCUSD", side="sell", qty=0.5, time_in_force="gtc")


def test_setup_posizione_us_equity_senza_asset_class_resta_day(tmp_path, monkeypatch):
    """Una posizione azionaria normale (asset_class="us_equity", o il campo
    assente del tutto in un mock di test) non deve mai finire su 'gtc' —
    solo asset_class="crypto" lo giustifica."""
    _isolate(tmp_path, monkeypatch)
    order_resp = {"id": "ord-qqq", "symbol": "QQQ", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions",
               return_value=[{"symbol": "QQQ", "qty": "1", "asset_class": "us_equity"}]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99950.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)
    mock_place.assert_called_once_with(symbol="QQQ", side="sell", qty=1.0, time_in_force="day")


# ─── _cancel_resting_orders ─────────────────────────────────────────────────


def test_cancel_resting_orders_annulla_ogni_ordine_aperto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    open_orders = [{"id": "ord-1"}, {"id": "ord-2"}]
    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=open_orders), \
         patch("src.ai_trader_run.paper_trading.cancel_order") as mock_cancel:
        ai_trader_run._cancel_resting_orders("GME")
    assert mock_cancel.call_count == 2
    mock_cancel.assert_any_call("ord-1")
    mock_cancel.assert_any_call("ord-2")


def test_cancel_resting_orders_nessun_ordine_aperto_non_chiama_cancel(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.cancel_order") as mock_cancel:
        ai_trader_run._cancel_resting_orders("GME")
    mock_cancel.assert_not_called()


def test_cancel_resting_orders_errore_non_bloccante(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_open_orders",
               side_effect=paper_trading.AlpacaError("rete giù")):
        ai_trader_run._cancel_resting_orders("GME")  # non deve sollevare


def test_sell_to_close_annulla_ordini_aperti_prima_di_vendere(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    order_resp = {"id": "ord-sell", "symbol": "GME", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[{"id": "ord-stop-vecchio"}]) as mock_get_open, \
         patch("src.ai_trader_run.paper_trading.cancel_order") as mock_cancel, \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place:
        ai_trader_run._sell_to_close({"symbol": "GME", "qty": "3"})
    mock_get_open.assert_called_once_with(symbol="GME")
    mock_cancel.assert_called_once_with("ord-stop-vecchio")
    mock_place.assert_called_once_with(symbol="GME", side="sell", qty=3.0, time_in_force="day")


# ─── _attach_native_stop ─────────────────────────────────────────────────────


def test_attach_native_stop_piazza_ordine_con_stop_price_corretto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    position = {"symbol": "RIVN", "qty": "100", "avg_entry_price": "10.00"}
    order_resp = {"id": "ord-stop", "symbol": "RIVN", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place:
        ai_trader_run._attach_native_stop("RIVN")
    mock_place.assert_called_once_with(
        symbol="RIVN", side="sell", qty=100.0, order_type="stop", stop_price=9.2
    )


def test_attach_native_stop_nessuna_posizione_non_piazza_nulla(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order") as mock_place:
        ai_trader_run._attach_native_stop("RIVN")
    mock_place.assert_not_called()


def test_attach_native_stop_errore_non_bloccante(tmp_path, monkeypatch):
    """Se Alpaca rifiuta l'ordine stop, non deve far fallire tutto il run:
    la posizione resta comunque protetta dal controllo giornaliero
    (_check_stop_losses)."""
    _isolate(tmp_path, monkeypatch)
    position = {"symbol": "RIVN", "qty": "100", "avg_entry_price": "10.00"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_order",
               side_effect=paper_trading.AlpacaError("422 rifiutato")):
        ai_trader_run._attach_native_stop("RIVN")  # non deve sollevare


# ─── _save_portfolio_history_snapshot ───────────────────────────────────────


def test_save_portfolio_history_snapshot_scrive_il_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    fake_history = {"timestamp": [1, 2], "equity": [99987.08, 100100.0], "timeframe": "1D"}
    with patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value=fake_history) as mock_get:
        ai_trader_run._save_portfolio_history_snapshot("2026-10-31")
    mock_get.assert_called_once_with(start="2026-10-31", timeframe="1D")
    with open(config.AI_TRADER_PORTFOLIO_HISTORY_FILE, encoding="utf-8") as fh:
        assert json.load(fh) == fake_history


def test_save_portfolio_history_snapshot_errore_non_scrive_e_non_solleva(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_portfolio_history",
               side_effect=paper_trading.AlpacaError("rete giù")):
        ai_trader_run._save_portfolio_history_snapshot("2026-10-31")  # non deve sollevare
    import os as os_module
    assert not os_module.path.exists(config.AI_TRADER_PORTFOLIO_HISTORY_FILE)


# ─── run_daily: BUY piazza anche lo stop nativo ────────────────────────────


def test_daily_buy_piazza_anche_lo_stop_nativo(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    buy_decision = [{"symbol": "RIVN", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0}]
    buy_order_resp = {"id": "ord-buy", "symbol": "RIVN", "status": "accepted"}
    new_position = {"symbol": "RIVN", "qty": "500", "avg_entry_price": "14.0"}

    # Prima di decide_all(): nessuna posizione aperta. Dopo il BUY,
    # _attach_native_stop rilegge le posizioni e trova quella appena aperta.
    positions_sequence = [[], [new_position], [new_position]]

    with patch("src.ai_trader_run.paper_trading.get_positions", side_effect=positions_sequence), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=buy_order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "90000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=buy_decision):
        ai_trader_run.run_daily(dry_run=False)

    buy_call = mock_place.call_args_list[0]
    assert buy_call.kwargs == {"symbol": "RIVN", "side": "buy", "notional": config.AI_TRADER_POSITION_NOTIONAL_USD}
    stop_call = mock_place.call_args_list[1]
    assert stop_call.kwargs["order_type"] == "stop"
    assert stop_call.kwargs["symbol"] == "RIVN"
    assert stop_call.kwargs["stop_price"] == round(14.0 * 0.92, 2)


# ─── Resilienza: un titolo/una posizione con problemi non blocca gli altri ──
# (audit di affidabilità richiesto dall'utente il 2026-10-31)


def test_check_stop_losses_un_fallimento_non_blocca_le_altre_posizioni(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    losing_positions = [
        {"symbol": "AAA", "qty": "5", "unrealized_plpc": "-0.12"},
        {"symbol": "BBB", "qty": "3", "unrealized_plpc": "-0.20"},
    ]
    order_resp = {"id": "ord-1", "symbol": "BBB", "status": "accepted"}

    def fake_place_order(symbol, **kwargs):
        if symbol == "AAA":
            raise paper_trading.AlpacaError("422 titolo sospeso")
        return order_resp

    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", side_effect=fake_place_order):
        sold = ai_trader_run._check_stop_losses(losing_positions)
    # AAA fallisce ma non impedisce a BBB di essere venduta
    assert sold == ["BBB"]


def test_run_daily_un_ordine_fallito_non_blocca_gli_altri_titoli(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    decisions = [
        {"symbol": "AAA", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0},
        {"symbol": "BBB", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0},
    ]

    def fake_place_order(symbol, **kwargs):
        if symbol == "AAA":
            raise paper_trading.AlpacaError("422 titolo non tradabile")
        return {"id": "ord-bbb", "symbol": "BBB", "status": "accepted"}

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", side_effect=fake_place_order) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "90000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=decisions):
        ai_trader_run.run_daily(dry_run=False)  # non deve sollevare

    # BBB deve essere stato tentato nonostante AAA sia fallito prima di lui
    symbols_tried = [call.kwargs.get("symbol") for call in mock_place.call_args_list]
    assert "BBB" in symbols_tried


def test_run_setup_una_chiusura_fallita_non_impedisce_experiment_json(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    positions = [{"symbol": "AAA", "qty": "1"}, {"symbol": "BBB", "qty": "1"}]

    def fake_place_order(symbol, **kwargs):
        if symbol == "AAA":
            raise paper_trading.AlpacaError("422 rifiutato")
        return {"id": "ord-bbb", "symbol": "BBB", "status": "accepted"}

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=positions), \
         patch("src.ai_trader_run.paper_trading.place_order", side_effect=fake_place_order), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)  # non deve sollevare
    experiment = ai_trader_run.load_experiment()
    assert experiment is not None
    assert experiment["status"] == "running"


def test_decide_all_asset_che_solleva_torna_hold_invece_di_bloccare(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ASSETS", ["NVDA", "AAPL"])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["NVDA", "AAPL"])
    monkeypatch.setattr(config, "SCANNER_FILE", str(tmp_path / "nessuno.json"))

    def fake_core_decision(asset):
        if asset == "NVDA":
            raise RuntimeError("predictions.jsonl corrotto")
        return {"symbol": asset, "model_used": "previsione_esistente", "decision": "BUY",
                "reasoning_short": "x", "cost_usd": 0.0}

    with patch("src.ai_trader.core_asset_decision", side_effect=fake_core_decision):
        decisions = ai_trader.decide_all()

    by_symbol = {d["symbol"]: d for d in decisions}
    assert by_symbol["AAPL"]["decision"] == "BUY"
    assert by_symbol["NVDA"]["decision"] == "HOLD"  # fallback di sicurezza, non un crash


def test_load_scanner_results_json_corrotto_torna_vuoto(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    bad_file = tmp_path / "scanner_corrotto.json"
    bad_file.write_text("{non è json valido")
    monkeypatch.setattr(config, "SCANNER_FILE", str(bad_file))
    assert ai_trader.load_scanner_results() == {}


def test_budget_file_corrotto_blocca_la_spesa_invece_di_azzerarla(tmp_path, monkeypatch):
    """Fail-safe deliberato: un file di stato illeggibile deve far
    assumere 'tetto raggiunto', mai 'zero speso' — altrimenti un file
    corrotto proprio vicino al limite potrebbe far sforare il tetto
    mensile reale."""
    _isolate(tmp_path, monkeypatch)
    year, month = __import__("datetime").date.today().year, __import__("datetime").date.today().month
    bad_file = tmp_path / "_state" / f"ai_trader_budget_{year}-{month:02d}.json"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("{corrotto")
    assert budget.get_trader_spent_usd() == config.AI_TRADER_MONTHLY_BUDGET_USD
    assert budget.trader_has_budget() is False


# ─── _update_benchmarks: aggancio a benchmark.py, mai bloccante ────────────


def test_run_setup_chiama_i_due_benchmark(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(ai_trader_run.benchmark, "update_buy_hold", lambda *a, **k: calls.append("buyhold"))
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: calls.append("momentum"))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)

    assert calls == ["buyhold", "momentum"]


def test_run_daily_chiama_i_due_benchmark(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    calls = []
    monkeypatch.setattr(ai_trader_run.benchmark, "update_buy_hold", lambda *a, **k: calls.append("buyhold"))
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: calls.append("momentum"))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value={"id": "x", "status": "accepted"}), \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "90000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=[]):
        ai_trader_run.run_daily(dry_run=False)

    assert calls == ["buyhold", "momentum"]


def test_un_benchmark_fallito_non_blocca_laltro_ne_il_trading_reale(tmp_path, monkeypatch):
    """Resilienza: i due benchmark sono richieste di rete indipendenti dal
    trading reale — se una fallisce (Yahoo giù, ticker senza dati),
    l'esperimento vero deve comunque aggiornarsi e l'altro benchmark deve
    comunque essere provato."""
    _isolate(tmp_path, monkeypatch)
    momentum_calls = []
    monkeypatch.setattr(ai_trader_run.benchmark, "update_buy_hold",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Yahoo giù")))
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum",
                         lambda *a, **k: momentum_calls.append(1))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)  # non deve sollevare

    assert momentum_calls == [1]  # provato comunque, nonostante l'altro sia fallito
    experiment = ai_trader_run.load_experiment()
    assert experiment is not None and experiment["status"] == "running"
