"""Market router — dispatch a canonical symbol to the provider owning its market.

The ``MARKET`` suffix of ``TICKER.MARKET`` decides ownership, so adding Taiwan is
a routing entry plus one provider; nothing downstream changes (it still sees one
``DataProvider`` speaking the canonical schema). Branching on *market* here is the
sanctioned dispatch point — downstream code never branches on provider/vendor.
See ``docs/ARCHITECTURE.md`` §1–2 and ``.claude/rules/canonical-schema.md``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from heimdall.data.base import DataProvider, NotSupported
from heimdall.data.symbols import parse_symbol


class RoutingProvider(DataProvider):
    """A :class:`DataProvider` that forwards each call to a per-market backend."""

    def __init__(self, routes: dict[str, DataProvider]) -> None:
        self._routes = dict(routes)

    @property
    def markets(self) -> frozenset[str]:  # type: ignore[override]
        return frozenset(self._routes)

    def _for(self, symbol: str) -> DataProvider:
        market = parse_symbol(symbol).market
        try:
            return self._routes[market]
        except KeyError:
            raise NotSupported(f"no provider routed for market {market!r}") from None

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._for(symbol).get_ohlcv(symbol, start, end)

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        return self._for(symbol).get_fundamentals(symbol, statement, period)

    def get_estimates(self, symbol: str) -> pd.DataFrame:
        return self._for(symbol).get_estimates(symbol)

    def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        return self._for(symbol).get_earnings_dates(symbol)


def price_provider() -> DataProvider:
    """Default price routing. yfinance already serves US + Taiwan (adjusted), so it
    owns every market; this stays a router so a market can be repointed later."""
    from heimdall.data.providers import YFinanceProvider

    yf = YFinanceProvider()
    return RoutingProvider({"US": yf, "TW": yf, "TWO": yf})


def fundamentals_provider() -> DataProvider:
    """Default fundamentals routing: EDGAR for US, FinMind for Taiwan."""
    from heimdall.data.providers import FinMindProvider, SecEdgarProvider

    finmind = FinMindProvider()
    return RoutingProvider({"US": SecEdgarProvider(), "TW": finmind, "TWO": finmind})


__all__ = ["RoutingProvider", "price_provider", "fundamentals_provider"]
