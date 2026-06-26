"""The ``DataProvider`` ABC — the interface every source implements.

A provider is the only place vendor-specific shapes may exist; it normalizes raw
vendor data into the canonical schema (``schema.py``) and tags provenance. A
source that cannot serve a method raises :class:`NotSupported` rather than
returning fabricated data. See ``docs/ARCHITECTURE.md`` §2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class ProviderError(RuntimeError):
    """Base class for provider failures."""


class NotSupported(ProviderError):
    """Raised when a provider cannot serve a requested method/market."""


class DataProvider(ABC):
    """Normalizes a single data source into the canonical schema.

    Subclasses declare the markets they own and implement the methods they can
    serve. Each provider owns its own rate limiting; the cache layer
    (:class:`~stockobserver.data.cache.CachedProvider`) wraps providers and is
    responsible for persistence/delta fetching, so providers stay stateless.
    """

    #: Markets this provider owns, e.g. ``frozenset({"US"})``.
    markets: frozenset[str] = frozenset()

    @property
    def name(self) -> str:
        """Short provenance tag written into the ``provider`` column."""
        return type(self).__name__.removesuffix("Provider").lower()

    @abstractmethod
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return canonical OHLCV for ``symbol`` over ``[start, end]`` (inclusive)."""

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not serve fundamentals")

    def get_estimates(self, symbol: str) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not serve estimates")

    def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        raise NotSupported(f"{self.name} does not serve earnings dates")
