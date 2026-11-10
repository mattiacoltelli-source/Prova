"""Test unitari per src/ai_trader.py, src/ai_trader_run.py e il tetto di
spesa mensile in dollari aggiunto a src/budget.py.

Nessuna chiamata di rete/Anthropic reale: il client è sempre mockato (vedi
FakeAnthropicClient sotto, stesso spirito di FakeResponse in
test_paper_trading.py per requests)."""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import pytest

from src import ai_trader, ai_trader_run, budget, config, paper_trading, storage


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "_state"))
    monkeypatch.setattr(config, "AI_TRADER_DECISIONS_FILE", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_DECISIONS_DAYS_DIR", str(tmp_path / "decisions_by_day"))
    # Nessun prezzo di riferimento di default: i test storici di run_daily
    # esercitano l'acquisto a importo; quelli ad azioni intere scrivono il file.
    monkeypatch.setattr(config, "SCANNER_FILE", str(tmp_path / "scanner_assente.json"))
    monkeypatch.setattr(ai_trader_run.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "AI_TRADER_EXPERIMENT_FILE", str(tmp_path / "experiment.json"))
    monkeypatch.setattr(config, "AI_TRADER_EQUITY_HISTORY_FILE", str(tmp_path / "equity_history.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_PORTFOLIO_HISTORY_FILE", str(tmp_path / "portfolio_history.json"))
    monkeypatch.setattr(config, "AI_TRADER_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PAPER_ORDERS_FILE", str(tmp_path / "orders.jsonl"))
    monkeypatch.setattr(config, "PAPER_ACCOUNT_FILE", str(tmp_path / "account.json"))
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_FILE", str(tmp_path / "benchmark_momentum.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_MEANREV_FILE", str(tmp_path / "benchmark_meanrev.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_REAL_TRADES_FILE", str(tmp_path / "trades_real.json"))
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_TRADES_FILE", str(tmp_path / "trades_momentum.json"))
    monkeypatch.setattr(config, "AI_TRADER_MEANREV_TRADES_FILE", str(tmp_path / "trades_meanrev.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    # _update_benchmarks e _update_trade_dashboards girano dopo ogni
    # setup/daily: senza questi no-op, ogni test di run_setup/run_daily
    # farebbe una vera chiamata di rete a Yahoo Finance e/o Alpaca (lenta,
    # flaky, contro il principio "nessuna chiamata di rete reale" dichiarato
    # in cima a questo file). I test dedicati all'integrazione sotto
    # sovrascrivono di nuovo questi mock per verificare che vengano
    # chiamati davvero.
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: None)
    monkeypatch.setattr(ai_trader_run.benchmark, "update_mean_reversion", lambda *a, **k: None)
    monkeypatch.setattr(ai_trader_run, "_update_trade_dashboards", lambda *a, **k: None)
    # Il controllo weekend/festività (_is_us_market_day) non deve rendere
    # flaky i test esistenti a seconda del giorno reale in cui gira la
    # suite (es. CI che gira di sabato, o in un giorno della lista
    # AI_TRADER_US_MARKET_HOLIDAYS): nessuno dei test sotto vuole verificare
    # QUESTO comportamento, lo fanno solo i test dedicati più in basso, che
    # sovrascrivono di nuovo questo mock.
    monkeypatch.setattr(ai_trader_run, "_is_us_market_day", lambda d: True)


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


def test_scanner_symbol_decision_parsing_fallito_registra_comunque_il_costo(tmp_path, monkeypatch):
    """Bug reale trovato in un code review pre-lancio, 2026-11-01:
    record_trader_call_cost() addebita il budget PRIMA di parse_decision().
    Se la risposta del modello non è JSON valido, il except tornava sempre
    cost_usd:0.0 anche se la spesa reale era già stata registrata nel file
    di stato mensile — qui la chiamata riesce (addebito reale) ma la
    risposta è malformata, quindi cost_usd deve riflettere la spesa vera,
    non azzerarsi."""
    _isolate(tmp_path, monkeypatch)
    fake_text = "risposta non JSON, troncata a metà"
    mock_client = type("C", (), {})()
    mock_client.messages = type("M", (), {"create": lambda self, **kw: FakeMessage(fake_text)})()
    with patch("src.ai_trader.anthropic.Anthropic", return_value=mock_client):
        decision = ai_trader.scanner_symbol_decision(
            "RIVN", {"price": 10, "currency": "USD"}, {}, config.AI_TRADER_HAIKU_MODEL
        )
    assert decision["decision"] == "HOLD"
    assert decision["cost_usd"] > 0
    assert budget.get_trader_spent_usd() == pytest.approx(decision["cost_usd"])


# ─── ai_trader.decide_all(): instradamento Sonnet/Haiku/previsione ────────


def test_decide_all_instrada_sonnet_su_flagged_e_rispetta_il_tetto_giornaliero(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "AI_TRADER_MAX_SONNET_CALLS_PER_DAY", 1)
    monkeypatch.setattr(config, "ASSETS", ["NVDA"])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["NVDA", "RIVN", "SOFI"])

    scanner_file = tmp_path / "scanner.json"
    scanner_file.write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
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


def test_decide_all_registra_lo_stato_di_salute_dati(tmp_path, monkeypatch):
    """decide_all() deve scrivere data_health_ai_judgment.json con solo i
    simboli davvero passati per una chiamata Anthropic falliti (non quelli
    saltati per budget esaurito o riga scanner mancante) — src/data_health.py,
    richiesto dall'utente il 2026-11-02 ("se qualche API non va, voglio che
    sia segnalato")."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ASSETS", [])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["RIVN", "SOFI", "PLTR"])

    scanner_file = tmp_path / "scanner.json"
    scanner_file.write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "thresholds": {},
        "results": [
            {"symbol": "RIVN", "flagged": False, "price": 10, "currency": "USD"},
            {"symbol": "SOFI", "flagged": False, "price": 8, "currency": "USD"},
            # PLTR assente: nessuna riga scanner, saltato — non conta come
            # fallimento dell'API, "attempted" deve essere 2, non 3.
        ],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))

    def fake_scanner_decision(symbol, row, thresholds, model):
        if symbol == "SOFI":
            raise RuntimeError("401 Unauthorized")
        return {"symbol": symbol, "model_used": model, "decision": "HOLD", "reasoning_short": "x", "cost_usd": 0.0}

    with patch("src.ai_trader.scanner_symbol_decision", side_effect=fake_scanner_decision):
        ai_trader.decide_all()

    with open(f"{config.STATE_DIR}/data_health_ai_judgment.json", encoding="utf-8") as fh:
        health = json.load(fh)
    assert health["total"] == 2
    assert health["failed_symbols"] == ["SOFI"]


def test_decide_all_skipped_budget_non_conta_come_errore_api(tmp_path, monkeypatch):
    """Un HOLD per budget esaurito non è un fallimento dell'API (già
    segnalato a parte dalla card budget) — non deve far scattare l'allarme
    salute dati."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "ASSETS", [])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["RIVN"])
    monkeypatch.setattr(config, "AI_TRADER_MONTHLY_BUDGET_USD", 0.0)

    scanner_file = tmp_path / "scanner.json"
    scanner_file.write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "thresholds": {},
        "results": [{"symbol": "RIVN", "flagged": False, "price": 10, "currency": "USD"}],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))

    with patch("src.ai_trader.anthropic.Anthropic") as mock_client_cls:
        ai_trader.decide_all()
    mock_client_cls.assert_not_called()

    with open(f"{config.STATE_DIR}/data_health_ai_judgment.json", encoding="utf-8") as fh:
        health = json.load(fh)
    assert health["failed_symbols"] == []
    assert health["alert"] is False


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


