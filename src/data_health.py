"""Traccia se una fonte di prezzi (Yahoo Finance, usata in modo indipendente
da market_scanner.py e benchmark.py) ha smesso di dare risultati utili per
gran parte dell'universo in un singolo giorno — non il fallimento isolato
di un ticker (normale, previsto, già gestito un simbolo alla volta dove
viene fatto il fetch), ma il segnale che la fonte si è rotta o ha cambiato
formato senza preavviso. Un file di stato per fonte, SOVRASCRITTO ogni
giorno: non è uno storico, serve solo a sapere se OGGI va tutto bene.

Scrittura non bloccante dove viene chiamato (stesso principio di
_update_benchmarks in ai_trader_run.py): un problema nel salvare questo
stato non deve mai interrompere lo scan o l'aggiornamento delle strategie
che lo producono."""
from __future__ import annotations

import datetime as dt
import json
import os

from . import config


def _health_file(source: str) -> str:
    return f"{config.STATE_DIR}/data_health_{source}.json"


def record_fetch_health(source: str, total: int, failed_symbols: list[str]) -> None:
    """Sovrascrive lo stato di oggi per questa fonte (es. "scanner",
    "benchmark"). total è la dimensione dell'universo tentato quel giorno,
    failed_symbols i simboli che non hanno dato un prezzo utilizzabile —
    per errore esplicito (eccezione) o perché i dati tornati erano
    insufficienti (es. troppe poche barre, stesso sintomo di un formato
    cambiato senza errore)."""
    os.makedirs(config.STATE_DIR, exist_ok=True)
    failure_rate = len(failed_symbols) / total if total else 0.0
    with open(_health_file(source), "w", encoding="utf-8") as fh:
        json.dump({
            "date": dt.date.today().isoformat(),
            "total": total,
            "failed_count": len(failed_symbols),
            "failed_symbols": failed_symbols,
            "failure_rate": round(failure_rate, 4),
            "alert": failure_rate > config.DATA_HEALTH_FAILURE_RATE_ALERT_THRESHOLD,
        }, fh)
