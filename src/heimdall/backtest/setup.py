"""Trade setup — ATR-based entry/stop/target/risk-reward (Morgan Stanley lens).

A simple, transparent long framework off the latest bar. The ``entry`` field is the
"buy it now" market reference (the latest close); on top of that it frames the two
actionable ways a trader actually gets in:

- **pullback** — buy a dip *below* price (at a passed support level, else ~1 ATR under
  the close),
- **breakout** — buy strength *above* price (at a passed resistance level, else ~1 ATR
  over the close).

Each of the two carries its **own** ATR stop and R-multiple targets, so risk is
measured from the price you'd actually pay, not from the current quote. Not a
recommendation — a framework for sizing risk consistently. Pair with the strategy's
own exit rules.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from heimdall.factors.indicators import atr


@dataclass(frozen=True, slots=True)
class EntryPlan:
    """One way into a trade: an entry with its own ATR stop and R-multiple targets."""

    entry: float
    stop: float
    risk: float  # entry - stop (per share)
    targets: list[float]  # price levels, one per reward/risk multiple


@dataclass(frozen=True, slots=True)
class TradeSetup:
    entry: float  # market reference — the latest close ("buy now")
    stop: float
    risk: float  # entry - stop (per share)
    atr: float
    targets: list[float]  # price levels
    rr: list[float]  # reward/risk multiples for each target
    pullback: EntryPlan  # buy a dip below price
    breakout: EntryPlan  # buy strength above price


def _plan(entry: float, a: float, atr_mult: float, rr: tuple[float, ...]) -> EntryPlan:
    """Build one entry's stop (``atr_mult`` ATRs below) and its R-multiple targets."""
    stop = entry - atr_mult * a
    risk = entry - stop
    return EntryPlan(entry=entry, stop=stop, risk=risk, targets=[entry + m * risk for m in rr])


def trade_setup(
    ohlcv: pd.DataFrame,
    atr_length: int = 14,
    atr_mult: float = 2.0,
    rr: tuple[float, ...] = (1.0, 2.0, 3.0),
    entry_atr_mult: float = 1.0,
    pullback_level: float | None = None,
    breakout_level: float | None = None,
) -> TradeSetup:
    """Long setup off the most recent bar's close and ATR.

    The market ``entry`` is the latest close. ``pullback_level`` / ``breakout_level``
    let a caller anchor the two structural entries to real chart levels (e.g. the
    nearest support / resistance); when omitted they fall back to ``entry_atr_mult``
    ATRs below / above the close, so both entries are always defined.
    """
    high = pd.Series(ohlcv["high"].to_numpy())
    low = pd.Series(ohlcv["low"].to_numpy())
    close = pd.Series(ohlcv["close"].to_numpy())

    a = float(atr(high, low, close, atr_length).iloc[-1])
    entry = float(close.iloc[-1])
    stop = entry - atr_mult * a
    risk = entry - stop

    pb_entry = pullback_level if pullback_level is not None else entry - entry_atr_mult * a
    bo_entry = breakout_level if breakout_level is not None else entry + entry_atr_mult * a

    return TradeSetup(
        entry=entry,
        stop=stop,
        risk=risk,
        atr=a,
        targets=[entry + m * risk for m in rr],
        rr=list(rr),
        pullback=_plan(pb_entry, a, atr_mult, rr),
        breakout=_plan(bo_entry, a, atr_mult, rr),
    )
