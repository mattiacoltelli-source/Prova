"""Test unitari per src/technicals.py: OBV, Chaikin Money Flow e forza
relativa vs benchmark, con fixture OHLCV sintetiche e valori attesi
calcolati a mano dalle stesse formule."""
from __future__ import annotations

from src import technicals


def _bar(close, volume=None, high=None, low=None):
    bar = {"date": "2026-01-01", "close": close}
    if volume is not None:
        bar["volume"] = volume
    if high is not None:
        bar["high"] = high
    if low is not None:
        bar["low"] = low
    return bar


# --- compute_obv_trend -------------------------------------------------


def test_obv_trend_accumulazione():
    # Chiusura in salita ad ogni barra: OBV cumula sempre +volume.
    closes = [100 + i for i in range(11)]
    bars = [_bar(c, volume=1000) for c in closes]
    assert technicals.compute_obv_trend(bars, lookback=10) == "accumulazione"


def test_obv_trend_distribuzione():
    # Chiusura in discesa ad ogni barra: OBV cumula sempre -volume.
    closes = [110 - i for i in range(11)]
    bars = [_bar(c, volume=1000) for c in closes]
    assert technicals.compute_obv_trend(bars, lookback=10) == "distribuzione"


def test_obv_trend_neutro():
    # Oscillazione su/giù che riporta l'OBV al punto di partenza.
    closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
    bars = [_bar(c, volume=1000) for c in closes]
    assert technicals.compute_obv_trend(bars, lookback=10) == "neutro"


def test_obv_trend_none_se_manca_volume():
    bars = [_bar(100 + i) for i in range(11)]  # nessun campo volume
    assert technicals.compute_obv_trend(bars, lookback=10) is None


def test_obv_trend_none_se_storico_insufficiente():
    bars = [_bar(100 + i, volume=1000) for i in range(5)]  # meno di lookback+1
    assert technicals.compute_obv_trend(bars, lookback=10) is None


# --- compute_cmf ---------------------------------------------------------


def test_cmf_valore_atteso():
    bars = [
        _bar(close=105, high=110, low=90, volume=1000),   # mfm=0.5  -> mfv=500
        _bar(close=80, high=100, low=80, volume=2000),    # mfm=-1.0 -> mfv=-2000
        _bar(close=110, high=120, low=100, volume=1000),  # mfm=0.0  -> mfv=0
    ]
    # sum(mfv) = -1500, sum(volume) = 4000 -> cmf = -0.375
    assert technicals.compute_cmf(bars, period=3) == -0.375


def test_cmf_ignora_barre_con_high_uguale_low():
    bars = [
        _bar(close=100, high=100, low=100, volume=5000),  # range nullo, esclusa
        _bar(close=105, high=110, low=90, volume=1000),   # mfv=500
        _bar(close=80, high=100, low=80, volume=2000),    # mfv=-2000
    ]
    # sum(mfv) = -1500, sum(volume) = 3000 (la prima barra non conta) -> -0.5
    assert technicals.compute_cmf(bars, period=3) == -0.5


def test_cmf_none_se_mancano_high_low_volume():
    bars = [_bar(close=100 + i) for i in range(20)]
    assert technicals.compute_cmf(bars) is None


def test_cmf_none_se_storico_insufficiente():
    bars = [_bar(close=100, high=110, low=90, volume=1000)] * 5  # < period
    assert technicals.compute_cmf(bars, period=20) is None


# --- compute_relative_strength_pct ---------------------------------------


def test_relative_strength_valore_atteso():
    asset_bars = [_bar(100 + i * 2) for i in range(6)]  # 100 -> 110, +10%
    benchmark_bars = [_bar(100 + i * 1) for i in range(6)]  # 100 -> 105, +5%
    assert technicals.compute_relative_strength_pct(asset_bars, benchmark_bars, lookback=5) == 5.0


def test_relative_strength_none_se_storico_insufficiente():
    asset_bars = [_bar(100 + i) for i in range(3)]
    benchmark_bars = [_bar(100 + i) for i in range(6)]
    assert technicals.compute_relative_strength_pct(asset_bars, benchmark_bars, lookback=5) is None


def test_relative_strength_none_se_prezzo_base_zero():
    asset_bars = [_bar(0)] + [_bar(100 + i) for i in range(5)]
    benchmark_bars = [_bar(100 + i) for i in range(6)]
    assert technicals.compute_relative_strength_pct(asset_bars, benchmark_bars, lookback=5) is None
