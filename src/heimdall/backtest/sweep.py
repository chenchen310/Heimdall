"""Parameter sweep — run a strategy across a grid and tabulate honest metrics.

Each combination is a full, cost-aware, next-bar-open backtest (no shortcuts), so
the resulting surface is comparable to single runs. Keep grids small and prefer
broad, stable regions over a single peak — a lone spike is usually overfit.
See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import pandas as pd

from heimdall.backtest.costs import DEFAULT_COSTS, Costs
from heimdall.backtest.engine import run_backtest
from heimdall.backtest.report import quick_metrics
from heimdall.backtest.strategies import STRATEGIES

_NAN_METRICS = {"total_return", "cagr", "sharpe", "max_drawdown"}


def sweep(
    ohlcv: pd.DataFrame,
    strategy_key: str,
    sweep_params: dict[str, Sequence[float]],
    fixed_params: dict[str, float] | None = None,
    costs: Costs = DEFAULT_COSTS,
) -> pd.DataFrame:
    """Backtest ``strategy_key`` over the Cartesian product of ``sweep_params``.

    Returns a tidy frame: one row per combination, with the swept parameters plus
    ``total_return``/``cagr``/``sharpe``/``max_drawdown``/``n_trades``. Invalid
    combinations (e.g. SMA fast >= slow) yield NaN metrics rather than raising.
    """
    strat = STRATEGIES[strategy_key]
    fixed = fixed_params or {}
    names = list(sweep_params)
    rows: list[dict[str, float]] = []

    for combo in itertools.product(*(sweep_params[n] for n in names)):
        params = {**fixed, **dict(zip(names, combo, strict=True))}
        try:
            entries, exits = strat.signals(ohlcv, **params)
            metrics = quick_metrics(run_backtest(ohlcv, entries, exits, costs=costs))
        except ValueError:  # invalid parameter region
            metrics = {**{k: float("nan") for k in _NAN_METRICS}, "n_trades": 0}
        rows.append({**dict(zip(names, combo, strict=True)), **metrics})

    return pd.DataFrame(rows)
