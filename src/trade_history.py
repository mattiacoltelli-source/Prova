"""Ricostruisce le operazioni di compravendita REALI sul conto paper Alpaca
dell'AI Trader, per la dashboard della pagina Trading AI.

Fonte: paper_trading.get_activities() (le esecuzioni vere, GET /v2/account/
activities?activity_types=FILL) — MAI data/paper/orders.jsonl, che salva
l'ordine al momento dell'invio (status "pending_new"/"accepted") e non
viene più aggiornato quando Alpaca lo esegue davvero: bug di dati reale
scoperto il 2026-11-02, filled_avg_price era sempre None lì.

Un acquisto e una vendita non sono automaticamente "la stessa operazione"
per Alpaca — qui vengono abbinati con un FIFO per titolo (il lotto
acquistato PRIMA viene venduto PRIMA), lo stesso criterio usato da
qualunque registro di trading: necessario perché l'AI potrebbe in
teoria riacquistare un titolo già venduto in precedenza, o vendere in più
tranche.
"""
from __future__ import annotations


def _to_float(value, scale: float = 1.0) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) * scale, 2)
    except (TypeError, ValueError):
        return None


def _transaction_date(fill: dict) -> str:
    return (fill.get("transaction_time") or "")[:10]


def derive_real_trades(fills: list[dict], positions: list[dict]) -> dict:
    """fills: esecuzioni da paper_trading.get_activities(), in qualunque
    ordine (vengono riordinate per data qui). positions: posizioni aperte
    da paper_trading.get_positions() — i numeri delle posizioni ANCORA
    aperte vengono presi da lì (stessa fonte già usata altrove nella
    pagina), non ricalcolati: solo le operazioni GIÀ CHIUSE richiedono
    l'abbinamento FIFO, perché Alpaca non espone da nessuna parte
    "quanto ho guadagnato su QUESTA specifica operazione conclusa"."""
    lots: dict[str, list[dict]] = {}
    closed: list[dict] = []

    for fill in sorted(fills, key=lambda f: f.get("transaction_time") or ""):
        symbol = fill.get("symbol")
        side = fill.get("side")
        try:
            qty = float(fill.get("qty") or 0)
            price = float(fill.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not symbol or qty <= 0 or price <= 0:
            continue
        date = _transaction_date(fill)
        queue = lots.setdefault(symbol, [])

        if side == "buy":
            queue.append({"qty": qty, "price": price, "date": date})
        elif side == "sell":
            remaining = qty
            while remaining > 1e-9 and queue:
                lot = queue[0]
                matched_qty = min(remaining, lot["qty"])
                pl_usd = matched_qty * (price - lot["price"])
                pl_pct = (price / lot["price"] - 1) * 100 if lot["price"] else None
                closed.append({
                    "symbol": symbol,
                    "entry_date": lot["date"],
                    "entry_price": round(lot["price"], 2),
                    "exit_date": date,
                    "exit_price": round(price, 2),
                    "qty": round(matched_qty, 6),
                    "pl_usd": round(pl_usd, 2),
                    "pl_pct": round(pl_pct, 2) if pl_pct is not None else None,
                })
                lot["qty"] -= matched_qty
                remaining -= matched_qty
                if lot["qty"] <= 1e-9:
                    queue.pop(0)
            # remaining > 0 qui vorrebbe dire una vendita senza un lotto
            # d'acquisto corrispondente (fill mancante/incompleto): ignorato
            # di proposito, non è un'operazione mostrabile, solo rumore.

    open_list = []
    for position in positions:
        symbol = position.get("symbol")
        queue = lots.get(symbol) or []
        open_list.append({
            "symbol": symbol,
            "entry_date": queue[0]["date"] if queue else None,
            "entry_price": _to_float(position.get("avg_entry_price")),
            "mark_price": _to_float(position.get("current_price")),
            "qty": _to_float(position.get("qty")),
            "pl_usd": _to_float(position.get("unrealized_pl")),
            "pl_pct": _to_float(position.get("unrealized_plpc"), scale=100),
        })

    closed.sort(key=lambda t: t["exit_date"], reverse=True)
    open_list.sort(key=lambda t: t["entry_date"] or "", reverse=True)
    return {"closed": closed, "open": open_list}
