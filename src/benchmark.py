"""Strategie di confronto per la pagina Trading AI, calcolate SOLO da prezzi
pubblici (Yahoo Finance, con fallback Twelve Data — data_sources/prices.py,
stessa fonte usata altrove nel progetto) — zero chiamate AI, zero ordini
reali su Alpaca, zero costo aggiuntivo sul budget mensile. Entrambe
partono dalla stessa data e dallo stesso capitale di
data/ai_trader/experiment.json, per restare un confronto onesto a parità di
condizioni con l'esperimento reale.

Momentum e Mean Reversion sono due strategie quantitative classiche A
REGOLE FISSE, senza nessun giudizio AI, filosoficamente opposte — ogni
giorno tengono equal-weight i titoli dell'universo scanner (stesso di
ai_trader.py) fino a un massimo di posizioni pari al tetto di
diversificazione dell'esperimento reale, investendo in totale al massimo
AI_TRADER_MAX_EXPOSURE_PCT (35%) del proprio capitale — non più il 100%,
il resto resta in contanti, stesso tetto di rischio di AI reale:
- Momentum tiene chi ha il MIGLIOR rendimento recente (continuazione del
  trend), nessun titolo con momentum positivo -> tutta in contanti.
- Mean Reversion tiene chi ha il PEGGIOR rendimento recente (scommessa sul
  ritorno verso la media, non sulla continuazione), nessun titolo sceso ->
  tutta in contanti. Finestra più corta (vedi
  AI_TRADER_MEANREV_LOOKBACK_DAYS in config.py): un ipervenduto di breve
  periodo è il segnale, non un trend di fondo.
Condividono la stessa implementazione (_update_strategy sotto), parametrica
su file di stato, finestra, tetto di posizioni e direzione della
classifica — non due copie quasi identiche del codice.

Punteggio tecnico (richiesto dall'utente il 2026-11-02, "non voglio filtri
rigidi"): dentro la lista già filtrata per rendimento sopra (chi sale per
Momentum, chi scende per Mean Reversion — invariata), ogni titolo prende
una fascia di priorità (alta/media/bassa) da quanti criteri tecnici
soddisfa (RSI, posizione/direzione delle medie mobili, volume relativo —
vedi _momentum_technical_score/_meanrev_technical_score e le relative
costanti in config.py). La fascia RIORDINA, non filtra: un titolo in
fascia bassa resta comunque candidato, solo più in fondo alla lista — mai
un paniere vuoto per motivi tecnici quando ci sono candidati validi per
rendimento.

update_momentum/update_mean_reversion sono pensate per essere chiamate da
ai_trader_run.py dentro un try/except separato dalla logica di trading
reale (vedi _update_benchmarks lì): un fallimento qui — Yahoo
irraggiungibile, un ticker senza dati — non deve mai bloccare un ordine
vero. Idempotenti per giorno: una seconda chiamata nello stesso giorno (run
manuale ripetuto) non aggiunge un secondo punto.

Ogni record salvato distingue TRE prezzi diversi per ogni titolo tenuto,
deliberatamente non un unico campo "prices" (bug reale corretto il
2026-11-02: un unico campo veniva sovrascritto ogni giorno con il prezzo
del giorno stesso, quindi per un titolo tenuto da più giorni non c'era più
modo di sapere a quanto era stato comprato all'origine):
- entry_prices: il prezzo di INGRESSO di ogni titolo attualmente tenuto,
  invariato per tutta la durata del possesso (si aggiorna SOLO il giorno in
  cui il titolo entra nel paniere).
- mark_prices: il prezzo di OGGI di ogni titolo attualmente tenuto, usato
  sia per segnare a mercato il giorno dopo sia per mostrare il
  guadagno/perdita non ancora realizzato di una posizione aperta.
- exit_prices: presente solo per i titoli USCITI quel giorno — il prezzo a
  cui sono stati "venduti" (altrimenti andrebbe perso per sempre un attimo
  dopo essere stato calcolato: prices_today non sopravvive oltre questa
  chiamata).
"""
from __future__ import annotations

import datetime as dt

import json
import os

import requests

from . import config, data_health, storage, technicals
from .data_sources import prices
from .data_sources.prices import DailyBar

class BenchmarkError(RuntimeError):
    pass


