"""Point-in-time correctness of the snapshot — the Phase 1 look-ahead guard.

A value must only be 'known' on/after its filing date, and 'latest' means the
most recently *ended* fiscal period (not the last row of a multi-year filing).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.factors.metrics import (
    _latest_annual,
    _revenue_growth_yoy,
    revenue_momentum_features,
    snapshot_row,
)
from heimdall.screener.snapshot import (
    build_row,
    build_snapshot_iter,
    load_snapshot,
    split_by_region,
)


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


def test_build_snapshot_iter_resumes_and_checkpoints(tmp_path: Path) -> None:
    prices, nofund = _Prices(_ohlcv()), _NoFundamentals()  # price-only rows
    syms = ["A.US", "B.US", "C.US"]

    seen = (-1, -1, -1, False)
    for p in build_snapshot_iter(
        syms, prices, nofund, date(2024, 4, 1), resume=False, checkpoint_every=2, root=tmp_path
    ):
        seen = (p.total, p.done, p.built, p.finished)
    assert seen == (3, 3, 3, True)
    assert sorted(load_snapshot(tmp_path)["symbol"].tolist()) == ["A.US", "B.US", "C.US"]

    # Resume keeps existing rows and fetches only the not-yet-built symbol.
    plan_total, last_built = -1, -1
    for i, p in enumerate(
        build_snapshot_iter([*syms, "D.US"], prices, nofund, date(2024, 4, 1), root=tmp_path)
    ):
        if i == 0:
            plan_total = p.total  # initial plan, before any fetch
        last_built = p.built
    assert plan_total == 1 and last_built == 1
    assert sorted(load_snapshot(tmp_path)["symbol"].tolist()) == ["A.US", "B.US", "C.US", "D.US"]


def test_build_snapshot_iter_tallies_failures(tmp_path: Path) -> None:
    class _Flaky(DataProvider):
        def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
            if symbol == "BAD.US":
                raise ProviderError("boom")  # one symbol blows up mid-crawl
            return _ohlcv()

    failures: dict[str, int] = {}
    built = -1
    for p in build_snapshot_iter(
        ["A.US", "BAD.US"], _Flaky(), _NoFundamentals(), date(2024, 4, 1), root=tmp_path
    ):
        failures, built = p.failures, p.built
    assert built == 1  # A.US built; BAD.US tallied, not fatal
    assert failures == {"ProviderError": 1}


# --- roadmap 7.1: liquidity + skip-month momentum + realized vol -------------


def _empty_fund() -> pd.DataFrame:
    return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)


def _ohlcv_series(close: list[float], volume: list[float] | None = None) -> pd.DataFrame:
    """Canonical OHLCV from explicit close/volume paths (adj_close mirrors close)."""
    n = len(close)
    c = pd.Series(close, dtype=float)
    v = pd.Series(volume if volume is not None else [1_000_000.0] * n, dtype=float)
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "date": pd.bdate_range("2023-01-02", periods=n),
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "adj_close": c,
            "volume": v,
            "currency": "USD",
            "provider": "test",
            "fetched_at": pd.Timestamp("2024-04-01"),
        }
    )[OHLCV_COLUMNS]


def test_dollar_vol_21d_uses_last_21_bars_median() -> None:
    # 21 tiny-volume bars then 21 bars at close 10 × volume 1000 = 10,000 traded value;
    # a full-history median would be dragged down — only the last 21 bars may count.
    close = [10.0] * 42
    volume = [0.1] * 21 + [1000.0] * 21
    m = snapshot_row("X.US", _ohlcv_series(close, volume), _empty_fund(), date(2024, 6, 1))
    assert m["dollar_vol_21d"] == pytest.approx(10_000.0)


def test_dollar_vol_21d_nan_on_short_history() -> None:
    m = snapshot_row("X.US", _ohlcv_series([10.0] * 20), _empty_fund(), date(2024, 6, 1))
    assert pd.isna(m["dollar_vol_21d"])


def test_ret_12_1_skips_the_last_month() -> None:
    # 252 bars at 100; the bar 21-back is 150; the FINAL bar spikes to 999 and must not
    # matter — skip-month momentum reads t−12m → t−1m, ignoring the most recent month.
    close = [100.0] * 252
    close[-21] = 150.0
    close[-1] = 999.0
    m = snapshot_row("X.US", _ohlcv_series(close), _empty_fund(), date(2024, 6, 1))
    assert m["ret_12_1"] == pytest.approx(0.5)  # 150 / 100 − 1
    short = snapshot_row("X.US", _ohlcv_series(close[:251]), _empty_fund(), date(2024, 6, 1))
    assert pd.isna(short["ret_12_1"])


def test_vol_63d_windowed_and_annualized() -> None:
    # Wild head, then 64 bars of exact 1% growth: the last 63 daily returns are constant,
    # so annualized realized vol is 0 — proving only the trailing window is used.
    head = [100.0, 200.0, 50.0, 400.0] * 10
    tail = [100.0 * 1.01**k for k in range(64)]
    m = snapshot_row("X.US", _ohlcv_series(head + tail), _empty_fund(), date(2024, 6, 1))
    assert m["vol_63d"] == pytest.approx(0.0, abs=1e-9)
    short = snapshot_row("X.US", _ohlcv_series([100.0] * 60), _empty_fund(), date(2024, 6, 1))
    assert pd.isna(short["vol_63d"])


# --- fix: TW monthly-revenue momentum wired into the LIVE snapshot -----------
# 11.2 added revenue_momentum_features only to the offline research panel
# (research.dataset) — the live snapshot (screener.snapshot -> Today's Picks)
# never computed it, so a certified tw-revenue-momentum spec could never rank a
# real pick no matter how often the snapshot was rebuilt. Fixed by moving the
# math to factors.metrics (one shared home) and threading it through
# snapshot_row / build_row / build_snapshot_iter, exactly as 11.2 did for the
# research panel.


def _rev_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    months = pd.to_datetime([m for m, _ in rows])
    return pd.DataFrame(
        {
            "symbol": "AAA.TW",
            "month": months,
            "filed_at": months + pd.DateOffset(months=1, days=9),  # §36: 10th of next month
            "revenue": [r for _, r in rows],
            "currency": "TWD",
            "provider": "finmind",
            "fetched_at": pd.Timestamp("2024-08-01"),
        }
    )


_REV_SERIES: list[tuple[str, float]] = (
    [(f"2023-{m:02d}-01", 100.0) for m in range(1, 13)]
    + [(f"2024-{m:02d}-01", 110.0) for m in range(1, 6)]
    + [("2024-06-01", 150.0)]
)


def test_revenue_momentum_features_known_answer_and_pit_flip() -> None:
    rev = _rev_frame(_REV_SERIES)
    # 2024-07-05: June (filed 7/10) is NOT yet knowable → latest known is May.
    before = revenue_momentum_features(rev, pd.Timestamp("2024-07-05"))
    assert before["rev_mom_yoy"] == pytest.approx(0.10)  # May 110 / 100 − 1
    # 2024-07-10: June becomes knowable → the feature flips to June's YoY.
    after = revenue_momentum_features(rev, pd.Timestamp("2024-07-10"))
    assert after["rev_mom_yoy"] == pytest.approx(0.50)  # June 150 / 100 − 1
    # accel = mean(Apr,May,Jun YoY) − mean(Jan,Feb,Mar YoY) = .2333 − .10
    assert after["rev_mom_accel"] == pytest.approx((0.10 + 0.10 + 0.50) / 3 - 0.10)


def test_revenue_momentum_features_guards() -> None:
    late = pd.Timestamp("2025-01-15")
    short = _rev_frame([(f"2024-{m:02d}-01", 100.0) for m in range(1, 11)])
    out = revenue_momentum_features(short, late)
    assert pd.isna(out["rev_mom_yoy"]) and pd.isna(out["rev_mom_accel"])
    zero_base = _rev_frame([("2023-06-01", 0.0), ("2024-06-01", 150.0)])
    assert pd.isna(revenue_momentum_features(zero_base, late)["rev_mom_yoy"])
    gapped = _rev_frame([r for r in _REV_SERIES if r[0] != "2024-03-01"])
    out = revenue_momentum_features(gapped, late)
    assert out["rev_mom_yoy"] == pytest.approx(0.50)  # June itself is fine
    assert pd.isna(out["rev_mom_accel"])  # prior-3 window spans the hole
    empty = revenue_momentum_features(pd.DataFrame(), late)
    assert pd.isna(empty["rev_mom_yoy"]) and pd.isna(empty["rev_mom_accel"])


def test_snapshot_row_merges_revenue_momentum_when_monthly_given() -> None:
    # Known-answer + PIT flip through the ACTUAL live-snapshot entry point (not
    # the pure function directly) — proves the as_of wiring, not just the math.
    rev = _rev_frame(_REV_SERIES)
    row = snapshot_row(
        "2330.TW", _ohlcv_at(40.0, n=260), _empty_fund(), date(2024, 7, 5), monthly=rev
    )
    assert row["rev_mom_yoy"] == pytest.approx(0.10)  # June not yet filed on 7/5
    row2 = snapshot_row(
        "2330.TW", _ohlcv_at(40.0, n=260), _empty_fund(), date(2024, 7, 10), monthly=rev
    )
    assert row2["rev_mom_yoy"] == pytest.approx(0.50)  # …filed by 7/10


def test_snapshot_row_omits_revenue_momentum_without_monthly() -> None:
    # Default (no `monthly`): the keys are ABSENT, not NaN — matches the research
    # panel's "US carries no rev_mom_* column at all" contract (test_research_dataset).
    row = snapshot_row("X.US", _ohlcv_at(40.0), _empty_fund(), date(2024, 6, 1))
    assert "rev_mom_yoy" not in row and "rev_mom_accel" not in row


class _RevenueProvider:
    """A ``monthly_revenue``-shaped callable: real data for TW, NotSupported for US."""

    def __init__(self, rev: pd.DataFrame) -> None:
        self._rev = rev
        self.calls: list[str] = []

    def __call__(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.calls.append(symbol)
        if not symbol.endswith(".TW"):
            raise NotSupported(f"no monthly revenue for {symbol}")
        return self._rev


def test_build_row_wires_revenue_momentum_for_tw() -> None:
    fn = _RevenueProvider(_rev_frame(_REV_SERIES))
    row = build_row(
        "2330.TW", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 7, 10), monthly_revenue=fn
    )
    assert row is not None
    assert row["rev_mom_yoy"] == pytest.approx(0.50)
    assert fn.calls == ["2330.TW"]


def test_build_row_gives_nan_not_omission_for_us_when_callable_provided() -> None:
    # A mixed-market build (--market all, or pasted mixed symbols) must produce ONE
    # consistent schema: the columns exist for every row, NaN where inapplicable —
    # never present-for-some-rows/absent-for-others in the same table.
    fn = _RevenueProvider(_rev_frame(_REV_SERIES))
    row = build_row(
        "X.US", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 7, 10), monthly_revenue=fn
    )
    assert row is not None
    assert "rev_mom_yoy" in row and pd.isna(row["rev_mom_yoy"])
    assert fn.calls == ["X.US"]  # attempted, not skipped — NotSupported is caught, not guessed


def test_build_row_without_monthly_revenue_omits_columns_entirely() -> None:
    # The default (no callable passed at all): unchanged pre-fix behavior.
    row = build_row("2330.TW", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 7, 10))
    assert row is not None
    assert "rev_mom_yoy" not in row


def test_build_snapshot_iter_mixed_market_gets_one_consistent_schema(tmp_path: Path) -> None:
    fn = _RevenueProvider(_rev_frame(_REV_SERIES))
    prices = _Prices(_ohlcv())
    for _ in build_snapshot_iter(
        ["2330.TW", "X.US"],
        prices,
        _NoFundamentals(),
        date(2024, 7, 10),
        root=tmp_path,
        monthly_revenue=fn,
    ):
        pass
    snap = load_snapshot(tmp_path).set_index("symbol")
    assert "rev_mom_yoy" in snap.columns  # present for BOTH rows of the one table
    assert snap.loc["2330.TW", "rev_mom_yoy"] == pytest.approx(0.50)
    assert pd.isna(snap.loc["X.US", "rev_mom_yoy"])


# --- roadmap 14.1: sector_map threading (the monthly_revenue opt-in precedent) ----


def test_build_row_with_sector_map_labels_known_symbol() -> None:
    row = build_row(
        "X.US",
        _Prices(_ohlcv()),
        _NoFundamentals(),
        date(2024, 4, 1),
        sector_map={"X.US": "Manufacturing"},
    )
    assert row is not None
    assert row["sector"] == "Manufacturing"


def test_build_row_sector_map_unknown_for_missing_symbol() -> None:
    # The map was given (opt-in) but doesn't cover this symbol — "Unknown", not omitted.
    row = build_row("X.US", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 4, 1), sector_map={})
    assert row is not None
    assert row["sector"] == "Unknown"


def test_build_row_without_sector_map_omits_column_entirely() -> None:
    # No sector_map argument at all: unchanged pre-14.1 behavior (existing callers).
    row = build_row("X.US", _Prices(_ohlcv()), _NoFundamentals(), date(2024, 4, 1))
    assert row is not None
    assert "sector" not in row


def test_build_snapshot_iter_mixed_symbols_sector_consistent_schema(tmp_path: Path) -> None:
    prices = _Prices(_ohlcv())
    for _ in build_snapshot_iter(
        ["2330.TW", "X.US"],
        prices,
        _NoFundamentals(),
        date(2024, 4, 1),
        root=tmp_path,
        sector_map={"2330.TW": "半導體業"},  # X.US deliberately absent from the map
    ):
        pass
    snap = load_snapshot(tmp_path).set_index("symbol")
    assert "sector" in snap.columns  # present for BOTH rows of the one table
    assert snap.loc["2330.TW", "sector"] == "半導體業"
    assert snap.loc["X.US", "sector"] == "Unknown"  # missing from the map, never dropped
