"""Bollinger-band mean-reversion signals (roadmap 18.8).

Enter long when the close crosses **down** through the lower band (a stretched
sell-off); exit when it crosses **up** through the middle band (the mean). Crossing,
not level, so a bar sitting outside the band does not fire every day.
"""

from __future__ import annotations

import pandas as pd

from heimdall.factors.indicators import bollinger


def bollinger_reversion_signals(
    close: pd.Series, length: int = 20, mult: float = 2.0
) -> tuple[pd.Series, pd.Series]:
    """Return ``(entries, exits)`` boolean Series aligned to ``close``."""
    if length < 2 or mult <= 0:
        raise ValueError("require length ≥ 2 and mult > 0")
    _, mid, lower = bollinger(close, length, mult)
    prev_close = close.shift(1)
    entries = (close < lower) & (prev_close >= lower.shift(1))
    exits = (close > mid) & (prev_close <= mid.shift(1))
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