def _fetch_bars(symbol: str) -> list[DailyBar]:
    """Storico di ~1 anno di borsa (data/chiusura/volume/massimo/minimo),
    con fallback Yahoo -> Twelve Data (prices.fetch_daily_history, già
    usato altrove nel progetto — non più una chiamata Yahoo diretta e
    senza riserva come prima). Era ~3 mesi fino al 2026-11-02: bastavano
    per il rendimento sul lookback delle strategie sotto, ma non per la
    SMA 200 del punteggio tecnico (richiede ~200 barre). L'ultima barra è
    il prezzo corrente, anche a mercato aperto."""
    bars = prices.fetch_daily_history(symbol, range_="1y")
    if len(bars) < 2:
        raise BenchmarkError(f"Storico insufficiente per {symbol}")
    return bars


def _sma_rising(bars: list[DailyBar], period: int = 50) -> bool | None:
    """SMA(period) di oggi sopra quella di AI_TRADER_SMA_RISING_LOOKBACK_DAYS
    giorni fa: la DIREZIONE della media, non solo la sua posizione rispetto
    al prezzo. None se lo storico non copre uno dei due punti — mai preso
    come "non crescente", solo come "non calcolabile" (il chiamante lo
    conta 0 punti, non un punto contro)."""
    lookback = config.AI_TRADER_SMA_RISING_LOOKBACK_DAYS
    if len(bars) <= lookback:
        return None
    sma_today = technicals.compute_sma(bars, period)
    sma_prior = technicals.compute_sma(bars[:-lookback], period)
    if sma_today is None or sma_prior is None:
        return None
    return sma_today > sma_prior


def _momentum_technical_score(bars: list[DailyBar]) -> int:
    """Quanti dei 5 criteri di precedenza Momentum sono soddisfatti (0-5) —
    vedi commento su config.AI_TRADER_MOMENTUM_RSI_RANGE per il perché di
    un punteggio semplice invece di una somma pesata. Un criterio non
    calcolabile (storico corto) non conta, non esclude."""
    score = 0
    last_close = bars[-1]["close"]

    rsi = technicals.compute_rsi(bars)
    low, high = config.AI_TRADER_MOMENTUM_RSI_RANGE
    if rsi is not None and low <= rsi <= high:
        score += 1

    sma50 = technicals.compute_sma(bars, 50)
    if sma50 is not None and last_close > sma50:
        score += 1

    if _sma_rising(bars, 50):
        score += 1

    sma200 = technicals.compute_sma(bars, 200)
    if sma200 is not None and last_close > sma200:
        score += 1

    relvol = technicals.compute_relative_volume(bars)
    if relvol is not None and relvol >= config.AI_TRADER_MOMENTUM_RELVOL_THRESHOLD:
        score += 1

    return score


def _meanrev_technical_score(bars: list[DailyBar]) -> int:
    """Quanti dei 4 criteri di precedenza Mean Reversion sono soddisfatti
    (0-4) — stesso principio di _momentum_technical_score sopra."""
    score = 0
    last_close = bars[-1]["close"]

    rsi = technicals.compute_rsi(bars)
    if rsi is not None and rsi < config.AI_TRADER_MEANREV_RSI_THRESHOLD:
        score += 1

    sma200 = technicals.compute_sma(bars, 200)
    if sma200 is not None and last_close > sma200:
        score += 1

    if _sma_rising(bars, 50):
        score += 1

    relvol = technicals.compute_relative_volume(bars)
    if relvol is not None and relvol >= config.AI_TRADER_MEANREV_RELVOL_THRESHOLD:
        score += 1

    return score


def _momentum_tier(score: int) -> int:
    """0=bassa, 1=media, 2=alta — soglie decise con l'utente sul massimo di
    5 punti di _momentum_technical_score."""
    if score >= 4:
        return 2
    if score >= 2:
        return 1
    return 0


def _meanrev_tier(score: int) -> int:
    """Come _momentum_tier, sul massimo di 4 punti di
    _meanrev_technical_score."""
    if score >= 3:
        return 2
    if score >= 1:
        return 1
    return 0


def _already_recorded_today(filepath: str, today_str: str) -> bool:
    records = storage.read_all(filepath)
    return bool(records) and records[-1].get("date") == today_str


