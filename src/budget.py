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
