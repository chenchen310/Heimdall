"""Concrete data providers. Each normalizes one vendor into the canonical schema."""

from __future__ import annotations

from stockobserver.data.providers.edgar import SecEdgarProvider
from stockobserver.data.providers.fred import FredProvider
from stockobserver.data.providers.yfinance import YFinanceProvider

__all__ = ["YFinanceProvider", "SecEdgarProvider", "FredProvider"]
