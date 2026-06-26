"""Factor portfolio backtest (bt) — hold the top-N by composite, rebalanced.

Selection at each rebalance date uses only point-in-time factor scores (data
filed/observed on/before that date); execution is at that date's close with
commissions. An equal-weight basket of the whole universe is run as a benchmark
so you can see whether the factor actually adds value.

Results carry **survivorship bias** over a current universe — an optimistic upper
bound, not a promise. See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import bt
import pandas as pd


@dataclass(frozen=True)
class PortfolioResult:
    equity: pd.DataFrame  # growth of $1 per strategy (columns: factor_topN, equal_weight)
    stats: dict[str, dict[str, float]]  # strategy -> {total_return, cagr, max_drawdown, sharpe}


def _topn_mask(
    panel: pd.DataFrame, index: pd.DatetimeIndex, n: int, factor_col: str
) -> pd.DataFrame:
    """Daily boolean hold-mask: top-N by factor on each rebalance date, held forward."""
    symbols = sorted(panel["symbol"].unique())
    # use 0/1 floats (not bool) so reindex+fill never round-trips through object dtype
    sel = pd.DataFrame(0.0, index=sorted(panel["date"].unique()), columns=symbols)
    for d, grp in panel.groupby("date"):
        top = grp.dropna(subset=[factor_col]).nlargest(n, factor_col)["symbol"]
        sel.loc[d, [s for s in top if s in sel.columns]] = 1.0
    daily = sel.reindex(index, method="ffill").fillna(0.0)
    return daily > 0


def _key_stats(stats: Any, name: str) -> dict[str, float]:
    return {
        "total_return": float(stats.loc["total_return", name]),
        "cagr": float(stats.loc["cagr", name]),
        "max_drawdown": float(stats.loc["max_drawdown", name]),
        "sharpe": float(stats.loc["daily_sharpe", name]),
    }


def backtest_portfolio(
    prices: pd.DataFrame,
    panel: pd.DataFrame,
    n: int = 5,
    factor_col: str = "composite_score",
    monthly: bool = True,
    commission_bps: float = 10.0,
    init_cash: float = 10_000.0,
) -> PortfolioResult:
    """Backtest a top-N factor portfolio vs an equal-weight benchmark."""
    mask = _topn_mask(panel, cast("pd.DatetimeIndex", prices.index), n, factor_col)
    run = bt.algos.RunMonthly() if monthly else bt.algos.RunQuarterly()

    def commission(q: float, p: float) -> float:
        return abs(q) * p * commission_bps / 1e4

    factor_strat = bt.Strategy(
        "factor_topN",
        [run, bt.algos.SelectWhere(mask), bt.algos.WeighEqually(), bt.algos.Rebalance()],
    )
    bench_strat = bt.Strategy(
        "equal_weight",
        [run, bt.algos.SelectAll(), bt.algos.WeighEqually(), bt.algos.Rebalance()],
    )
    backtests = [
        bt.Backtest(s, prices, initial_capital=init_cash, commissions=commission)
        for s in (factor_strat, bench_strat)
    ]
    res = bt.run(*backtests)

    equity = cast("pd.DataFrame", res.prices).copy()
    equity = equity / equity.iloc[0]  # growth of $1
    stats = {name: _key_stats(res.stats, name) for name in ("factor_topN", "equal_weight")}
    return PortfolioResult(equity=equity, stats=stats)
