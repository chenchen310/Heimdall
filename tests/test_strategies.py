"""Signal correctness for the breakout and RSI mean-reversion strategies."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockobserver.backtest.signals import breakout_signals, rsi_reversion_signals
from stockobserver.factors.indicators import rsi


def _ohlcv(close: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=len(close))
    c = pd.Series(close, dtype=float)
    return pd.DataFrame({"date": dates, "open": c, "high": c, "low": c, "close": c, "adj_close": c})


def test_breakout_fires_on_new_highs_and_lows() -> None:
    # high=low=close so the channel is unambiguous.
    ohlcv = _ohlcv([10, 10, 10, 11, 12, 11, 9, 8])
    entries, exits = breakout_signals(ohlcv, entry=2, exit=2)
    assert np.flatnonzero(entries.to_numpy()).tolist() == [3, 4]  # broke prior 2-bar high
    assert np.flatnonzero(exits.to_numpy()).tolist() == [6, 7]  # broke prior 2-bar low


def test_rsi_reversion_obeys_crossing_invariant() -> None:
    # Rise (RSI high) → decline into oversold (down-cross 30) → recovery into
    # overbought (up-cross 70). Starting high ensures a genuine down-cross.
    close = pd.Series(
        list(np.linspace(100, 120, 20))
        + list(np.linspace(120, 80, 25))
        + list(np.linspace(80, 140, 25)),
        dtype=float,
    )
    entries, exits = rsi_reversion_signals(close, length=14, lower=30, upper=70)
    r = rsi(close, 14)

    assert entries.any() and exits.any()
    for i in np.flatnonzero(entries.to_numpy()):  # each entry is a genuine down-cross
        assert r.iloc[i] < 30 and r.iloc[i - 1] >= 30
    for i in np.flatnonzero(exits.to_numpy()):  # each exit is a genuine up-cross
        assert r.iloc[i] > 70 and r.iloc[i - 1] <= 70


def test_registry_strategies_run_with_defaults() -> None:
    from stockobserver.backtest.strategies import STRATEGIES

    ohlcv = _ohlcv(list(100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 260))))
    for strat in STRATEGIES.values():
        entries, exits = strat.signals(ohlcv, **{k: p.default for k, p in strat.params.items()})
        assert entries.dtype == bool and exits.dtype == bool
        assert len(entries) == len(ohlcv)
