"""Due strategie di confronto per la pagina Trading AI, calcolate SOLO da
prezzi pubblici Yahoo Finance (stessa fonte di market_scanner.py) — zero
chiamate AI, zero ordini reali su Alpaca, zero costo aggiuntivo sul budget
mensile. Partono dalla stessa data e dallo stesso capitale di
data/ai_trader/experiment.json, per restare un confronto onesto a parità
di condizioni con l'esperimento reale:

- Buy & Hold: "se invece avessi comprato SPY il primo giorno e non avessi
  più toccato nulla". Nessuna logica di selezione, solo il prezzo SPY nel
  tempo applicato allo stesso capitale di partenza.
- Momentum: una strategia quantitativa classica A REGOLE FISSE, senza
  nessun giudizio AI — ogni giorno tiene equal-weight i titoli
  dell'universo scanner (stesso di ai_trader.py) con il miglior rendimento
  negli ultimi AI_TRADER_MOMENTUM_LOOKBACK_DAYS giorni di borsa, fino a un
  massimo di AI_TRADER_MOMENTUM_TOP_N posizioni (stesso tetto di
  diversificazione dell'esperimento reale). Nessun titolo con momentum
  positivo -> tutta in contanti, coerente con una strategia
  trend-following classica (non compra mai "controcorrente").

Entrambe le funzioni sono pensate per essere chiamate da ai_trader_run.py
dentro un try/except separato dalla logica di trading reale (vedi
_update_benchmarks lì): un fallimento qui — Yahoo irraggiungibile, un
ticker senza dati — non deve mai bloccare un ordine vero. Idempotenti per
giorno: una seconda chiamata nello stesso giorno (run manuale ripetuto)
non aggiunge un secondo punto.
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
    market_scanner.fetch_symbol). Margine ampio sopra
    AI_TRADER_MOMENTUM_LOOKBACK_DAYS per restare coperti anche con qualche
    giorno di festività di mercato in mezzo."""
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


def update_buy_hold(today: dt.date, experiment: dict) -> None:
    """Un punto al giorno: equity teorica se i soldi di partenza
    dell'esperimento fossero finiti tutti su AI_TRADER_BENCHMARK_SYMBOL il
    giorno 1 e non fossero più stati toccati (nessun ribilanciamento, nessun
    dividendo reinvestito a parte — SPY li reinveste già nel suo prezzo? No:
    l'ETF paga dividendi in contanti, qui ignorati di proposito per
    restare un confronto SOLO sul prezzo, stessa semplificazione implicita
    dell'esperimento reale che non riceve dividendi sulle posizioni aperte)."""
    today_str = today.isoformat()
    if _already_recorded_today(config.AI_TRADER_BUYHOLD_FILE, today_str):
        return
    closes = _fetch_closes(config.AI_TRADER_BENCHMARK_SYMBOL)
    price_today = closes[-1]

    existing = storage.read_all(config.AI_TRADER_BUYHOLD_FILE)
    if not existing:
        # Primo punto: l'ancora è il prezzo di oggi stesso, equity = quella
        # di partenza dell'esperimento reale (stesso capitale, stesso
        # giorno di partenza).
        storage.append_record(config.AI_TRADER_BUYHOLD_FILE, {
            "date": today_str,
            "anchor_price": price_today,
            "equity_usd": round(experiment["start_equity_usd"], 2),
        })
        return

    anchor_price = existing[0]["anchor_price"]
    equity_usd = experiment["start_equity_usd"] * (price_today / anchor_price)
    storage.append_record(config.AI_TRADER_BUYHOLD_FILE, {
        "date": today_str,
        "anchor_price": anchor_price,
        "equity_usd": round(equity_usd, 2),
    })


def _universe() -> list[str]:
    return [s for s in config.SCANNER_STOCKS if s not in config.AI_TRADER_EXCLUDED_TICKERS]


def update_momentum(today: dt.date, experiment: dict) -> None:
    """Un punto al giorno: segna a mercato il paniere di IERI con i prezzi di
    OGGI, poi decide il paniere per DOMANI in base al rendimento a
    AI_TRADER_MOMENTUM_LOOKBACK_DAYS giorni di ogni titolo dell'universo.
    Nessun giudizio AI, nessun ordine reale: solo prezzi Yahoo e aritmetica."""
    today_str = today.isoformat()
    if _already_recorded_today(config.AI_TRADER_MOMENTUM_FILE, today_str):
        return

    prices_today: dict[str, float] = {}
    momentum_rank: list[tuple[str, float]] = []
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
        lookback = config.AI_TRADER_MOMENTUM_LOOKBACK_DAYS
        if len(closes) > lookback:
            momentum_pct = closes[-1] / closes[-1 - lookback] - 1
            momentum_rank.append((symbol, momentum_pct))

    existing = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)
    previous_holdings = existing[-1]["holdings"] if existing else {}
    previous_equity = existing[-1]["equity_usd"] if existing else experiment["start_equity_usd"]
    previous_prices = existing[-1].get("prices", {}) if existing else {}

    if previous_holdings:
        day_return = 0.0
        for symbol, weight in previous_holdings.items():
            prev_price = previous_prices.get(symbol)
            curr_price = prices_today.get(symbol)
            if prev_price and curr_price:
                day_return += weight * (curr_price / prev_price - 1)
        equity_usd = previous_equity * (1 + day_return)
    else:
        equity_usd = previous_equity

    momentum_rank.sort(key=lambda pair: pair[1], reverse=True)
    positive = [symbol for symbol, pct in momentum_rank if pct > 0][: config.AI_TRADER_MOMENTUM_TOP_N]
    new_holdings = {symbol: 1 / len(positive) for symbol in positive} if positive else {}

    # Prezzi salvati per DUE scopi, non solo uno: quelli dei nuovi titoli
    # servono domani per segnare a mercato (sopra), quelli dei titoli USCITI
    # oggi (in previous_holdings ma non più in new_holdings) servono SOLO a
    # mostrare "a quanto ha venduto" nella lista movimenti del frontend — se
    # non li salvassimo qui, andrebbero persi per sempre (prices_today non
    # sopravvive oltre questa chiamata).
    exited_today = set(previous_holdings) - set(new_holdings)
    relevant_symbols = set(new_holdings) | exited_today
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": today_str,
        "equity_usd": round(equity_usd, 2),
        "holdings": new_holdings,
        "prices": {symbol: prices_today[symbol] for symbol in relevant_symbols if symbol in prices_today},
    })
