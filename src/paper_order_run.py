"""Orchestratore chiamato da .github/workflows/paper_order.yml.

Invia UN ordine paper su Alpaca con i parametri passati da riga di comando
(gli input del workflow_dispatch: è l'utente a scriverli quando lancia il
workflow a mano — il sì esplicito richiesto da ogni ordine, vedi
paper_trading.py). Nessuno schedule, nessun automatismo: senza un run
manuale con questi parametri non succede nulla.
"""
from __future__ import annotations

import argparse
import sys

from . import paper_trading


def run(
    symbol: str,
    side: str,
    qty: float | None,
    notional: float | None,
    order_type: str,
    limit_price: float | None,
    dry_run: bool,
) -> None:
    if dry_run:
        print(
            f"[DRY-RUN] ordine NON inviato: {side} {qty or notional}"
            f"{'quota' if notional else ''} {symbol} ({order_type}"
            f"{f' @ {limit_price}' if limit_price else ''})"
        )
        return

    order = paper_trading.place_order(
        symbol=symbol,
        side=side,
        qty=qty,
        notional=notional,
        order_type=order_type,
        limit_price=limit_price,
    )
    saved = paper_trading.record_order(order)
    print(
        f"Ordine inviato: {saved['side']} {saved['qty'] or saved['notional']} "
        f"{saved['symbol']} — stato: {saved['status']} (id Alpaca: {saved['alpaca_order_id']})"
    )

    account = paper_trading.get_account()
    positions = paper_trading.get_positions()
    paper_trading.snapshot_account(account, positions)
    print(f"Istantanea conto aggiornata: equity ${account.get('equity')}, {len(positions)} posizioni aperte.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--qty", type=float, default=None)
    parser.add_argument("--notional", type=float, default=None)
    parser.add_argument("--order-type", default="market", choices=["market", "limit"])
    parser.add_argument("--limit-price", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if (args.qty is None) == (args.notional is None):
        print("Errore: specifica esattamente uno tra --qty e --notional.", file=sys.stderr)
        sys.exit(1)

    try:
        run(
            symbol=args.symbol,
            side=args.side,
            qty=args.qty,
            notional=args.notional,
            order_type=args.order_type,
            limit_price=args.limit_price,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Errore fatale: {exc}", file=sys.stderr)
        raise
