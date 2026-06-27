"""Point-in-time correctness of the snapshot — the Phase 1 look-ahead guard.

A value must only be 'known' on/after its filing date, and 'latest' means the
most recently *ended* fiscal period (not the last row of a multi-year filing).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import OHLCV_COLUMNS
from heimdall.factors.metrics import _latest_annual, _revenue_growth_yoy
from heimdall.screener.snapshot import build_row


def _fundamentals() -> pd.DataFrame:
    # FY2022 filed 2023-02; FY2023 filed 2024-02; the 2024 10-K also re-reports
    # FY2022 as a comparative (same filed date as FY2023).
    rows = [
        ("revenue", "2022-12-31", "2023-02-01", 100.0),
        ("revenue", "2023-12-31", "2024-02-01", 120.0),
        ("revenue", "2022-12-31", "2024-02-01", 100.0),  # comparative in FY2023 10-K
        ("net_income", "2023-12-31", "2024-02-01", 20.0),
    ]
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "metric": [r[0] for r in rows],
            "statement": "income",
            "period": "annual",
            "fiscal_end": pd.to_datetime([r[1] for r in rows]),
            "filed_at": pd.to_datetime([r[2] for r in rows]),
            "value": [r[3] for r in rows],
            "currency": "USD",
            "provider": "edgar",
            "fetched_at": pd.Timestamp("2024-03-01"),
        }
    )


def test_only_filed_values_are_known() -> None:
    f = _fundamentals()
    # In mid-2023 only FY2022 (filed Feb 2023) is knowable.
    assert _latest_annual(f, date(2023, 6, 1))["revenue"] == 100.0
    # By mid-2024 the FY2023 10-K is out → latest revenue is FY2023.
    assert _latest_annual(f, date(2024, 6, 1))["revenue"] == 120.0


def test_latest_picks_max_fiscal_end_not_last_filed_row() -> None:
    # FY2022 and FY2023 share a filed date; 'latest' must be the newer period.
    f = _fundamentals()
    assert _latest_annual(f, date(2024, 6, 1))["revenue"] == 120.0


def test_revenue_growth_is_point_in_time() -> None:
    f = _fundamentals()
    assert pd.isna(_revenue_growth_yoy(f, date(2023, 6, 1)))  # only one year known
    assert _revenue_growth_yoy(f, date(2024, 6, 1)) == pytest.approx(0.2)  # 120/100 - 1


def _ohlcv(n: int = 60) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = pd.Series(100 + np.linspace(0, 10, n), dtype=float)
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000.0,
            "currency": "USD",
            "provider": "test",
            "fetched_at": pd.Timestamp("2024-04-01"),
        }
    )[OHLCV_COLUMNS]


class _Prices(DataProvider):
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._df


class _NoFundamentals(DataProvider):
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotSupported("prices not served here")

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        raise ProviderError("no SEC CIK for ticker")  # e.g. a VTI name not in EDGAR


def test_build_row_degrades_to_price_only_when_fundamentals_missing() -> None:
    # A symbol EDGAR can't resolve must still produce a (price-only) row, not vanish.
    row = build_row("X.US", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 4, 1))
    assert row is not None
    assert row["symbol"] == "X.US"
    assert pd.notna(row["price"])  # technicals present
    assert pd.isna(row["pe"])  # no fundamentals → valuation NaN, not a crash


def test_build_row_returns_none_without_prices() -> None:
    empty = pd.DataFrame(columns=OHLCV_COLUMNS)
    assert build_row("X.US", _Prices(empty), _NoFundamentals(), date(2024, 4, 1)) is None
