"""Single-strategy backtest engine (vectorbt).

The honesty mechanism lives here: a signal derived from bar *t*'s close is
shifted one bar and executed at bar *t+1*'s **open**, with commissions and
slippage applied. Executing on the signal bar's own close/open would import the
future. See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import pandas as pd
import vectorbt as vbt

from heimdall.backtest.costs import DEFAULT_COSTS, Costs


def _indexed(ohlcv: pd.DataFrame, col: str) -> pd.Series:
    return pd.Series(
        ohlcv[col].to_numpy(),
        index=pd.DatetimeIndex(ohlcv["date"]),
        name=col,
        dtype="float64",
    )


def run_backtest(
    ohlcv: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    costs: Costs = DEFAULT_COSTS,
    init_cash: float = 10_000.0,
) -> vbt.Portfolio:
    """Backtest decision signals against canonical ``ohlcv``.

    ``entries``/``exits`` are decision signals timed to the bar that produced
    them (e.g. from :func:`sma_crossover_signals`); they are filled on the next
    bar's open with ``costs`` applied. Portfolio is valued on adjusted close.
    """
    idx = pd.DatetimeIndex(ohlcv["date"])
    open_ = _indexed(ohlcv, "open")
    close = _indexed(ohlcv, "adj_close")

    entries = entries.reindex(idx).fillna(False).astype(bool)
    exits = exits.reindex(idx).fillna(False).astype(bool)

    # Next-bar-open execution: shift the decision forward one bar, fill at open.
    entries_exec = entries.shift(1, fill_value=False)
    exits_exec = exits.shift(1, fill_value=False)

    return vbt.Portfolio.from_signals(
        close=close,
        entries=entries_exec,
        exits=exits_exec,
        price=open_,
        fees=costs.fees,
        slippage=costs.slippage,
        init_cash=init_cash,
        freq="1D",
    )
