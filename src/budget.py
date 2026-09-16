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


# --- Tetto separato per trend_run.py (cadenza settimanale, non giornaliera) -

def _trend_state_file(iso_year: int, iso_week: int) -> str:
    return f"{config.STATE_DIR}/ai_calls_trend_{iso_year}-W{iso_week:02d}.json"


def _this_iso_week() -> tuple[int, int]:
    iso = dt.date.today().isocalendar()
    return iso[0], iso[1]


def get_trend_call_count() -> int:
    year, week = _this_iso_week()
    path = _trend_state_file(year, week)
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("count", 0)


def _set_trend_call_count(count: int) -> None:
    year, week = _this_iso_week()
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(_trend_state_file(year, week), "w", encoding="utf-8") as fh:
        json.dump({"iso_year": year, "iso_week": week, "count": count}, fh)


def reserve_trend_call() -> bool:
    """Analogo di reserve_call() ma sul tetto settimanale
    MAX_TREND_AI_CALLS_PER_WEEK — cadenza di trend_run.py."""
    count = get_trend_call_count()
    if count >= config.MAX_TREND_AI_CALLS_PER_WEEK:
        return False
    _set_trend_call_count(count + 1)
    return True
