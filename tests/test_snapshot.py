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
from heimdall.factors.metrics import _latest_annual, _revenue_growth_yoy, snapshot_row
from heimdall.screener.snapshot import build_row, split_by_region


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


def _fund_two_years() -> pd.DataFrame:
    rows = []

    def add(metric: str, end: str, filed: str, value: float) -> None:
        rows.append(
            {
                "symbol": "X.US",
                "metric": metric,
                "statement": "income",
                "period": "annual",
                "fiscal_end": pd.Timestamp(end),
                "filed_at": pd.Timestamp(filed),
                "value": float(value),
                "currency": "USD",
                "provider": "test",
                "fetched_at": pd.Timestamp("2024-03-01"),
            }
        )

    latest = {
        "revenue": 1000, "net_income": 100, "operating_income": 150, "pretax_income": 125,
        "eps_diluted": 2.0, "gross_profit": 400, "equity": 500, "liabilities": 300,
        "shares_outstanding": 50, "cash": 100, "long_term_debt": 200, "cfo": 180,
        "capex": 80, "dep_amort": 50, "interest_expense": 30,
    }  # fmt: skip
    for m, v in latest.items():
        add(m, "2023-12-31", "2024-02-15", v)
    for m, v in {"revenue": 800, "eps_diluted": 1.6, "shares_outstanding": 55}.items():
        add(m, "2022-12-31", "2023-02-15", v)
    return pd.DataFrame(rows)


def _ohlcv_at(price: float, n: int = 60) -> pd.DataFrame:
    df = _ohlcv(n)
    df["adj_close"] = float(price)  # flat → snapshot price = `price`
    return df


def test_snapshot_row_derived_metrics_known_answer() -> None:
    # price 40 × 50 shares = market_cap 2000; values chosen to verify by hand.
    m = snapshot_row("X.US", _ohlcv_at(40.0), _fund_two_years(), date(2024, 6, 1))
    assert m["market_cap"] == pytest.approx(2000)
    assert m["ebitda"] == pytest.approx(200)  # operating_income 150 + D&A 50
    assert m["net_debt"] == pytest.approx(100)  # debt 200 − cash 100
    assert m["ev"] == pytest.approx(2100)  # mktcap 2000 + net_debt 100
    assert m["fcf"] == pytest.approx(100)  # cfo 180 − capex 80
    assert m["fcf_margin"] == pytest.approx(0.10)
    assert m["operating_margin"] == pytest.approx(0.15)
    assert m["ev_ebitda"] == pytest.approx(10.5)
    assert m["ev_fcf"] == pytest.approx(21.0)
    assert m["interest_coverage"] == pytest.approx(5.0)  # EBIT 150 / interest 30
    assert m["net_debt_to_ebitda"] == pytest.approx(0.5)
    assert m["roic"] == pytest.approx(0.20)  # NOPAT 150×(100/125)=120 / IC 600
    assert m["eps_growth_yoy"] == pytest.approx(0.25)  # 2.0 / 1.6 − 1
    assert m["peg"] == pytest.approx(0.8)  # pe 20 / (25)
    # shares 55 → 50: net buyback, negative dilution.
    assert m["share_dilution_yoy"] == pytest.approx(50 / 55 - 1)
    assert m["buyback_yield"] == pytest.approx(1 - 50 / 55)
    assert m["currency"] == "USD"  # follows the market suffix, not hardcoded


def test_snapshot_row_currency_follows_market() -> None:
    # The unit bug: a TW row's TWD figures must not be labeled (and compared as) USD.
    us = snapshot_row("X.US", _ohlcv_at(40.0), _fund_two_years(), date(2024, 6, 1))
    tw = snapshot_row("2330.TW", _ohlcv_at(40.0), _fund_two_years(), date(2024, 6, 1))
    assert us["currency"] == "USD"
    assert tw["currency"] == "TWD"


def test_split_by_region_partitions_us_and_taiwan() -> None:
    snap = pd.DataFrame(
        {
            "symbol": ["AAPL.US", "2330.TW", "MSFT.US", "6488.TWO"],
            "price": [1.0, 2.0, 3.0, 4.0],
        }
    )
    groups = split_by_region(snap)
    assert list(groups) == ["US", "Taiwan"]  # US first, per market-definition order
    assert groups["US"]["symbol"].tolist() == ["AAPL.US", "MSFT.US"]
    assert groups["Taiwan"]["symbol"].tolist() == ["2330.TW", "6488.TWO"]  # .TW + .TWO together


def test_split_by_region_empty_snapshot() -> None:
    assert split_by_region(pd.DataFrame()) == {}
