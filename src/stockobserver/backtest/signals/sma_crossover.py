"""SMA crossover signals (the Phase 0 vertical-slice strategy).

Signals are computed from a price Series (use split-adjusted close) and are
*decision* signals timed to the bar whose close produced them. The engine is
responsible for executing them on the **next** bar's open — never here — so this
function carries no look-ahead. See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import pandas as pd

from stockobserver.factors.indicators import sma


def sma_crossover_signals(
    close: pd.Series, fast: int = 20, slow: int = 50
) -> tuple[pd.Series, pd.Series]:
    """Return ``(entries, exits)`` boolean Series aligned to ``close``.

    Entry on the bar where the fast SMA crosses **above** the slow SMA; exit on
    the bar where it crosses **below**.
    """
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be < slow ({slow})")

    fast_ma = sma(close, fast)
    slow_ma = sma(close, slow)
    prev_fast, prev_slow = fast_ma.shift(1), slow_ma.shift(1)

    entries = (fast_ma > slow_ma) & (prev_fast <= prev_slow)
    exits = (fast_ma < slow_ma) & (prev_fast >= prev_slow)
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
