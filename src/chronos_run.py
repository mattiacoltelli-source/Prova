"""Orchestratore per le previsioni "ombra" di Chronos-Bolt-tiny (Amazon,
open-source, Apache-2.0): per ogni previsione AI reale generata OGGI da
predict_run.py, genera la previsione corrispondente di Chronos sullo
stesso asset/orizzonte/prezzo/soglia di volatilità, e la appende a
data/<asset>/chronos_predictions.jsonl — collegata alla previsione AI da
prediction_id, mai una previsione indipendente.

Chiamato da .github/workflows/predict.yml SUBITO DOPO predict_run.py,
nella stessa sessione: senza una previsione AI dello stesso giorno non
c'è nulla da affiancare. Idempotente (_already_shadowed): un rerun lo
stesso giorno non duplica nulla.

Il modello vede SOLO lo storico prezzi (nessuna news/macro/fondamentali):
è un confronto deliberato con un approccio numerico puro, non un
tentativo di sostituire l'agente AI — vedi REPORT.md per l'accuratezza
comparata.

    python -m src.chronos_run
"""
from __future__ import annotations

import datetime as dt
import sys
import uuid

from . import config, storage, volatility
from .data_sources import prices

MODEL_ID = "amazon/chronos-bolt-tiny"

# Limite di contesto del modello (verificato: pipeline.model_context_length
# == 2048 per chronos-bolt-tiny): troncare lo storico più vecchio invece di
# passare più barre di quante il modello supporti.
MAX_CONTEXT_BARS = 2048

# Sotto questa soglia il contesto è troppo corto perché una previsione
# abbia senso (poche settimane di storico): salta invece di forzarla.
MIN_CONTEXT_BARS = 60


def _already_shadowed(asset: str, ai_prediction_id: str) -> bool:
    existing = storage.read_all(config.chronos_predictions_file(asset))
    return any(r["prediction_id"] == ai_prediction_id for r in existing)


def _find_context_end(
    dates: list[str], closes: list[float], price_at_generation: float, generated_at_date: str
) -> int | None:
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


def _load_pipeline():
    """Import e caricamento isolati in una funzione a parte (non inline in
    run()) apposta per poterli sostituire nei test con un mock: senza
    questo, un test di run() richiederebbe torch/chronos-forecasting
    installati solo per esercitare la logica di orchestrazione, che non ha
    nulla a che fare con il modello in sé."""
    try:
        from chronos import BaseChronosPipeline
    except ImportError:
        print("chronos-forecasting non installato: pip install torch chronos-forecasting", file=sys.stderr)
        raise
    print(f"Carico {MODEL_ID} (CPU)...")
    return BaseChronosPipeline.from_pretrained(MODEL_ID, device_map="cpu")


def _median_forecast(pipeline, context: list[float], prediction_length: int) -> float:
    import torch

    tensor = torch.tensor(context, dtype=torch.float32)
    # predict_quantiles(..., quantile_levels=[0.5]) invece di predict() +
    # indicizzazione a mano: la forma del tensore restituito è
    # [num_serie, prediction_length, num_quantili] (verificato con un test
    # diretto sulla versione installata del pacchetto).
    quantiles, _mean = pipeline.predict_quantiles(
        inputs=tensor, prediction_length=prediction_length, quantile_levels=[0.5]
    )
    return float(quantiles[0, -1, 0])


def run(today_et: dt.date | None = None) -> None:
    today_et = today_et or dt.datetime.now(config.EASTERN).date()
    today_iso = today_et.isoformat()
    horizon_by_code = {h.code: h for h in config.HORIZONS}

    pipeline = None  # caricato pigro: solo se c'è davvero qualcosa da fare oggi

    for asset in config.ASSETS:
        todays_predictions = [
            p for p in storage.read_all(config.predictions_file(asset))
            if p["generated_at"][:10] == today_iso and not _already_shadowed(asset, p["id"])
        ]
        if not todays_predictions:
            continue

        if pipeline is None:
            pipeline = _load_pipeline()

        bars = prices.fetch_daily_history(asset, range_=config.PRICE_HISTORY_RANGE)
        dates = [b["date"] for b in bars]
        closes = [b["close"] for b in bars]

        for pred in todays_predictions:
            horizon = horizon_by_code.get(pred["horizon"])
            if horizon is None:
                continue

            end_idx = _find_context_end(dates, closes, pred["price_at_generation"], pred["generated_at"][:10])
            if end_idx is None or end_idx < MIN_CONTEXT_BARS:
                print(f"[{asset}/{pred['horizon']}] contesto storico insufficiente, salto.")
                continue

            start_idx = max(0, end_idx + 1 - MAX_CONTEXT_BARS)
            context = closes[start_idx: end_idx + 1]
            prediction_length = max(1, round(horizon.trading_days))

            try:
                forecast_price = _median_forecast(pipeline, context, prediction_length)
            except Exception as exc:  # noqa: BLE001 - un errore su una riga non deve bloccare le altre
                print(f"[{asset}/{pred['horizon']}] errore Chronos: {exc}")
                continue

            change_pct = (forecast_price - pred["price_at_generation"]) / pred["price_at_generation"] * 100
            predicted_class = volatility.classify_change(change_pct, pred["volatility_threshold_pct"])

            record = {
                "id": str(uuid.uuid4()),
                "prediction_id": pred["id"],
                "asset": asset,
                "horizon": pred["horizon"],
                "generated_at": pred["generated_at"],
                "target_at": pred["target_at"],
                "price_at_generation": pred["price_at_generation"],
                "volatility_threshold_pct": pred["volatility_threshold_pct"],
                "model": MODEL_ID,
                "forecast_price": round(forecast_price, 4),
                "predicted_class": predicted_class,
            }
            storage.append_record(config.chronos_predictions_file(asset), record)
            print(f"[{asset}/{pred['horizon']}] Chronos: {predicted_class} (agente AI: {pred['predicted_class']})")


if __name__ == "__main__":
    run()
