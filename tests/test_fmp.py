"""FMP drop-in provider: golden normalization to the canonical schema; key gating."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.data.base import NotSupported
from heimdall.data.providers.fmp import (
    FmpProvider,
    _normalize_earnings,
    _normalize_fundamentals,
    _normalize_ohlcv,
)
from heimdall.data.schema import EARNINGS_COLUMNS, FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.data.symbols import Symbol

_STATEMENTS = {
    "income": [
        {
            "date": "2023-12-31",
            "period": "FY",
            "fillingDate": "2024-02-01",
            "revenue": 1200,
            "netIncome": 260,
            "epsdiluted": 2.6,
            "weightedAverageShsOutDil": 100,
            "interestExpense": 20,
            "incomeBeforeTax": 320,
        }
    ],
    "balance": [
        {
            "date": "2023-12-31",
            "period": "FY",
            "fillingDate": "2024-02-01",
            "totalAssets": 2000,
            "totalLiabilities": 300,
            "totalStockholdersEquity": 500,
        }
    ],
    "cashflow": [
        {
            "date": "2023-12-31",
            "period": "FY",
            "fillingDate": "2024-02-01",
            "operatingCashFlow": 300,
            "capitalExpenditure": -50,
            "depreciationAndAmortization": 40,
        }
    ],
}


def test_normalize_fundamentals_to_canonical() -> None:
    df = _normalize_fundamentals(_STATEMENTS, Symbol("X", "US"))
    assert list(df.columns) == FUNDAMENTALS_COLUMNS
    assert df["provider"].unique().tolist() == ["fmp"]
    assert {"revenue", "net_income", "assets", "equity", "cfo", "capex"} <= set(df["metric"])
    # new line items feeding interest coverage / ROIC / EBITDA
    assert {"interest_expense", "pretax_income", "dep_amort"} <= set(df["metric"])
    assert df["filed_at"].notna().all()  # point-in-time invariant
    rev = df[df["metric"] == "revenue"].iloc[0]
    assert rev["value"] == 1200 and rev["period"] == "annual"
    # FMP capex is negative; canonical stores a positive magnitude (matches EDGAR)
    assert df.loc[df["metric"] == "capex", "value"].iloc[0] == 50


def test_normalize_ohlcv_sorted_and_adjusted() -> None:
    raw = {
        "symbol": "X",
        "historical": [
            {
                "date": "2024-01-03",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "adjClose": 10.4,
                "volume": 1000,
            },
            {
                "date": "2024-01-02",
                "open": 9,
                "high": 10,
                "low": 8,
                "close": 9.5,
                "adjClose": 9.4,
                "volume": 2000,
            },
        ],
    }
    df = _normalize_ohlcv(raw, Symbol("X", "US"))
    assert list(df.columns) == OHLCV_COLUMNS
    assert df["date"].is_monotonic_increasing
    assert df.iloc[0]["adj_close"] == 9.4
    assert df["symbol"].unique().tolist() == ["X.US"]


def test_normalize_earnings() -> None:
    raw = [
        {
            "date": "2024-11-01",
            "eps": None,
            "epsEstimated": 1.3,
            "revenue": None,
            "revenueEstimated": 120,
        },
        {
            "date": "2024-08-01",
            "eps": 1.1,
            "epsEstimated": 1.2,
            "revenue": 108,
            "revenueEstimated": 110,
        },
    ]
    df = _normalize_earnings(raw, Symbol("X", "US"))
    assert list(df.columns) == EARNINGS_COLUMNS
    assert df["symbol"].unique().tolist() == ["X.US"]
    # FMP leaves eps null for not-yet-reported dates → flagged future
    assert bool(df.loc[df["date"] == pd.Timestamp("2024-11-01"), "is_future"].iloc[0]) is True
    assert bool(df.loc[df["date"] == pd.Timestamp("2024-08-01"), "is_future"].iloc[0]) is False


def test_provider_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    with pytest.raises(NotSupported, match="FMP_API_KEY"):
        FmpProvider(api_key=None).get_fundamentals("X.US", "all", "annual")
