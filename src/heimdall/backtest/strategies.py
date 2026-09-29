"""Strategy registry — a uniform ``(ohlcv, **params) -> (entries, exits)`` view.

Each strategy declares its tunable parameters (with sweepable ranges) so the UI
can render inputs and the sweep can build grids generically. Signal math lives in
``signals/``; this module only adapts it to a common shape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from heimdall.backtest.signals import (
    bollinger_reversion_signals,
    breakout_signals,
    macd_cross_signals,
    rsi_reversion_signals,
    sma_crossover_signals,
)


@dataclass(frozen=True, slots=True)
class Param:
    """A tunable integer/float parameter with UI + sweep bounds."""

    default: float
    lo: float
    hi: float
    step: float = 1.0
    integer: bool = True


@dataclass(frozen=True, slots=True)
class Strategy:
    label: str
    signals: Callable[..., tuple[pd.Series, pd.Series]]
    params: dict[str, Param]


def _close(ohlcv: pd.DataFrame) -> pd.Series:
    return pd.Series(ohlcv["adj_close"].to_numpy(), index=pd.DatetimeIndex(ohlcv["date"]))


def _sma(ohlcv: pd.DataFrame, fast: int = 20, slow: int = 50) -> tuple[pd.Series, pd.Series]:
    return sma_crossover_signals(_close(ohlcv), fast=fast, slow=slow)


def _breakout(ohlcv: pd.DataFrame, entry: int = 20, exit: int = 10) -> tuple[pd.Series, pd.Series]:
    return breakout_signals(ohlcv, entry=entry, exit=exit)


def _rsi(
    ohlcv: pd.DataFrame, length: int = 14, lower: float = 30, upper: float = 70
) -> tuple[pd.Series, pd.Series]:
    return rsi_reversion_signals(_close(ohlcv), length=length, lower=lower, upper=upper)


def _macd(
    ohlcv: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series]:
    return macd_cross_signals(_close(ohlcv), fast=fast, slow=slow, signal=signal)


def _bollinger(
    ohlcv: pd.DataFrame, length: int = 20, mult: float = 2.0
) -> tuple[pd.Series, pd.Series]:
    return bollinger_reversion_signals(_close(ohlcv), length=length, mult=mult)


STRATEGIES: dict[str, Strategy] = {
    "sma_crossover": Strategy(
        "SMA crossover",
        _sma,
        {"fast": Param(20, 5, 100), "slow": Param(50, 10, 300)},
    ),
    "breakout": Strategy(
        "Donchian breakout",
        _breakout,
        {"entry": Param(20, 5, 120), "exit": Param(10, 5, 120)},
    ),
    "rsi_reversion": Strategy(
        "RSI mean-reversion",
        _rsi,
        {
            "length": Param(14, 2, 50),
            "lower": Param(30, 5, 45),
            "upper": Param(70, 55, 95),
        },
    ),
    "macd_cross": Strategy(
        "MACD crossover",
        _macd,
        {"fast": Param(12, 3, 50), "slow": Param(26, 10, 120), "signal": Param(9, 3, 30)},
    ),
    "bollinger_reversion": Strategy(
        "Bollinger mean-reversion",
        _bollinger,
        {"length": Param(20, 5, 100), "mult": Param(2.0, 1.0, 3.5, step=0.25, integer=False)},
    ),
}
