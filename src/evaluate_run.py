"""Orchestratore chiamato da .github/workflows/evaluate.yml.

Scorre data/pending.json, valuta le previsioni il cui orizzonte è scaduto
confrontandole con il prezzo reale, appende l'esito e rigenera REPORT.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import config, report, storage, volatility
from .data_sources import prices

# Bug reale trovato in produzione il 2026-09-04: fetch_daily_history()
# include una barra per la sessione di OGGI anche a mercato ancora aperto
# (verificato dal vivo: due chiamate a pochi secondi di distanza a mercato
# aperto ritornavano close/volume diversi per la stessa data — una barra
# ancora in aggiornamento, non la chiusura definitiva). price_on_or_after()
# la prenderebbe come "prima barra >= target_date" per un orizzonte che
# scade proprio oggi, valutando la previsione contro un prezzo non
# definitivo e scrivendolo per sempre nella catena hash. Rischio concreto
# per un run manuale di recupero, che (a differenza dei due tick
# schedulati, entrambi dopo le 20:15 UTC/22:15 italiane) può partire in
# qualunque momento della giornata.
#
# Secondo bug reale, stessa famiglia, trovato il 2026-09-04 da revisione
# del codice: il primo gate confrontava target_at.date() con oggi, non la
# data della barra REALMENTE restituita da price_on_or_after(). Un
# orizzonte 1g generato di venerdì ha target_at = sabato
# (_target_at somma giorni di calendario, non di borsa); un run manuale il
# lunedì successivo, prima delle 16:00 ET, aveva target_at.date()=sabato
# != oggi=lunedì, quindi il gate non scattava — ma price_on_or_after()
# avanza comunque alla prima barra disponibile >= sabato, cioè quella di
# lunedì, riproducendo esattamente il bug che questo gate doveva evitare.
# Stesso problema per un orizzonte che cade su una festività di borsa.
# Fix: controllare la data della barra DOPO averla ottenuta, non provare a
# indovinarla prima dalla sola data dell'orizzonte.
MARKET_CLOSE_ET = dt.time(16, 0)


def _find_prediction(asset: str, prediction_id: str) -> dict | None:
    for record in storage.read_all(config.predictions_file(asset)):
        if record["id"] == prediction_id:
            return record
    return None


def run(dry_run: bool, now_utc: dt.datetime | None = None) -> None:
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    now_et = now_utc.astimezone(config.EASTERN)
    pending = storage.load_pending()
    if not pending:
        print("Nessuna previsione in attesa di valutazione.")
    else:
        for entry in pending:
            target_at = dt.datetime.fromisoformat(entry["target_at"])
            if target_at > now_utc:
                continue

            asset = entry["asset"]

            prediction = _find_prediction(asset, entry["id"])
            if prediction is None:
                print(f"[{asset}] previsione {entry['id']} non trovata, salto.")
                continue

            try:
                target_bar = prices.price_on_or_after(asset, target_at.date().isoformat())
            except Exception as exc:  # noqa: BLE001
                print(f"[{asset}] prezzo reale non ancora disponibile per {entry['id']}: {exc}")
                continue

            if target_bar["date"] == now_et.date().isoformat() and now_et.time() < MARKET_CLOSE_ET:
                print(
                    f"[{asset}] la barra disponibile ({target_bar['date']}) è quella di oggi e il "
                    f"mercato è ancora aperto ({now_et.strftime('%H:%M')} ET): valutazione rimandata "
                    "a dopo la chiusura (16:00 ET), per non usare un prezzo non ancora definitivo."
                )
                continue

            price_at_generation = prediction["price_at_generation"]
            actual_change_pct = round(
                (target_bar["close"] - price_at_generation) / price_at_generation * 100, 4
            )
            # Riusa la soglia congelata al momento della previsione: mai ricalcolata,
            # per evitare look-ahead bias nella misura di accuratezza.
            actual_class = volatility.classify_change(
                actual_change_pct, prediction["volatility_threshold_pct"]
            )
            outcome = {
                "prediction_id": entry["id"],
                "asset": asset,
                "horizon": entry["horizon"],
                "evaluated_at": now_utc.isoformat(),
                "price_at_target": target_bar["close"],
                "target_bar_date": target_bar["date"],
                "actual_change_pct": actual_change_pct,
                "actual_class": actual_class,
                "predicted_class": prediction["predicted_class"],
                "confidence": prediction["confidence"],
                "correct": actual_class == prediction["predicted_class"],
            }

            if dry_run:
                print(f"[DRY-RUN] outcome {asset}/{entry['horizon']}: {outcome}")
                continue

            storage.append_record(config.outcomes_file(asset), outcome)
            storage.remove_pending(entry["id"])
            print(
                f"[{asset}/{entry['horizon']}] valutata: predetto {outcome['predicted_class']} "
                f"reale {outcome['actual_class']} -> {'CORRETTO' if outcome['correct'] else 'ERRATO'}"
            )

    if not dry_run:
        report.generate_report()
        print(f"{config.REPORT_FILE} rigenerato.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
