from __future__ import annotations

import pytest
from src import config, volatility


def test_daily_returns_pct():
    bars = [
        {"date": "2026-08-01", "close": 100.0},
        {"date": "2026-08-02", "close": 102.0},
        {"date": "2026-08-03", "close": 101.0},
    ]
    returns = volatility.daily_returns_pct(bars)
    assert len(returns) == 2
    assert round(returns[0], 4) == 2.0
    assert round(returns[1], 4) == round((-1.0 / 102.0) * 100, 4)


def test_classify_change():
    threshold = 1.5
    assert volatility.classify_change(2.0, threshold) == "UP"
    assert volatility.classify_change(-2.0, threshold) == "DOWN"
    assert volatility.classify_change(1.0, threshold) == "FLAT"
    assert volatility.classify_change(-1.0, threshold) == "FLAT"
    assert volatility.classify_change(1.5, threshold) == "FLAT"
    assert volatility.classify_change(-1.5, threshold) == "FLAT"


def test_compute_threshold_pct():
    # 10 bars = 9 returns
    bars = [{"date": f"2026-08-{i:02d}", "close": 100.0 + i} for i in range(1, 11)]
    horizon = config.Horizon(code="1d", days=1, trading_days=1)
    thresh = volatility.compute_threshold_pct(bars, horizon)
    assert isinstance(thresh, float)
    assert thresh > 0

    # Test failure on small historical data
    short_bars = bars[:4]
    with pytest.raises(ValueError, match="insufficiente"):
        volatility.compute_threshold_pct(short_bars, horizon)