def _expected_last_session(today: dt.date) -> str:
    """Ultima seduta USA attesa nei dati quando il giro gira nel giorno
    `today` (data UTC): l'ultimo giorno di borsa STRETTAMENTE precedente.
    Prudente apposta: il giro serale delle 22:10 UTC di un giorno di borsa
    potrebbe già avere la barra di quel giorno, ma qui si pretende solo
    quella di ieri; quello delle 02:00 UTC del giorno dopo deve avere quella
    del giorno appena chiuso."""
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in config.AI_TRADER_US_MARKET_HOLIDAYS:
        d -= dt.timedelta(days=1)
    return d.isoformat()


ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_RECENT_DAYS = 60  # ~40 sedute: bastano per rendimento 20gg, SMA lunghe restano a Yahoo
ALPACA_PRICE_DIFF_ALERT_PCT = 0.5


def _fetch_alpaca_bars(symbols: list[str], today: dt.date) -> dict[str, list[dict]]:
    """Barre giornaliere recenti (massimo, minimo, chiusura) di TUTTI i
    simboli in poche richieste da Alpaca — gli stessi prezzi con cui vengono
    eseguiti gli ordini di AI reale. Feed "sip" (tutte le borse, ritardo di
    15 minuti sul piano gratuito, irrilevante a mercato chiuso); se il piano
    lo rifiuta ripiega su "iex". Qualunque errore -> {} e il chiamante usa
    solo Yahoo: Alpaca migliora i prezzi, non è mai un punto di rottura."""
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return {}
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    start = (today - dt.timedelta(days=ALPACA_RECENT_DAYS)).isoformat()
    for feed in ("sip", "iex"):
        try:
            out: dict[str, list[dict]] = {}
            token = None
            for _ in range(20):
                params = {
                    "symbols": ",".join(symbols), "timeframe": "1Day", "start": start,
                    "adjustment": "raw", "feed": feed, "limit": 10000, "sort": "asc",
                }
                if token:
                    params["page_token"] = token
                resp = requests.get(ALPACA_DATA_URL, params=params, headers=headers, timeout=20)
                if not resp.ok:
                    raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
                payload = resp.json()
                for sym, rows in (payload.get("bars") or {}).items():
                    out.setdefault(sym, []).extend(rows)
                token = payload.get("next_page_token")
                if not token:
                    break
            if out:
                return {
                    sym: [
                        {"date": r["t"][:10], "close": float(r["c"]), "high": float(r["h"]), "low": float(r["l"])}
                        for r in rows
                    ]
                    for sym, rows in out.items()
                }
        except Exception:  # noqa: BLE001 - si prova l'altro feed, poi Yahoo
            continue
    return {}


def _merge_bars(yahoo_bars: list[DailyBar], alpaca_bars: list[dict]) -> tuple[list[DailyBar], float]:
    """Yahoo come base (storico lungo e volumi), prezzi di Alpaca sopra per
    le date che Alpaca copre. Ritorna anche la massima differenza % di
    chiusura tra le due fonti sulle date in comune (0 se nessuna)."""
    by_date = {b["date"]: dict(b) for b in yahoo_bars}
    max_diff = 0.0
    for a in alpaca_bars:
        cur = by_date.get(a["date"])
        if cur and cur.get("close"):
            max_diff = max(max_diff, abs(a["close"] / cur["close"] - 1) * 100)
        merged = cur or {"date": a["date"]}
        merged.update(close=a["close"], high=a["high"], low=a["low"])
        by_date[a["date"]] = merged
    return [by_date[d] for d in sorted(by_date)], max_diff  # type: ignore[misc]


