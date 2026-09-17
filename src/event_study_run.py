"""Applica event_study alle date CPI raccolte e stampa/salva i risultati.

    python -m src.event_study_run              # scrive data/event_study.json
    python -m src.event_study_run --dry-run    # stampa e basta

Analisi offline, come src/baseline_run.py: non gira in CI e non serve
rieseguirla spesso. Ha senso rilanciarla quando si aggiungono date di
evento, asset o un nuovo regime da confrontare.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

from . import config, event_study
from .data_sources import prices

CPI_DATES_FILE = "data/tradingview/cpi_release_dates.json"
OUTPUT_FILE = "data/event_study.json"


def _load_regimes() -> dict:
    with open(CPI_DATES_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)["regimi"]


def compute() -> dict:
    regimes = _load_regimes()

    bars_by_asset = {}
    for asset in config.ASSETS:
        try:
            bars_by_asset[asset] = prices.fetch_daily_history(
                asset, range_=config.BASELINE_HISTORY_RANGE
            )
        except Exception as exc:  # noqa: BLE001 - un asset mancante non blocca gli altri
            print(f"[{asset}] storico non disponibile: {exc}")

    results = {}
    for name, regime in regimes.items():
        dates = set(regime["dates"])
        outcome = event_study.event_day_ratio(bars_by_asset, dates)
        if outcome is None:
            print(f"[{name}] giorni di evento insufficienti, saltato")
            continue
        outcome["inflation_yoy_pct"] = regime.get("inflazione_yoy_pct")
        outcome["event_dates_in_regime"] = len(dates)
        results[name] = outcome
        flag = "SIGNIFICATIVO" if outcome["significant"] else "non significativo"
        print(
            f"[{name}] rapporto {outcome['ratio']}x "
            f"IC95 {outcome['ci_95']} — {flag} "
            f"(inflazione {outcome['inflation_yoy_pct']}%)"
        )

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "domanda": (
            "La banda FLAT (VOLATILITY_K * ATR14 * sqrt(giorni)) va allargata "
            "quando l'orizzonte contiene la pubblicazione del CPI?"
        ),
        "metodo": (
            "Rapporto fra movimento giornaliero medio assoluto nei giorni CPI e "
            "negli altri giorni della STESSA finestra temporale, aggregando "
            "NVDA/MSFT/AAPL. IC 95% via bootstrap. Vedi src/event_study.py."
        ),
        "regimes": results,
    }


def run(dry_run: bool) -> None:
    payload = compute()
    if not payload["regimes"]:
        print("Nessun regime calcolabile.")
        return
    if dry_run:
        print("\n--dry-run: niente scritto su disco.")
        return
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nScritto {OUTPUT_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
