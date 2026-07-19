"""Morgan Stanley technical dashboard — a computed payload from OHLCV.

Trend across timeframes, moving-average state, momentum (RSI/MACD), volatility
(ATR/Bollinger), swing support/resistance, Fibonacci retracements, and an ATR
trade setup. Pure computation (no LLM) — the optional ``personas`` layer turns
this into prose. See ``docs/ARCHITECTURE.md`` (persona→module map).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from heimdall.backtest.setup import TradeSetup, trade_setup
from heimdall.factors.indicators import atr, bollinger, macd, rsi, sma


@dataclass(frozen=True)
class TechnicalReport:
    symbol: str
    price: float
    trend: dict[str, str]  # short / medium / long -> up / down / sideways
    moving_averages: dict[str, float]  # sma_20 / sma_50 / sma_200
    ma_cross: str | None  # "golden" / "death" / None (recent)
    rsi_14: float
    macd: dict[str, float]  # line / signal / hist
    bollinger: dict[str, float]  # upper / mid / lower / percent_b
    atr_14: float
    support: list[float]
    resistance: list[float]
    fibonacci: dict[str, float]  # ratio label -> price
    setup: TradeSetup


def _trend(fast: float, slow: float, tol: float = 0.005) -> str:
    if pd.isna(fast) or pd.isna(slow):
        return "n/a"
    if fast > slow * (1 + tol):
        return "up"
    if fast < slow * (1 - tol):
        return "down"
    return "sideways"


def _recent_cross(fast: pd.Series, slow: pd.Series, window: int = 15) -> str | None:
    diff = (fast - slow).dropna()
    if len(diff) < window + 1:
        return None
    first, last = float(diff.iloc[-window]), float(diff.iloc[-1])
    if first < 0 < last:
        return "golden"
    if first > 0 > last:
        return "death"
    return None


def _swings(values: npt.NDArray[np.float64], k: int, kind: str) -> list[float]:
    out: list[float] = []
    for i in range(k, len(values) - k):
        window = values[i - k : i + k + 1]
        if (kind == "max" and values[i] == window.max()) or (
            kind == "min" and values[i] == window.min()
        ):
            out.append(float(values[i]))
    return out


def _support_resistance(
    ohlcv: pd.DataFrame, price: float, lookback: int = 160, k: int = 5
) -> tuple[list[float], list[float]]:
    recent = ohlcv.tail(lookback)
    highs = _swings(recent["high"].to_numpy(), k, "max")
    lows = _swings(recent["low"].to_numpy(), k, "min")
    resistance = sorted({round(h, 2) for h in highs if h > price})[:3]
    support = sorted({round(lo, 2) for lo in lows if lo < price}, reverse=True)[:3]
    return support, resistance


def _fibonacci(ohlcv: pd.DataFrame, lookback: int = 160) -> dict[str, float]:
    recent = ohlcv.tail(lookback)
    hi, lo = float(recent["high"].max()), float(recent["low"].min())
    span = hi - lo
    return {f"{r:.1%}": round(hi - span * r, 2) for r in (0.0, 0.236, 0.382, 0.5, 0.618, 1.0)}


def technical_report(symbol: str, ohlcv: pd.DataFrame) -> TechnicalReport:
    """Compute the technical dashboard payload for ``symbol`` from canonical OHLCV."""
    close = ohlcv["adj_close"].reset_index(drop=True)
    price = float(close.iloc[-1])
    s20, s50, s200 = sma(close, 20), sma(close, 50), sma(close, 200)
    up, mid, low = bollinger(close, 20)
    band = float(up.iloc[-1]) - float(low.iloc[-1])
    line, signal, hist = macd(close)
    support, resistance = _support_resistance(ohlcv, price)

    return TechnicalReport(
        symbol=symbol,
        price=price,
        trend={
            "short": _trend(price, float(s20.iloc[-1])),
            "medium": _trend(float(s20.iloc[-1]), float(s50.iloc[-1])),
            "long": _trend(float(s50.iloc[-1]), float(s200.iloc[-1])),
        },
        moving_averages={
            "sma_20": float(s20.iloc[-1]),
            "sma_50": float(s50.iloc[-1]),
            "sma_200": float(s200.iloc[-1]),
        },
        ma_cross=_recent_cross(s50, s200),
        rsi_14=float(rsi(close, 14).iloc[-1]),
        macd={
            "line": float(line.iloc[-1]),
            "signal": float(signal.iloc[-1]),
            "hist": float(hist.iloc[-1]),
        },
        bollinger={
            "upper": float(up.iloc[-1]),
            "mid": float(mid.iloc[-1]),
            "lower": float(low.iloc[-1]),
            "percent_b": (price - float(low.iloc[-1])) / band if band else float("nan"),
        },
        atr_14=float(atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14).iloc[-1]),
        support=support,
        resistance=resistance,
        fibonacci=_fibonacci(ohlcv),
        # Anchor the two structural entries to real chart levels: buy a dip to the
        # nearest support, buy a breakout over the nearest resistance. Lists are
        # ordered nearest-to-price first (see ``_support_resistance``); when a side
        # has no swing level, ``trade_setup`` falls back to an ATR offset.
        setup=trade_setup(
            ohlcv,
            pullback_level=support[0] if support else None,
            breakout_level=resistance[0] if resistance else None,
        ),
    )
