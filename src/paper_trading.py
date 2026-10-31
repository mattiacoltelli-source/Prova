"""Portafoglio paper trading su Alpaca: account, posizioni, invio ordini.

Sempre e solo paper (ALPACA_PAPER_BASE_URL sotto): questa è l'unica cosa
che separa la simulazione da un conto vero, e per questo è una costante
fissata qui nel codice, mai un parametro passato da chi chiama o letto da
una variabile d'ambiente — un errore di configurazione a runtime non deve
poter mandare un ordine a un conto reale.

Ogni ordine passa da un sì esplicito dell'utente PRIMA di questa chiamata:
questo modulo non decide mai da solo se/cosa comprare, esegue solo quello
che gli viene chiesto esplicitamente (src/paper_order_run.py, lanciato a
mano via workflow_dispatch con i parametri dell'ordine come input).
"""
from __future__ import annotations

import os

import requests

from . import config, storage

# Paper, sempre. Mai api.alpaca.markets (conto vero) in questo file.
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
TIMEOUT = 15


class AlpacaError(RuntimeError):
    pass


def _headers() -> dict:
    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise AlpacaError("ALPACA_API_KEY / ALPACA_SECRET_KEY non impostate nell'ambiente.")
    return {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}


def get_account() -> dict:
    resp = requests.get(f"{ALPACA_PAPER_BASE_URL}/v2/account", headers=_headers(), timeout=TIMEOUT)
    if not resp.ok:
        raise AlpacaError(f"GET /v2/account fallita ({resp.status_code}): {resp.text}")
    return resp.json()


def get_positions() -> list[dict]:
    resp = requests.get(f"{ALPACA_PAPER_BASE_URL}/v2/positions", headers=_headers(), timeout=TIMEOUT)
    if not resp.ok:
        raise AlpacaError(f"GET /v2/positions fallita ({resp.status_code}): {resp.text}")
    return resp.json()


def place_order(
    symbol: str,
    side: str,
    qty: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    limit_price: float | None = None,
    stop_price: float | None = None,
    time_in_force: str = "day",
) -> dict:
    """Invia un ordine reale al conto paper. Nessun retry automatico sugli
    errori di rete: a differenza di una GET (vedi data_sources/http.py), una
    POST /v2/orders non è sicura da ripetere alla cieca — se la richiesta è
    partita ma la risposta si è persa, un retry rischierebbe di inviare lo
    stesso ordine due volte. Un fallimento di rete qui risale a chi chiama
    come errore esplicito, mai ritentato in silenzio."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side deve essere 'buy' o 'sell', non {side!r}")
    if order_type not in ("market", "limit", "stop"):
        raise ValueError(f"order_type deve essere 'market', 'limit' o 'stop', non {order_type!r}")
    if order_type == "limit" and limit_price is None:
        raise ValueError("limit_price è obbligatorio per un ordine 'limit'")
    if order_type == "stop" and stop_price is None:
        raise ValueError("stop_price è obbligatorio per un ordine 'stop'")
    if (qty is None) == (notional is None):
        raise ValueError("specifica esattamente uno tra qty e notional, non entrambi o nessuno")
    # Crypto (simbolo "BASE/QUOTE", es. BTC/USD) accetta solo gtc/ioc come
    # time_in_force: "day" non ha senso per un mercato che non chiude mai,
    # e Alpaca lo rifiuta. Controllato qui, prima della rete, invece di
    # lasciar tornare un 422 poco chiaro da Alpaca — stesso principio delle
    # validazioni sopra.
    is_crypto = "/" in symbol
    if is_crypto and time_in_force not in ("gtc", "ioc"):
        raise ValueError(
            f"time_in_force per un ordine crypto ({symbol}) deve essere 'gtc' o 'ioc', non {time_in_force!r}"
        )

    payload = {
        "symbol": symbol.upper(),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if qty is not None:
        payload["qty"] = str(qty)
    else:
        payload["notional"] = str(notional)
    if order_type == "limit":
        payload["limit_price"] = str(limit_price)
    if order_type == "stop":
        payload["stop_price"] = str(stop_price)

    resp = requests.post(
        f"{ALPACA_PAPER_BASE_URL}/v2/orders", headers=_headers(), json=payload, timeout=TIMEOUT
    )
    if not resp.ok:
        raise AlpacaError(f"POST /v2/orders fallita ({resp.status_code}): {resp.text}")
    return resp.json()


def get_open_orders(symbol: str | None = None) -> list[dict]:
    """Ordini ancora aperti (status=open), opzionalmente filtrati per
    simbolo — serve ad ai_trader_run.py per annullare uno stop nativo
    rimasto appeso quando una posizione viene chiusa da un'altra parte
    (giudizio AI o stop-loss python), prima che provi a vendere azioni che
    non ci sono più."""
    params = {"status": "open"}
    if symbol:
        params["symbols"] = symbol.upper()
    resp = requests.get(f"{ALPACA_PAPER_BASE_URL}/v2/orders", headers=_headers(), params=params, timeout=TIMEOUT)
    if not resp.ok:
        raise AlpacaError(f"GET /v2/orders fallita ({resp.status_code}): {resp.text}")
    return resp.json()


def cancel_order(order_id: str) -> None:
    """Annulla un ordine aperto. Un 404 (l'ordine è già stato eseguito o
    annullato nel frattempo, caso normale per un ordine stop su cui si è
    appena fatta una GET) non è un errore: chi chiama voleva solo
    assicurarsi che l'ordine non fosse più lì, e non lo è."""
    resp = requests.delete(f"{ALPACA_PAPER_BASE_URL}/v2/orders/{order_id}", headers=_headers(), timeout=TIMEOUT)
    if not resp.ok and resp.status_code != 404:
        raise AlpacaError(f"DELETE /v2/orders/{order_id} fallita ({resp.status_code}): {resp.text}")


