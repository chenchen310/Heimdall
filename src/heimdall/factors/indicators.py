"""Technical indicators — thin canonical wrappers over ``pandas_ta``.

Indicators return plain lowercase-named Series so downstream code never depends
on pandas_ta's column naming. More indicators (RSI, MACD, ATR, Bollinger) land
in Phase 1+; Phase 0 needs only SMA for the vertical-slice strategy.
"""

from __future__ import annotations

from typing import cast

import pandas as pd
import pandas_ta as ta


def _empty(index: pd.Index, name: str) -> pd.Series:
    return pd.Series(index=index, dtype="float64", name=name)


def sma(close: pd.Series, length: int) -> pd.Series:
    """Simple moving average of ``close`` over ``length`` bars."""
    out = ta.sma(close, length=length)
    if out is None:  # insufficient data → all-NaN series
        out = _empty(close.index, f"sma_{length}")
    out.name = f"sma_{length}"
    return cast("pd.Series", out)


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index (0–100)."""
    out = ta.rsi(close, length=length)
    if out is None:
        out = _empty(close.index, f"rsi_{length}")
    out.name = f"rsi_{length}"
    return cast("pd.Series", out)


def bollinger(
    close: pd.Series, length: int = 20, mult: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands as ``(upper, mid, lower)`` (mid = SMA)."""
    mid = sma(close, length)
    std = close.rolling(length).std()
    upper = (mid + mult * std).rename(f"bb_upper_{length}")
    lower = (mid - mult * std).rename(f"bb_lower_{length}")
    return upper, mid.rename(f"bb_mid_{length}"), lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average True Range — volatility, used for stop placement in trade setups."""
    out = ta.atr(high=high, low=low, close=close, length=length)
    if out is None:
        out = _empty(close.index, f"atr_{length}")
    out.name = f"atr_{length}"
    return cast("pd.Series", out)


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD as ``(macd_line, signal_line, histogram)``."""
    out = ta.macd(close, fast=fast, slow=slow, signal=signal)
    if out is None or out.empty:
        e = _empty(close.index, "macd")
        return e.rename("macd"), e.rename("macd_signal"), e.rename("macd_hist")
    cols = list(out.columns)  # MACD_*, MACDh_*, MACDs_*
    line = out[next(c for c in cols if c.startswith("MACD_"))].rename("macd")
    hist = out[next(c for c in cols if c.startswith("MACDh_"))].rename("macd_hist")
    sig = out[next(c for c in cols if c.startswith("MACDs_"))].rename("macd_signal")
    return cast("pd.Series", line), cast("pd.Series", sig), cast("pd.Series", hist)
