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


# --- compute_sma_trend / compute_ema_trend --------------------------------


def test_sma_trend_rialzista():
    # Ultimi 50 valori più alti dei 200: SMA corta > SMA lunga.
    closes = [100] * 150 + [100 + i for i in range(50)]
    bars = [_bar(c) for c in closes]
    assert technicals.compute_sma_trend(bars, short_period=50, long_period=200) == "rialzista"


def test_sma_trend_ribassista():
    closes = [100] * 150 + [100 - i for i in range(50)]
    bars = [_bar(c) for c in closes]
    assert technicals.compute_sma_trend(bars, short_period=50, long_period=200) == "ribassista"


def test_sma_trend_none_se_storico_insufficiente():
    bars = [_bar(100) for _ in range(199)]  # < long_period
    assert technicals.compute_sma_trend(bars, short_period=50, long_period=200) is None


def test_ema_trend_rialzista():
    closes = [100] * 30 + [100 + i for i in range(21)]
    bars = [_bar(c) for c in closes]
    assert technicals.compute_ema_trend(bars, short_period=9, long_period=21) == "rialzista"


def test_ema_trend_none_se_storico_insufficiente():
    bars = [_bar(100) for _ in range(20)]  # < long_period
    assert technicals.compute_ema_trend(bars, short_period=9, long_period=21) is None


# --- compute_rsi -----------------------------------------------------------


def test_rsi_valore_atteso():
    # 14 variazioni: 10 rialzi di +1, 4 ribassi di -1.
    # avg_gain = 10/14, avg_loss = 4/14, rs = 2.5, rsi = 100 - 100/3.5
    closes = [100]
    for d in [1, 1, 1, 1, 1, -1, 1, 1, -1, 1, 1, -1, 1, -1, 1]:
        closes.append(closes[-1] + d)
    bars = [_bar(c) for c in closes]
    assert technicals.compute_rsi(bars, period=14) == round(100 - 100 / 3.5, 2)


def test_rsi_100_se_solo_rialzi():
    closes = [100 + i for i in range(15)]
    bars = [_bar(c) for c in closes]
    assert technicals.compute_rsi(bars, period=14) == 100.0


def test_rsi_none_se_storico_insufficiente():
    bars = [_bar(100 + i) for i in range(10)]
    assert technicals.compute_rsi(bars, period=14) is None


# --- compute_macd ------------------------------------------------------


def test_macd_calcolo_a_mano():
    # Periodi piccoli (fast=2, slow=3, signal=2) per poter verificare a mano.
    closes = [10, 11, 12, 13, 14, 15, 16]
    bars = [_bar(c) for c in closes]

    k_fast, k_slow, k_sig = 2 / 3, 2 / 4, 2 / 3
    ema_fast = [sum(closes[:2]) / 2]
    for v in closes[2:]:
        ema_fast.append(v * k_fast + ema_fast[-1] * (1 - k_fast))
    ema_slow = [sum(closes[:3]) / 3]
    for v in closes[3:]:
        ema_slow.append(v * k_slow + ema_slow[-1] * (1 - k_slow))
    macd_line = [f - s for f, s in zip(ema_fast[1:], ema_slow)]  # offset slow-fast=1
    signal = [sum(macd_line[:2]) / 2]
    for v in macd_line[2:]:
        signal.append(v * k_sig + signal[-1] * (1 - k_sig))
    expected = {
        "macd": round(macd_line[-1], 4),
        "signal": round(signal[-1], 4),
        "histogram": round(macd_line[-1] - signal[-1], 4),
    }
    assert technicals.compute_macd(bars, fast_period=2, slow_period=3, signal_period=2) == expected


def test_macd_none_se_storico_insufficiente():
    bars = [_bar(100 + i) for i in range(10)]
    assert technicals.compute_macd(bars, fast_period=12, slow_period=26, signal_period=9) is None


# --- compute_atr_pct -------------------------------------------------------


def test_atr_pct_valore_atteso():
    bars = [
        _bar(close=100, high=105, low=95),
        _bar(close=102, high=108, low=100),  # tr = max(8, 8, 2) = 8
        _bar(close=101, high=104, low=99),   # tr = max(5, 2, 3) = 5
    ]
    # atr = (8+5)/2 = 6.5, close=101 -> 6.5/101*100
    assert technicals.compute_atr_pct(bars, period=2) == round(6.5 / 101 * 100, 2)


def test_atr_pct_none_se_mancano_high_low():
    bars = [_bar(close=100 + i) for i in range(20)]
    assert technicals.compute_atr_pct(bars, period=14) is None


