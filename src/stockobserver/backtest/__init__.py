"""Backtesting: signals (vectorbt) and portfolios (bt). Phase 0/2 = single-strategy."""

from __future__ import annotations

from stockobserver.backtest.costs import DEFAULT_COSTS, ZERO_COSTS, Costs
from stockobserver.backtest.engine import run_backtest
from stockobserver.backtest.portfolio import PortfolioResult, backtest_portfolio
from stockobserver.backtest.report import (
    drawdown_series,
    equity_curve,
    quick_metrics,
    summary_metrics,
    tear_sheet,
)
from stockobserver.backtest.setup import TradeSetup, trade_setup
from stockobserver.backtest.strategies import STRATEGIES, Param, Strategy
from stockobserver.backtest.sweep import sweep

__all__ = [
    "Costs",
    "DEFAULT_COSTS",
    "ZERO_COSTS",
    "run_backtest",
    "STRATEGIES",
    "Strategy",
    "Param",
    "sweep",
    "backtest_portfolio",
    "PortfolioResult",
    "trade_setup",
    "TradeSetup",
    "equity_curve",
    "drawdown_series",
    "quick_metrics",
    "summary_metrics",
    "tear_sheet",
]