def get_portfolio_history(start: str, timeframe: str = "1D") -> dict:
    """Curva equity calcolata da Alpaca stesso (GET /v2/account/portfolio/
    history), non la nostra accumulazione manuale (vedi
    AI_TRADER_EQUITY_HISTORY_FILE in config.py) — copre correttamente i
    giorni di mercato chiuso. start è una data ISO (es. l'inizio
    dell'esperimento); con timeframe="1D" (il default qui) Alpaca include
    solo i giorni in cui il mercato era aperto."""
    resp = requests.get(
        f"{ALPACA_PAPER_BASE_URL}/v2/account/portfolio/history",
        headers=_headers(),
        params={"start": start, "timeframe": timeframe},
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise AlpacaError(f"GET /v2/account/portfolio/history fallita ({resp.status_code}): {resp.text}")
    return resp.json()


def record_order(order_response: dict) -> dict:
    """Salva l'ordine appena inviato (o il suo rifiuto) nella catena hash
    di orders.jsonl. Riceve la risposta grezza di Alpaca così com'è: non
    reinterpreta mai lo stato di un ordine, lo riporta alla lettera."""
    record = {
        "alpaca_order_id": order_response.get("id"),
        "symbol": order_response.get("symbol"),
        "side": order_response.get("side"),
        "order_type": order_response.get("type"),
        "qty": order_response.get("qty"),
        "notional": order_response.get("notional"),
        "limit_price": order_response.get("limit_price"),
        "time_in_force": order_response.get("time_in_force"),
        "status": order_response.get("status"),
        "submitted_at": order_response.get("submitted_at"),
        "filled_at": order_response.get("filled_at"),
        "filled_qty": order_response.get("filled_qty"),
        "filled_avg_price": order_response.get("filled_avg_price"),
    }
    return storage.append_record(config.PAPER_ORDERS_FILE, record)


def snapshot_account(account: dict, positions: list[dict]) -> None:
    """Sovrascrive data/paper/account.json con lo stato attuale del conto.
    Non è storico (vedi commento su PAPER_ACCOUNT_FILE in config.py): ogni
    run la ricalcola da zero da quello che Alpaca riporta in quel momento."""
    import json

    snapshot = {
        "equity": account.get("equity"),
        "cash": account.get("cash"),
        "buying_power": account.get("buying_power"),
        "portfolio_value": account.get("portfolio_value"),
        "account_number": account.get("account_number"),
        "status": account.get("status"),
        "positions": [
            {
                "symbol": p.get("symbol"),
                "qty": p.get("qty"),
                "avg_entry_price": p.get("avg_entry_price"),
                "current_price": p.get("current_price"),
                "market_value": p.get("market_value"),
                "unrealized_pl": p.get("unrealized_pl"),
                "unrealized_plpc": p.get("unrealized_plpc"),
            }
            for p in positions
        ],
    }
    os.makedirs(os.path.dirname(config.PAPER_ACCOUNT_FILE), exist_ok=True)
    with open(config.PAPER_ACCOUNT_FILE, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)
        fh.write("\n")
