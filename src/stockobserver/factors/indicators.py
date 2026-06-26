"""Technical indicators — thin canonical wrappers over ``pandas_ta``.

Indicators return plain lowercase-named Series so downstream code never depends
on pandas_ta's column naming. More indicators (RSI, MACD, ATR, Bollinger) land
in Phase 1+; Phase 0 needs only SMA for the vertical-slice strategy.
"""

from __future__ import annotations

from typing import cast

import pandas as pd
import pandas_ta as ta


def sma(close: pd.Series, length: int) -> pd.Series:
    """Simple moving average of ``close`` over ``length`` bars."""
    out = ta.sma(close, length=length)
    if out is None:  # insufficient data → all-NaN series
        out = pd.Series(index=close.index, dtype="float64")
    out.name = f"sma_{length}"
    return cast("pd.Series", out)