def test_atr_pct_none_se_storico_insufficiente():
    bars = [_bar(close=100, high=105, low=95)] * 5
    assert technicals.compute_atr_pct(bars, period=14) is None


# --- compute_beta ------------------------------------------------------


def test_beta_asset_due_volte_piu_volatile():
    # Rendimenti giornalieri dell'asset sempre doppi (e non costanti, altrimenti
    # la varianza del benchmark sarebbe 0) di quelli del benchmark -> beta=2.
    returns = [0.02 if i % 2 == 0 else -0.01 for i in range(60)]
    bench_closes = [100]
    for r in returns:
        bench_closes.append(bench_closes[-1] * (1 + r))
    asset_closes = [50]
    for r in returns:
        asset_closes.append(asset_closes[-1] * (1 + 2 * r))
    asset_bars = [_bar(c) for c in asset_closes]
    bench_bars = [_bar(c) for c in bench_closes]
    assert technicals.compute_beta(asset_bars, bench_bars, lookback=60) == 2.0


def test_beta_none_se_storico_insufficiente():
    asset_bars = [_bar(100 + i) for i in range(10)]
    bench_bars = [_bar(100 + i) for i in range(60)]
    assert technicals.compute_beta(asset_bars, bench_bars, lookback=60) is None


# --- compute_bollinger_percent_b -------------------------------------


def test_bollinger_percent_b_valore_atteso():
    # 19 barre a 100 + 1 a 110: media e deviazione standard calcolabili a mano.
    closes = [100] * 19 + [110]
    bars = [_bar(c) for c in closes]
    mean = (100 * 19 + 110) / 20
    variance = (19 * (100 - mean) ** 2 + (110 - mean) ** 2) / 20
    std = variance**0.5
    upper, lower = mean + 2 * std, mean - 2 * std
    expected = round((110 - lower) / (upper - lower), 4)
    assert technicals.compute_bollinger_percent_b(bars, period=20) == expected


def test_bollinger_percent_b_meta_banda_se_nessuna_volatilita():
    bars = [_bar(100) for _ in range(20)]  # std=0 -> upper==lower
    assert technicals.compute_bollinger_percent_b(bars, period=20) is None


def test_bollinger_percent_b_none_se_storico_insufficiente():
    bars = [_bar(100) for _ in range(10)]
    assert technicals.compute_bollinger_percent_b(bars, period=20) is None


# --- compute_52w_range_position -------------------------------------------


def test_52w_range_position_valore_atteso():
    # 15 barre neutre (non toccano max/min) + [90, 100, 120, 80, 96]: max=120,
    # min=80, ultimo=96. Servono >=20 barre in totale (soglia minima).
    closes = [95] * 15 + [90, 100, 120, 80, 96]
    bars = [_bar(c) for c in closes]
    result = technicals.compute_52w_range_position(bars, lookback=252)
    assert result == {
        "pct_from_high": round((96 - 120) / 120 * 100, 2),
        "pct_from_low": round((96 - 80) / 80 * 100, 2),
    }


def test_52w_range_position_usa_solo_lookback_barre():
    # Il massimo (200) è a 4 barre dalla fine, fuori dalla finestra di
    # lookback=3, va ignorato. Padding iniziale per superare la soglia minima.
    closes = [95] * 17 + [200, 90, 100, 96]
    bars = [_bar(c) for c in closes]
    result = technicals.compute_52w_range_position(bars, lookback=3)
    assert result == {
        "pct_from_high": round((96 - 100) / 100 * 100, 2),
        "pct_from_low": round((96 - 90) / 90 * 100, 2),
    }


def test_52w_range_position_none_se_storico_insufficiente():
    bars = [_bar(100) for _ in range(10)]
    assert technicals.compute_52w_range_position(bars) is None


# --- compute_relative_volume -----------------------------------------------


def test_relative_volume_valore_atteso():
    bars = [_bar(100, volume=1000) for _ in range(20)] + [_bar(101, volume=1500)]
    # media precedente = 1000, ultima barra = 1500 -> 1.5x
    assert technicals.compute_relative_volume(bars, period=20) == 1.5


def test_relative_volume_none_se_manca_volume():
    bars = [_bar(100) for _ in range(21)]
    assert technicals.compute_relative_volume(bars, period=20) is None


def test_relative_volume_none_se_storico_insufficiente():
    bars = [_bar(100, volume=1000) for _ in range(10)]
    assert technicals.compute_relative_volume(bars, period=20) is None
