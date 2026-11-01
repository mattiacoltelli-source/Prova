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
    for symbol in _universe():
        try:
            bars = _fetch_bars(symbol)
        except Exception:  # noqa: BLE001 - un titolo alla volta, mai fatale
            failed_symbols.append(symbol)
            continue
        closes = [b["close"] for b in bars]
        prices_today[symbol] = closes[-1]
        bars_by_symbol[symbol] = bars
        if len(closes) > lookback_days:
            pct = closes[-1] / closes[-1 - lookback_days] - 1
            rank.append((symbol, pct))

    try:
        data_health.record_fetch_health("benchmark", len(_universe()), failed_symbols)
    except Exception:  # noqa: BLE001 - lo stato di salute non deve mai bloccare la strategia vera
        pass

    existing = storage.read_all(filepath)
    last = existing[-1] if existing else {}
    previous_holdings = last.get("holdings", {})
    previous_equity = last.get("equity_usd", experiment["start_equity_usd"])
    previous_mark_prices = last.get("mark_prices", {})
    previous_entry_prices = last.get("entry_prices", {})

    if previous_holdings:
        day_return = 0.0
        for symbol, weight in previous_holdings.items():
            prev_price = previous_mark_prices.get(symbol)
            curr_price = prices_today.get(symbol)
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
    exit_prices = {symbol: prices_today[symbol] for symbol in exited_today if symbol in prices_today}

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
