"""FinMind (Taiwan) provider: golden normalization + the annual-aggregation traps.

The load-bearing test is ``test_fundamentals_*``: it pins that income lines are
**summed** across standalone quarters while cash-flow lines are taken at
**year-end** (they are cumulative YTD) — getting either wrong silently corrupts
every Taiwan valuation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.data.base import NotSupported
from heimdall.data.providers.finmind import (
    FinMindProvider,
    _normalize_fundamentals,
    _normalize_month_revenue,
    _normalize_ohlcv,
)
from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.data.symbols import Symbol

_TW = Symbol("2330", "TW")

# Real FinMind TaiwanStockPrice rows (note: max=high, min=low, no adjusted close).
_PRICE_ROWS = [
    {
        "date": "2024-01-03",
        "stock_id": "2330",
        "Trading_Volume": 40134497,
        "Trading_money": 23267025945,
        "open": 584.0,
        "max": 585.0,
        "min": 576.0,
        "close": 578.0,
        "spread": -15.0,
        "Trading_turnover": 56916,
    },
    {
        "date": "2024-01-02",
        "stock_id": "2330",
        "Trading_Volume": 27997826,
        "Trading_money": 16549619798,
        "open": 590.0,
        "max": 593.0,
        "min": 589.0,
        "close": 593.0,
        "spread": 0.0,
        "Trading_turnover": 20667,
    },
]


def _income(year: int, quarters: dict[str, list[float]]) -> list[dict[str, object]]:
    """Standalone-quarterly income rows: ``{type: [q1, q2, q3, q4]}``."""
    months = ["03-31", "06-30", "09-30", "12-31"]
    return [
        {"date": f"{year}-{m}", "stock_id": "2330", "type": t, "value": vals[i]}
        for t, vals in quarters.items()
        for i, m in enumerate(months)
    ]


def _cumulative(year: int, type_: str, ytd: list[float]) -> list[dict[str, object]]:
    """Cumulative-YTD cash-flow rows: ``ytd`` is [Q1, H1, 9M, FY]."""
    months = ["03-31", "06-30", "09-30", "12-31"]
    return [
        {"date": f"{year}-{m}", "stock_id": "2330", "type": type_, "value": ytd[i]}
        for i, m in enumerate(months)
    ]


def _balance(year: int, types: dict[str, float]) -> list[dict[str, object]]:
    return [
        {"date": f"{year}-12-31", "stock_id": "2330", "type": t, "value": v}
        for t, v in types.items()
    ]


def _statements() -> dict[str, list[dict[str, object]]]:
    income = (
        _income(
            2023,
            {
                "Revenue": [100, 110, 120, 130],
                "IncomeAfterTaxes": [10, 10, 10, 10],
                "EPS": [1, 1, 1, 1],
            },
        )
        + _income(
            2024,
            {
                "Revenue": [120, 130, 140, 150],
                "IncomeAfterTaxes": [12, 12, 12, 14],
                "EPS": [1, 1, 1, 2],
                "PreTaxIncome": [13, 13, 13, 15],
            },
        )
        # An incomplete year (missing Q4) must NOT yield an annual figure.
        + [{"date": "2025-03-31", "stock_id": "2330", "type": "Revenue", "value": 200}]
    )
    cashflow = (
        _cumulative(2023, "CashFlowsFromOperatingActivities", [25, 50, 75, 100])
        + _cumulative(2023, "PropertyAndPlantAndEquipment", [-7, -15, -22, -30])
        + _cumulative(2024, "CashFlowsFromOperatingActivities", [30, 60, 90, 120])
        + _cumulative(2024, "PropertyAndPlantAndEquipment", [-10, -20, -30, -40])
        + _cumulative(2024, "Depreciation", [20, 40, 60, 80])
    )
    balance = _balance(
        2023, {"TotalAssets": 280, "Liabilities": 90, "Equity": 180, "CashAndCashEquivalents": 45}
    ) + _balance(
        2024, {"TotalAssets": 300, "Liabilities": 100, "Equity": 200, "CashAndCashEquivalents": 50}
    )
    return {"income": income, "balance": balance, "cashflow": cashflow}


def test_ohlcv_normalizes_to_canonical_unadjusted() -> None:
    df = _normalize_ohlcv(_PRICE_ROWS, _TW)
    assert list(df.columns) == OHLCV_COLUMNS
    assert df["date"].is_monotonic_increasing
    assert df["symbol"].unique().tolist() == ["2330.TW"]
    assert df["currency"].unique().tolist() == ["TWD"]
    assert df["provider"].unique().tolist() == ["finmind"]
    row = df[df["date"] == pd.Timestamp("2024-01-02")].iloc[0]
    assert row["high"] == 593.0 and row["low"] == 589.0  # max->high, min->low
    assert row["adj_close"] == row["close"]  # unadjusted: adj mirrors close
    assert row["volume"] == 27997826


def test_ohlcv_empty() -> None:
    assert list(_normalize_ohlcv([], _TW).columns) == OHLCV_COLUMNS
    assert _normalize_ohlcv([], _TW).empty


def test_fundamentals_aggregate_to_canonical_annual() -> None:
    df = _normalize_fundamentals(_statements(), _TW)
    assert list(df.columns) == FUNDAMENTALS_COLUMNS
    assert (df["period"] == "annual").all()
    assert df["currency"].unique().tolist() == ["TWD"]
    assert df["provider"].unique().tolist() == ["finmind"]
    assert df["filed_at"].notna().all()  # point-in-time invariant

    def val(metric: str, year: int) -> float:
        end = pd.Timestamp(year, 12, 31)
        return float(df[(df["metric"] == metric) & (df["fiscal_end"] == end)]["value"].iloc[0])

    # Income flows are SUMMED across the four standalone quarters.
    assert val("revenue", 2024) == 540 and val("revenue", 2023) == 460
    assert val("net_income", 2024) == 50 and val("eps_diluted", 2024) == 5
    # Cash flow is CUMULATIVE YTD → year-end value, never the 30+60+90+120 sum.
    assert val("cfo", 2024) == 120 and val("cfo", 2023) == 100
    # capex stored as a positive magnitude (FinMind reports it negative).
    assert val("capex", 2024) == 40
    # new line items: pre-tax income (income, summed) and D&A (cash flow, year-end).
    assert val("pretax_income", 2024) == 54  # 13+13+13+15
    assert val("dep_amort", 2024) == 80  # cumulative year-end, never the sum
    # Balance is the year-end snapshot.
    assert val("equity", 2024) == 200 and val("liabilities", 2024) == 100
    # shares = annual net income / annual EPS (par-independent): 50 / 5 = 10.
    assert val("shares_outstanding", 2024) == 10


def test_fundamentals_filed_at_is_lagged() -> None:
    df = _normalize_fundamentals(_statements(), _TW)
    fy24 = df[df["fiscal_end"] == pd.Timestamp("2024-12-31")].iloc[0]
    # ~90-day lag past fiscal-year end (no filing date in the feed).
    assert fy24["filed_at"] == pd.Timestamp("2024-12-31") + pd.Timedelta(days=90)


def test_fundamentals_incomplete_year_excluded() -> None:
    df = _normalize_fundamentals(_statements(), _TW)
    years = set(df[df["metric"] == "revenue"]["fiscal_end"].dt.year)
    assert years == {2023, 2024}  # 2025 has only Q1 → no annual figure


def test_fundamentals_quarter_period_empty() -> None:
    out = FinMindProvider(token=None).get_fundamentals("2330.TW", "all", "quarter")
    assert list(out.columns) == FUNDAMENTALS_COLUMNS and out.empty


def test_month_revenue_normalizes() -> None:
    raw = [
        {
            "date": "2024-08-01",
            "stock_id": "2330",
            "revenue": 256953058000,
            "revenue_month": 7,
            "revenue_year": 2024,
        },
        {
            "date": "2024-09-01",
            "stock_id": "2330",
            "revenue": 250866368000,
            "revenue_month": 8,
            "revenue_year": 2024,
        },
        {
            "date": "2025-01-01",
            "stock_id": "2330",
            "revenue": 260000000000,
            "revenue_month": 12,
            "revenue_year": 2024,
        },
    ]
    df = _normalize_month_revenue(raw, _TW)
    assert df["symbol"].unique().tolist() == ["2330.TW"]
    assert df.iloc[0]["month"] == pd.Timestamp("2024-07-01")
    assert df.iloc[0]["revenue"] == 256953058000.0
    assert df["currency"].unique().tolist() == ["TWD"]
    # §36 point-in-time rule: month M's revenue is knowable on the 10th of M+1.
    assert df.iloc[0]["filed_at"] == pd.Timestamp("2024-08-10")
    assert df.iloc[1]["filed_at"] == pd.Timestamp("2024-09-10")
    assert df.iloc[2]["filed_at"] == pd.Timestamp("2025-01-10")  # December rolls the year


def test_rejects_non_taiwan_market() -> None:
    with pytest.raises(NotSupported, match="market US"):
        FinMindProvider().get_ohlcv(
            "AAPL.US", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-02-01").date()
        )
