"""Donchian channel breakout signals.

Enter long when the close breaks above the highest high of the prior ``entry``
bars; exit when it breaks below the lowest low of the prior ``exit`` bars. The
rolling windows are shifted one bar so the channel uses only *prior* data; the
engine still executes on the next bar's open. See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import pandas as pd


def breakout_signals(
    ohlcv: pd.DataFrame, entry: int = 20, exit: int = 10
) -> tuple[pd.Series, pd.Series]:
    """Return ``(entries, exits)`` boolean Series aligned to ``ohlcv`` rows."""
    if entry < 1 or exit < 1:
        raise ValueError("breakout lookbacks must be >= 1")

    idx = pd.DatetimeIndex(ohlcv["date"])
    close = pd.Series(ohlcv["close"].to_numpy(), index=idx)
    high = pd.Series(ohlcv["high"].to_numpy(), index=idx)
    low = pd.Series(ohlcv["low"].to_numpy(), index=idx)

    upper = high.rolling(entry).max().shift(1)  # prior `entry`-bar high
    lower = low.rolling(exit).min().shift(1)  # prior `exit`-bar low

    entries = close > upper
    exits = close < lower
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
