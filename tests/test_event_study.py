"""Test di src/event_study.py: barre sintetiche costruite perché il
risultato sia verificabile a mente. Nessuna rete."""
from __future__ import annotations

import datetime as dt

from src import event_study


def _bars(moves_pct: list[float], start: str = "2020-01-01") -> list[dict]:
    """Barre con il movimento percentuale richiesto rispetto alla
    precedente. La prima barra vale 100 e non produce movimento."""
    day = dt.date.fromisoformat(start)
    close = 100.0
    out = [{"date": day.isoformat(), "close": close}]
    for i, m in enumerate(moves_pct, start=1):
        close = close * (1 + m / 100)
        out.append({"date": (day + dt.timedelta(days=i)).isoformat(), "close": close})
    return out


def test_daily_abs_moves_separa_eventi_e_normali():
    bars = _bars([1.0, -2.0, 3.0, -1.0])
    events = {bars[2]["date"], bars[4]["date"]}
    ev, non = event_study.daily_abs_moves(bars, events)

    # Entrambi i giorni di evento sono misurati, compreso il primo: la
    # finestra si ancora a bars[1] proprio per poterne calcolare il
    # movimento.
    assert [round(x, 2) for x in ev] == [2.0, 1.0]
    # bars[1] è solo l'ancora: fornisce la chiusura precedente, ma il suo
    # movimento (+1%) appartiene al periodo PRIMA della finestra e non va
    # contato fra i giorni normali confrontati con gli eventi.
    assert [round(x, 2) for x in non] == [3.0]


def test_daily_abs_moves_si_limita_alla_finestra_degli_eventi():
    """Confrontare giorni di evento di un'epoca con giorni normali di
    un'altra misurerebbe la differenza fra epoche, non l'effetto evento."""
    bars = _bars([5.0] * 10 + [0.1] * 10)
    # Eventi solo nella seconda metà: la prima metà (movimenti da 5%) deve
    # restare completamente fuori dal confronto.
    events = {bars[15]["date"], bars[18]["date"]}
    ev, non = event_study.daily_abs_moves(bars, events)

    assert all(m < 1.0 for m in non), "le barre fuori finestra non vanno incluse"
    assert len(ev) == 2


def test_daily_abs_moves_senza_eventi():
    assert event_study.daily_abs_moves(_bars([1.0, 2.0]), set()) == ([], [])


def test_event_day_ratio_none_sotto_il_minimo_di_eventi():
    bars = _bars([1.0] * 50)
    events = {bars[i]["date"] for i in range(1, 5)}
    assert event_study.event_day_ratio({"X": bars}, events) is None


def test_event_day_ratio_rileva_un_raddoppio_costruito():
    """Giorni di evento con movimento esattamente doppio: il rapporto deve
    essere 2.0 e l'intervallo non deve contenere 1.0."""
    moves = []
    event_positions = []
    for i in range(60):
        if i % 5 == 0:
            moves.append(2.0)
            event_positions.append(i + 1)
        else:
            moves.append(1.0)
    bars = _bars(moves)
    events = {bars[p]["date"] for p in event_positions}

    result = event_study.event_day_ratio({"X": bars}, events)
    assert result is not None
    assert abs(result["ratio"] - 2.0) < 0.05
    assert result["significant"] is True
    assert result["ci_95"][0] > 1.0


def test_event_day_ratio_non_segnala_nulla_se_gli_eventi_sono_come_gli_altri():
    """Controprova: senza differenza reale, `significant` deve restare
    False. È il caso che protegge dal leggere un effetto nel rumore."""
    moves = [1.0] * 120
    bars = _bars(moves)
    events = {bars[i]["date"] for i in range(1, 121, 5)}

    result = event_study.event_day_ratio({"X": bars}, events)
    assert result is not None
    assert abs(result["ratio"] - 1.0) < 1e-6
    assert result["significant"] is False


def test_event_day_ratio_aggrega_piu_asset_e_riporta_il_dettaglio():
    bars_a = _bars([2.0 if i % 5 == 0 else 1.0 for i in range(60)])
    bars_b = _bars([3.0 if i % 5 == 0 else 1.0 for i in range(60)])
    events = {bars_a[i]["date"] for i in range(1, 61, 5)}

    result = event_study.event_day_ratio({"A": bars_a, "B": bars_b}, events)
    assert result is not None
    assert set(result["ratio_by_asset"]) == {"A", "B"}
    assert result["ratio_by_asset"]["B"] > result["ratio_by_asset"]["A"]
    assert result["event_days_observed"] > result["event_days_observed"] / 2
