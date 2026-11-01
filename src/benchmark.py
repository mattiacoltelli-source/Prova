"""Strategie di confronto per la pagina Trading AI, calcolate SOLO da prezzi
pubblici Yahoo Finance (stessa fonte di market_scanner.py) — zero chiamate
AI, zero ordini reali su Alpaca, zero costo aggiuntivo sul budget mensile.
Entrambe partono dalla stessa data e dallo stesso capitale di
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

from . import config, storage
from .data_sources import http

YAHOO_UA = {"User-Agent": "Mozilla/5.0 (predictive-agent research script)"}
TIMEOUT = 15


class BenchmarkError(RuntimeError):
    pass


def _fetch_closes(symbol: str) -> list[float]:
    """Storico di ~3 mesi di chiusure giornaliere (l'ultima è il prezzo
    corrente, anche a mercato aperto — stesso comportamento di
    market_scanner.fetch_symbol). Margine ampio sopra la finestra più lunga
    usata dalle strategie sotto (AI_TRADER_MOMENTUM_LOOKBACK_DAYS), per
    restare coperti anche con qualche giorno di festività di mercato in
    mezzo."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    resp = http.get(url, params={"range": "3mo", "interval": "1d"}, headers=YAHOO_UA, timeout=TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("chart", {}).get("result")
    if not results:
        raise BenchmarkError(f"Nessun dato Yahoo per {symbol}")
    quote = results[0].get("indicators", {}).get("quote", [{}])[0]
    closes = [c for c in (quote.get("close") or []) if c is not None]
    if len(closes) < 2:
        raise BenchmarkError(f"Storico insufficiente per {symbol}")
    return closes


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
    rank: list[tuple[str, float]] = []
    # Un titolo alla volta, mai fatale per gli altri (stesso principio di
    # market_scanner.scan()): un ticker illiquido o senza dati quel giorno
    # non deve bloccare il calcolo per tutti gli altri. Se un titolo tenuto
    # da ieri non si riesce a riprezzare oggi, il suo contributo alla
    # performance di oggi viene semplicemente saltato (approssimazione
    # accettabile per un confronto indicativo, non per un ordine reale).
    for symbol in _universe():
        try:
            closes = _fetch_closes(symbol)
        except Exception:  # noqa: BLE001 - un titolo alla volta, mai fatale
            continue
        prices_today[symbol] = closes[-1]
        if len(closes) > lookback_days:
            pct = closes[-1] / closes[-1 - lookback_days] - 1
            rank.append((symbol, pct))

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
        selected = [symbol for symbol, pct in rank if pct < 0][:top_n]
    else:
        selected = [symbol for symbol, pct in rank if pct > 0][:top_n]
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
