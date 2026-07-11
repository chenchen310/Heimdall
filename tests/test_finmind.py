"""FinMind (Taiwan) provider: golden normalization + the annual-aggregation traps.

The load-bearing test is ``test_fundamentals_*``: it pins that income lines are
**summed** across standalone quarters while cash-flow lines are taken at
**year-end** (they are cumulative YTD) — getting either wrong silently corrupts
every Taiwan valuation.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from heimdall.data.base import NotSupported
from heimdall.data.providers.finmind import (
    FinMindProvider,
    _merge_chips,
    _normalize_fundamentals,
    _normalize_institutional,
    _normalize_institutional_market_wide,
    _normalize_lending,
    _normalize_margin,
    _normalize_month_revenue,
    _normalize_ohlcv,
    _normalize_shareholding,
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


# --- roadmap 11.3: daily chip/flow datasets (法人籌碼) -------------------------

# Real FinMind TaiwanStockInstitutionalInvestorsBuySell shape (buy/sell in shares).
_INST_ROWS = [
    # 2024-01-02
    {"date": "2024-01-02", "stock_id": "2330", "name": "Foreign_Dealer_Self", "buy": 0, "sell": 0},
    {"date": "2024-01-02", "stock_id": "2330", "name": "Dealer_self", "buy": 80000, "sell": 641052},
    {
        "date": "2024-01-02",
        "stock_id": "2330",
        "name": "Dealer_Hedging",
        "buy": 25585,
        "sell": 472504,
    },
    {
        "date": "2024-01-02",
        "stock_id": "2330",
        "name": "Foreign_Investor",
        "buy": 19034488,
        "sell": 11202763,
    },
    {
        "date": "2024-01-02",
        "stock_id": "2330",
        "name": "Investment_Trust",
        "buy": 869000,
        "sell": 109685,
    },
    # 2024-01-03 — a non-zero Foreign_Dealer_Self and a negative trust net
    {
        "date": "2024-01-03",
        "stock_id": "2330",
        "name": "Foreign_Investor",
        "buy": 10000000,
        "sell": 8000000,
    },
    {
        "date": "2024-01-03",
        "stock_id": "2330",
        "name": "Foreign_Dealer_Self",
        "buy": 500000,
        "sell": 100000,
    },
    {
        "date": "2024-01-03",
        "stock_id": "2330",
        "name": "Investment_Trust",
        "buy": 300000,
        "sell": 500000,
    },
    {"date": "2024-01-03", "stock_id": "2330", "name": "Dealer_self", "buy": 1, "sell": 2},
    {"date": "2024-01-03", "stock_id": "2330", "name": "Dealer_Hedging", "buy": 3, "sell": 4},
]
_HOLD_ROWS = [
    {"date": "2024-01-02", "stock_id": "2330", "ForeignInvestmentSharesRatio": 73.08},
    {"date": "2024-01-03", "stock_id": "2330", "ForeignInvestmentSharesRatio": 73.05},
    {
        "date": "2024-01-04",
        "stock_id": "2330",
        "ForeignInvestmentSharesRatio": 73.05,
    },  # inst lacks this day
]
_MARGIN_ROWS = [
    {
        "date": "2024-01-02",
        "stock_id": "2330",
        "MarginPurchaseTodayBalance": 12844,
        "ShortSaleTodayBalance": 46,
    },
    {
        "date": "2024-01-03",
        "stock_id": "2330",
        "MarginPurchaseTodayBalance": 13785,
        "ShortSaleTodayBalance": 85,
    },
]
# Real FinMind TaiwanDailyShortSaleBalances shape (roadmap 17.1; share-denominated).
_LENDING_ROWS = [
    {"date": "2024-01-02", "stock_id": "2330", "SBLShortSalesCurrentDayBalance": 11170514},
    {"date": "2024-01-03", "stock_id": "2330", "SBLShortSalesCurrentDayBalance": 11159514},
]


def test_institutional_sums_foreign_trust_and_dealer_separately() -> None:
    df = _normalize_institutional(_INST_ROWS)
    assert list(df.columns) == [
        "date",
        "foreign_net_shares",
        "trust_net_shares",
        "dealer_net_shares",
    ]
    assert df["date"].is_monotonic_increasing
    d2 = df[df["date"] == pd.Timestamp("2024-01-02")].iloc[0]
    # foreign = Foreign_Investor net + Foreign_Dealer_Self net.
    assert d2["foreign_net_shares"] == (19034488 - 11202763) + 0
    assert d2["trust_net_shares"] == 869000 - 109685
    # dealer = Dealer_self net + Dealer_Hedging net — carried, but a SEPARATE column
    # (roadmap 15.2), never mixed into foreign/trust (still excluded from those).
    assert d2["dealer_net_shares"] == (80000 - 641052) + (25585 - 472504)
    d3 = df[df["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert d3["foreign_net_shares"] == (10000000 - 8000000) + (
        500000 - 100000
    )  # dealer-self summed in
    assert d3["trust_net_shares"] == 300000 - 500000  # negatives preserved
    assert d3["dealer_net_shares"] == (1 - 2) + (3 - 4)


# --- roadmap 15.2: bulk per-date institutional buy/sell (market-wide) --------


# A real bulk (no data_id) TaiwanStockInstitutionalInvestorsBuySell response shape:
# multiple stock_ids for ONE date. 2330 has all three investor types; 2317
# deliberately has NO Investment_Trust row, exercising the "column exists globally
# (from 2330) but this stock_id's combo fills 0.0" pivot edge case.
def _bulk_row(stock_id: str, name: str, buy: int, sell: int) -> dict[str, object]:
    return {"date": "2024-01-02", "stock_id": stock_id, "name": name, "buy": buy, "sell": sell}


_BULK_INST_ROWS = [
    _bulk_row("2330", "Foreign_Investor", 19034488, 11202763),
    _bulk_row("2330", "Investment_Trust", 869000, 109685),
    _bulk_row("2330", "Dealer_self", 80000, 641052),
    _bulk_row("2317", "Foreign_Investor", 5000000, 4000000),
    _bulk_row("2317", "Dealer_Hedging", 1000, 500),
]


def test_institutional_market_wide_golden() -> None:
    df = _normalize_institutional_market_wide(_BULK_INST_ROWS)
    assert list(df.columns) == [
        "stock_id",
        "date",
        "foreign_net_shares",
        "trust_net_shares",
        "dealer_net_shares",
    ]
    assert set(df["stock_id"]) == {"2330", "2317"}
    r2330 = df[df["stock_id"] == "2330"].iloc[0]
    assert r2330["foreign_net_shares"] == 19034488 - 11202763
    assert r2330["trust_net_shares"] == 869000 - 109685
    assert r2330["dealer_net_shares"] == 80000 - 641052
    r2317 = df[df["stock_id"] == "2317"].iloc[0]
    assert r2317["foreign_net_shares"] == 5000000 - 4000000
    assert r2317["trust_net_shares"] == 0.0  # no Investment_Trust row for 2317 — filled, not NaN
    assert r2317["dealer_net_shares"] == 1000 - 500


def test_institutional_market_wide_empty() -> None:
    out = _normalize_institutional_market_wide([])
    assert out.empty
    assert list(out.columns) == [
        "stock_id",
        "date",
        "foreign_net_shares",
        "trust_net_shares",
        "dealer_net_shares",
    ]


def test_bulk_institutional_by_date_returns_none_on_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real free-tier response: HTTP 400, "please update your user level".
    class _Refused:
        status_code = 400

        def json(self) -> dict[str, object]:
            return {"status": 400, "msg": "Your level is register..."}

    monkeypatch.setattr("requests.get", lambda *a, **k: _Refused())
    assert FinMindProvider(token=None).bulk_institutional_by_date(date(2024, 1, 2)) is None


def test_bulk_institutional_by_date_returns_none_on_empty_market(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A closed-market day (weekend/holiday): 200 status, empty data — also a clean None.
    class _Empty:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"status": 200, "data": []}

    monkeypatch.setattr("requests.get", lambda *a, **k: _Empty())
    assert FinMindProvider(token=None).bulk_institutional_by_date(date(2024, 1, 6)) is None


def test_get_omits_data_id_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Ok:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"status": 200, "data": []}

    def _fake_get(url: str, params: dict[str, object], timeout: int) -> object:
        captured.update(params)
        return _Ok()

    monkeypatch.setattr("requests.get", _fake_get)
    FinMindProvider(token=None)._get(
        "TaiwanStockInstitutionalInvestorsBuySell", None, date(2024, 1, 2), date(2024, 1, 2)
    )
    assert "data_id" not in captured  # bulk shape: omitted entirely, not sent as "None"


def test_shareholding_and_margin_pick_the_right_columns() -> None:
    hold = _normalize_shareholding(_HOLD_ROWS)
    assert list(hold.columns) == ["date", "foreign_hold_ratio"]
    assert hold[hold["date"] == pd.Timestamp("2024-01-02")]["foreign_hold_ratio"].iloc[0] == 73.08
    margin = _normalize_margin(_MARGIN_ROWS)
    assert list(margin.columns) == ["date", "margin_balance", "margin_short_balance"]
    d3 = margin[margin["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert d3["margin_balance"] == 13785.0
    assert d3["margin_short_balance"] == 85.0


# --- roadmap 17.1: sell-side chip data (借券/融券) -----------------------------


def test_lending_normalizes_share_denominated_balance() -> None:
    df = _normalize_lending(_LENDING_ROWS, _TW)
    assert list(df.columns) == [
        "symbol",
        "date",
        "sbl_short_balance",
        "currency",
        "provider",
        "fetched_at",
    ]
    assert df["symbol"].unique().tolist() == ["2330.TW"]
    assert df["date"].is_monotonic_increasing
    d3 = df[df["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert d3["sbl_short_balance"] == 11159514.0


def test_lending_normalizer_empty() -> None:
    out = _normalize_lending([], _TW)
    assert out.empty
    assert list(out.columns) == [
        "symbol",
        "date",
        "sbl_short_balance",
        "currency",
        "provider",
        "fetched_at",
    ]


def test_merge_chips_outer_joins_and_stamps() -> None:
    df = _merge_chips(
        _normalize_institutional(_INST_ROWS),
        _normalize_shareholding(_HOLD_ROWS),
        _normalize_margin(_MARGIN_ROWS),
        _TW,
    )
    assert df["symbol"].unique().tolist() == ["2330.TW"]
    assert df["currency"].unique().tolist() == ["TWD"]
    assert df["provider"].unique().tolist() == ["finmind"]
    # 2024-01-04 exists in shareholding only → outer-joined, other streams NaN.
    d4 = df[df["date"] == pd.Timestamp("2024-01-04")].iloc[0]
    assert d4["foreign_hold_ratio"] == 73.05
    assert pd.isna(d4["foreign_net_shares"]) and pd.isna(d4["margin_balance"])
    assert pd.isna(d4["margin_short_balance"])
    d3 = df[df["date"] == pd.Timestamp("2024-01-03")].iloc[0]
    assert d3["margin_short_balance"] == 85.0  # carried through the merge (roadmap 17.1)


def test_chip_normalizers_empty() -> None:
    assert _normalize_institutional([]).empty
    assert _normalize_shareholding([]).empty
    assert _normalize_margin([]).empty
    assert _normalize_lending([], _TW).empty
    assert _merge_chips(
        _normalize_institutional([]), _normalize_shareholding([]), _normalize_margin([]), _TW
    ).empty