# ─── _is_us_market_day: weekend e festività USA ────────────────────────────


def test_is_us_market_day_giorno_feriale_normale():
    assert ai_trader_run._is_us_market_day(dt.date(2027, 1, 19)) is True  # martedì normale


def test_is_us_market_day_weekend_falso():
    assert ai_trader_run._is_us_market_day(dt.date(2027, 1, 23)) is False  # sabato
    assert ai_trader_run._is_us_market_day(dt.date(2027, 1, 24)) is False  # domenica


def test_is_us_market_day_festivita_falso():
    # Ogni data elencata in config.AI_TRADER_US_MARKET_HOLIDAYS dev'essere
    # riconosciuta come non di mercato, non solo quella usata per il test
    # dedicato sotto — copre tutte e sei in un colpo solo.
    for iso_date in config.AI_TRADER_US_MARKET_HOLIDAYS:
        d = dt.date.fromisoformat(iso_date)
        assert ai_trader_run._is_us_market_day(d) is False, f"{iso_date} dovrebbe essere festività"


def test_is_us_market_day_thanksgiving_falso():
    assert ai_trader_run._is_us_market_day(dt.date(2026, 11, 26)) is False


def test_daily_rispetta_is_us_market_day_falso(tmp_path, monkeypatch):
    """Bug reale trovato in un code review pre-lancio, 2026-11-01: run_daily
    non aveva nessun controllo su weekend/festività, quindi un run di
    festività chiamava comunque i modelli pagati su un mercato fermo.
    Verifica il collegamento (run_daily chiama davvero _is_us_market_day e
    si ferma se torna False) senza dover simulare una data specifica —
    _is_us_market_day stesso è già testato a parte sopra, su tutte e sei le
    festività elencate più il weekend."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_trader_run, "_is_us_market_day", lambda d: False)
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": "2027-06-01", "status": "running"}, fh)
    with patch("src.ai_trader_run.paper_trading.get_positions") as mock_positions:
        ai_trader_run.run_daily(dry_run=False)
    mock_positions.assert_not_called()


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


def test_daily_riusa_decisioni_gia_registrate_oggi(tmp_path, monkeypatch):
    """Bug reale trovato in un code review pre-lancio, 2026-11-01: run_daily
    non aveva nessuna protezione contro una seconda esecuzione lo stesso
    giorno (es. rilancio manuale dopo un run fallito a metà) — decide_all()
    richiamava di nuovo tutti i modelli a pagamento, duplicando sia la spesa
    sul budget mensile sia le righe in decisions.jsonl. Qui una decisione
    BUY per NVDA è già registrata per oggi: run_daily non deve richiamare
    decide_all(), ma deve comunque piazzare l'ordine (recuperabilità di un
    run parziale: la decisione già presa va comunque eseguita)."""
    _isolate(tmp_path, monkeypatch)
    end_date = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)
    storage.append_record(config.AI_TRADER_DECISIONS_FILE, {
        "symbol": "NVDA", "model_used": config.AI_TRADER_HAIKU_MODEL, "decision": "BUY",
        "reasoning_short": "Decisione già presa in un run precedente oggi.",
        "cost_usd": 0.01, "date": dt.date.today().isoformat(),
    })
    order_resp = {"id": "ord-nvda", "symbol": "NVDA", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000", "buying_power": "50000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all") as mock_decide:
        ai_trader_run.run_daily(dry_run=False)
    mock_decide.assert_not_called()
    mock_place.assert_any_call(symbol="NVDA", side="buy", notional=config.ai_trader_position_notional(99000.0))
    # una sola riga per oggi: non è stata duplicata
    today_decisions = [d for d in storage.read_all(config.AI_TRADER_DECISIONS_FILE) if d["date"] == dt.date.today().isoformat()]
    assert len(today_decisions) == 1


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
    # Prima lettura: l'ordine c'è; seconda (dopo l'annullamento): sparito.
    with patch("src.ai_trader_run.paper_trading.get_open_orders", side_effect=[[{"id": "ord-stop-vecchio"}], []]) as mock_get_open, \
         patch("src.ai_trader_run.paper_trading.cancel_order") as mock_cancel, \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=order_resp) as mock_place:
        ai_trader_run._sell_to_close({"symbol": "GME", "qty": "3"})
    assert mock_get_open.call_count == 2   # controllo + attesa che l'annullamento sia effettivo
    mock_cancel.assert_called_once_with("ord-stop-vecchio")
    mock_place.assert_called_once_with(symbol="GME", side="sell", qty=3.0, time_in_force="day")


# ─── config.ai_trader_position_notional (esposizione a scaglioni) ─────────


def test_position_notional_fascia_piu_bassa_sotto_50k():
    assert config.ai_trader_position_notional(25_000.0) == 1_000.0


def test_position_notional_seconda_fascia_50k_70k():
    assert config.ai_trader_position_notional(60_000.0) == 1_500.0


def test_position_notional_terza_fascia_replica_il_comportamento_precedente():
    # Equity di partenza dell'esperimento: deve dare lo stesso risultato
    # dei $2.500 fissi di prima del passaggio a scaglioni.
    assert config.ai_trader_position_notional(100_000.0) == 2_500.0


def test_position_notional_fascia_piu_alta_sopra_130k():
    assert config.ai_trader_position_notional(150_000.0) == 3_000.0


def test_position_notional_confine_esatto_50k_e_gia_seconda_fascia():
    # "< 50.000" esclude il confine stesso: a 50.000 esatti si è già nella
    # seconda fascia ($1.500), non nella prima.
    assert config.ai_trader_position_notional(50_000.0) == 1_500.0


def test_position_notional_confine_esatto_70k_e_gia_terza_fascia():
    assert config.ai_trader_position_notional(70_000.0) == 2_500.0


def test_position_notional_confine_esatto_130k_e_gia_quarta_fascia():
    assert config.ai_trader_position_notional(130_000.0) == 3_000.0


# ─── _attach_native_exit ─────────────────────────────────────────────────────


def test_attach_native_exit_piazza_oco_con_stop_e_take_profit_corretti(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    monkeypatch.setattr(config, "AI_TRADER_TAKE_PROFIT_PCT", 16.0)
    position = {"symbol": "RIVN", "qty": "100", "avg_entry_price": "10.00"}
    order_resp = {"id": "ord-oco", "symbol": "RIVN", "status": "accepted"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order", return_value=order_resp) as mock_place:
        ai_trader_run._attach_native_exit("RIVN")
    mock_place.assert_called_once_with(
        symbol="RIVN", qty=100.0, stop_price=9.2, take_profit_price=11.6, time_in_force="gtc"
    )


def test_attach_native_exit_nessuna_posizione_non_piazza_nulla(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order") as mock_place:
        ai_trader_run._attach_native_exit("RIVN")
    mock_place.assert_not_called()


def test_attach_native_exit_errore_non_bloccante(tmp_path, monkeypatch):
    """Se Alpaca rifiuta l'ordine OCO, non deve far fallire tutto il run: la
    posizione resta comunque protetta sul lato stop-loss dal controllo
    giornaliero (_check_stop_losses) — il take-profit no, ma non è un
    rischio di perdita."""
    _isolate(tmp_path, monkeypatch)
    position = {"symbol": "RIVN", "qty": "100", "avg_entry_price": "10.00"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order",
               side_effect=paper_trading.AlpacaError("422 rifiutato")):
        ai_trader_run._attach_native_exit("RIVN")  # non deve sollevare


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


# ─── run_daily: BUY piazza anche la coppia OCO stop/take-profit ───────────


def test_daily_buy_piazza_anche_stop_e_take_profit_nativi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    monkeypatch.setattr(config, "AI_TRADER_TAKE_PROFIT_PCT", 16.0)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    buy_decision = [{"symbol": "RIVN", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0}]
    buy_order_resp = {"id": "ord-buy", "symbol": "RIVN", "status": "accepted"}
    oco_order_resp = {"id": "ord-oco", "symbol": "RIVN", "status": "accepted"}
    new_position = {"symbol": "RIVN", "qty": "500", "avg_entry_price": "14.0"}

    # Prima di decide_all(): nessuna posizione aperta. Dopo il BUY,
    # _attach_native_exit rilegge le posizioni e trova quella appena aperta.
    positions_sequence = [[], [new_position], [new_position]]

    with patch("src.ai_trader_run.paper_trading.get_positions", side_effect=positions_sequence), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=buy_order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order", return_value=oco_order_resp) as mock_oco, \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "90000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=buy_decision):
        ai_trader_run.run_daily(dry_run=False)

    buy_call = mock_place.call_args_list[0]
    assert buy_call.kwargs == {"symbol": "RIVN", "side": "buy", "notional": config.ai_trader_position_notional(100000.0)}
    mock_oco.assert_called_once_with(
        symbol="RIVN", qty=500.0, stop_price=round(14.0 * 0.92, 2), take_profit_price=round(14.0 * 1.16, 2),
        time_in_force="gtc",
    )


# ─── run_daily: tetto del 35% di esposizione (AI_TRADER_MAX_EXPOSURE_PCT) ──


def test_daily_buy_bloccato_se_supererebbe_il_35_percento_investito(tmp_path, monkeypatch):
    """A equity $100.000 il tetto è $35.000. Una posizione esistente da
    $34.000 lascia solo $1.000 di margine: un BUY da $2.500 (lo scaglione a
    quell'equity) lo sfonderebbe (36.500) e deve essere saltato, anche se
    il conto avrebbe sia il buying power sia uno slot libero su 14."""
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    existing_position = {"symbol": "ZZZ", "qty": "100", "market_value": "34000"}
    buy_decision = [{"symbol": "RIVN", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0}]

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[existing_position]), \
         patch("src.ai_trader_run.paper_trading.place_order") as mock_place, \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "50000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=buy_decision):
        ai_trader_run.run_daily(dry_run=False)

    mock_place.assert_not_called()


def test_daily_buy_entra_se_resta_sotto_il_35_percento(tmp_path, monkeypatch):
    """Stesso scenario della prova sopra ma con $1.000 di posizione esistente
    invece di $34.000: il BUY da $2.500 resta sotto il tetto (3.500 <=
    35.000) e deve partire normalmente."""
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    existing_position = {"symbol": "ZZZ", "qty": "10", "market_value": "1000"}
    buy_decision = [{"symbol": "RIVN", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0}]
    buy_order_resp = {"id": "ord-buy", "symbol": "RIVN", "status": "accepted"}

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[existing_position]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value=buy_order_resp) as mock_place, \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order"), \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "50000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=buy_decision):
        ai_trader_run.run_daily(dry_run=False)

    mock_place.assert_called_once_with(symbol="RIVN", side="buy", notional=2500.0)


def test_daily_registra_lo_stato_di_salute_ordini_alpaca(tmp_path, monkeypatch):
    """Un ordine rifiutato da Alpaca deve finire in
    data_health_alpaca_orders.json, non solo stampato nei log — src/data_health.py,
    richiesto dall'utente il 2026-11-02 ("se qualche API non va, voglio
    che sia segnalato")."""
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    decisions = [
        {"symbol": "RIVN", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0},
        {"symbol": "SOFI", "decision": "BUY", "reasoning_short": "x", "model_used": "haiku", "cost_usd": 0.0},
    ]
    ok_resp = {"id": "ord-ok", "symbol": "SOFI", "status": "accepted"}

    def fake_place_order(symbol, **kwargs):
        if symbol == "RIVN":
            raise paper_trading.AlpacaError("422 titolo sospeso")
        return ok_resp

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", side_effect=fake_place_order), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order"), \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "50000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=decisions):
        ai_trader_run.run_daily(dry_run=False)

    with open(f"{config.STATE_DIR}/data_health_alpaca_orders.json", encoding="utf-8") as fh:
        health = json.load(fh)
    assert health["total"] == 2
    assert health["failed_symbols"] == ["RIVN"]


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


