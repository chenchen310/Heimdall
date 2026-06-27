"""Market router: dispatch by the symbol's MARKET to the owning provider."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from heimdall.data.base import DataProvider, NotSupported
from heimdall.data.router import RoutingProvider


class _Fake(DataProvider):
    def __init__(self, tag: str) -> None:
        self.tag = tag

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return pd.DataFrame({"symbol": [symbol], "who": [self.tag]})

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        return pd.DataFrame({"symbol": [symbol], "who": [self.tag]})


def _router() -> RoutingProvider:
    return RoutingProvider({"US": _Fake("us"), "TW": _Fake("tw"), "TWO": _Fake("tw")})


def test_routes_by_market() -> None:
    r = _router()
    d0, d1 = date(2024, 1, 1), date(2024, 2, 1)
    assert r.get_ohlcv("AAPL.US", d0, d1)["who"].iloc[0] == "us"
    assert r.get_ohlcv("2330.TW", d0, d1)["who"].iloc[0] == "tw"
    assert r.get_fundamentals("6488.TWO", "all", "annual")["who"].iloc[0] == "tw"
    assert r.markets == frozenset({"US", "TW", "TWO"})


def test_unrouted_market_raises() -> None:
    r = RoutingProvider({"US": _Fake("us")})
    with pytest.raises(NotSupported, match="market 'TW'"):
        r.get_ohlcv("2330.TW", date(2024, 1, 1), date(2024, 2, 1))
