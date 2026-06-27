"""Vanguard ETF construction — mean-variance optimization via PyPortfolioOpt.

Given a basket of ETFs, compute max-Sharpe or min-volatility weights on the
efficient frontier. (HRP is skipped pending a PyPortfolioOpt/scipy fix.) Free
data — ETF prices via yfinance. Expected returns from history are noisy; treat
the weights as a starting point, not gospel.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

METHODS = ("max_sharpe", "min_volatility")


@dataclass(frozen=True)
class PortfolioWeights:
    method: str
    weights: dict[str, float]  # ticker -> weight (only non-zero)
    expected_return: float  # annualized
    volatility: float  # annualized
    sharpe: float


def prices_wide(ohlcv_map: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a wide adj-close price frame (dates × ticker) from per-ticker OHLCV."""
    cols = {t: df.set_index("date")["adj_close"] for t, df in ohlcv_map.items() if not df.empty}
    return pd.DataFrame(cols).sort_index().dropna()


def optimize_portfolio(prices: pd.DataFrame, method: str = "max_sharpe") -> PortfolioWeights:
    """Optimize weights over ``prices`` (wide adj-close) by ``method``."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    from pypfopt import EfficientFrontier, expected_returns, risk_models

    mu = expected_returns.mean_historical_return(prices)
    cov = risk_models.sample_cov(prices)
    ef = EfficientFrontier(mu, cov)
    if method == "max_sharpe":
        ef.max_sharpe()
    else:
        ef.min_volatility()

    cleaned = ef.clean_weights()
    ret, vol, sharpe = ef.portfolio_performance()
    return PortfolioWeights(
        method=method,
        weights={k: round(float(v), 4) for k, v in cleaned.items() if v > 0},
        expected_return=float(ret),
        volatility=float(vol),
        sharpe=float(sharpe),
    )
