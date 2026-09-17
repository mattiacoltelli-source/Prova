"""Baseline storiche calcolate sui prezzi, senza AI.

A cosa serve: `REPORT.md` misura l'accuratezza dell'agente, ma un numero di
accuratezza da solo non dice nulla finché non c'è un metro di paragone.
"33% corrette" è un buon risultato o un pessimo risultato? Dipende da quanto
farebbe una strategia banale sugli stessi asset e sugli stessi orizzonti.

`report.py` confronta già con due baseline calcolate sullo storico
dell'agente (random e persistenza). Quelle però vivono sulle poche decine di
esiti raccolti finora. Qui si calcola una baseline diversa: la **frequenza
storica reale** delle classi UP/DOWN/FLAT su tutto lo storico di prezzo
disponibile (decenni). Da lì esce la baseline più dura da battere e la più
onesta: "prevedi sempre la classe più frequente e non guardare nulla".

Tutto quello che c'è in questo modulo è statistica sui prezzi: nessuna
chiamata al modello, quindi nessun look-ahead bias possibile dal lato AI.
Il look-ahead dal lato dati è evitato esplicitamente — la soglia usata per
classificare il movimento a partire dalla barra `i` è calcolata solo sulle
barre fino alla `i`, esattamente come fa `predict_run.py` in produzione.
"""
from __future__ import annotations

import datetime as dt

from . import config, volatility
from .data_sources.prices import DailyBar

# Barre passate da includere nella finestra su cui si calcola la soglia.
# compute_threshold_pct() si basa su compute_atr_pct(period=14), che guarda
# solo le ultime 15 barre: passare l'intera storia fino alla barra i darebbe
# lo stesso identico risultato, ma su decine di migliaia di barre e tre
# orizzonti diventa inutilmente lento. 40 è abbondantemente sopra il minimo.
_THRESHOLD_WINDOW = 40

# Sotto questo numero di osservazioni una distribuzione non viene riportata:
# con pochi campioni le percentuali sono rumore, esattamente come già fa
# error_analysis.MIN_SAMPLE_SIZE per lo storico dell'agente.
MIN_OBSERVATIONS = 250

CLASSES = ("UP", "DOWN", "FLAT")


def _target_date(session_date: str, horizon_days: int) -> str:
    """Stessa regola di predict_run._target_at(): data della barra di
    partenza più i giorni di CALENDARIO dell'orizzonte (non giorni di
    trading)."""
    return (dt.date.fromisoformat(session_date) + dt.timedelta(days=horizon_days)).isoformat()


def realized_moves(
    bars: list[DailyBar], horizon: config.Horizon
) -> list[tuple[str, float, float]]:
    """Per ogni barra utilizzabile ritorna (data, movimento %, soglia FLAT %)
    dell'orizzonte dato.

    La soglia è quella "congelata" alla barra di partenza, come in
    produzione: mai ricalcolata con dati che a quel momento non esistevano.
    Il prezzo di arrivo è la prima barra con data >= data target, la stessa
    regola di `prices.price_on_or_after()` usata da `evaluate_run.py` per
    gestire weekend e festivi.
    """
    dates = [b["date"] for b in bars]
    close_by_date = {b["date"]: b["close"] for b in bars}
    out: list[tuple[str, float, float]] = []

    for i, bar in enumerate(bars):
        window = bars[max(0, i - _THRESHOLD_WINDOW) : i + 1]
        try:
            threshold_pct = volatility.compute_threshold_pct(window, horizon)
        except ValueError:
            continue  # storico ancora troppo corto per l'ATR

        target = _target_date(bar["date"], horizon.days)
        future_date = next((d for d in dates[i + 1 :] if d >= target), None)
        if future_date is None:
            # Da qui in poi l'orizzonte cade oltre l'ultima barra nota: non
            # c'è un esito reale con cui confrontarsi, e inventarlo
            # (troncando all'ultima barra) falserebbe la distribuzione.
            break

        start = bar["close"]
        if start == 0:
            continue
        change_pct = (close_by_date[future_date] - start) / start * 100
        out.append((bar["date"], change_pct, threshold_pct))

    return out


def class_distribution(bars: list[DailyBar], horizon: config.Horizon) -> dict | None:
    """Frequenza storica di UP/DOWN/FLAT per l'orizzonte dato.

    `majority_class` / `majority_pct` sono la baseline vera e propria:
    l'accuratezza che otterrebbe chi prevedesse sempre la stessa classe,
    senza guardare niente. None se le osservazioni sono meno di
    MIN_OBSERVATIONS.
    """
    moves = realized_moves(bars, horizon)
    if len(moves) < MIN_OBSERVATIONS:
        return None

    counts = dict.fromkeys(CLASSES, 0)
    for _, change_pct, threshold_pct in moves:
        counts[volatility.classify_change(change_pct, threshold_pct)] += 1

    total = len(moves)
    pct = {cls: round(counts[cls] / total * 100, 1) for cls in CLASSES}
    majority_class = max(CLASSES, key=lambda cls: counts[cls])
    return {
        "horizon": horizon.code,
        "observations": total,
        "first_date": moves[0][0],
        "last_date": moves[-1][0],
        "counts": counts,
        "pct": pct,
        "majority_class": majority_class,
        "majority_pct": pct[majority_class],
    }


def k_calibration(
    bars: list[DailyBar], horizon: config.Horizon, k_values: list[float]
) -> list[dict]:
    """Quota di movimenti che finirebbero in FLAT per ogni valore di
    VOLATILITY_K, a parità di tutto il resto.

    Serve a rispondere "K=0.4 è tarato bene?" con i dati invece che a
    intuito: la soglia scalata (ATR% * sqrt(giorni)) viene ricavata una sola
    volta per barra e poi confrontata con ogni K, quindi il costo non
    cresce con il numero di K provati.
    """
    moves = realized_moves(bars, horizon)
    if len(moves) < MIN_OBSERVATIONS:
        return []

    # realized_moves() ritorna la soglia già moltiplicata per VOLATILITY_K:
    # si divide per riottenere la parte "neutra" (ATR% * sqrt(giorni)) e
    # poterla riscalare con un K diverso.
    if config.VOLATILITY_K == 0:
        return []
    scaled = [(abs(change_pct), threshold_pct / config.VOLATILITY_K) for _, change_pct, threshold_pct in moves]

    rows = []
    for k in k_values:
        flat = sum(1 for abs_change, unit in scaled if abs_change <= k * unit)
        rows.append(
            {
                "k": k,
                "flat_pct": round(flat / len(scaled) * 100, 1),
                "is_current": k == config.VOLATILITY_K,
            }
        )
    return rows
