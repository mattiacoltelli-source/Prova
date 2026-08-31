"""Script di generazione del file data.json per la PWA Dashboard."""
from __future__ import annotations

import json
import os
from typing import Any

from src import config, storage


def build_data() -> dict[str, Any]:
    assets_data = {}
    total_evaluated_global = 0
    total_correct_global = 0
    total_pending_global = 0

    # Carica pending se esiste
    pending_count = 0
    if os.path.exists(config.PENDING_FILE):
        try:
            with open(config.PENDING_FILE, "r", encoding="utf-8") as f:
                pending_list = json.load(f)
                pending_count = len(pending_list)
        except Exception:
            pending_count = 0

    total_pending_global = pending_count

    for asset in ["SPY", "AAPL"]:
        asset_lower = asset.lower()
        preds_file = config.predictions_file(asset_lower)
        outcomes_file = config.outcomes_file(asset_lower)

        predictions = storage.read_all(preds_file)
        outcomes = storage.read_all(outcomes_file)

        # Accuracy asset
        total_eval = len(outcomes)
        correct_eval = sum(1 for o in outcomes if o.get("correct"))

        total_evaluated_global += total_eval
        total_correct_global += correct_eval

        acc_pct = round((correct_eval / total_eval * 100), 1) if total_eval > 0 else 0.0

        # Formatta valutati per la tabella
        evaluated_formatted = []
        for o in reversed(outcomes):
            date_str = o.get("evaluated_at", "")[:10] if o.get("evaluated_at") else ""
            evaluated_formatted.append({
                "date": date_str,
                "horizon": o.get("horizon", ""),
                "predicted": o.get("predicted_class", ""),
                "actual": o.get("actual_class", ""),
                "correct": bool(o.get("correct")),
            })

        # Formatta predizioni per la tabella
        preds_formatted = []
        for p in reversed(predictions):
            date_str = p.get("generated_at", "")[:10] if p.get("generated_at") else ""
            preds_formatted.append({
                "date": date_str,
                "horizon": p.get("horizon", ""),
                "predicted_class": p.get("predicted_class", ""),
                "confidence": p.get("confidence", 0),
            })

        # Costruisci punti per il grafico
        chart_points = []
        for p in predictions:
            if "price_at_generation" in p:
                chart_points.append({
                    "date": p.get("generated_at", "")[:10],
                    "price": float(p["price_at_generation"]),
                    "type": "initial",
                })
        for o in outcomes:
            if "price_at_target" in o:
                chart_points.append({
                    "date": o.get("evaluated_at", "")[:10],
                    "price": float(o["price_at_target"]),
                    "type": "target",
                })

        assets_data[asset] = {
            "accuracy_pct": acc_pct,
            "total_evaluated": total_eval,
            "evaluated": evaluated_formatted,
            "predictions": preds_formatted,
            "chart_points": chart_points,
        }

    global_acc_pct = round((total_correct_global / total_evaluated_global * 100), 1) if total_evaluated_global > 0 else 0.0

    return {
        "global_accuracy_pct": global_acc_pct,
        "total_evaluated": total_evaluated_global,
        "total_pending": total_pending_global,
        "assets": assets_data,
    }


def main():
    data = build_data()
    out_path = os.path.join(os.path.dirname(config.DATA_DIR), "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"data.json generato con successo in {out_path}")


if __name__ == "__main__":
    main()
