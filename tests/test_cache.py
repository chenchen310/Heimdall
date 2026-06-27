"""Delta-fetch behavior of CachedProvider (no network).

The point of the cache is that already-fetched dates are never re-requested —
only the missing head/tail. A FakeProvider records exactly what was asked for.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider
from heimdall.data.cache import CachedProvider
from heimdall.data.schema import OHLCV_COLUMNS


class FakeProvider(DataProvider):
    """Returns deterministic business-day bars and logs requested ranges."""

    markets = frozenset({"US"})

    def __init__(self) -> None:
        self.requests: list[tuple[date, date]] = []

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.requests.append((start, end))
        days = pd.bdate_range(start, end)
        n = len(days)
        return pd.DataFrame(
            {
                "symbol": [symbol] * n,
                "date": days,
                "open": range(n),
                "high": range(n),
                "low": range(n),
                "close": range(n),
                "adj_close": range(n),
                "volume": [100] * n,
                "currency": ["USD"] * n,
                "provider": ["fake"] * n,
                "fetched_at": [pd.Timestamp("2024-01-01")] * n,
            },
            columns=OHLCV_COLUMNS,
        )


def test_first_fetch_requests_full_range(tmp_path: Path) -> None:
    fake = FakeProvider()
    cp = CachedProvider(fake, root=tmp_path)
    out = cp.get_ohlcv("AAPL.US", date(2024, 1, 2), date(2024, 1, 5))
    assert fake.requests == [(date(2024, 1, 2), date(2024, 1, 5))]
    assert len(out) == 4  # Tue..Fri


def test_extend_only_fetches_tail(tmp_path: Path) -> None:
    fake = FakeProvider()
    cp = CachedProvider(fake, root=tmp_path)
    cp.get_ohlcv("AAPL.US", date(2024, 1, 2), date(2024, 1, 5))
    out = cp.get_ohlcv("AAPL.US", date(2024, 1, 2), date(2024, 1, 10))

    # second request is ONLY the gap after the cached max (2024-01-05)
    assert fake.requests[1] == (date(2024, 1, 6), date(2024, 1, 10))
    # full union returned, no duplicates
    assert out["date"].is_monotonic_increasing
    assert not out["date"].duplicated().any()
    assert out["date"].max() == pd.Timestamp("2024-01-10")


def test_cached_subrange_makes_no_request(tmp_path: Path) -> None:
    fake = FakeProvider()
    cp = CachedProvider(fake, root=tmp_path)
    cp.get_ohlcv("AAPL.US", date(2024, 1, 2), date(2024, 1, 10))
    n_before = len(fake.requests)
    out = cp.get_ohlcv("AAPL.US", date(2024, 1, 3), date(2024, 1, 4))
    assert len(fake.requests) == n_before  # nothing new fetched
    assert len(out) == 2


def test_persists_across_instances(tmp_path: Path) -> None:
    CachedProvider(FakeProvider(), root=tmp_path).get_ohlcv(
        "AAPL.US", date(2024, 1, 2), date(2024, 1, 5)
    )
    fake2 = FakeProvider()
    out = CachedProvider(fake2, root=tmp_path).get_ohlcv(
        "AAPL.US", date(2024, 1, 2), date(2024, 1, 5)
    )
    assert fake2.requests == []  # served entirely from the Parquet on disk
    assert len(out) == 4
