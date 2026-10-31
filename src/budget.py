"""Tetto di spesa AI enforced a livello di codice (oltre al limite in
console.anthropic.com già impostato manualmente). Un contatore giornaliero
persistito in data/_state/ blocca nuove chiamate al modello una volta
raggiunto MAX_AI_CALLS_PER_DAY."""
from __future__ import annotations

import datetime as dt
import json
import os

from . import config


def _state_file(date: str) -> str:
    return f"{config.STATE_DIR}/ai_calls_{date}.json"


def _today() -> str:
    return dt.date.today().isoformat()


def get_call_count() -> int:
    path = _state_file(_today())
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("count", 0)


def _set_call_count(count: int) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(_state_file(_today()), "w", encoding="utf-8") as fh:
        json.dump({"date": _today(), "count": count}, fh)


def has_budget() -> bool:
    return get_call_count() < config.MAX_AI_CALLS_PER_DAY


def reserve_call() -> bool:
    """Riserva una chiamata al modello se il budget giornaliero lo consente.
    Ritorna False (senza incrementare nulla) se il tetto è già raggiunto."""
    count = get_call_count()
    if count >= config.MAX_AI_CALLS_PER_DAY:
        return False
    _set_call_count(count + 1)
    return True


# --- Tetto separato per trend_run.py (cadenza MENSILE, non giornaliera) ----
# Settimanale -> mensile il 2026-09-17: un ciclo pluriennale (orizzonti
# 1-10 anni) non cambia in modo significativo da una settimana all'altra,
# ricalcolarlo più spesso sprecava solo budget AI senza aggiungere segnale
# (feedback utente).

def _trend_state_file(year: int, month: int) -> str:
    return f"{config.STATE_DIR}/ai_calls_trend_{year}-{month:02d}.json"


def _this_month() -> tuple[int, int]:
    today = dt.date.today()
    return today.year, today.month


def get_trend_call_count() -> int:
    year, month = _this_month()
    path = _trend_state_file(year, month)
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("count", 0)


def _set_trend_call_count(count: int) -> None:
    year, month = _this_month()
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(_trend_state_file(year, month), "w", encoding="utf-8") as fh:
        json.dump({"year": year, "month": month, "count": count}, fh)


def reserve_trend_call() -> bool:
    """Analogo di reserve_call() ma sul tetto mensile
    MAX_TREND_AI_CALLS_PER_MONTH — cadenza di trend_run.py."""
    count = get_trend_call_count()
    if count >= config.MAX_TREND_AI_CALLS_PER_MONTH:
        return False
    _set_trend_call_count(count + 1)
    return True


# --- Tetto separato per ai_trader.py, in DOLLARI non in numero di chiamate
# ---------------------------------------------------------------------------
# A differenza dei due tetti sopra (un conteggio di chiamate, perché ogni
# chiamata costa più o meno uguale con lo stesso modello), ai_trader.py usa
# due modelli di prezzo molto diversi (Haiku 5.5 e Sonnet 5.5, vedi
# config.AI_TRADER_PRICING_PER_MILLION_TOKENS) sullo stesso tetto mensile in
# euro/dollari richiesto dall'utente — un conteggio di chiamate non
# rifletterebbe il vero costo. Il costo di ogni chiamata è calcolato dai
# token REALI restituiti da Anthropic (response.usage), non stimato: lo
# stesso principio di "niente stime quando il dato vero è disponibile" già
# seguito altrove in questo progetto (es. baseline reali invece di soglie
# indovinate).

def _trader_budget_state_file(year: int, month: int) -> str:
    return f"{config.STATE_DIR}/ai_trader_budget_{year}-{month:02d}.json"


def get_trader_spent_usd() -> float:
    year, month = _this_month()
    path = _trader_budget_state_file(year, month)
    if not os.path.exists(path):
        return 0.0
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("spent_usd", 0.0)


def _set_trader_spent_usd(spent_usd: float) -> None:
    year, month = _this_month()
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(_trader_budget_state_file(year, month), "w", encoding="utf-8") as fh:
        json.dump({"year": year, "month": month, "spent_usd": round(spent_usd, 6)}, fh)


def trader_has_budget() -> bool:
    return get_trader_spent_usd() < config.AI_TRADER_MONTHLY_BUDGET_USD


def estimate_call_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Costo in dollari di una chiamata, dato il modello e i token REALI
    restituiti da Anthropic (response.usage.input_tokens/output_tokens),
    mai una stima a priori del prompt."""
    pricing = config.AI_TRADER_PRICING_PER_MILLION_TOKENS[model]
    return input_tokens / 1_000_000 * pricing["input"] + output_tokens / 1_000_000 * pricing["output"]


def record_trader_call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Aggiunge al contatore mensile il costo reale di una chiamata appena
    fatta e ritorna quel costo in dollari. A differenza di reserve_call()/
    reserve_trend_call(), non blocca nulla da sola: la chiamata al modello è
    già avvenuta quando si conosce il costo reale (i token si sanno solo
    dopo la risposta) — il controllo preventivo è trader_has_budget(),
    chiamato PRIMA di fare la richiesta."""
    cost = estimate_call_cost_usd(model, input_tokens, output_tokens)
    _set_trader_spent_usd(get_trader_spent_usd() + cost)
    return cost
