"""Backtest metric extraction (quick + summary)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stockobserver.backtest.engine import run_backtest
from stockobserver.backtest.report import quick_metrics, summary_metrics
from stockobserver.backtest.signals import sma_crossover_signals


def _pf() -> object:
    n = 160
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = pd.Series(100 + np.linspace(0, 50, n) + 5 * np.sin(np.arange(n) / 8), dtype=float)
    ohlcv = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adj_close": close,
        }
    )
    entries, exits = sma_crossover_signals(close.set_axis(dates), fast=5, slow=20)
    return run_backtest(ohlcv, entries, exits)


def test_quick_metrics_keys_and_ranges() -> None:
    m = quick_metrics(_pf())
    assert set(m) == {"total_return", "cagr", "sharpe", "max_drawdown", "n_trades"}
    assert m["max_drawdown"] <= 0  # drawdown is non-positive
    assert m["n_trades"] >= 1
    assert math.isfinite(m["total_return"])


def test_summary_adds_trade_stats() -> None:
    m = summary_metrics(_pf())
    assert {"win_rate", "profit_factor", "sortino"} <= set(m)
    assert 0.0 <= m["win_rate"] <= 1.0
