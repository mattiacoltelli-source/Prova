from __future__ import annotations

from src.technical_indicators import (
    calculate_bollinger_bands,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
    compute_all_indicators,
)


def test_calculate_sma():
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calculate_sma(closes, 3) == 40.0
    assert calculate_sma(closes, 10) is None


def test_calculate_rsi():
    # 15 values, constant increase -> RSI 100
    up_closes = [float(i) for i in range(1, 20)]
    rsi = calculate_rsi(up_closes, 14)
    assert rsi is not None
    assert rsi > 90.0

    # Down closes
    down_closes = [float(100 - i) for i in range(1, 20)]
    rsi_down = calculate_rsi(down_closes, 14)
    assert rsi_down is not None
    assert rsi_down < 10.0


def test_calculate_macd():
    closes = [float(i) for i in range(1, 40)]
    macd = calculate_macd(closes)
    assert macd["macd_line"] is not None
    assert macd["macd_signal"] is not None
    assert macd["macd_histogram"] is not None


def test_calculate_bollinger_bands():
    closes = [10.0] * 20
    bb = calculate_bollinger_bands(closes, window=20)
    assert bb["bb_middle"] == 10.0
    assert bb["bb_upper"] == 10.0
    assert bb["bb_lower"] == 10.0


def test_compute_all_indicators():
    closes = [float(i) for i in range(1, 250)]
    indicators = compute_all_indicators(closes)
    assert indicators["rsi_14"] is not None
    assert indicators["sma_50"] is not None
    assert indicators["sma_200"] is not None
    assert indicators["macd_line"] is not None
    assert indicators["bb_upper"] is not None
