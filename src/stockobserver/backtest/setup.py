"""Trade setup — ATR-based entry/stop/target/risk-reward (Morgan Stanley lens).

A simple, transparent long setup off the latest bar: stop a multiple of ATR below
entry, targets at R-multiples of that risk. Not a recommendation — a framework for
sizing risk consistently. Pair with the strategy's own exit rules.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stockobserver.factors.indicators import atr


@dataclass(frozen=True, slots=True)
class TradeSetup:
    entry: float
    stop: float
    risk: float  # entry - stop (per share)
    atr: float
    targets: list[float]  # price levels
    rr: list[float]  # reward/risk multiples for each target


def trade_setup(
    ohlcv: pd.DataFrame,
    atr_length: int = 14,
    atr_mult: float = 2.0,
    rr: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> TradeSetup:
    """Long setup off the most recent bar's close and ATR."""
    high = pd.Series(ohlcv["high"].to_numpy())
    low = pd.Series(ohlcv["low"].to_numpy())
    close = pd.Series(ohlcv["close"].to_numpy())

    a = float(atr(high, low, close, atr_length).iloc[-1])
    entry = float(close.iloc[-1])
    stop = entry - atr_mult * a
    risk = entry - stop
    return TradeSetup(
        entry=entry,
        stop=stop,
        risk=risk,
        atr=a,
        targets=[entry + m * risk for m in rr],
        rr=list(rr),
    )
