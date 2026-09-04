"""Orchestratore chiamato da .github/workflows/predict.yml.

Genera previsioni per ogni asset x orizzonte, se siamo in uno degli slot
orari configurati (o se --force è passato per un test manuale) e se il
budget giornaliero di chiamate AI lo consente.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid

from . import budget, config, predictor, storage, technicals, volatility
from .data_sources import fundamentals, insider, macro, news, prices

BENCHMARK_TICKER = "SPY"

# fetch_analyst_outlook costa 2 chiamate Alpha Vantage per asset (6/giorno
# per i 3 asset), sul tetto gratuito condiviso di 25/giorno con
# fondamentali/news di riserva — in pratica spesso già esaurito da un solo
# giorno di uso normale/di test (osservato in produzione il 2026-09-04: la
# primissima chiamata analyst_outlook della giornata ha trovato la quota
# già a zero). Le stime di consenso e la prossima data di bilancio non
# cambiano in modo significativo da un giorno all'altro, quindi una
# chiamata riuscita resta valida per diversi giorni invece che uno solo —
# riduce il consumo di quota di questa funzione di ~7x, lasciando margine
# reale alle altre due fonti che condividono la stessa chiave.
ANALYST_OUTLOOK_CACHE_DAYS = 7

# Apertura regolare NYSE/NASDAQ. Prima di quest'ora, prices.fetch_latest_price()
# ritorna ancora il prezzo dell'ultima chiusura (Yahoo regularMarketPrice non si
# aggiorna finché la sessione regolare non riparte); dopo, ritornerebbe invece
# un prezzo intraday in movimento — inutilizzabile come "prezzo di riferimento"
# di una previsione, perché l'orizzonte di ogni previsione (target_at) deve
# essere ancorato alla data di una chiusura REALE, sempre la stessa usata come
# prezzo. Vedi _reference_price().
MARKET_OPEN_ET = dt.time(9, 30)


def _reference_price(asset: str, bars: list, now_et: dt.datetime) -> tuple[float, str, str, dt.date]:
    """Prezzo di riferimento per la previsione (price, asof, source) e la
    data della sessione a cui appartiene — sempre l'ultima chiusura REALE
    già conclusa, mai un prezzo intraday in corso, a prescindere da quando
    lo script gira (schedulato prima dell'apertura, o un recupero manuale
    più tardi).

    Bug reale in produzione il 2026-09-03: un run manuale partito 1 minuto
    dopo l'apertura (9:31 ET) ha preso come prezzo di riferimento un
    prezzo intraday di oggi, ma l'orizzonte "1g" è stato comunque ancorato
    a "oggi + 1 giorno" (calcolato solo dall'orario di esecuzione) — la
    previsione ha finito per coprire il resto della sessione di oggi PIÙ
    l'intera sessione di domani, quasi due giorni di trading invece di
    uno. La data di sessione ritornata qui è sempre quella VERA del
    prezzo usato, cosicché target_at (vedi _target_at()) resti sempre
    coerente con esso, indipendentemente dall'orario di esecuzione.

    Secondo bug reale, stessa famiglia, trovato il 2026-09-03 da revisione
    del codice: il ramo pre-apertura calcolava la data di sessione come
    "oggi - 1 giorno" senza controllare se ieri fosse un vero giorno di
    borsa. Un lunedì l'ultima chiusura vera è venerdì, non domenica — per
    l'orizzonte 1g il calcolo si autocorreggeva per puro caso (arrotondato
    comunque al lunedì da price_on_or_after in fase di valutazione), ma
    per 7g/1m l'orizzonte finiva ancorato 2-3 giorni più avanti del
    dovuto, ogni lunedì e dopo ogni festività, sballando silenziosamente
    l'accuratezza misurata su quei due orizzonti. Fix: la data di sessione
    si legge sempre dall'ultima barra storica reale precedente a oggi
    (stessa fonte usata dal ramo post-apertura), mai da un'aritmetica sul
    calendario."""
    today_iso = now_et.date().isoformat()
    completed = [bar for bar in bars if bar["date"] < today_iso]
    if not completed:
        raise ValueError(f"Nessuna chiusura storica precedente a oggi per {asset}")
    session_date = dt.date.fromisoformat(completed[-1]["date"])

    if now_et.time() < MARKET_OPEN_ET:
        price, asof, source = prices.fetch_latest_price(asset)
        return price, asof, source, session_date

    last_bar = completed[-1]
    asof = f"{last_bar['date']}T00:00:00+00:00"
    return last_bar["close"], asof, "historical_bar", session_date


def _target_at(session_date: dt.date, horizon_days: int) -> dt.datetime:
    return dt.datetime.combine(session_date, dt.time.min, tzinfo=dt.timezone.utc) + dt.timedelta(days=horizon_days)


def _slot_label(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _slots_state_path(day: dt.date) -> str:
    return f"{config.STATE_DIR}/predict_slots_{day.isoformat()}.json"


def _done_slots(day: dt.date) -> set[str]:
    path = _slots_state_path(day)
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as fh:
        return set(json.load(fh).get("done_slots", []))


def _mark_slot_done(day: dt.date, label: str) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    done = _done_slots(day) | {label}
    with open(_slots_state_path(day), "w", encoding="utf-8") as fh:
        json.dump({"date": day.isoformat(), "done_slots": sorted(done)}, fh)


def _mark_today_done(day: dt.date, slot_label: str) -> None:
    """Segna come fatto lo slot appena eseguito. Un --force reale (non
    dry-run) copre un giro di previsioni completo esattamente come un tick
    schedulato, quindi marca TUTTI gli slot configurati del giorno — non
    solo un'etichetta "manual-force" a parte, che find_due_slot non
    riconoscerebbe mai come uno slot vero. Bug osservato in produzione il
    2026-09-02: un recupero manuale con --force non marcava nulla, così un
    tick schedulato scattato più tardi lo stesso giorno trovava lo slot
    ancora libero e generava un secondo giro di previsioni reali duplicate
    per NVDA/MSFT/AAPL."""
    if slot_label == "manual-force":
        for hour, minute in config.PREDICTION_SLOTS_ET:
            _mark_slot_done(day, _slot_label(hour, minute))
    else:
        _mark_slot_done(day, slot_label)


def _analyst_outlook_state_path(asset: str, day: dt.date) -> str:
    return f"{config.STATE_DIR}/analyst_outlook_{asset.lower()}_{day.isoformat()}.json"


def _cached_analyst_outlook(asset: str, day: dt.date) -> tuple[bool, dict | None]:
    """(già disponibile in cache?, outlook-o-None). La cache di OGGI (anche
    None, cioè un tentativo già fatto e fallito) blocca sempre un secondo
    fetch lo stesso giorno, come prima. In più, riusa un outlook REALE
    (mai un fallimento) trovato in uno degli ultimi ANALYST_OUTLOOK_CACHE_DAYS
    giorni: un fallimento vecchio (quota esaurita quel giorno) non viene
    mai riusato, si ritenta comunque al prossimo run reale."""
    path = _analyst_outlook_state_path(asset, day)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return True, json.load(fh).get("outlook")

    for offset in range(1, ANALYST_OUTLOOK_CACHE_DAYS):
        candidate_path = _analyst_outlook_state_path(asset, day - dt.timedelta(days=offset))
        if not os.path.exists(candidate_path):
            continue
        with open(candidate_path, "r", encoding="utf-8") as fh:
            outlook = json.load(fh).get("outlook")
        if outlook is not None:
            return True, outlook

    return False, None


def _save_analyst_outlook_cache(asset: str, day: dt.date, outlook: dict | None) -> None:
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(_analyst_outlook_state_path(asset, day), "w", encoding="utf-8") as fh:
        json.dump({"date": day.isoformat(), "outlook": outlook}, fh)


def _get_analyst_outlook(asset: str, day: dt.date, dry_run: bool) -> dict | None:
    already_fetched, cached = _cached_analyst_outlook(asset, day)
    if already_fetched:
        return cached
    if dry_run:
        # Un test non deve consumare la quota gratuita di Alpha Vantage
        # (25 richieste/giorno, condivisa con fondamentali/news di riserva)
        # che serve ai run reali: niente chiamata, niente cache scritta, così
        # un run reale nello stesso giorno può ancora tentare il fetch vero.
        return None
    try:
        outlook = fundamentals.fetch_analyst_outlook(asset, today=day)
    except Exception:  # noqa: BLE001 - segnale opzionale, mai bloccante
        outlook = None
    _save_analyst_outlook_cache(asset, day, outlook)
    return outlook


def find_due_slot(now_et: dt.datetime) -> str | None:
    """Ritorna il primo slot del giorno già scattato e non ancora eseguito,
    entro la finestra di recupero. Robusto a run schedulate in ritardo:
    una run in ritardo esegue comunque il prossimo slot dovuto invece di
    saltarlo (a differenza di un confronto a tolleranza simmetrica attorno
    all'orario nominale)."""
    done = _done_slots(now_et.date())
    for hour, minute in config.PREDICTION_SLOTS_ET:
        label = _slot_label(hour, minute)
        if label in done:
            continue
        slot_dt = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot_dt <= now_et <= slot_dt + dt.timedelta(minutes=config.SLOT_CATCHUP_MINUTES):
            return label
    return None


def run(dry_run: bool, force: bool) -> None:
    now_et = dt.datetime.now(config.EASTERN)
    if not force and now_et.weekday() >= 5:
        print(f"Weekend ({now_et.isoformat()}), nessuna previsione.")
        return

    if force:
        # --force ignora solo il vincolo di ORARIO (utile oltre la finestra
        # di recupero, es. un run manuale tardivo), MAI il controllo "già
        # fatto oggi": senza questo controllo un secondo tap su "Run
        # workflow" lo stesso giorno (o un force lanciato dopo che lo slot
        # schedulato era già scattato con successo) rigenererebbe un
        # secondo giro di previsioni reali duplicate per NVDA/MSFT/AAPL,
        # con relativo consumo di budget AI — esattamente il tipo di
        # doppione che _mark_today_done esiste per evitare nell'altro
        # verso (force prima, schedulato dopo).
        already_done = _done_slots(now_et.date())
        if all(_slot_label(h, m) in already_done for h, m in config.PREDICTION_SLOTS_ET):
            print(f"Slot di oggi già fatto ({now_et.isoformat()}), --force non rigenera previsioni duplicate.")
            return
        slot_label = "manual-force"
    else:
        slot_label = find_due_slot(now_et)
        if slot_label is None:
            print(f"Nessuno slot dovuto ({now_et.isoformat()}), esco senza consumare budget.")
            return

    now_utc = dt.datetime.now(dt.timezone.utc)

    try:
        benchmark_bars = prices.fetch_daily_history(BENCHMARK_TICKER)
    except Exception:  # noqa: BLE001 - la forza relativa è un segnale opzionale
        benchmark_bars = None

    sector_bars_by_ticker: dict[str, list] = {}
    for sector_ticker in set(config.SECTOR_BENCHMARK.values()):
        try:
            sector_bars_by_ticker[sector_ticker] = prices.fetch_daily_history(sector_ticker)
        except Exception:  # noqa: BLE001 - segnale opzionale, mai bloccante
            continue

    for asset in config.ASSETS:
        try:
            bars = prices.fetch_daily_history(asset)
            price, price_asof, price_source, session_date = _reference_price(asset, bars, now_et)
        except Exception as exc:  # noqa: BLE001
            print(f"[{asset}] skipped_no_data: {exc}")
            continue

        news_items = news.fetch_recent_news(asset)
        fundamentals_data = fundamentals.fetch_fundamentals(asset)
        macro_data = macro.fetch_macro_snapshot() if _macro_key_present() else {}
        analyst_outlook = _get_analyst_outlook(asset, now_et.date(), dry_run)
        insider_summary = insider.fetch_insider_summary(asset)

        sector_ticker = config.SECTOR_BENCHMARK.get(asset)
        sector_bars = sector_bars_by_ticker.get(sector_ticker) if sector_ticker else None

        technical_signals = {
            "obv_trend": technicals.compute_obv_trend(bars),
            "cmf": technicals.compute_cmf(bars),
            "relative_strength_vs_spy_pct": (
                technicals.compute_relative_strength_pct(bars, benchmark_bars)
                if benchmark_bars
                else None
            ),
            "sma_trend": technicals.compute_sma_trend(bars),
            "ema_trend": technicals.compute_ema_trend(bars),
            "rsi_14": technicals.compute_rsi(bars),
            "macd": technicals.compute_macd(bars),
            "atr_pct": technicals.compute_atr_pct(bars),
            "beta_vs_spy": (
                technicals.compute_beta(bars, benchmark_bars) if benchmark_bars else None
            ),
            "bollinger_percent_b": technicals.compute_bollinger_percent_b(bars),
            "range_52w": technicals.compute_52w_range_position(bars),
            "relative_volume": technicals.compute_relative_volume(bars),
            "sector_benchmark": sector_ticker,
            "relative_strength_vs_sector_pct": (
                technicals.compute_relative_strength_pct(bars, sector_bars)
                if sector_bars
                else None
            ),
            "beta_vs_sector": (
                technicals.compute_beta(bars, sector_bars) if sector_bars else None
            ),
        }

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
                    news_items, fundamentals_data, macro_data, technical_signals, analyst_outlook,
                    insider_summary,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{asset}/{horizon.code}] skipped_model_error: {exc}")
                continue

            record = {
                "id": str(uuid.uuid4()),
                "asset": asset,
                "horizon": horizon.code,
                "generated_at": now_utc.isoformat(),
                "target_at": _target_at(session_date, horizon.days).isoformat(),
                "price_at_generation": price,
                "price_source": price_source,
                "predicted_class": pred["predicted_class"],
                "confidence": pred["confidence"],
                "volatility_threshold_pct": threshold_pct,
                "model": config.ANTHROPIC_MODEL,
                "inputs_summary": {
                    "news_count": len(news_items),
                    "news_sentiment_avg": news.average_sentiment(news_items),
                    "fundamentals_source": fundamentals_data["source"] if fundamentals_data else None,
                    "macro_keys": sorted(macro_data.keys()),
                    "technicals": technical_signals,
                    "analyst_outlook": analyst_outlook,
                    "insider_summary": insider_summary,
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

    if not dry_run:
        _mark_today_done(now_et.date(), slot_label)


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
