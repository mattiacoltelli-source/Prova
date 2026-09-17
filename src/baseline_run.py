"""Calcola le baseline storiche e le salva in data/baseline.json.

Non gira nella pipeline quotidiana: è un'analisi offline da lanciare a mano
(o molto di rado), perché il risultato si muove pochissimo — aggiungere
qualche settimana di barre a venticinque anni di storico non sposta una
distribuzione. Rigenerarlo ha senso quando cambia qualcosa che lo influenza
davvero: l'insieme degli asset, gli orizzonti, o la formula della soglia
(`VOLATILITY_K` / `volatility.compute_threshold_pct`).

    python -m src.baseline_run              # scrive data/baseline.json
    python -m src.baseline_run --dry-run    # stampa e basta

Fonte dati: la stessa cascata Yahoo -> Twelve Data già usata da tutto il
resto del progetto, con `range_="max"` invece del default. Nessuna API key
nuova, nessuna fonte a pagamento: il file prodotto resta quindi
rigenerabile da chiunque, anche fra anni.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

from . import baseline, config
from .data_sources import prices

# Valori di VOLATILITY_K da provare nella tabella di calibrazione. Coprono
# sia bande molto strette (FLAT raro, quasi un binario UP/DOWN) sia molto
# larghe (FLAT dominante), così il valore in uso si legge in un contesto
# invece che da solo.
K_VALUES = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8]


def compute() -> dict:
    """Ritorna la struttura completa delle baseline, senza scrivere nulla."""
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    assets: dict[str, dict] = {}

    for asset in config.ASSETS:
        try:
            bars = prices.fetch_daily_history(asset, range_=config.BASELINE_HISTORY_RANGE)
        except Exception as exc:  # noqa: BLE001 - un asset senza dati non blocca gli altri
            print(f"[{asset}] storico non disponibile: {exc}")
            continue

        horizons: dict[str, dict] = {}
        calibration: dict[str, list] = {}
        for horizon in config.HORIZONS:
            distribution = baseline.class_distribution(bars, horizon)
            if distribution is None:
                print(f"[{asset}/{horizon.code}] osservazioni insufficienti, saltato")
                continue
            horizons[horizon.code] = distribution
            calibration[horizon.code] = baseline.k_calibration(bars, horizon, K_VALUES)
            print(
                f"[{asset}/{horizon.code}] n={distribution['observations']} "
                f"UP {distribution['pct']['UP']}% "
                f"DOWN {distribution['pct']['DOWN']}% "
                f"FLAT {distribution['pct']['FLAT']}% "
                f"-> baseline {distribution['majority_class']} {distribution['majority_pct']}%"
            )

        if not horizons:
            continue

        assets[asset] = {
            "bars": len(bars),
            "first_bar": bars[0]["date"],
            "last_bar": bars[-1]["date"],
            "horizons": horizons,
            "k_calibration": calibration,
        }

    return {
        "generated_at": generated_at,
        "volatility_k": config.VOLATILITY_K,
        "history_range": config.BASELINE_HISTORY_RANGE,
        "source": "Yahoo Finance (fallback Twelve Data) — prezzi rettificati per split",
        "assets": assets,
    }


def run(dry_run: bool) -> None:
    payload = compute()
    if not payload["assets"]:
        print("Nessuna baseline calcolata: nessun asset con storico sufficiente.")
        return
    if dry_run:
        print("\n--dry-run: niente scritto su disco.")
        return
    os.makedirs(os.path.dirname(config.BASELINE_FILE), exist_ok=True)
    with open(config.BASELINE_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nScritto {config.BASELINE_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