def test_load_scanner_results_dati_di_oggi_vengono_letti(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    scanner_file = tmp_path / "scanner_oggi.json"
    scanner_file.write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "results": [{"symbol": "RIVN", "price": 10}],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))
    assert "RIVN" in ai_trader.load_scanner_results()


def test_load_scanner_results_dati_vecchi_tornano_vuoto(tmp_path, monkeypatch):
    """Bug reale trovato in un code review pre-lancio, 2026-11-01: senza
    questo controllo, uno scanner bloccato da giorni/settimane (market_scanner.yml
    fallito in silenzio) veniva letto come se fosse di oggi, facendo
    decidere l'AI su dati vecchi senza nessun segnale dell'anomalia.
    Deterministico (non dipende dal giorno della settimana): la chiusura
    dell'ultima seduta è fissata a ieri, il file è di 3 giorni fa."""
    _isolate(tmp_path, monkeypatch)
    now = dt.datetime.now(dt.timezone.utc)
    monkeypatch.setattr(ai_trader, "last_session_close_utc", lambda n: now - dt.timedelta(days=1))
    scanner_file = tmp_path / "scanner_vecchio.json"
    scanner_file.write_text(json.dumps({
        "generated_at": (now - dt.timedelta(days=3)).isoformat(),
        "results": [{"symbol": "RIVN", "price": 10}],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))
    assert ai_trader.load_scanner_results() == {}


def test_load_scanner_results_senza_generated_at_torna_vuoto(tmp_path, monkeypatch):
    """Un file scanner reale ha sempre generated_at (vedi market_scanner.scan());
    se manca è un dato sospetto, non va trattato come fresco."""
    _isolate(tmp_path, monkeypatch)
    scanner_file = tmp_path / "scanner_senza_data.json"
    scanner_file.write_text(json.dumps({"results": [{"symbol": "RIVN", "price": 10}]}))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))
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


