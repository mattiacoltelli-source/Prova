"""Calcolo degli indicatori tecnici principali in Python (RSI, MACD, SMA, Bollinger Bands)."""
from __future__ import annotations

import math
from typing import TypedDict


class TechnicalIndicators(TypedDict):
    rsi_14: float | None
    sma_50: float | None
    sma_200: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None


def calculate_sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 4)


def calculate_ema(closes: list[float], window: int) -> list[float]:
    if len(closes) < window:
        return []
    multiplier = 2 / (window + 1)
    ema_list = [sum(closes[:window]) / window]
    for price in closes[window:]:
        new_ema = (price - ema_list[-1]) * multiplier + ema_list[-1]
        ema_list.append(new_ema)
    return ema_list


def calculate_rsi(closes: list[float], window: int = 14) -> float | None:
    if len(closes) < window + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window

    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def calculate_macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, float | None]:
    if len(closes) < slow + signal:
        return {"macd_line": None, "macd_signal": None, "macd_histogram": None}

    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)

    offset = slow - fast
    aligned_fast = ema_fast[offset:]

    macd_line = [f - s for f, s in zip(aligned_fast, ema_slow)]
    if len(macd_line) < signal:
        return {"macd_line": None, "macd_signal": None, "macd_histogram": None}

    signal_ema = calculate_ema(macd_line, signal)

    latest_macd = macd_line[-1]
    latest_signal = signal_ema[-1]
    latest_hist = latest_macd - latest_signal

    return {
        "macd_line": round(latest_macd, 4),
        "macd_signal": round(latest_signal, 4),
        "macd_histogram": round(latest_hist, 4),
    }


def calculate_bollinger_bands(
    closes: list[float], window: int = 20, num_std: float = 2.0
) -> dict[str, float | None]:
    if len(closes) < window:
        return {"bb_upper": None, "bb_middle": None, "bb_lower": None}

    recent = closes[-window:]
    sma = sum(recent) / window
    variance = sum((x - sma) ** 2 for x in recent) / window
    std_dev = math.sqrt(variance)

    return {
        "bb_upper": round(sma + num_std * std_dev, 4),
        "bb_middle": round(sma, 4),
        "bb_lower": round(sma - num_std * std_dev, 4),
    }


def compute_all_indicators(closes: list[float]) -> TechnicalIndicators:
    rsi = calculate_rsi(closes)
    sma_50 = calculate_sma(closes, 50)
    sma_200 = calculate_sma(closes, 200)
    macd = calculate_macd(closes)
    bb = calculate_bollinger_bands(closes)

    return {
        "rsi_14": rsi,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "macd_line": macd["macd_line"],
        "macd_signal": macd["macd_signal"],
        "macd_histogram": macd["macd_histogram"],
        "bb_upper": bb["bb_upper"],
        "bb_middle": bb["bb_middle"],
        "bb_lower": bb["bb_lower"],
    }
