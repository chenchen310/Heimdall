"""Parameter sweep produces a comparable grid and handles invalid combos."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockobserver.backtest.sweep import sweep


def _trending_ohlcv(n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = pd.Series(100 + np.linspace(0, 40, n) + np.sin(np.arange(n) / 5), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adj_close": close,
        }
    )


def test_grid_shape_and_columns() -> None:
    grid = sweep(_trending_ohlcv(), "sma_crossover", {"fast": [5, 10], "slow": [20, 30]})
    assert len(grid) == 4  # 2 x 2 combinations
    for col in ["fast", "slow", "sharpe", "total_return", "max_drawdown", "n_trades"]:
        assert col in grid.columns


def test_invalid_combo_yields_nan_not_error() -> None:
    # fast >= slow is invalid for sma_crossover → NaN metrics, no exception.
    grid = sweep(_trending_ohlcv(), "sma_crossover", {"fast": [30], "slow": [10]})
    assert len(grid) == 1
    assert np.isnan(grid["sharpe"].iloc[0])
    assert grid["n_trades"].iloc[0] == 0
