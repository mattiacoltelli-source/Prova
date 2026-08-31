"""Test unitari per il modulo di backtesting quantitativo su 2 anni."""
from __future__ import annotations

from src import backtest


def test_calculate_max_drawdown():
    # Picco a 100, poi calo a 80 -> Drawdown 20%
    series = [100.0, 110.0, 90.0, 88.0, 120.0]
    dd = backtest._calculate_max_drawdown(series)
    assert dd == 20.0


def test_generate_quantitative_signal_short_bars():
    bars = [{"date": "2024-01-01", "close": 100.0} for _ in range(10)]
    signal = backtest.generate_quantitative_signal(bars, 5)
    assert signal == "FLAT"


def test_run_backtest_for_asset():
    summary = backtest.run_backtest_for_asset("SPY", horizon_days=1)
    assert summary["asset"] == "SPY"
    assert "ai_total_return_pct" in summary
    assert "buy_hold_total_return_pct" in summary
    assert "win_rate_pct" in summary
    assert "ai_max_drawdown_pct" in summary
    assert isinstance(summary["equity_curve"], list)
