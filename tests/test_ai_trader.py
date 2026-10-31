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
    monkeypatch.setattr(config, "PAPER_ORDERS_FILE", str(tmp_path / "orders.jsonl"))
    monkeypatch.setattr(config, "PAPER_ACCOUNT_FILE", str(tmp_path / "account.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")


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
         patch("src.ai_trader_run.paper_trading.snapshot_account"):
        ai_trader_run.run_setup(dry_run=False)
    mock_place.assert_called_once_with(symbol="QQQ", side="sell", qty=1.0, time_in_force="day")
    experiment = ai_trader_run.load_experiment()
    assert experiment["status"] == "running"
    assert experiment["start_equity_usd"] == 99950.0
    history = storage.read_all(config.AI_TRADER_EQUITY_HISTORY_FILE)
    assert len(history) == 1
    assert history[0]["equity_usd"] == 99950.0


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
         patch("src.ai_trader.decide_all", return_value=[]):
        ai_trader_run.run_daily(dry_run=False)
    mock_place.assert_any_call(symbol="GME", side="sell", qty=5.0, time_in_force="day")


def test_setup_chiude_posizione_crypto_con_gtc_non_day(tmp_path, monkeypatch):
    """Bug reale scoperto al primo run di setup: Alpaca rifiuta
    time_in_force='day' (il default) per un simbolo crypto come BTC/USD,
    che la posizione manuale precedente aveva davvero."""
    _isolate(tmp_path, monkeypatch)
    order_resp = {"id": "ord-btc", "symbol": "BTC/USD", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[{"symbol": "BTC/USD", "qty": "0.5"}]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99950.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"):
        ai_trader_run.run_setup(dry_run=False)
    mock_place.assert_called_once_with(symbol="BTC/USD", side="sell", qty=0.5, time_in_force="gtc")
