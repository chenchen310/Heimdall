"""RSI mean-reversion signals.

Enter long when RSI crosses **down** through ``lower`` (oversold); exit when it
crosses **up** through ``upper`` (recovered). Crossing (not level) avoids firing
on every bar while the indicator sits in a zone.
"""

from __future__ import annotations

import pandas as pd

from stockobserver.factors.indicators import rsi


def rsi_reversion_signals(
    close: pd.Series, length: int = 14, lower: float = 30, upper: float = 70
) -> tuple[pd.Series, pd.Series]:
    """Return ``(entries, exits)`` boolean Series aligned to ``close``."""
    if not 0 < lower < upper < 100:
        raise ValueError("require 0 < lower < upper < 100")

    r = rsi(close, length)
    prev = r.shift(1)
    entries = (r < lower) & (prev >= lower)
    exits = (r > upper) & (prev <= upper)
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
