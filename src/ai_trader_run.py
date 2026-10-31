"""Orchestratore chiamato da .github/workflows/ai_trader.yml.

Due modalità:
- setup: chiude TUTTE le posizioni aperte sul conto paper (incluse quelle
  manuali già esistenti) e fissa data/ai_trader/experiment.json con la
  data di inizio/fine e l'equity di partenza — quella risultante DOPO la
  chiusura, non un numero inventato: il conto paper Alpaca non ha
  un'API di reset, "100.000" richiesto dall'utente è il punto di partenza
  teorico, ma la cifra vera da cui misurare il guadagno/perdita reale
  dell'esperimento è quella che il conto ha davvero in quel momento (molto
  vicina a $100.000 di default Alpaca, meno il P&L dei due ordini manuali
  precedenti — nessuna commissione paper da sottrarre). Idempotente: se
  experiment.json esiste già non fa nulla, per non poter resettare per
  errore un esperimento già in corso.
- daily: controlla prima lo stop-loss sulle posizioni aperte (indipendente
  dal giudizio AI del giorno), poi una decisione per ogni titolo
  dell'universo (ai_trader.decide_all(), che chiama i modelli pagati), poi
  invia gli ordini di conseguenza, poi aggiorna l'istantanea del conto
  (stessa data/paper/account.json già letta dalla pagina Paper — stesso
  conto Alpaca, nessun file duplicato). No-op se l'esperimento non è
  (ancora) partito o è già scaduto (6 mesi, config.AI_TRADER_DURATION_DAYS).

dry_run qui non chiama MAI i modelli pagati (a differenza di un dry_run che
si limitasse a non scrivere su disco): un giudizio AI costa soldi reali nel
momento stesso in cui viene fatto, non quando il risultato viene salvato —
"test sicuro" deve significare zero chiamate, non solo zero file scritti.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import ai_trader, budget, config, paper_trading, storage


def _sell_to_close(position: dict) -> dict:
    """Vende l'intera quantità per chiudere una posizione, scegliendo il
    time_in_force giusto: Alpaca rifiuta 'day' (il default di
    paper_trading.place_order) per una posizione crypto.

    Bug reale scoperto in due run di setup falliti di fila: il PRIMO
    tentativo di fix usava "/" in symbol per riconoscere una crypto (come fa
    paper_trading.place_order() per un simbolo scelto da noi, es.
    "BTC/USD"), ma GET /v2/positions di Alpaca ritorna il simbolo di una
    posizione crypto SENZA slash (es. "BTCUSD") — quindi quel controllo
    falliva silenziosamente e il bug si ripresentava identico. Il campo
    affidabile è asset_class ("crypto" vs "us_equity"), fornito da Alpaca
    stesso su ogni posizione, non dedotto dalla forma della stringa."""
    symbol = position["symbol"]
    qty = abs(float(position["qty"]))
    time_in_force = "gtc" if position.get("asset_class") == "crypto" else "day"
    order = paper_trading.place_order(symbol=symbol, side="sell", qty=qty, time_in_force=time_in_force)
    return paper_trading.record_order(order)


def _record_equity(date_str: str, equity_usd: float) -> None:
    """Un punto in più nella curva equity nel tempo — append-only, a
    differenza di account.json che viene sovrascritto ad ogni run (vedi
    commento su AI_TRADER_EQUITY_HISTORY_FILE in config.py)."""
    storage.append_record(config.AI_TRADER_EQUITY_HISTORY_FILE, {"date": date_str, "equity_usd": equity_usd})


def load_experiment() -> dict | None:
    if not os.path.exists(config.AI_TRADER_EXPERIMENT_FILE):
        return None
    with open(config.AI_TRADER_EXPERIMENT_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_experiment(data: dict) -> None:
    os.makedirs(os.path.dirname(config.AI_TRADER_EXPERIMENT_FILE), exist_ok=True)
    with open(config.AI_TRADER_EXPERIMENT_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")


def run_setup(dry_run: bool) -> None:
    existing = load_experiment()
    if existing is not None:
        print(
            f"experiment.json esiste già (iniziato il {existing['start_date']}): "
            "setup saltato, nessuna modifica."
        )
        return

    positions = paper_trading.get_positions()
    if dry_run:
        print(
            f"[DRY-RUN] chiuderei {len(positions)} posizioni aperte "
            f"({', '.join(p['symbol'] for p in positions) or 'nessuna'}) e fisserei "
            "experiment.json. Nessun ordine inviato, nessun file scritto."
        )
        return

    for position in positions:
        _sell_to_close(position)
        print(f"Posizione manuale chiusa: {position['symbol']} ({position['qty']})")

    account = paper_trading.get_account()
    start_date = dt.date.today()
    end_date = start_date + dt.timedelta(days=config.AI_TRADER_DURATION_DAYS)
    experiment = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_equity_usd": float(account["equity"]),
        "status": "running",
    }
    _save_experiment(experiment)
    paper_trading.snapshot_account(account, paper_trading.get_positions())
    _record_equity(experiment["start_date"], experiment["start_equity_usd"])
    print(
        f"Esperimento avviato: {experiment['start_date']} -> {experiment['end_date']}, "
        f"equity di partenza ${experiment['start_equity_usd']:.2f}"
    )


def _check_stop_losses(positions: list[dict]) -> list[str]:
    """Vende subito ogni posizione sotto AI_TRADER_STOP_LOSS_PCT, prima e
    indipendentemente dal giudizio AI del giorno. Ritorna i simboli
    venduti."""
    sold = []
    for position in positions:
        plpc = position.get("unrealized_plpc")
        if plpc is None:
            continue
        if float(plpc) * 100 <= config.AI_TRADER_STOP_LOSS_PCT:
            _sell_to_close(position)
            sold.append(position["symbol"])
    return sold


def run_daily(dry_run: bool) -> None:
    experiment = load_experiment()
    if experiment is None:
        print("Esperimento non ancora avviato: lancia prima la modalità 'setup'. Nessuna azione.")
        return
    if experiment.get("status") != "running":
        print(f"Esperimento già concluso ({experiment.get('status')}). Nessuna azione.")
        return

    today = dt.date.today()
    end_date = dt.date.fromisoformat(experiment["end_date"])
    if today > end_date:
        if dry_run:
            print(f"[DRY-RUN] l'esperimento è scaduto il {end_date.isoformat()}: chiuderei qui, nessuna modifica.")
            return
        account = paper_trading.get_account()
        experiment["status"] = "finished"
        experiment["final_equity_usd"] = float(account["equity"])
        experiment["finished_at"] = today.isoformat()
        _save_experiment(experiment)
        _record_equity(today.isoformat(), experiment["final_equity_usd"])
        print(
            f"Esperimento scaduto il {end_date.isoformat()}: nessun nuovo ordine, "
            f"equity finale ${experiment['final_equity_usd']:.2f}"
        )
        return

    positions = paper_trading.get_positions()
    if dry_run:
        print(
            f"[DRY-RUN] {len(positions)} posizioni aperte, esperimento attivo fino al "
            f"{experiment['end_date']}. Nessuna chiamata AI, nessun ordine inviato "
            "(un giudizio AI costa soldi reali appena viene fatto, il dry-run non lo fa mai)."
        )
        return

    stopped_out = _check_stop_losses(positions)
    if stopped_out:
        print(f"Stop-loss attivato su: {', '.join(stopped_out)}")
        positions = paper_trading.get_positions()

    open_symbols = {p["symbol"] for p in positions}
    decisions = ai_trader.decide_all()
    for decision in decisions:
        ai_trader.record_decision({**decision, "date": today.isoformat()})

    account = paper_trading.get_account()
    buying_power = float(account["buying_power"])

    for decision in decisions:
        symbol = decision["symbol"]
        action = decision["decision"]
        if action == "SELL" and symbol in open_symbols:
            position = next(p for p in positions if p["symbol"] == symbol)
            _sell_to_close(position)
            open_symbols.discard(symbol)
            print(f"SELL {symbol} — {decision['reasoning_short']}")
        elif action == "BUY" and symbol not in open_symbols:
            if len(open_symbols) >= config.AI_TRADER_MAX_POSITIONS:
                continue
            if buying_power < config.AI_TRADER_POSITION_NOTIONAL_USD:
                continue
            order = paper_trading.place_order(
                symbol=symbol, side="buy", notional=config.AI_TRADER_POSITION_NOTIONAL_USD
            )
            paper_trading.record_order(order)
            open_symbols.add(symbol)
            buying_power -= config.AI_TRADER_POSITION_NOTIONAL_USD
            print(f"BUY {symbol} — {decision['reasoning_short']}")

    account = paper_trading.get_account()
    positions = paper_trading.get_positions()
    paper_trading.snapshot_account(account, positions)
    _record_equity(today.isoformat(), float(account["equity"]))
    print(
        f"Run giornaliero completato: equity ${account['equity']}, {len(positions)} posizioni aperte, "
        f"spesa AI questo mese ${budget.get_trader_spent_usd():.4f} / ${config.AI_TRADER_MONTHLY_BUDGET_USD:.2f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["setup", "daily"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.mode == "setup":
            run_setup(args.dry_run)
        else:
            run_daily(args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
