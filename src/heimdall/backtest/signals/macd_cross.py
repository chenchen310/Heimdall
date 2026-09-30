"""MACD crossover signals (roadmap 18.8).

Enter long when the MACD line crosses **above** its signal line; exit when it crosses
**below**. Decision signals timed to the bar that produced them — the engine fills
on the next bar's open (``.claude/rules/backtest-honesty.md``).
"""

from __future__ import annotations

import pandas as pd

from heimdall.factors.indicators import macd


def macd_cross_signals(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series]:
    """Return ``(entries, exits)`` boolean Series aligned to ``close``."""
    if not 0 < fast < slow:
        raise ValueError(f"require 0 < fast ({fast}) < slow ({slow})")
    line, sig, _ = macd(close, fast=fast, slow=slow, signal=signal)
    prev_line, prev_sig = line.shift(1), sig.shift(1)
    entries = (line > sig) & (prev_line <= prev_sig)
    exits = (line < sig) & (prev_line >= prev_sig)
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)
