"""Higher-level analysis: fundamental, technical, risk, macro, rotation, ETF, earnings.

Produces structured, computed payloads (plain dicts/dataclasses) for the UI and,
optionally, the decoupled ``personas`` AI-report layer. No LLM calls here.
"""

from __future__ import annotations

from heimdall.analytics.chips import cumulative_flows
from heimdall.analytics.earnings import EarningsReport, earnings_report
from heimdall.analytics.fundamental import FundamentalReport, fundamental_report
from heimdall.analytics.macro import MacroReport, macro_dashboard
from heimdall.analytics.portfolio_opt import (
    PortfolioWeights,
    optimize_portfolio,
    prices_wide,
)
from heimdall.analytics.risk import RiskReport, risk_report
from heimdall.analytics.rotation import SECTOR_ETFS, RotationReport, sector_rotation
from heimdall.analytics.technical import TechnicalReport, technical_report

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
    "cumulative_flows",
]
