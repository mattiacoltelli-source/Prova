"""Quanto si allarga la distribuzione dei movimenti nei giorni di evento.

La banda FLAT del progetto è `VOLATILITY_K * ATR%(14) * sqrt(giorni)`
(`volatility.compute_threshold_pct`). È **cieca rispetto a cosa cade dentro
la finestra**: un orizzonte a 7 giorni che contiene la pubblicazione del CPI
riceve la stessa banda di una settimana senza nulla in calendario.

Questo modulo misura se quella cecità costa qualcosa, confrontando il
movimento medio assoluto nei giorni di evento con quello degli altri giorni
dello stesso periodo. Il rapporto fra i due è la risposta: 1.0 significa che
gli eventi non allargano nulla e la banda va bene com'è; 1.5 significa che
nei giorni di evento il prezzo si muove una volta e mezza tanto.

Il confronto è **contemporaneo** (giorni di evento contro giorni normali
della stessa finestra), quindi il livello di volatilità del periodo si
semplifica da solo: il rapporto misura l'effetto evento *in aggiunta* alla
volatilità ambientale, che è esattamente ciò che l'ATR già cattura.

Come per `baseline.py`: solo statistica sui prezzi, nessuna chiamata al
modello, nessun look-ahead possibile.
"""
from __future__ import annotations

import random
import statistics

from .data_sources.prices import DailyBar

# Sotto questa soglia di giorni di evento il rapporto non viene calcolato:
# con pochi eventi l'intervallo di confidenza diventa così largo da non
# distinguere 0.5 da 2.0, e riportare il numero puntuale sarebbe fuorviante.
MIN_EVENT_DAYS = 10

BOOTSTRAP_SAMPLES = 4000
CONFIDENCE = 0.95


def daily_abs_moves(
    bars: list[DailyBar], event_dates: set[str]
) -> tuple[list[float], list[float]]:
    """Separa i movimenti giornalieri assoluti (in %) fra giorni di evento e
    giorni normali, limitandosi all'intervallo coperto da `event_dates`.

    Limitarsi a quell'intervallo è essenziale: confrontare i giorni CPI del
    2022 con i giorni normali del 2016 misurerebbe la differenza fra due
    epoche di mercato, non l'effetto dell'evento.
    """
    if not event_dates:
        return [], []
    lo, hi = min(event_dates), max(event_dates)

    # La finestra parte UNA BARRA PRIMA del primo giorno di evento, non dal
    # giorno stesso: il movimento di una barra si calcola rispetto alla
    # precedente, quindi ancorare la finestra esattamente a `lo` scarterebbe
    # in silenzio il movimento del primo evento. Su decine di eventi
    # l'effetto sul rapporto è minimo, ma è una perdita sistematica e
    # gratuita — e su un campione piccolo conta.
    first = next((i for i, b in enumerate(bars) if b["date"] >= lo), None)
    if first is None:
        return [], []
    window = [b for b in bars[max(0, first - 1) :] if b["date"] <= hi]

    event_moves: list[float] = []
    normal_moves: list[float] = []
    for i in range(1, len(window)):
        previous = window[i - 1]["close"]
        if previous == 0:
            continue
        move = abs((window[i]["close"] - previous) / previous * 100)
        if window[i]["date"] in event_dates:
            event_moves.append(move)
        else:
            normal_moves.append(move)
    return event_moves, normal_moves


def _bootstrap_ratio_ci(
    event_moves: list[float], normal_moves: list[float], seed: int = 42
) -> tuple[float, float]:
    """Intervallo di confidenza sul rapporto fra le medie, ricampionando i
    due gruppi in modo indipendente.

    Serve il bootstrap e non una formula chiusa perché la distribuzione dei
    movimenti giornalieri ha code spesse: le assunzioni di normalità che
    starebbero dietro a un test t darebbero un intervallo troppo stretto
    proprio dove conta, cioè sui movimenti grandi.
    """
    rng = random.Random(seed)
    ratios = []
    for _ in range(BOOTSTRAP_SAMPLES):
        a = statistics.mean(rng.choices(event_moves, k=len(event_moves)))
        b = statistics.mean(rng.choices(normal_moves, k=len(normal_moves)))
        if b == 0:
            continue
        ratios.append(a / b)
    ratios.sort()
    tail = (1 - CONFIDENCE) / 2
    return ratios[int(tail * len(ratios))], ratios[int((1 - tail) * len(ratios))]


def event_day_ratio(
    bars_by_asset: dict[str, list[DailyBar]], event_dates: set[str], seed: int = 42
) -> dict | None:
    """Rapporto fra movimento medio nei giorni di evento e nei giorni
    normali, aggregando tutti gli asset passati.

    `significant` è True quando l'intervallo di confidenza NON contiene 1.0:
    solo in quel caso si può dire che l'evento allarga davvero i movimenti
    invece che sembrarlo per caso. None se i giorni di evento coperti dai
    dati sono meno di MIN_EVENT_DAYS.
    """
    pooled_event: list[float] = []
    pooled_normal: list[float] = []
    per_asset: dict[str, float] = {}

    for asset, bars in bars_by_asset.items():
        event_moves, normal_moves = daily_abs_moves(bars, event_dates)
        if not event_moves or not normal_moves:
            continue
        per_asset[asset] = round(
            statistics.mean(event_moves) / statistics.mean(normal_moves), 3
        )
        pooled_event += event_moves
        pooled_normal += normal_moves

    if len(pooled_event) < MIN_EVENT_DAYS or not pooled_normal:
        return None

    mean_event = statistics.mean(pooled_event)
    mean_normal = statistics.mean(pooled_normal)
    if mean_normal == 0:
        return None
    low, high = _bootstrap_ratio_ci(pooled_event, pooled_normal, seed=seed)

    return {
        "event_days_observed": len(pooled_event),
        "normal_days_observed": len(pooled_normal),
        "mean_abs_move_event_pct": round(mean_event, 3),
        "mean_abs_move_normal_pct": round(mean_normal, 3),
        "ratio": round(mean_event / mean_normal, 3),
        "ci_95": [round(low, 3), round(high, 3)],
        "significant": not (low <= 1.0 <= high),
        "ratio_by_asset": per_asset,
    }
