"""Orchestratore chiamato da .github/workflows/snapshot.yml.

Prende un'istantanea del prezzo corrente per ogni asset (3 volte al giorno
durante l'orario di mercato, non un ticker live) e la salva in
data/<asset>/snapshot.json. Nessuna nuova fonte: riusa
prices.fetch_latest_price(), la stessa funzione già usata da predict_run.py
per price_at_generation, quindi nessuna chiave API aggiuntiva.

Serve solo a mostrare in dashboard "a che punto è" una previsione rispetto
al prezzo di riferimento — non è una valutazione (quella resta compito di
evaluate_run.py, sull'orizzonte completo e con la soglia congelata).

Tetto di config.SNAPSHOT_MAX_PER_DAY round/giorno (cache in
data/_state/snapshot_count_<data>.json), condiviso tra i tick schedulati e
un eventuale run manuale di recupero: se uno dei 3 tick non scatta, un
click manuale lo recupera, ma il totale del giorno resta comunque 3.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from . import config
from .data_sources import prices


def _snapshot_count_state_path(day: dt.date) -> str:
    return f"{config.STATE_DIR}/snapshot_count_{day.isoformat()}.json"


def _snapshot_count_today(day: dt.date) -> int:
    path = _snapshot_count_state_path(day)
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("count", 0)


def _increment_snapshot_count(day: dt.date) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    count = _snapshot_count_today(day) + 1
    with open(_snapshot_count_state_path(day), "w", encoding="utf-8") as fh:
        json.dump({"date": day.isoformat(), "count": count}, fh)


def run(dry_run: bool) -> None:
    now_utc = dt.datetime.now(dt.timezone.utc)
    today = now_utc.date()

    # Tetto condiviso tra i 3 tick schedulati e un eventuale run manuale di
    # recupero (link nel pannello info della dashboard, come per
    # predict.yml): senza questo contatore, un tocco manuale dopo che i 3
    # tick schedulati fossero già scattati con successo produrrebbe una
    # quarta istantanea nello stesso giorno. Un dry-run non consuma il
    # tetto (non scrive nulla di reale) e non ne è bloccato.
    if not dry_run:
        count = _snapshot_count_today(today)
        if count >= config.SNAPSHOT_MAX_PER_DAY:
            print(
                f"Già fatte {count} istantanee oggi (limite {config.SNAPSHOT_MAX_PER_DAY}/giorno), "
                "esco senza scrivere."
            )
            return

    wrote_any = False
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
        wrote_any = True

    if wrote_any and not dry_run:
        _increment_snapshot_count(today)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
