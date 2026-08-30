#!/usr/bin/env python3
"""Interfaccia CLI principale per l'agente predittivo AI.

Uso:
  python main.py predict [--dry-run] [--force]
  python main.py evaluate [--dry-run]
  python main.py report
"""
from __future__ import annotations

import argparse
import sys

from src import evaluate_run, predict_run, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente predittivo AI — SPY & AAPL")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Comando predict
    predict_parser = subparsers.add_parser("predict", help="Genera previsioni per gli asset configurati")
    predict_parser.add_argument("--dry-run", action="store_true", help="Esegue senza salvare o chiamare budget")
    predict_parser.add_argument("--force", action="store_true", help="Ignora il controllo dello slot orario e del weekend")

    # Comando evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Valuta le previsioni scadute e rigenera REPORT.md")
    eval_parser.add_argument("--dry-run", action="store_true", help="Esegue senza salvare gli esiti o aggiornare il report")

    # Comando report
    subparsers.add_parser("report", help="Rigenera il report REPORT.md dallo storico degli esiti")

    args = parser.parse_args()

    if args.command == "predict":
        predict_run.run(dry_run=args.dry_run, force=args.force)
    elif args.command == "evaluate":
        evaluate_run.run(dry_run=args.dry_run)
    elif args.command == "report":
        report.generate_report()
        print("REPORT.md aggiornato con successo.")


if __name__ == "__main__":
    main()
