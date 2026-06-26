"""Higher-level analysis: fundamental & technical dashboards (and risk/macro later).

Produces structured, computed payloads (plain dicts/dataclasses) for the UI and,
optionally, the decoupled ``personas`` AI-report layer. No LLM calls here.
"""

from __future__ import annotations

from stockobserver.analytics.fundamental import FundamentalReport, fundamental_report
from stockobserver.analytics.technical import TechnicalReport, technical_report

__all__ = [
    "FundamentalReport",
    "fundamental_report",
    "TechnicalReport",
    "technical_report",
]
