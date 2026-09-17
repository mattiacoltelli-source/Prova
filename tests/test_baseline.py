"""Test delle baseline storiche: nessuna rete, barre sintetiche costruite a
mano in modo che il risultato atteso sia verificabile a mente."""
from __future__ import annotations

import datetime as dt

from src import baseline, config


def _bars(closes: list[float], start: str = "2020-01-01") -> list[dict]:
    """Barre giornaliere consecutive (anche nei weekend: le funzioni testate
    ragionano su date, non su calendari di borsa) con high/low simmetrici
    intorno alla chiusura, così l'ATR è definito e non nullo."""
    day = dt.date.fromisoformat(start)
    out = []
    for i, close in enumerate(closes):
        out.append(
            {
                "date": (day + dt.timedelta(days=i)).isoformat(),
                "close": close,
                "high": close * 1.01,
                "low": close * 0.99,
            }
        )
    return out


HORIZON_1D = config.Horizon(code="1d", days=1, trading_days=1)


def test_realized_moves_usa_solo_dati_passati_per_la_soglia():
    """La soglia della barra i non deve dipendere dalle barre successive:
    è il vincolo anti look-ahead che vale anche in produzione."""
    closes = [100.0] * 40 + [100.0, 130.0, 100.0]
    moves = baseline.realized_moves(_bars(closes), HORIZON_1D)

    # Il salto a 130 è l'ultima parte della serie. La soglia calcolata sulle
    # barre precedenti non può essersi "accorta" di quel salto.
    before_jump = [m for m in moves if m[0] <= "2020-02-09"]
    assert before_jump, "servono osservazioni prima del salto"
    assert all(threshold < 1.0 for _, _, threshold in before_jump)


def test_realized_moves_si_ferma_quando_lorizzonte_supera_lo_storico():
    """L'ultima barra non ha un futuro con cui confrontarsi: va esclusa, non
    troncata all'ultimo prezzo noto (falserebbe la distribuzione)."""
    closes = [100.0 + i * 0.5 for i in range(60)]
    bars = _bars(closes)
    moves = baseline.realized_moves(bars, HORIZON_1D)

    assert moves, "con 60 barre ci devono essere osservazioni"
    assert moves[-1][0] < bars[-1]["date"]


def test_class_distribution_none_sotto_il_minimo_di_osservazioni():
    moves = baseline.class_distribution(_bars([100.0] * 30), HORIZON_1D)
    assert moves is None


def test_class_distribution_serie_piatta_e_tutta_flat():
    """Prezzo che non si muove mai: ogni movimento è 0% e cade dentro
    qualsiasi banda, quindi FLAT al 100%."""
    result = baseline.class_distribution(_bars([100.0] * 400), HORIZON_1D)

    assert result is not None
    assert result["pct"]["FLAT"] == 100.0
    assert result["majority_class"] == "FLAT"
    assert result["counts"]["UP"] == 0
    assert result["counts"]["DOWN"] == 0
    assert result["observations"] >= baseline.MIN_OBSERVATIONS


def test_class_distribution_percentuali_sommano_a_cento():
    closes = [100.0 + (i % 7) * 2 - (i % 3) for i in range(500)]
    result = baseline.class_distribution(_bars(closes), HORIZON_1D)

    assert result is not None
    assert abs(sum(result["pct"].values()) - 100.0) < 0.2
    assert sum(result["counts"].values()) == result["observations"]


def test_k_calibration_e_monotona_e_marca_il_k_in_uso():
    """Allargare la banda non può ridurre la quota di FLAT: è la proprietà
    che rende la tabella leggibile come calibrazione."""
    closes = [100.0 + (i % 11) * 1.5 - (i % 5) for i in range(600)]
    rows = baseline.k_calibration(_bars(closes), HORIZON_1D, [0.2, 0.4, 0.8])

    assert [r["k"] for r in rows] == [0.2, 0.4, 0.8]
    flat_pcts = [r["flat_pct"] for r in rows]
    assert flat_pcts == sorted(flat_pcts)
    assert [r["is_current"] for r in rows] == [k == config.VOLATILITY_K for k in (0.2, 0.4, 0.8)]


def test_k_calibration_vuota_sotto_il_minimo():
    assert baseline.k_calibration(_bars([100.0] * 30), HORIZON_1D, [0.4]) == []
