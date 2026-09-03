"""Orchestratore chiamato da .github/workflows/snapshot.yml.

Prende un'istantanea del prezzo corrente per ogni asset (3 volte al giorno
durante l'orario di mercato, non un ticker live) e la salva in
data/<asset>/snapshot.json. Nessuna nuova fonte: riusa
prices.fetch_latest_price(), la stessa funzione già usata da predict_run.py
per price_at_generation, quindi nessuna chiave API aggiuntiva.

Serve solo a mostrare in dashboard "a che punto è" una previsione rispetto
al prezzo di riferimento — non è una valutazione (quella resta compito di
evaluate_run.py, sull'orizzonte completo e con la soglia congelata).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import config
from .data_sources import prices


def run(dry_run: bool) -> None:
    now_utc = dt.datetime.now(dt.timezone.utc)
    for asset in config.ASSETS:
        try:
            price, price_asof, price_source = prices.fetch_latest_price(asset)
        except Exception as exc:  # noqa: BLE001 - istantanea opzionale, mai bloccante
            print(f"[{asset}] skipped_no_data: {exc}")
            continue

        snapshot = {
            "asset": asset,
            "price": price,
            "price_asof": price_asof,
            "price_source": price_source,
            "snapshot_at": now_utc.isoformat(),
        }

        if dry_run:
            print(f"[DRY-RUN] {asset}: {snapshot}")
            continue

        path = config.snapshot_file(asset)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh)
        print(f"[{asset}] istantanea salvata: {price} ({price_source})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
