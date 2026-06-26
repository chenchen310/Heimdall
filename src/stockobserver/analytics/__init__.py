"""Higher-level analysis: fundamental, technical, risk, macro, rotation, ETF, earnings.

Produces structured, computed payloads (plain dicts/dataclasses) for the UI and,
optionally, the decoupled ``personas`` AI-report layer. No LLM calls here.
"""

from __future__ import annotations

from stockobserver.analytics.earnings import EarningsReport, earnings_report
from stockobserver.analytics.fundamental import FundamentalReport, fundamental_report
from stockobserver.analytics.macro import MacroReport, macro_dashboard
from stockobserver.analytics.portfolio_opt import (
    PortfolioWeights,
    optimize_portfolio,
    prices_wide,
)
from stockobserver.analytics.risk import RiskReport, risk_report
from stockobserver.analytics.rotation import SECTOR_ETFS, RotationReport, sector_rotation
from stockobserver.analytics.technical import TechnicalReport, technical_report

__all__ = [
    "FundamentalReport",
    "fundamental_report",
    "TechnicalReport",
    "technical_report",
    "RiskReport",
    "risk_report",
    "MacroReport",
    "macro_dashboard",
    "RotationReport",
    "sector_rotation",
    "SECTOR_ETFS",
    "PortfolioWeights",
    "optimize_portfolio",
    "prices_wide",
    "EarningsReport",
    "earnings_report",
]