def test_run_setup_chiama_update_benchmarks(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: calls.append("momentum"))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)

    assert calls == ["momentum"]


def test_run_daily_chiama_update_benchmarks(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    end_date = (__import__("datetime").date.today() + __import__("datetime").timedelta(days=30)).isoformat()
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump({"start_date": "2026-01-01", "end_date": end_date, "status": "running"}, fh)

    calls = []
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum", lambda *a, **k: calls.append("momentum"))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value={"id": "x", "status": "accepted"}), \
         patch("src.ai_trader_run.paper_trading.get_account",
               return_value={"equity": "100000", "buying_power": "90000"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}), \
         patch("src.ai_trader.decide_all", return_value=[]):
        ai_trader_run.run_daily(dry_run=False)

    assert calls == ["momentum"]


def test_un_benchmark_fallito_non_blocca_il_trading_reale(tmp_path, monkeypatch):
    """Resilienza: il confronto Momentum è una richiesta di rete
    indipendente dal trading reale — se fallisce (Yahoo giù, ticker senza
    dati), l'esperimento vero deve comunque aggiornarsi."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ai_trader_run.benchmark, "update_momentum",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Yahoo giù")))

    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value={"equity": "99000.0"}), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run.paper_trading.get_portfolio_history", return_value={"timestamp": [], "equity": []}):
        ai_trader_run.run_setup(dry_run=False)  # non deve sollevare

    experiment = ai_trader_run.load_experiment()
    assert experiment is not None and experiment["status"] == "running"


# ─── _update_trade_dashboards: i due elenchi di operazioni, mai bloccanti ──


def test_update_trade_dashboards_scrive_i_due_file_json(tmp_path, monkeypatch):
    # Catturato PRIMA di _isolate: quella funzione sostituisce
    # ai_trader_run._update_trade_dashboards con un no-op per tutti gli
    # altri test (vedi commento lì) — questi tre test vogliono invece
    # verificare la funzione VERA, quindi tengono un riferimento diretto
    # all'oggetto funzione originale, non al nome del modulo (che dopo
    # _isolate punterebbe al no-op).
    real_update_trade_dashboards = ai_trader_run._update_trade_dashboards
    _isolate(tmp_path, monkeypatch)
    experiment = {"start_date": "2026-10-31", "start_equity_usd": 100000.0}
    fills = [
        {"symbol": "NVDA", "side": "buy", "qty": "10", "price": "100.0",
         "transaction_time": "2026-10-31T14:30:00Z"},
        {"symbol": "NVDA", "side": "sell", "qty": "10", "price": "110.0",
         "transaction_time": "2026-11-02T14:30:00Z"},
    ]
    from src import storage as storage_module
    storage_module.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAPL": 1.0}, "entry_prices": {"AAPL": 50.0},
        "mark_prices": {"AAPL": 50.0}, "exit_prices": {},
    })

    with patch("src.ai_trader_run.paper_trading.get_activities", return_value=fills) as mock_activities, \
         patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]):
        real_update_trade_dashboards(experiment)

    mock_activities.assert_called_once_with(after="2026-10-31")

    with open(config.AI_TRADER_REAL_TRADES_FILE, encoding="utf-8") as fh:
        real_trades = json.load(fh)
    assert len(real_trades["closed"]) == 1
    assert real_trades["closed"][0]["symbol"] == "NVDA"
    assert real_trades["closed"][0]["pl_usd"] == 100.0

    with open(config.AI_TRADER_MOMENTUM_TRADES_FILE, encoding="utf-8") as fh:
        momentum_trades = json.load(fh)
    assert len(momentum_trades["open"]) == 1
    assert momentum_trades["open"][0]["symbol"] == "AAPL"


def test_update_trade_dashboards_reale_fallito_non_blocca_momentum(tmp_path, monkeypatch):
    real_update_trade_dashboards = ai_trader_run._update_trade_dashboards
    _isolate(tmp_path, monkeypatch)
    experiment = {"start_date": "2026-10-31", "start_equity_usd": 100000.0}
    from src import storage as storage_module
    storage_module.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {}, "entry_prices": {}, "mark_prices": {}, "exit_prices": {},
    })

    with patch("src.ai_trader_run.paper_trading.get_activities",
               side_effect=RuntimeError("Alpaca giù")):
        real_update_trade_dashboards(experiment)  # non deve sollevare

    import os as os_module
    assert not os_module.path.exists(config.AI_TRADER_REAL_TRADES_FILE)
    assert os_module.path.exists(config.AI_TRADER_MOMENTUM_TRADES_FILE)


def test_update_trade_dashboards_momentum_fallito_non_blocca_reale(tmp_path, monkeypatch):
    real_update_trade_dashboards = ai_trader_run._update_trade_dashboards
    _isolate(tmp_path, monkeypatch)
    experiment = {"start_date": "2026-10-31", "start_equity_usd": 100000.0}
    # AI_TRADER_MOMENTUM_FILE non esiste: storage.read_all torna [] (non un
    # errore) — per forzare davvero un fallimento lato Momentum, il modo più
    # realistico è un file corrotto piuttosto che un file assente.
    with open(config.AI_TRADER_MOMENTUM_FILE, "w", encoding="utf-8") as fh:
        fh.write("{non è jsonl valido")

    with patch("src.ai_trader_run.paper_trading.get_activities", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]):
        real_update_trade_dashboards(experiment)  # non deve sollevare

    import os as os_module
    assert os_module.path.exists(config.AI_TRADER_REAL_TRADES_FILE)  # scritto comunque
    assert not os_module.path.exists(config.AI_TRADER_MOMENTUM_TRADES_FILE)  # mai arrivato a scriverlo


def test_update_trade_dashboards_scrive_anche_mean_reversion(tmp_path, monkeypatch):
    """Specchio di test_update_trade_dashboards_scrive_i_due_file_json: ora
    sono tre file, non due — stesso principio, terza strategia."""
    real_update_trade_dashboards = ai_trader_run._update_trade_dashboards
    _isolate(tmp_path, monkeypatch)
    experiment = {"start_date": "2026-10-31", "start_equity_usd": 100000.0}
    from src import storage as storage_module
    storage_module.append_record(config.AI_TRADER_MEANREV_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"SOFI": 1.0}, "entry_prices": {"SOFI": 15.0},
        "mark_prices": {"SOFI": 15.0}, "exit_prices": {},
    })

    with patch("src.ai_trader_run.paper_trading.get_activities", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]):
        real_update_trade_dashboards(experiment)

    with open(config.AI_TRADER_MEANREV_TRADES_FILE, encoding="utf-8") as fh:
        meanrev_trades = json.load(fh)
    assert len(meanrev_trades["open"]) == 1
    assert meanrev_trades["open"][0]["symbol"] == "SOFI"


def test_update_trade_dashboards_mean_reversion_fallito_non_blocca_le_altre(tmp_path, monkeypatch):
    real_update_trade_dashboards = ai_trader_run._update_trade_dashboards
    _isolate(tmp_path, monkeypatch)
    experiment = {"start_date": "2026-10-31", "start_equity_usd": 100000.0}
    # Stesso trucco di test_update_trade_dashboards_momentum_fallito_non_blocca_reale:
    # un file corrotto, non assente (assente torna [] senza errore).
    with open(config.AI_TRADER_MEANREV_FILE, "w", encoding="utf-8") as fh:
        fh.write("{non è jsonl valido")

    with patch("src.ai_trader_run.paper_trading.get_activities", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]):
        real_update_trade_dashboards(experiment)  # non deve sollevare

    import os as os_module
    assert os_module.path.exists(config.AI_TRADER_REAL_TRADES_FILE)  # scritto comunque
    assert os_module.path.exists(config.AI_TRADER_MOMENTUM_TRADES_FILE)  # scritto comunque
    assert not os_module.path.exists(config.AI_TRADER_MEANREV_TRADES_FILE)  # mai arrivato a scriverlo


# ─── Rinnovo quotidiano della coppia OCO (scade a fine sessione, "day") ────


def test_renew_missing_native_exits_ricrea_solo_dove_manca(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    def fake_open_orders(symbol=None):
        return [{"id": "ord-live"}] if symbol == "AAA" else []

    with patch("src.ai_trader_run.paper_trading.get_open_orders", side_effect=fake_open_orders), \
         patch("src.ai_trader_run._attach_native_exit") as mock_attach:
        ai_trader_run._renew_missing_native_exits({"AAA", "BBB"})
    mock_attach.assert_called_once_with("BBB")


def test_renew_missing_native_exits_errore_controllo_non_blocca_ne_duplica(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("src.ai_trader_run.paper_trading.get_open_orders",
               side_effect=paper_trading.AlpacaError("rete giù")), \
         patch("src.ai_trader_run._attach_native_exit") as mock_attach:
        ai_trader_run._renew_missing_native_exits({"AAA"})
    mock_attach.assert_not_called()


def test_decide_all_sonnet_segue_l_ordine_dello_scanner_non_quello_della_watchlist(tmp_path, monkeypatch):
    """SOFI è prima di RIVN in SCANNER_STOCKS ma lo scanner mette RIVN in
    cima (segnale più forte): con un solo slot Sonnet deve andare a RIVN."""
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "AI_TRADER_MAX_SONNET_CALLS_PER_DAY", 1)
    monkeypatch.setattr(config, "ASSETS", [])
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["SOFI", "RIVN"])
    scanner_file = tmp_path / "scanner.json"
    scanner_file.write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "thresholds": {},
        "results": [
            {"symbol": "RIVN", "flagged": True, "price": 10, "currency": "USD"},
            {"symbol": "SOFI", "flagged": True, "price": 8, "currency": "USD"},
        ],
    }))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scanner_file))
    used = {}

    def fake_decision(symbol, row, thresholds, model):
        used[symbol] = model
        return {"symbol": symbol, "model_used": model, "decision": "HOLD", "reasoning_short": "x", "cost_usd": 0.0}

    with patch("src.ai_trader.scanner_symbol_decision", side_effect=fake_decision):
        decisions = ai_trader.decide_all()
    assert used["RIVN"] == config.AI_TRADER_SONNET_MODEL
    assert used["SOFI"] == config.AI_TRADER_HAIKU_MODEL
    assert [d["symbol"] for d in decisions] == ["RIVN", "SOFI"]


def test_parse_decision_recupera_risposta_troncata():
    out = ai_trader.parse_decision('{"decision": "HOLD", "reasoning_short": "Solo il breakout')
    assert out["decision"] == "HOLD"
    assert "breakout" in out["reasoning_short"]


def test_parse_decision_recupera_json_malformato():
    out = ai_trader.parse_decision('{"decision": "BUY" "reasoning_short": "ok"}')
    assert out["decision"] == "BUY"


def test_parse_decision_risposta_vuota_resta_errore():
    import pytest
    with pytest.raises(ai_trader.DecisionParseError):
        ai_trader.parse_decision("")


def test_scanner_decision_riprova_una_volta_su_risposta_vuota(monkeypatch):
    monkeypatch.setattr(ai_trader.budget, "trader_has_budget", lambda: True)
    monkeypatch.setattr(ai_trader.budget, "record_trader_call_cost", lambda *a: 0.001)
    replies = iter([("", 10, 0), ('{"decision": "HOLD", "reasoning_short": "ok"}', 10, 10)])
    monkeypatch.setattr(ai_trader, "call_model", lambda m, p: next(replies))
    out = ai_trader.scanner_symbol_decision("XYZ", {}, {}, "m")
    assert out["decision"] == "HOLD" and not out.get("error")
    assert out["cost_usd"] == 0.002


import pytest as _pytest

_ORIG_TREND = ai_trader._trend_context


@_pytest.fixture(autouse=True)
def _no_trend_network(monkeypatch):
    monkeypatch.setattr(ai_trader, "_trend_context", lambda symbol: None)


def test_prompt_include_trend_e_regola_buy():
    p = ai_trader.build_scanner_prompt(
        "XYZ", {"price": 10}, {}, {"rsi": 60.0, "vs_sma50_pct": 3.2, "vs_sma200_pct": 8.0, "ret20_pct": 5.5}
    )
    assert "RSI(14): 60.0" in p and "media a 50 giorni: 3.2%" in p and "BUY se il trend è positivo" in p


def test_prompt_trend_mancante_non_disponibile():
    assert "RSI(14): non disponibile" in ai_trader.build_scanner_prompt("XYZ", {}, {}, None)


def test_trend_context_calcola_indicatori(monkeypatch):
    bars = [
        {"date": f"d{i}", "open": 100 + i * 0.5, "high": 100 + i * 0.5, "low": 100 + i * 0.5,
         "close": 100 + i * 0.5, "volume": 1000}
        for i in range(250)
    ]
    monkeypatch.setattr(ai_trader.prices, "fetch_daily_history", lambda s, range_="1y": bars)
    ctx = _ORIG_TREND("XYZ")
    assert ctx["ret20_pct"] > 0 and ctx["vs_sma50_pct"] > 0 and ctx["vs_sma200_pct"] > 0
    assert ctx["rsi"] is not None


def test_trend_context_storico_corto_none(monkeypatch):
    monkeypatch.setattr(ai_trader.prices, "fetch_daily_history", lambda s, range_="1y": [])
    assert _ORIG_TREND("XYZ") is None


# ─── Freschezza dello Scanner rispetto alla chiusura (2026-11-05) ───────────

@_pytest.fixture(autouse=True)
def _no_fresh_scan_network(monkeypatch):
    """Di default nessuna scansione nuova (niente rete nei test)."""
    monkeypatch.setattr(ai_trader, "_fresh_scan", lambda: None)


def test_last_session_close_ora_solare_e_legale():
    utc = dt.timezone.utc
    # novembre (EST): chiusura 21:00 UTC
    assert ai_trader.last_session_close_utc(dt.datetime(2026, 11, 4, 22, 10, tzinfo=utc)) == dt.datetime(2026, 11, 4, 21, 0, tzinfo=utc)
    # luglio (EDT): chiusura 20:00 UTC
    assert ai_trader.last_session_close_utc(dt.datetime(2026, 7, 8, 22, 10, tzinfo=utc)) == dt.datetime(2026, 7, 8, 20, 0, tzinfo=utc)


def test_last_session_close_prima_della_chiusura_usa_il_giorno_prima():
    utc = dt.timezone.utc
    # mercoledì 4 nov alle 19:40 UTC la seduta è ancora aperta: vale la chiusura di martedì
    assert ai_trader.last_session_close_utc(dt.datetime(2026, 11, 4, 19, 40, tzinfo=utc)) == dt.datetime(2026, 11, 3, 21, 0, tzinfo=utc)


def test_last_session_close_weekend_torna_a_venerdi():
    utc = dt.timezone.utc
    assert ai_trader.last_session_close_utc(dt.datetime(2026, 11, 7, 12, 0, tzinfo=utc)) == dt.datetime(2026, 11, 6, 21, 0, tzinfo=utc)


def _write_scan(tmp_path, monkeypatch, generated_at, symbol="RIVN"):
    f = tmp_path / "scan.json"
    f.write_text(json.dumps({"generated_at": generated_at.isoformat(), "results": [{"symbol": symbol, "price": 10}]}))
    monkeypatch.setattr(config, "SCANNER_FILE", str(f))


def test_scanner_prima_della_chiusura_fa_una_scansione_nuova(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = dt.datetime.now(dt.timezone.utc)
    close = ai_trader.last_session_close_utc(now)
    _write_scan(tmp_path, monkeypatch, close - dt.timedelta(hours=1))   # parziale
    monkeypatch.setattr(ai_trader, "_fresh_scan", lambda: {"results": [{"symbol": "NEW", "price": 1}]})
    assert set(ai_trader.load_scanner_results()) == {"NEW"}


def test_scanner_dopo_la_chiusura_non_rifa_la_scansione(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = dt.datetime.now(dt.timezone.utc)
    close = ai_trader.last_session_close_utc(now)
    _write_scan(tmp_path, monkeypatch, close + dt.timedelta(minutes=1))
    def boom():
        raise AssertionError("non doveva rifare la scansione")
    monkeypatch.setattr(ai_trader, "_fresh_scan", boom)
    assert "RIVN" in ai_trader.load_scanner_results()


def test_scansione_nuova_fallita_ripiega_sul_file_di_oggi(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = dt.datetime.now(dt.timezone.utc)
    close = ai_trader.last_session_close_utc(now)
    # prima della chiusura ma stessa data UTC di oggi: si ripiega (con avviso)
    gen = close - dt.timedelta(minutes=30)
    if gen.date() != now.date():
        pytest.skip("la chiusura è di un altro giorno UTC: scenario non riproducibile ora")
    _write_scan(tmp_path, monkeypatch, gen)
    assert "RIVN" in ai_trader.load_scanner_results()   # _fresh_scan() -> None


def test_export_decision_days_scrive_un_file_per_giorno_e_indice(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_DECISIONS_DAYS_DIR", str(tmp_path / "days"))
    for day, sym in (("2026-11-03", "AAA"), ("2026-11-03", "BBB"), ("2026-11-04", "AAA")):
        ai_trader.record_decision({
            "symbol": sym, "date": day, "decision": "HOLD", "model_used": "m",
            "reasoning_short": "x", "cost_usd": 0.0,
        })
    written = ai_trader.export_decision_days()
    assert written == ["2026-11-03", "2026-11-04"]
    idx = json.loads((tmp_path / "days" / "index.json").read_text())
    assert idx["dates"] == ["2026-11-04", "2026-11-03"] and idx["counts"]["2026-11-03"] == 2
    day = json.loads((tmp_path / "days" / "2026-11-03.json").read_text())
    assert [r["symbol"] for r in day] == ["AAA", "BBB"]
    assert "record_hash" not in day[0] and "prev_hash" not in day[0]   # niente hash nella copia
    assert ai_trader.export_decision_days() == []   # niente da riscrivere se non è cambiato nulla


# ─── Giro programmato partito dopo la mezzanotte UTC (2026-11-07) ──────────

def _run_daily_check_day(monkeypatch, event_name):
    import types
    seen = []
    class FakeDate(dt.date):
        @classmethod
        def today(cls):
            return dt.date(2026, 11, 7)   # sabato (data UTC al momento del giro)
    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 11, 7, 1, 50, tzinfo=dt.timezone.utc)
    fake_dt = types.SimpleNamespace(date=FakeDate, datetime=FakeDT, timedelta=dt.timedelta, timezone=dt.timezone, time=dt.time)
    monkeypatch.setattr(ai_trader_run, "dt", fake_dt)
    monkeypatch.setattr(ai_trader_run, "load_experiment", lambda: {"status": "running", "end_date": "2027-05-02", "start_date": "2026-11-01"})
    monkeypatch.setattr(ai_trader_run, "_is_us_market_day", lambda d: seen.append(d) or False)
    if event_name:
        monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    else:
        monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    ai_trader_run.run_daily(dry_run=False)
    return seen


def test_giro_programmato_dopo_mezzanotte_usa_il_giorno_prima(monkeypatch):
    seen = _run_daily_check_day(monkeypatch, "schedule")
    assert seen == [dt.date(2026, 11, 6)]   # venerdì, non sabato


def test_giro_manuale_dopo_mezzanotte_usa_la_data_di_oggi(monkeypatch):
    seen = _run_daily_check_day(monkeypatch, "workflow_dispatch")
    assert seen == [dt.date(2026, 11, 7)]


# ─── Azioni intere + protezioni native (2026-11-10) ─────────────────────────

def test_whole_share_qty():
    assert ai_trader_run._whole_share_qty(2500.0, 100.0) == 25
    assert ai_trader_run._whole_share_qty(2500.0, 1400.0) == 2      # 2800 $, entro 1,5x
    assert ai_trader_run._whole_share_qty(2500.0, 2000.0) == 1
    assert ai_trader_run._whole_share_qty(2500.0, 4000.0) == 0      # 1 azione > 1,5x l'importo
    assert ai_trader_run._whole_share_qty(2500.0, None) == 0
    assert ai_trader_run._whole_share_qty(2500.0, 0) == 0


def test_attach_native_exit_protegge_solo_la_parte_intera(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    position = {"symbol": "KO", "qty": "26.57", "avg_entry_price": "94.08"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order", return_value={"id": "o"}) as mock_place:
        ai_trader_run._attach_native_exit("KO")
    assert mock_place.call_args.kwargs["qty"] == 26.0
    assert mock_place.call_args.kwargs["time_in_force"] == "gtc"


def test_attach_native_exit_meno_di_una_azione_non_piazza_nulla(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    position = {"symbol": "LLY", "qty": "0.61", "avg_entry_price": "1410.0"}
    with patch("src.ai_trader_run.paper_trading.get_positions", return_value=[position]), \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order") as mock_place:
        ai_trader_run._attach_native_exit("LLY")
    mock_place.assert_not_called()


def test_check_stop_losses_vende_anche_al_take_profit(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "AI_TRADER_STOP_LOSS_PCT", -8.0)
    monkeypatch.setattr(config, "AI_TRADER_TAKE_PROFIT_PCT", 16.0)
    positions = [
        {"symbol": "UP", "qty": "5", "unrealized_plpc": "0.17"},
        {"symbol": "MID", "qty": "5", "unrealized_plpc": "0.10"},
        {"symbol": "DOWN", "qty": "5", "unrealized_plpc": "-0.09"},
    ]
    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.place_order", return_value={"id": "x", "status": "accepted"}):
        sold = ai_trader_run._check_stop_losses(positions)
    assert sold == ["UP", "DOWN"]


def test_daily_buy_con_prezzo_noto_usa_bracket_ad_azioni_intere(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({"generated_at": "x", "results": [{"symbol": "RIVN", "price": 14.0}]}))
    monkeypatch.setattr(config, "SCANNER_FILE", str(scan))
    monkeypatch.setattr(ai_trader_run, "load_experiment", lambda: {"status": "running", "start_date": "2026-11-01", "end_date": "2027-05-02", "start_equity_usd": 100000.0})
    decisions = [{"symbol": "RIVN", "decision": "BUY", "model_used": "m", "reasoning_short": "x", "cost_usd": 0.0}]
    account = {"equity": "100000", "buying_power": "200000", "cash": "100000"}
    with patch("src.ai_trader_run.ai_trader.decide_all", return_value=decisions), \
         patch("src.ai_trader_run.paper_trading.get_account", return_value=account), \
         patch("src.ai_trader_run.paper_trading.get_positions", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=[]), \
         patch("src.ai_trader_run.paper_trading.snapshot_account"), \
         patch("src.ai_trader_run._save_portfolio_history_snapshot"), \
         patch("src.ai_trader_run.paper_trading.place_order") as mock_plain, \
         patch("src.ai_trader_run.paper_trading.place_oco_exit_order") as mock_oco, \
         patch("src.ai_trader_run.paper_trading.place_bracket_buy", return_value={"id": "b1", "symbol": "RIVN", "status": "accepted"}) as mock_bracket:
        ai_trader_run.run_daily(dry_run=False)
    # 2500 / 14 = 178,6 -> 179 azioni; stop 12,88 e take-profit 16,24 sul prezzo di riferimento
    mock_bracket.assert_called_once_with(symbol="RIVN", qty=179, stop_price=12.88, take_profit_price=16.24)
    mock_plain.assert_not_called()
    mock_oco.assert_not_called()


def test_write_protection_status_classifica_le_posizioni(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    positions = [
        {"symbol": "FULL", "qty": "10"},
        {"symbol": "PART", "qty": "9.37"},
        {"symbol": "NONE", "qty": "0.6"},
    ]
    orders = [
        {"symbol": "FULL", "side": "sell", "qty": "10"}, {"symbol": "FULL", "side": "sell", "qty": "10"},
        {"symbol": "PART", "side": "sell", "qty": "9"},
        {"symbol": "NONE", "side": "buy", "qty": "5"},
    ]
    with patch("src.ai_trader_run.paper_trading.get_open_orders", return_value=orders):
        ai_trader_run._write_protection_status(positions)
    st = json.loads((tmp_path / "_state" / "protection_status.json").read_text())["positions"]
    assert [st[s]["level"] for s in ("FULL", "PART", "NONE")] == ["alpaca", "parziale", "notturna"]
