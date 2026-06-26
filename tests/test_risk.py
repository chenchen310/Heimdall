"""Bridgewater risk metrics: Beta/correlation, drawdown, VaR/CVaR, liquidity."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from stockobserver.analytics.risk import risk_report


def _ohlcv(close: pd.Series, volume: float) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-01", periods=len(close))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adj_close": close,
            "volume": volume,
        }
    )


def _walk() -> pd.Series:
    rng = np.random.default_rng(0)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 260)), dtype=float)


def test_beta_one_versus_itself() -> None:
    o = _ohlcv(_walk(), volume=2e7)  # ~$2B/day → high liquidity
    rep = risk_report("X.US", o, o)  # benchmark == itself
    assert rep.beta == pytest.approx(1.0)
    assert rep.correlation == pytest.approx(1.0)
    assert rep.annual_vol > 0
    assert rep.max_drawdown <= 0
    assert rep.var_95 <= 0 and rep.cvar_95 <= rep.var_95  # tail beyond VaR
    assert rep.recession_stress == pytest.approx(-0.30)  # beta 1 × -30% shock
    assert rep.liquidity == "high"


def test_liquidity_tiers() -> None:
    flat = pd.Series([100.0] * 40)
    assert risk_report("X.US", _ohlcv(flat, 2e7), _ohlcv(flat, 2e7)).liquidity == "high"
    assert risk_report("X.US", _ohlcv(flat, 2e6), _ohlcv(flat, 2e6)).liquidity == "medium"
    assert risk_report("X.US", _ohlcv(flat, 1e5), _ohlcv(flat, 1e5)).liquidity == "low"
