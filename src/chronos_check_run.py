"""Diagnostico ad-hoc: confronta Chronos-Bolt-tiny (Amazon, open-source,
Apache-2.0 — modello di previsione numerica su serie storiche, zero
news/macro/fondamentali) con l'agente AI di Predict, come terzo baseline
accanto a persistenza e frequenza storica già in REPORT.md.

Non scrive su data/: gira a parte, nessun impatto sulla pipeline di
produzione (predict_run.py). Lanciato solo via
.github/workflows/chronos_baseline_check.yml (workflow_dispatch).

Metodologia: per ogni esito già valutato in outcomes.jsonl, ricostruisce
il contesto di prezzi REALMENTE disponibile al momento di quella
previsione (nessun look-ahead), chiede a Chronos una previsione per lo
stesso orizzonte, classifica il risultato con la STESSA soglia di
volatilità congelata usata per l'agente AI (volatility.classify_change),
e confronta con l'esito reale già noto.

    python -m src.chronos_check_run
"""
from __future__ import annotations

import sys
from collections import defaultdict

from . import config, storage, volatility
from .data_sources import prices

MODEL_ID = "amazon/chronos-bolt-tiny"

# Limite di contesto documentato per i modelli Chronos-Bolt: troncare lo
# storico più vecchio invece di passare più barre di quante il modello
# supporti (10y di storico daily supera questo limite).
MAX_CONTEXT_BARS = 2048

# Sotto questa soglia il contesto è troppo corto perché una previsione
# abbia senso (poche settimane di storico): salta invece di forzare un
# numero comunque fuorviante.
MIN_CONTEXT_BARS = 60


def _load_predictions_by_id(asset: str) -> dict[str, dict]:
    return {p["id"]: p for p in storage.read_all(config.predictions_file(asset))}


def _find_context_end(dates: list[str], closes: list[float], price_at_generation: float, generated_at_date: str) -> int | None:
    """Indice dell'ultima barra con date <= generated_at_date il cui close
    combacia con price_at_generation (stessa fonte Yahoo, stesso
    arrotondamento a 4 decimali di prices.py: il match è quasi sempre
    esatto). None se non trovata."""
    best = None
    for i, (d, c) in enumerate(zip(dates, closes)):
        if d > generated_at_date:
            break
        if abs(c - price_at_generation) < 0.005:
            best = i
    return best


def _median_forecast(pipeline, context: list[float], prediction_length: int) -> float:
    import torch

    tensor = torch.tensor(context, dtype=torch.float32)
    # predict_quantiles(..., quantile_levels=[0.5]) invece di predict() +
    # indicizzazione a mano: l'argomento si chiama "inputs" (non "context")
    # nella versione installata (chronos-forecasting 2.x) e la forma del
    # tensore è [num_serie, prediction_length, num_quantili] — verificato
    # con un test diretto, diverso da quanto mostrato nella documentazione
    # pubblica per una versione precedente del pacchetto.
    quantiles, _mean = pipeline.predict_quantiles(
        inputs=tensor, prediction_length=prediction_length, quantile_levels=[0.5]
    )
    return float(quantiles[0, -1, 0])


def run() -> None:
    try:
        from chronos import BaseChronosPipeline
    except ImportError:
        print("chronos-forecasting non installato: pip install torch chronos-forecasting", file=sys.stderr)
        raise

    print(f"Carico {MODEL_ID} (CPU)...")
    pipeline = BaseChronosPipeline.from_pretrained(MODEL_ID, device_map="cpu")

    horizon_by_code = {h.code: h for h in config.HORIZONS}
    results_by_group: dict[tuple[str, str], list[bool]] = defaultdict(list)
    skipped = 0
    total_outcomes = 0

    for asset in config.ASSETS:
        outcomes = storage.read_all(config.outcomes_file(asset))
        if not outcomes:
            continue
        predictions_by_id = _load_predictions_by_id(asset)

        print(f"[{asset}] storico prezzi...")
        bars = prices.fetch_daily_history(asset, range_=config.PRICE_HISTORY_RANGE)
        dates = [b["date"] for b in bars]
        closes = [b["close"] for b in bars]

        for outcome in outcomes:
            total_outcomes += 1
            pred = predictions_by_id.get(outcome["prediction_id"])
            horizon = horizon_by_code.get(outcome["horizon"])
            if pred is None or horizon is None:
                skipped += 1
                continue

            generated_date = pred["generated_at"][:10]
            end_idx = _find_context_end(dates, closes, pred["price_at_generation"], generated_date)
            if end_idx is None or end_idx < MIN_CONTEXT_BARS:
                skipped += 1
                continue

            start_idx = max(0, end_idx + 1 - MAX_CONTEXT_BARS)
            context = closes[start_idx: end_idx + 1]
            prediction_length = max(1, round(horizon.trading_days))

            try:
                forecast_price = _median_forecast(pipeline, context, prediction_length)
            except Exception as exc:  # noqa: BLE001 - un errore su una riga non deve fermare il confronto
                print(f"[{asset}/{outcome['horizon']}] errore Chronos: {exc}")
                skipped += 1
                continue

            change_pct = (forecast_price - pred["price_at_generation"]) / pred["price_at_generation"] * 100
            chronos_class = volatility.classify_change(change_pct, pred["volatility_threshold_pct"])

            correct = chronos_class == outcome["actual_class"]
            results_by_group[(asset, outcome["horizon"])].append(correct)

    print()
    print("=== Chronos-Bolt-tiny come baseline, sullo stesso storico valutato di Predict ===")
    print()
    all_results: list[bool] = []
    for (asset, horizon_code), rows in sorted(results_by_group.items()):
        all_results.extend(rows)
        n = len(rows)
        pct = round(sum(rows) / n * 100, 1) if n else 0.0
        print(f"{asset}/{horizon_code}: {pct}% (n={n})")

    if all_results:
        overall_pct = round(sum(all_results) / len(all_results) * 100, 1)
        print()
        print(f"Totale: {overall_pct}% (n={len(all_results)}, {skipped} esiti saltati su {total_outcomes})")
    else:
        print("Nessun confronto calcolabile (dati insufficienti).")


if __name__ == "__main__":
    run()
