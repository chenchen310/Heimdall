"""Factor portfolio backtest (bt) on synthetic prices: selection, benchmark, costs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from heimdall.backtest.portfolio import backtest_portfolio

_DATES = pd.bdate_range("2022-01-03", periods=260)


def _prices() -> pd.DataFrame:
    n = len(_DATES)
    return pd.DataFrame(
        {
            "A.US": 100 * np.exp(0.002 * np.arange(n)),  # strong uptrend (best)
            "B.US": 100 * np.ones(n),  # flat
            "C.US": 100 * np.exp(-0.001 * np.arange(n)),  # downtrend
        },
        index=_DATES,
    )


def _panel(prices: pd.DataFrame) -> pd.DataFrame:
    rebal = sorted(
        {
            prices.index[prices.index <= ts][-1]
            for ts in pd.date_range(_DATES[0], _DATES[-1], freq="ME")
        }
    )
    scores = {"A.US": 90.0, "B.US": 50.0, "C.US": 10.0}  # A always ranks top
    return pd.DataFrame(
        [{"date": d, "symbol": s, "composite_score": v} for d in rebal for s, v in scores.items()]
    )


def test_top1_holds_best_and_beats_equal_weight() -> None:
    prices = _prices()
    res = backtest_portfolio(prices, _panel(prices), n=1, commission_bps=0.0)
    assert set(res.stats) == {"factor_topN", "equal_weight"}
    # holding only the strong uptrend beats the equal-weight basket
    assert res.stats["factor_topN"]["total_return"] > res.stats["equal_weight"]["total_return"]
    assert (res.equity.iloc[0] == 1.0).all()  # normalized to growth of $1


def test_commissions_reduce_return() -> None:
    prices = _prices()
    panel = _panel(prices)
    free = backtest_portfolio(prices, panel, n=1, commission_bps=0.0)
    costly = backtest_portfolio(prices, panel, n=1, commission_bps=50.0)
    assert costly.stats["factor_topN"]["total_return"] < free.stats["factor_topN"]["total_return"]
