"""Vanguard ETF construction: weights, methods, price-frame assembly."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockobserver.analytics.portfolio_opt import optimize_portfolio, prices_wide


def _prices() -> pd.DataFrame:
    dates = pd.bdate_range("2022-01-01", periods=400)
    rng = np.random.default_rng(0)
    data = 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, (400, 4)), axis=0)
    return pd.DataFrame(data, index=dates, columns=["A", "B", "C", "D"])


def test_max_sharpe_weights_sum_to_one() -> None:
    pw = optimize_portfolio(_prices(), "max_sharpe")
    assert pw.method == "max_sharpe"
    assert sum(pw.weights.values()) == pytest.approx(1.0, abs=0.02)
    assert all(w > 0 for w in pw.weights.values())


def test_min_volatility_runs() -> None:
    pw = optimize_portfolio(_prices(), "min_volatility")
    assert pw.volatility > 0


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="method must be"):
        optimize_portfolio(_prices(), "hrp")


def test_prices_wide_drops_unaligned_nans() -> None:
    dr = pd.bdate_range("2023-01-02", periods=5)
    a = pd.DataFrame({"date": dr, "adj_close": [1.0, 2, 3, 4, 5]})
    b = pd.DataFrame(
        {
            "date": dr[1:].append(pd.bdate_range("2023-01-09", periods=1)),
            "adj_close": [9.0, 8, 7, 6, 5],
        }
    )
    wide = prices_wide({"A.US": a, "B.US": b})
    assert list(wide.columns) == ["A.US", "B.US"]
    assert not wide.isna().any().any()  # rows without both are dropped
