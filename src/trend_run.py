"""Orchestratore chiamato da .github/workflows/trend.yml.

Genera un'analisi di trend di lungo periodo per ogni asset in
config.ROBOTICS_ASSETS, con cadenza per-asset (config.ASSET_CADENCE_MONTHS:
1 mese per THK/Harmonic Drive/TER, 3 mesi/trimestrale per VRT — il segnale
che conta per VRT, la crescita di backlog/ordini, esce solo con le
trimestrali) — analogo di predict_run.py, ma su orizzonti pluriennali
invece che orario/giornaliero.

Stato in data/_state/trend_done.json: {"ASSET": "ultimo periodo fatto"},
dove il periodo è "AAAA-MM" per cadenza mensile o "AAAA-MM" del primo mese
del trimestre per cadenza trimestrale (vedi _period_key) — un solo file
condiviso invece di un file per mese, così un asset trimestrale non
richiede una logica separata dagli asset mensili: stesso schema, cadenza
diversa. Sostituisce il precedente trend_slots_<anno>-<mese>.json (un
file per mese, cadenza mensile fissa per tutti) il 2026-09-17 con
l'aggiunta di VRT."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid

from . import budget, config, sector_report, storage, technicals, trend_analysis, trend_predictor
from .data_sources import news, prices


def _state_path() -> str:
    return f"{config.STATE_DIR}/trend_done.json"


def _period_key(asset: str, today: dt.date) -> str:
    """"AAAA-MM" del primo mese del periodo corrente per la cadenza di
    quell'asset — es. cadenza mensile: sempre il mese corrente; cadenza
    trimestrale: 01/04/07/10 (il trimestre a cui appartiene oggi)."""
    months = config.ASSET_CADENCE_MONTHS.get(asset, 1)
    period_index = (today.month - 1) // months
    period_start_month = period_index * months + 1
    return f"{today.year}-{period_start_month:02d}"


def _load_done() -> dict[str, str]:
    if not os.path.exists(_state_path()):
        return {}
    with open(_state_path(), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _is_due(asset: str, today: dt.date, done: dict[str, str]) -> bool:
    return done.get(asset) != _period_key(asset, today)


def _mark_asset_done(asset: str, today: dt.date) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    done = _load_done()
    done[asset] = _period_key(asset, today)
    with open(_state_path(), "w", encoding="utf-8") as fh:
        json.dump(done, fh)


def run(dry_run: bool, force: bool) -> None:
    now_utc = dt.datetime.now(dt.timezone.utc)
    today = now_utc.date()
    done = _load_done()

    if not force and not any(_is_due(a, today, done) for a in config.ROBOTICS_ASSETS):
        print("Nessun asset in scadenza per questo periodo, esco senza consumare budget.")
        return

    try:
        benchmark_bars = prices.fetch_daily_history(config.ROBOTICS_BENCHMARK_TICKER, range_="10y")
    except Exception as exc:  # noqa: BLE001 - il benchmark è un segnale opzionale
        print(f"[benchmark {config.ROBOTICS_BENCHMARK_TICKER}] skipped_no_data: {exc}")
        benchmark_bars = None

    for asset in config.ROBOTICS_ASSETS:
        if not force and not _is_due(asset, today, done):
            print(f"[{asset}] già analizzato per questo periodo, salto.")
            continue

        ticker = config.ROBOTICS_TICKER[asset]
        try:
            bars = prices.fetch_daily_history(ticker, range_="10y")
        except Exception as exc:  # noqa: BLE001
            print(f"[{asset}] skipped_no_data: {exc}")
            continue

        metrics = trend_analysis.build_trend_metrics(bars, config.TREND_HORIZONS_YEARS, config.TREND_MA_WEEKS)

        # Storico episodi "molto estesa" + esito reale di ognuno (correzione,
        # recupero) e distanza da ATH/52w high: puro calcolo sui prezzi già
        # scaricati, nessuna chiamata AI per questi numeri — passati al
        # modello solo come contesto da commentare, mai da "calcolare" lui
        # stesso (vedi trend_analysis.find_extended_episodes).
        weekly_series = trend_analysis.build_weekly_series(bars, config.TREND_MA_WEEKS)
        episodes = trend_analysis.find_extended_episodes(weekly_series)
        episode_summary = trend_analysis.summarize_extended_episodes(episodes)
        ath_info = trend_analysis.compute_ath_distance(bars)
        range_52w = technicals.compute_52w_range_position(bars)
        ath_info["pct_from_52w_high"] = range_52w["pct_from_high"] if range_52w else None
        metrics["extended_episodes"] = episode_summary
        metrics["ath_distance"] = ath_info

        sox_correlation = None
        beta_vs_sox = None
        if benchmark_bars:
            sox_correlation = trend_analysis.compute_annual_return_correlation(bars, benchmark_bars)
            # lookback=252 (~1 anno di barre) invece del default 60 di
            # technicals.compute_beta: qui serve una stima di beta stabile
            # su orizzonte lungo, non reattiva al breve termine come per
            # predict_run.py.
            beta_vs_sox = technicals.compute_beta(bars, benchmark_bars, lookback=252)

        news_items = news.fetch_recent_news(config.ROBOTICS_NEWS_QUERY[asset], lookback_days=14, limit=6)

        if not dry_run and not budget.reserve_trend_call():
            print(f"[{asset}] skipped_budget_cap: tetto mensile raggiunto")
            continue

        try:
            analysis = trend_predictor.generate_trend_analysis(
                asset, ticker, metrics, news_items, sox_correlation, beta_vs_sox,
                config.TREND_PROMPT_CONTEXT[asset],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{asset}] skipped_model_error: {exc}")
            continue

        record = {
            "id": str(uuid.uuid4()),
            "asset": asset,
            "ticker": ticker,
            "generated_at": now_utc.isoformat(),
            "model": config.ANTHROPIC_MODEL,
            "metrics": metrics,
            "sox_correlation": sox_correlation,
            "beta_vs_sox": beta_vs_sox,
            "news_count": len(news_items),
            "trend_direction": analysis["trend_direction"],
            "confidence": analysis["confidence"],
            "cycle_assessment": analysis["cycle_assessment"],
            "key_drivers": analysis["key_drivers"],
            "risk_notes": analysis["risk_notes"],
        }

        if dry_run:
            print(f"[DRY-RUN] {asset}: {json.dumps(record, indent=2, ensure_ascii=False)}")
            continue

        saved = storage.append_record(config.trend_file(asset), record)

        # Non hash-chained come predictions.jsonl/trend.jsonl (qui non c'è
        # nulla da verificare, è solo il dato per il grafico prezzo+MA sulla
        # pagina Robotica): sovrascritto ad ogni run, stesso pattern di
        # snapshot_file() per gli asset Tech.
        series_path = config.price_series_file(asset)
        os.makedirs(os.path.dirname(series_path), exist_ok=True)
        with open(series_path, "w", encoding="utf-8") as fh:
            json.dump({"asset": asset, "ticker": ticker, "ma_weeks": config.TREND_MA_WEEKS, "weekly": weekly_series}, fh)

        print(
            f"[{asset}] analisi trend salvata: {saved['trend_direction']} "
            f"(confidence {saved['confidence']}%, fase ciclo {metrics['cycle_phase']})"
        )
        _mark_asset_done(asset, today)

    _run_sector_summary(now_utc, today, dry_run, force)


def _run_sector_summary(now_utc: dt.datetime, today: dt.date, dry_run: bool, force: bool) -> None:
    """Sintesi mensile "a livello di paniere": confronta le ultime letture
    disponibili di tutti gli asset (non rifà il fetch prezzi/news, riusa i
    trend.jsonl già scritti sopra in questo stesso run o in run precedenti).
    Stessa cadenza/stato di _is_due/_mark_asset_done sopra, con la chiave
    pseudo-asset config.SECTOR_SUMMARY_KEY."""
    done = _load_done()
    if not force and not _is_due(config.SECTOR_SUMMARY_KEY, today, done):
        print("[sector_summary] già fatta per questo periodo, salto.")
        return

    asset_records: dict[str, dict] = {}
    for asset in config.ROBOTICS_ASSETS:
        records = storage.read_all(config.trend_file(asset))
        if records:
            asset_records[asset] = records[-1]

    if len(asset_records) < 2:
        print(f"[sector_summary] skipped_no_data: solo {len(asset_records)} asset con almeno una lettura, servono almeno 2.")
        return

    aggregates = trend_analysis.compute_sector_aggregates(asset_records)

    if not dry_run and not budget.reserve_trend_call():
        print("[sector_summary] skipped_budget_cap: tetto mensile raggiunto")
        return

    try:
        analysis = sector_report.generate_sector_report(asset_records, aggregates)
    except Exception as exc:  # noqa: BLE001
        print(f"[sector_summary] skipped_model_error: {exc}")
        return

    record = {
        "id": str(uuid.uuid4()),
        "generated_at": now_utc.isoformat(),
        "model": config.ANTHROPIC_MODEL,
        "assets_snapshot": {
            asset: {
                "generated_at": r.get("generated_at"),
                "trend_direction": r.get("trend_direction"),
                "cycle_phase": r.get("metrics", {}).get("cycle_phase"),
                "confidence": r.get("confidence"),
            }
            for asset, r in asset_records.items()
        },
        "aggregates": aggregates,
        "sector_narrative": analysis["sector_narrative"],
        "overall_direction": analysis["overall_direction"],
    }

    if dry_run:
        print(f"[DRY-RUN] sector_summary: {json.dumps(record, indent=2, ensure_ascii=False)}")
        return

    saved = storage.append_record(config.sector_summary_file(), record)
    print(f"[sector_summary] sintesi salvata: {saved['overall_direction']} su {len(asset_records)} asset")
    _mark_asset_done(config.SECTOR_SUMMARY_KEY, today)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="ignora il controllo 'già fatto per questo periodo'")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
