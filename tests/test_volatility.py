from __future__ import annotations

import pytest
from src import config, volatility


def _bars_with_range(n: int, base: float = 100.0, daily_range_pct: float = 2.0) -> list[dict]:
    """Barre OHLC sintetiche con un true range costante (in % del prezzo),
    così l'ATR atteso è calcolabile a mano nel test."""
    bars = []
    close = base
    for i in range(n):
        half_range = close * (daily_range_pct / 100) / 2
        bars.append(
            {
                "date": f"2026-08-{i + 1:02d}",
                "close": close,
                "high": close + half_range,
                "low": close - half_range,
            }
        )
        close += 0.01  # variazione trascurabile, evita divisioni per zero
    return bars


def test_classify_change():
    threshold = 1.5
    assert volatility.classify_change(2.0, threshold) == "UP"
    assert volatility.classify_change(-2.0, threshold) == "DOWN"
    assert volatility.classify_change(1.0, threshold) == "FLAT"
    assert volatility.classify_change(-1.0, threshold) == "FLAT"
    assert volatility.classify_change(1.5, threshold) == "FLAT"
    assert volatility.classify_change(-1.5, threshold) == "FLAT"


def test_compute_threshold_pct_usa_atr_e_scala_per_orizzonte():
    bars = _bars_with_range(20, daily_range_pct=2.0)
    horizon_1d = config.Horizon(code="1d", days=1, trading_days=1)
    horizon_7d = config.Horizon(code="7d", days=7, trading_days=5)

    thresh_1d = volatility.compute_threshold_pct(bars, horizon_1d)
    thresh_7d = volatility.compute_threshold_pct(bars, horizon_7d)

    assert thresh_1d > 0
    # Stessa base ATR, scalata per sqrt(trading_days): l'orizzonte più
    # lungo deve avere una banda più larga, in proporzione a sqrt(5).
    assert thresh_7d == pytest.approx(thresh_1d * (5 ** 0.5), rel=1e-3)


def test_compute_threshold_pct_fallisce_con_storico_insufficiente():
    horizon = config.Horizon(code="1d", days=1, trading_days=1)
    short_bars = _bars_with_range(5)
    with pytest.raises(ValueError, match="insufficiente"):
        volatility.compute_threshold_pct(short_bars, horizon)


def test_compute_threshold_pct_fallisce_senza_high_low():
    # Fonte di fallback che non fornisce high/low: l'ATR non è calcolabile.
    horizon = config.Horizon(code="1d", days=1, trading_days=1)
    bars = [{"date": f"2026-08-{i:02d}", "close": 100.0 + i} for i in range(1, 20)]
    with pytest.raises(ValueError, match="insufficiente"):
        volatility.compute_threshold_pct(bars, horizon)
