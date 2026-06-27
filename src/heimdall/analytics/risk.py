"""Bridgewater risk memo — volatility, Beta, drawdown, VaR/CVaR, stress test.

Computed directly from returns (transparent and testable) rather than through a
heavier optimizer; ``riskfolio-lib`` remains available for advanced risk-parity
work later. Pair point estimates with drawdown and a stress scenario, never a
single number — see ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

_TRADING_DAYS = 252


@dataclass(frozen=True)
class RiskReport:
    symbol: str
    annual_vol: float  # annualized volatility
    beta: float  # vs benchmark
    correlation: float  # vs benchmark
    max_drawdown: float  # most-negative peak-to-trough (<= 0)
    var_95: float  # daily historical VaR (5th percentile, <= 0)
    cvar_95: float  # daily expected shortfall beyond VaR (<= 0)
    downside_vol: float  # annualized downside deviation
    sharpe: float
    recession_stress: float  # estimated return under a market shock = beta * shock
    liquidity: str  # high / medium / low


def _returns(ohlcv: pd.DataFrame) -> pd.Series:
    s = pd.Series(
        ohlcv["adj_close"].to_numpy(), index=pd.DatetimeIndex(ohlcv["date"]), dtype="float64"
    )
    return s.pct_change().dropna()


def _liquidity_tier(ohlcv: pd.DataFrame) -> str:
    dollar_vol = float((ohlcv["close"] * ohlcv["volume"]).tail(20).mean())
    if dollar_vol >= 1e9:
        return "high"
    if dollar_vol >= 1e8:
        return "medium"
    return "low"


def risk_report(
    symbol: str,
    ohlcv: pd.DataFrame,
    benchmark_ohlcv: pd.DataFrame,
    market_shock: float = -0.30,
) -> RiskReport:
    """Compute the risk memo for ``symbol`` vs a market benchmark (e.g. SPY)."""
    r = _returns(ohlcv)
    rb = _returns(benchmark_ohlcv)
    joined = pd.concat([r.rename("a"), rb.rename("b")], axis=1, join="inner").dropna()
    a, b = joined["a"], joined["b"]

    vol = float(a.std())
    bench_var = float(b.var())
    beta = float(a.cov(b) / bench_var) if bench_var > 0 else float("nan")
    var95 = float(a.quantile(0.05))
    downside = float(a[a < 0].std())

    eq = (1 + a).cumprod()
    return RiskReport(
        symbol=symbol,
        annual_vol=vol * math.sqrt(_TRADING_DAYS),
        beta=beta,
        correlation=float(a.corr(b)) if vol > 0 and bench_var > 0 else float("nan"),
        max_drawdown=float((eq / eq.cummax() - 1).min()),
        var_95=var95,
        cvar_95=float(a[a <= var95].mean()),
        downside_vol=downside * math.sqrt(_TRADING_DAYS),
        sharpe=float(a.mean()) / vol * math.sqrt(_TRADING_DAYS) if vol > 0 else float("nan"),
        recession_stress=beta * market_shock,
        liquidity=_liquidity_tier(ohlcv),
    )
