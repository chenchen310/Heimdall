"""Concrete data providers. Each normalizes one vendor into the canonical schema."""

from __future__ import annotations

from stockobserver.data.providers.yfinance import YFinanceProvider

__all__ = ["YFinanceProvider"]
