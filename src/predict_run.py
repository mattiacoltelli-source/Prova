"""Orchestratore chiamato da .github/workflows/predict.yml.

Genera previsioni per ogni asset x orizzonte, se siamo in uno degli slot
orari configurati (o se --force è passato per un test manuale) e se il
budget giornaliero di chiamate AI lo consente.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid

from . import budget, config, predictor, storage, technical_indicators, volatility
from .data_sources import fundamentals, macro, news, prices


def in_prediction_slot(now_et: dt.datetime) -> bool:
    for hour, minute, tolerance in config.PREDICTION_SLOTS_ET:
        slot = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if abs((now_et - slot).total_seconds()) <= tolerance * 60:
            return True
    return False


def run(dry_run: bool, force: bool) -> None:
    now_et = dt.datetime.now(config.EASTERN)
    if not force and now_et.weekday() >= 5:
        print(f"Weekend ({now_et.isoformat()}), nessuna previsione.")
        return
    if not force and not in_prediction_slot(now_et):
        print(f"Fuori dagli slot di previsione ({now_et.isoformat()}), esco senza consumare budget.")
        return

    now_utc = dt.datetime.now(dt.timezone.utc)

    for asset in config.ASSETS:
        try:
            bars = prices.fetch_daily_history(asset)
            price, price_asof, price_source = prices.fetch_latest_price(asset)
        except Exception as exc:  # noqa: BLE001
            print(f"[{asset}] skipped_no_data: {exc}")
            continue

        news_items = news.fetch_recent_news(asset)
        fundamentals_data = fundamentals.fetch_fundamentals(asset)
        macro_data = macro.fetch_macro_snapshot() if _macro_key_present() else {}

        closes = [b["close"] for b in bars] if bars else []
        tech_indicators = technical_indicators.compute_all_indicators(closes) if closes else None

        for horizon in config.HORIZONS:
            try:
                threshold_pct = volatility.compute_threshold_pct(bars, horizon)
            except ValueError as exc:
                print(f"[{asset}/{horizon.code}] skipped_no_data: {exc}")
                continue

            if not dry_run and not budget.reserve_call():
                print(f"[{asset}/{horizon.code}] skipped_budget_cap: tetto giornaliero raggiunto")
                continue

            try:
                pred = predictor.generate_prediction(
                    asset, horizon.code, price, price_asof, threshold_pct,
                    news_items, fundamentals_data, macro_data, tech_indicators,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{asset}/{horizon.code}] skipped_model_error: {exc}")
                continue

            record = {
                "id": str(uuid.uuid4()),
                "asset": asset,
                "horizon": horizon.code,
                "generated_at": now_utc.isoformat(),
                "target_at": (now_utc + dt.timedelta(days=horizon.days)).isoformat(),
                "price_at_generation": price,
                "price_source": price_source,
                "predicted_class": pred["predicted_class"],
                "confidence": pred["confidence"],
                "volatility_threshold_pct": threshold_pct,
                "model": config.ANTHROPIC_MODEL,
                "inputs_summary": {
                    "news_count": len(news_items),
                    "fundamentals_source": fundamentals_data["source"] if fundamentals_data else None,
                    "macro_keys": sorted(macro_data.keys()),
                },
                "reasoning_short": pred["reasoning_short"],
            }

            if dry_run:
                print(f"[DRY-RUN] {asset}/{horizon.code}: {record}")
                continue

            saved = storage.append_record(config.predictions_file(asset), record)
            storage.add_pending(
                {"id": saved["id"], "asset": asset, "horizon": horizon.code, "target_at": saved["target_at"]}
            )
            print(f"[{asset}/{horizon.code}] previsione salvata: {saved['predicted_class']} ({saved['confidence']}%)")


def _macro_key_present() -> bool:
    import os

    return bool(os.environ.get("FRED_API_KEY"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="ignora il controllo dello slot orario")
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
