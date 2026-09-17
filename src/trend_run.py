"""Orchestratore chiamato da .github/workflows/trend.yml.

Genera un'analisi di trend di lungo periodo per ogni asset in
config.ROBOTICS_ASSETS, al massimo una volta per settimana ISO (stato in
data/_state/trend_slots_<anno>-W<settimana>.json) — analogo di
predict_run.py, ma con cadenza settimanale invece che oraria: un ciclo
semiconduttori/robotica non cambia in modo significativo da un giorno
all'altro, ricalcolarlo più spesso sprecherebbe solo budget AI."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid

from . import budget, config, storage, technicals, trend_analysis, trend_predictor
from .data_sources import news, prices


def _slot_state_path(iso_year: int, iso_week: int) -> str:
    return f"{config.STATE_DIR}/trend_slots_{iso_year}-W{iso_week:02d}.json"


def _current_iso_week() -> tuple[int, int]:
    iso = dt.date.today().isocalendar()
    return iso[0], iso[1]


def _done_this_week() -> set[str]:
    year, week = _current_iso_week()
    path = _slot_state_path(year, week)
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as fh:
        return set(json.load(fh).get("done_assets", []))


def _mark_asset_done(asset: str) -> None:
    year, week = _current_iso_week()
    os.makedirs(config.STATE_DIR, exist_ok=True)
    done = _done_this_week() | {asset}
    with open(_slot_state_path(year, week), "w", encoding="utf-8") as fh:
        json.dump({"iso_year": year, "iso_week": week, "done_assets": sorted(done)}, fh)


def run(dry_run: bool, force: bool) -> None:
    now_utc = dt.datetime.now(dt.timezone.utc)
    done = _done_this_week()

    if not force and set(config.ROBOTICS_ASSETS) <= done:
        print("Tutti gli asset robotica già analizzati questa settimana, esco senza consumare budget.")
        return

    try:
        benchmark_bars = prices.fetch_daily_history(config.ROBOTICS_BENCHMARK_TICKER, range_="10y")
    except Exception as exc:  # noqa: BLE001 - il benchmark è un segnale opzionale
        print(f"[benchmark {config.ROBOTICS_BENCHMARK_TICKER}] skipped_no_data: {exc}")
        benchmark_bars = None

    for asset in config.ROBOTICS_ASSETS:
        if not force and asset in done:
            print(f"[{asset}] già analizzato questa settimana, salto.")
            continue

        ticker = config.ROBOTICS_TICKER[asset]
        try:
            bars = prices.fetch_daily_history(ticker, range_="10y")
        except Exception as exc:  # noqa: BLE001
            print(f"[{asset}] skipped_no_data: {exc}")
            continue

        metrics = trend_analysis.build_trend_metrics(bars, config.TREND_HORIZONS_YEARS, config.TREND_MA_WEEKS)

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
            print(f"[{asset}] skipped_budget_cap: tetto settimanale raggiunto")
            continue

        try:
            analysis = trend_predictor.generate_trend_analysis(
                asset, ticker, metrics, news_items, sox_correlation, beta_vs_sox,
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
        weekly_series = trend_analysis.build_weekly_series(bars, config.TREND_MA_WEEKS)
        series_path = config.price_series_file(asset)
        os.makedirs(os.path.dirname(series_path), exist_ok=True)
        with open(series_path, "w", encoding="utf-8") as fh:
            json.dump({"asset": asset, "ticker": ticker, "ma_weeks": config.TREND_MA_WEEKS, "weekly": weekly_series}, fh)

        print(
            f"[{asset}] analisi trend salvata: {saved['trend_direction']} "
            f"(confidence {saved['confidence']}%, fase ciclo {metrics['cycle_phase']})"
        )
        _mark_asset_done(asset)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="ignora il controllo 'già fatto questa settimana'")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
