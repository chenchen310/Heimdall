"""Portfolio statistics from daily return series (roadmap 18.3) — pure numpy/pandas.

The daily engine's stats table: every figure is an optimistic upper bound
(``.claude/rules/backtest-honesty.md``) and is shown beside its drawdown, never alone.
Risk-free rate is 0 throughout (the same convention as ``backtest.report.quick_metrics``).
"""

from __future__ import annotations

import math
from typing import cast

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _cagr(r: pd.Series) -> float:
    n = len(r)
    if n == 0:
        return float("nan")
    growth = float(np.prod(1.0 + r.to_numpy(dtype=float)))
    return growth ** (TRADING_DAYS / n) - 1.0 if growth > 0 else -1.0


def _ann_ratio(x: pd.Series) -> float:
    sd = float(x.std())
    return float(x.mean()) / sd * math.sqrt(TRADING_DAYS) if sd > 0 else float("nan")


def drawdown(r: pd.Series) -> pd.Series:
    eq = (1.0 + r).cumprod()
    return eq / eq.cummax() - 1.0


def max_drawdown_duration(r: pd.Series) -> int:
    """Longest run of trading days spent below a prior equity peak."""
    under = (drawdown(r) < 0).to_numpy()
    longest = run = 0
    for flag in under:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest


def monthly(r: pd.Series) -> pd.Series:
    """Calendar-month compounded returns."""
    idx = cast("pd.DatetimeIndex", r.index)
    return (1.0 + r).groupby(idx.to_period("M")).prod() - 1.0


def portfolio_stats(
    r: pd.Series, benchmark: pd.Series, universe: pd.Series | None = None
) -> dict[str, float]:
    """The headline table for one strategy vs its benchmark (and EW universe)."""
    r, benchmark = r.align(benchmark, join="inner")
    dd = drawdown(r)
    mdd = float(dd.min()) if len(dd) else float("nan")
    cagr = _cagr(r)
    downside = float(r[r < 0].std())
    var_b = float(benchmark.var())
    beta = float(r.cov(benchmark) / var_b) if var_b > 0 else float("nan")
    excess = r - benchmark
    rm, bm = monthly(r), monthly(benchmark)
    out: dict[str, float] = {
        "cagr": cagr,
        "benchmark_cagr": _cagr(benchmark),
        "vol": float(r.std()) * math.sqrt(TRADING_DAYS),
        "sharpe": _ann_ratio(r),
        "benchmark_sharpe": _ann_ratio(benchmark),
        "sortino": float(r.mean()) / downside * math.sqrt(TRADING_DAYS)
        if downside > 0
        else float("nan"),
        "max_drawdown": mdd,
        "max_drawdown_days": float(max_drawdown_duration(r)),
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "beta": beta,
        "alpha_ann": (float(r.mean()) - beta * float(benchmark.mean())) * TRADING_DAYS
        if not np.isnan(beta)
        else float("nan"),
        "tracking_error": float(excess.std()) * math.sqrt(TRADING_DAYS),
        "ir_vs_benchmark": _ann_ratio(excess),
        "pct_months_beating_benchmark": float((rm > bm).mean()) if len(rm) else float("nan"),
    }
    if universe is not None:
        r_u, u = r.align(universe, join="inner")
        out["universe_cagr"] = _cagr(u)
        out["ir_vs_universe"] = _ann_ratio(r_u - u)
    return out


def yearly_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """Calendar-year compounded returns, one column per series (partial years included)."""
    idx = cast("pd.DatetimeIndex", returns.index)
    return (1.0 + returns).groupby(idx.year).prod() - 1.0


def rolling_excess(r: pd.Series, benchmark: pd.Series, window: int = TRADING_DAYS) -> pd.Series:
    """Trailing-``window`` compounded strategy return minus the benchmark's."""
    r, benchmark = r.align(benchmark, join="inner")
    roll = (1.0 + r).rolling(window).apply(np.prod, raw=True) - 1.0
    roll_b = (1.0 + benchmark).rolling(window).apply(np.prod, raw=True) - 1.0
    return roll - roll_b
