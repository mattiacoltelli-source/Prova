"""Test unitari per src/trade_history.py: abbinamento FIFO dei fill reali
Alpaca in operazioni chiuse/aperte, con guadagno/perdita per ciascuna."""
from __future__ import annotations

from src import trade_history


def _fill(symbol, side, qty, price, date):
    return {
        "symbol": symbol, "side": side, "qty": str(qty), "price": str(price),
        "transaction_time": f"{date}T14:30:00.000000Z",
    }


def test_acquisto_poi_vendita_completa_produce_una_operazione_chiusa():
    fills = [
        _fill("NVDA", "buy", 10, 100.0, "2026-11-02"),
        _fill("NVDA", "sell", 10, 110.0, "2026-11-05"),
    ]
    result = trade_history.derive_real_trades(fills, positions=[])
    assert result["open"] == []
    assert len(result["closed"]) == 1
    trade = result["closed"][0]
    assert trade["symbol"] == "NVDA"
    assert trade["entry_date"] == "2026-11-02"
    assert trade["entry_price"] == 100.0
    assert trade["exit_date"] == "2026-11-05"
    assert trade["exit_price"] == 110.0
    assert trade["qty"] == 10.0
    assert trade["pl_usd"] == 100.0  # 10 * (110 - 100)
    assert trade["pl_pct"] == 10.0


def test_vendita_in_perdita_ha_pl_negativo():
    fills = [
        _fill("AAPL", "buy", 5, 200.0, "2026-11-02"),
        _fill("AAPL", "sell", 5, 180.0, "2026-11-04"),
    ]
    trade = trade_history.derive_real_trades(fills, positions=[])["closed"][0]
    assert trade["pl_usd"] == -100.0  # 5 * (180 - 200)
    assert trade["pl_pct"] == -10.0


def test_vendita_parziale_lascia_il_resto_come_posizione_aperta():
    fills = [_fill("MU", "buy", 10, 50.0, "2026-11-02"), _fill("MU", "sell", 4, 60.0, "2026-11-03")]
    positions = [{"symbol": "MU", "qty": "6", "avg_entry_price": "50.0", "current_price": "62.0",
                  "unrealized_pl": "72.0", "unrealized_plpc": "0.12"}]
    result = trade_history.derive_real_trades(fills, positions)

    assert len(result["closed"]) == 1
    assert result["closed"][0]["qty"] == 4.0

    assert len(result["open"]) == 1
    open_pos = result["open"][0]
    assert open_pos["symbol"] == "MU"
    assert open_pos["entry_date"] == "2026-11-02"  # dal lotto rimasto, non dal fill venduto
    assert open_pos["entry_price"] == 50.0  # da Alpaca (posizione), non ricalcolato
    assert open_pos["mark_price"] == 62.0
    assert open_pos["qty"] == 6.0
    assert open_pos["pl_usd"] == 72.0
    assert open_pos["pl_pct"] == 12.0  # 0.12 * 100, Alpaca lo dà come frazione


def test_due_acquisti_prezzi_diversi_vendita_fifo_su_entrambi():
    """Il lotto comprato PRIMA viene venduto PRIMA: una vendita che supera
    il primo lotto deve generare due operazioni chiuse distinte, ciascuna
    con il proprio prezzo d'ingresso."""
    fills = [
        _fill("TSLA", "buy", 5, 100.0, "2026-11-01"),
        _fill("TSLA", "buy", 5, 120.0, "2026-11-02"),
        _fill("TSLA", "sell", 8, 150.0, "2026-11-05"),
    ]
    result = trade_history.derive_real_trades(fills, positions=[
        {"symbol": "TSLA", "avg_entry_price": "120.0", "current_price": "150.0",
         "unrealized_pl": "30.0", "unrealized_plpc": "0.25"},
    ])
    closed = sorted(result["closed"], key=lambda t: t["entry_price"])
    assert len(closed) == 2
    assert closed[0]["entry_price"] == 100.0 and closed[0]["qty"] == 5.0
    assert closed[1]["entry_price"] == 120.0 and closed[1]["qty"] == 3.0
    assert len(result["open"]) == 1
    assert result["open"][0]["entry_date"] == "2026-11-02"  # dal secondo lotto, ancora parzialmente aperto


def test_vendita_senza_acquisto_corrispondente_viene_ignorata_non_crasha():
    fills = [_fill("GME", "sell", 5, 20.0, "2026-11-02")]
    result = trade_history.derive_real_trades(fills, positions=[])
    assert result["closed"] == []
    assert result["open"] == []


def test_fill_con_qty_o_prezzo_non_numerico_viene_saltato_non_crasha():
    fills = [
        {"symbol": "BAD", "side": "buy", "qty": "non-numero", "price": "100.0",
         "transaction_time": "2026-11-02T14:30:00Z"},
        _fill("NVDA", "buy", 1, 100.0, "2026-11-02"),
    ]
    result = trade_history.derive_real_trades(fills, positions=[])
    assert result["closed"] == []  # NVDA non ha avuto vendita, nessuna chiusa
    assert result["open"] == []    # BAD non è in positions, non compare


def test_ordinamento_chiuse_per_data_di_uscita_decrescente():
    fills = [
        _fill("AAA", "buy", 1, 10.0, "2026-11-01"), _fill("AAA", "sell", 1, 11.0, "2026-11-02"),
        _fill("BBB", "buy", 1, 10.0, "2026-11-01"), _fill("BBB", "sell", 1, 11.0, "2026-11-04"),
    ]
    result = trade_history.derive_real_trades(fills, positions=[])
    exit_dates = [t["exit_date"] for t in result["closed"]]
    assert exit_dates == sorted(exit_dates, reverse=True)