def _write_price_check(today_str: str, compared: int, diffs: dict[str, float]) -> None:
    """Diagnostica Alpaca vs Yahoo: quali titoli differiscono oltre la soglia."""
    try:
        os.makedirs(config.STATE_DIR, exist_ok=True)
        flagged = {s: round(d, 2) for s, d in diffs.items() if d > ALPACA_PRICE_DIFF_ALERT_PCT}
        with open(os.path.join(config.STATE_DIR, "benchmark_price_check.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "date": today_str, "compared": compared,
                "max_diff_pct": round(max(diffs.values(), default=0.0), 2),
                "over_threshold": flagged,
            }, fh, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - diagnostica, mai fatale
        pass


def _universe() -> list[str]:
    return [s for s in config.SCANNER_STOCKS if s not in config.AI_TRADER_EXCLUDED_TICKERS]


def _update_strategy(
    filepath: str,
    today: dt.date,
    experiment: dict,
    lookback_days: int,
    top_n: int,
    pick_fallen: bool,
) -> None:
    """Un punto al giorno: segna a mercato il paniere di IERI con i prezzi di
    OGGI, poi decide il paniere per DOMANI in base al rendimento a
    lookback_days giorni di ogni titolo dell'universo. Nessun giudizio AI,
    nessun ordine reale: solo prezzi Yahoo e aritmetica.

    pick_fallen=False (Momentum): tiene chi è salito di più, mai chi è sceso.
    pick_fallen=True (Mean Reversion): tiene chi è sceso di più, mai chi è
    salito — stessa logica, classifica e condizione invertite."""
    today_str = today.isoformat()
    if _already_recorded_today(filepath, today_str):
        return

    prices_today: dict[str, float] = {}
    bars_by_symbol: dict[str, list[DailyBar]] = {}
    rank: list[tuple[str, float]] = []
    failed_symbols: list[str] = []
    # Un titolo alla volta, mai fatale per gli altri (stesso principio di
    # market_scanner.scan()): un ticker illiquido o senza dati quel giorno
    # non deve bloccare il calcolo per tutti gli altri. Se un titolo tenuto
    # da ieri non si riesce a riprezzare oggi, il suo contributo alla
    # performance di oggi viene semplicemente saltato (approssimazione
    # accettabile per un confronto indicativo, non per un ordine reale).
    # I falliti vengono comunque raccolti per data_health sotto: un singolo
    # ticker illiquido è normale, ma se falliscono tutti insieme è il
    # segnale che la fonte si è rotta (vedi config.DATA_HEALTH_FAILURE_RATE_ALERT_THRESHOLD).
    expected_session = _expected_last_session(today)
    alpaca_by_symbol = _fetch_alpaca_bars(_universe(), today)
    price_diffs: dict[str, float] = {}
    for symbol in _universe():
        alpaca_rows = alpaca_by_symbol.get(symbol)
        try:
            bars = _fetch_bars(symbol)
        except Exception:  # noqa: BLE001 - un titolo alla volta, mai fatale
            # Yahoo non risponde: se Alpaca ha il titolo si va avanti con le
            # sole barre recenti (senza volume e senza SMA 200: punteggi
            # tecnici a 0 punti, mai un'esclusione).
            if alpaca_rows:
                bars = list(alpaca_rows)
            else:
                failed_symbols.append(symbol)
                continue
        else:
            if alpaca_rows:
                bars, diff = _merge_bars(bars, alpaca_rows)
                price_diffs[symbol] = diff
        # Dati vecchi: l'ultima barra è precedente all'ultima seduta attesa
        # (la fonte non ha ancora pubblicato il giorno appena chiuso, o ha
        # servito una risposta in cache). Visto il 2026-11-04: tutti i 14
        # titoli tenuti con i prezzi di due sedute prima, quindi un giorno
        # "a rendimento zero" scritto per sbagliato. Stesso trattamento di
        # un fallimento di fetch: il titolo non entra nel calcolo di oggi.
        if bars[-1]["date"] < expected_session:
            failed_symbols.append(symbol)
            continue
        closes = [b["close"] for b in bars]
        prices_today[symbol] = closes[-1]
        bars_by_symbol[symbol] = bars
        if len(closes) > lookback_days:
            pct = closes[-1] / closes[-1 - lookback_days] - 1
            rank.append((symbol, pct))

    _write_price_check(today_str, len(price_diffs), price_diffs)
    try:
        data_health.record_fetch_health("benchmark", len(_universe()), failed_symbols)
    except Exception:  # noqa: BLE001 - lo stato di salute non deve mai bloccare la strategia vera
        pass

    # Se troppi titoli hanno dati non aggiornati (o non scaricabili) il
    # giorno NON si scrive: meglio un buco nel grafico, recuperato dal giro
    # dopo (che confronta con l'ultimo prezzo registrato), che un giorno a
    # rendimento zero con acquisti a prezzi vecchi. Lo stato di salute sopra
    # ha già segnalato il problema nell'app.
    universe_size = len(_universe())
    if universe_size and len(failed_symbols) / universe_size > config.DATA_HEALTH_FAILURE_RATE_ALERT_THRESHOLD:
        print(
            f"Benchmark {filepath}: {len(failed_symbols)}/{universe_size} titoli senza dati aggiornati "
            f"(attesa ultima seduta {expected_session}): giorno {today_str} non registrato."
        )
        return

    existing = storage.read_all(filepath)
    last = existing[-1] if existing else {}
    previous_holdings = last.get("holdings", {})
    previous_equity = last.get("equity_usd", experiment["start_equity_usd"])
    previous_mark_prices = last.get("mark_prices", {})
    previous_entry_prices = last.get("entry_prices", {})

    # Stop-loss e take-profit come in AI reale (stessi livelli di config,
    # misurati sul prezzo d'ingresso originale): se nella seduta di oggi il
    # minimo tocca lo stop o il massimo tocca il take-profit, la posizione
    # esce a quel livello (non alla chiusura). Se la barra non ha
    # massimo/minimo si usa la chiusura. Se tocca entrambi lo stesso giorno
    # vale lo stop (ipotesi prudente: l'ordine dei due tocchi non si sa).
    # Un titolo uscito così oggi non rientra nel paniere di domani.
    stopped_out: dict[str, float] = {}
    for symbol in previous_holdings:
        entry = previous_entry_prices.get(symbol)
        bars = bars_by_symbol.get(symbol)
        if not entry or not bars:
            continue
        bar = bars[-1]
        low = bar.get("low", bar["close"])
        high = bar.get("high", bar["close"])
        stop_level = entry * (1 + config.AI_TRADER_STOP_LOSS_PCT / 100)
        take_level = entry * (1 + config.AI_TRADER_TAKE_PROFIT_PCT / 100)
        if low <= stop_level:
            stopped_out[symbol] = stop_level
        elif high >= take_level:
            stopped_out[symbol] = take_level

    if previous_holdings:
        day_return = 0.0
        for symbol, weight in previous_holdings.items():
            prev_price = previous_mark_prices.get(symbol)
            curr_price = stopped_out.get(symbol, prices_today.get(symbol))
            if prev_price and curr_price:
                day_return += weight * (curr_price / prev_price - 1)
        equity_usd = previous_equity * (1 + day_return)
    else:
        equity_usd = previous_equity

    rank.sort(key=lambda pair: pair[1], reverse=not pick_fallen)
    if pick_fallen:
        eligible = [symbol for symbol, pct in rank if pct < 0]
        tier_fn = _meanrev_tier
        score_fn = _meanrev_technical_score
    else:
        eligible = [symbol for symbol, pct in rank if pct > 0]
        tier_fn = _momentum_tier
        score_fn = _momentum_technical_score
    # Punteggio tecnico come PRECEDENZA dentro la lista già filtrata per
    # rendimento sopra, non come filtro in più: eligible non perde né
    # guadagna nessun simbolo qui, viene solo riordinato. sorted() è
    # stabile anche con reverse=True, quindi a parità di fascia l'ordine
    # resta quello di "eligible" (il rendimento sul lookback, come prima
    # di questa modifica) — un titolo ipercomprato/senza conferme tecniche
    # non esce mai dalla lista, scende solo più in basso. Richiesto
    # dall'utente il 2026-11-02: "non voglio filtri rigidi... gli altri
    # titoli devono comunque poter essere selezionati se hanno un buon
    # rendimento."
    eligible = [symbol for symbol in eligible if symbol not in stopped_out]
    tiered = sorted(eligible, key=lambda s: tier_fn(score_fn(bars_by_symbol[s])), reverse=True)
    selected = tiered[:top_n]
    # Non più il 100% del capitale diviso equal-weight tra i selezionati:
    # stesso tetto del 35% di AI reale (config.AI_TRADER_MAX_EXPOSURE_PCT),
    # il resto resta in contanti — "troppo rischioso" investire tutto ogni
    # giorno, richiesto dall'utente il 2026-11-02 per restare un confronto
    # onesto con AI reale anche sul fronte del rischio, non solo del
    # rendimento. day_return sopra somma solo i pesi dei titoli tenuti, già
    # pronto per pesi che non sommano a 1.0: la quota non investita
    # contribuisce 0 al rendimento del giorno, esattamente come contanti.
    new_holdings = (
        {symbol: config.AI_TRADER_MAX_EXPOSURE_PCT / len(selected) for symbol in selected}
        if selected
        else {}
    )

    exited_today = set(previous_holdings) - set(new_holdings)
    entered_today = set(new_holdings) - set(previous_holdings)

    # entry_prices: invariato per chi resta (il prezzo a cui è ENTRATO
    # originariamente, non quello di oggi), il prezzo di oggi solo per chi
    # entra adesso nel paniere.
    new_entry_prices = {}
    for symbol in new_holdings:
        if symbol in entered_today:
            new_entry_prices[symbol] = prices_today.get(symbol)
        else:
            new_entry_prices[symbol] = previous_entry_prices.get(symbol)

    new_mark_prices = {symbol: prices_today[symbol] for symbol in new_holdings if symbol in prices_today}
    exit_prices = {
        symbol: round(stopped_out[symbol], 4) if symbol in stopped_out else prices_today[symbol]
        for symbol in exited_today
        if symbol in stopped_out or symbol in prices_today
    }

    storage.append_record(filepath, {
        "date": today_str,
        "equity_usd": round(equity_usd, 2),
        "holdings": new_holdings,
        "entry_prices": new_entry_prices,
        "mark_prices": new_mark_prices,
        "exit_prices": exit_prices,
    })


def update_momentum(today: dt.date, experiment: dict) -> None:
    _update_strategy(
        config.AI_TRADER_MOMENTUM_FILE, today, experiment,
        config.AI_TRADER_MOMENTUM_LOOKBACK_DAYS, config.AI_TRADER_MOMENTUM_TOP_N,
        pick_fallen=False,
    )


def update_mean_reversion(today: dt.date, experiment: dict) -> None:
    _update_strategy(
        config.AI_TRADER_MEANREV_FILE, today, experiment,
        config.AI_TRADER_MEANREV_LOOKBACK_DAYS, config.AI_TRADER_MEANREV_TOP_N,
        pick_fallen=True,
    )


def derive_strategy_trades(history: list[dict]) -> dict:
    """Dallo storico giorno-per-giorno (holdings + entry_prices +
    mark_prices + exit_prices) ricostruisce l'elenco delle operazioni:
    chiuse (con rendimento % realizzato) e ancora aperte (con il rendimento
    non realizzato a oggi, rispetto al prezzo di ingresso). Funzione pura,
    nessuna chiamata di rete — ricalcolata da zero ogni giorno da
    ai_trader_run.py, mai accumulata in modo incrementale: lo storico
    completo è già tutto dentro il rispettivo benchmark_*.jsonl. Condivisa
    da Momentum e Mean Reversion: stesso formato di storico per entrambe."""
    open_trades: dict[str, dict] = {}
    closed: list[dict] = []
    for record in history:
        date = record.get("date")
        holdings = record.get("holdings", {})
        entry_prices = record.get("entry_prices", {})
        exit_prices = record.get("exit_prices", {})
        for symbol in holdings:
            if symbol not in open_trades:
                entry_price = entry_prices.get(symbol)
                if entry_price is not None:
                    open_trades[symbol] = {"entry_date": date, "entry_price": entry_price}
        for symbol, exit_price in exit_prices.items():
            opened = open_trades.pop(symbol, None)
            if opened is None:
                continue
            entry_price = opened["entry_price"]
            return_pct = (exit_price / entry_price - 1) * 100 if entry_price else None
            closed.append({
                "symbol": symbol,
                "entry_date": opened["entry_date"],
                "entry_price": entry_price,
                "exit_date": date,
                "exit_price": exit_price,
                "return_pct": round(return_pct, 2) if return_pct is not None else None,
            })

    latest_mark_prices = history[-1].get("mark_prices", {}) if history else {}
    open_list = []
    for symbol, opened in open_trades.items():
        entry_price = opened["entry_price"]
        mark_price = latest_mark_prices.get(symbol)
        return_pct = (mark_price / entry_price - 1) * 100 if (entry_price and mark_price is not None) else None
        open_list.append({
            "symbol": symbol,
            "entry_date": opened["entry_date"],
            "entry_price": entry_price,
            "mark_price": mark_price,
            "return_pct": round(return_pct, 2) if return_pct is not None else None,
        })

    closed.sort(key=lambda t: t["exit_date"], reverse=True)
    open_list.sort(key=lambda t: t["entry_date"], reverse=True)
    return {"closed": closed, "open": open_list}


# Alias storico: stesso test suite esistente, stesso nome pubblico, ora solo
# un sottile passacarte verso l'implementazione condivisa sopra.
def derive_momentum_trades(history: list[dict]) -> dict:
    return derive_strategy_trades(history)


def derive_meanrev_trades(history: list[dict]) -> dict:
    return derive_strategy_trades(history)
