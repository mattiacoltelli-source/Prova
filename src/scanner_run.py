"""Orchestratore chiamato da .github/workflows/market_scanner.yml.

Scansiona config.SCANNER_STOCKS + config.SCANNER_CRYPTO
(market_scanner.scan()) e salva il risultato in config.SCANNER_FILE.
Istantanea sovrascritta ad ogni run, stesso principio di
PAPER_ACCOUNT_FILE/BASELINE_FILE: non è uno storico da preservare, è lo
stato più recente, ricalcolabile in qualsiasi momento dalle stesse fonti
pubbliche (nessuna chiave richiesta: solo Yahoo Finance).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import config, market_scanner


def run(dry_run: bool) -> None:
    result = market_scanner.scan(market_scanner.all_symbols())
    failed = [e["symbol"] for e in result["errors"]]
    print(f"Scansionati {len(result['results'])} simboli ok, {len(failed)} falliti: {failed}")
    flagged = [r["symbol"] for r in result["results"] if r["flagged"]]
    print(f"Segnalati: {flagged or 'nessuno'}")

    if dry_run:
        print("[DRY-RUN] nessun file scritto.")
        return

    path = config.SCANNER_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    print(f"Salvato in {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
