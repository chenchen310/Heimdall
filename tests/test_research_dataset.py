"""Research dataset (roadmap 7.3) — the persisted labelled panel.

The load-bearing test is the **PIT leak test**: a fundamental filed after
month-end *t* must be invisible in row *t*. Every downstream number (IC, beat
rates, certification gates) inherits its honesty from this file. The resume
test pins the other institution: features are frozen at first write (vendor
restatements must not rewrite history), while still-NaN labels are refreshed.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.research import gates
from heimdall.research.dataset import (
    DatasetProgress,
    build_dataset_iter,
    load_panel,
    meta_path,
)


def _ohlcv_geo(
    symbol: str,
    n: int,
    daily: float,
    s0: float = 100.0,
    volume: float = 1_000_000.0,
    start: str = "2022-01-03",
) -> pd.DataFrame:
    """Geometric price path (close == adj_close) on business days."""
    c = pd.Series([s0 * (1.0 + daily) ** k for k in range(n)], dtype=float)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.bdate_range(start, periods=n),
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "adj_close": c,
            "volume": float(volume),
            "currency": "USD",
            "provider": "test",
            "fetched_at": pd.Timestamp("2024-01-01"),
        }
    )[OHLCV_COLUMNS]


class _Prices(DataProvider):
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        df = self._frames.get(symbol)
        if df is None:
            raise ProviderError(f"no prices for {symbol}")
        return df


class _Funds(DataProvider):
    def __init__(self, frames: dict[str, pd.DataFrame] | None = None) -> None:
        self._frames = frames or {}

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotSupported("prices not served here")

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        return self._frames.get(symbol, pd.DataFrame(columns=FUNDAMENTALS_COLUMNS))


def _fund_row(
    symbol: str, metric: str, fiscal_end: str, filed_at: str, value: float
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "metric": metric,
        "statement": "income",
        "period": "annual",
        "fiscal_end": pd.Timestamp(fiscal_end),
        "filed_at": pd.Timestamp(filed_at),
        "value": float(value),
        "currency": "USD",
        "provider": "test",
        "fetched_at": pd.Timestamp("2024-01-01"),
    }


def _drive(it: Iterator[DatasetProgress]) -> DatasetProgress:
    prog = next(it)  # the plan (total_months is fixed from here on)
    for prog in it:  # noqa: B007 — the same instance is mutated and re-yielded
        pass
    return prog


def _spy_and_x(n: int = 500) -> dict[str, pd.DataFrame]:
    return {"SPY.US": _ohlcv_geo("SPY.US", n, 0.0005), "X.US": _ohlcv_geo("X.US", n, 0.001)}


def test_pit_fundamental_never_leaks(tmp_path: Path) -> None:
    # Revenue filed 2023-08-15: the July row must not see it; the August row must.
    funds = _Funds(
        {"X.US": pd.DataFrame([_fund_row("X.US", "revenue", "2022-12-31", "2023-08-15", 123.0)])}
    )
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(_spy_and_x()),
            funds,
            "US",
            date(2023, 6, 1),
            date(2023, 9, 30),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    panel = load_panel("US", tmp_path)
    july = panel[panel["date"] == pd.Timestamp("2023-07-31")].iloc[0]
    august = panel[panel["date"] == pd.Timestamp("2023-08-31")].iloc[0]
    assert pd.isna(july["revenue"])  # filed after month-end t ⇒ invisible at t
    assert august["revenue"] == 123.0  # visible once filed


def test_labels_known_answer_and_rel_sign(tmp_path: Path) -> None:
    gs, gb = 0.001, 0.0005  # stock compounds faster than the benchmark
    frames = _spy_and_x()
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(frames),
            _Funds(),
            "US",
            date(2023, 1, 1),
            date(2023, 6, 30),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    panel = load_panel("US", tmp_path).sort_values("date")
    months = sorted(panel["date"].unique())
    t0, t1 = pd.Timestamp(months[0]), pd.Timestamp(months[1])
    cal = frames["X.US"]["date"]
    n1 = int(cal.searchsorted(t1) - cal.searchsorted(t0))  # bars to the next rebalance
    row = panel[panel["date"] == t0].iloc[0]
    assert row["fwd_1m"] == pytest.approx((1 + gs) ** n1 - 1)
    assert row["fwd_3m"] == pytest.approx((1 + gs) ** 63 - 1)
    assert row["fwd_6m"] == pytest.approx((1 + gs) ** 126 - 1)
    assert row["fwd_3m_rel"] == pytest.approx(((1 + gs) ** 63) - ((1 + gb) ** 63))
    assert row["fwd_3m_rel"] > 0  # faster grower beats the benchmark


def test_incomplete_forward_window_is_nan(tmp_path: Path) -> None:
    # Data ends a few bars after the last rebalance: its labels must be NaN, never partial.
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(_spy_and_x(n=460)),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 9, 30),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    panel = load_panel("US", tmp_path)
    last = panel[panel["date"] == panel["date"].max()].iloc[0]
    assert pd.isna(last["fwd_1m"]) and pd.isna(last["fwd_3m"]) and pd.isna(last["fwd_6m"])
    first = panel[panel["date"] == panel["date"].min()].iloc[0]
    assert pd.notna(first["fwd_1m"]) and pd.notna(first["fwd_3m"])
    assert pd.isna(first["fwd_6m"])  # +126 bars still runs past the data


def test_eligibility_flags_with_reasons(tmp_path: Path) -> None:
    frames = {
        "SPY.US": _ohlcv_geo("SPY.US", 500, 0.0005),
        "OK.US": _ohlcv_geo("OK.US", 500, 0.0),  # eligible
        "LOWP.US": _ohlcv_geo("LOWP.US", 500, 0.0, s0=1.0),  # $1 < $2 floor
        "THIN.US": _ohlcv_geo("THIN.US", 500, 0.0, volume=100.0),  # $10k/day traded
        "NEW.US": _ohlcv_geo("NEW.US", 120, 0.0, start="2023-03-01"),  # < 252 bars
    }
    _drive(
        build_dataset_iter(
            ["OK.US", "LOWP.US", "THIN.US", "NEW.US"],
            _Prices(frames),
            _Funds(),
            "US",
            date(2023, 7, 1),
            date(2023, 8, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    month = load_panel("US", tmp_path)
    month = month[month["date"] == pd.Timestamp("2023-07-31")].set_index("symbol")
    assert bool(month.loc["OK.US", "eligible"]) is True
    assert month.loc["OK.US", "inelig_reason"] == ""
    assert month.loc["LOWP.US", "inelig_reason"] == "price"
    assert month.loc["THIN.US", "inelig_reason"] == "liquidity"
    assert month.loc["NEW.US", "inelig_reason"] == "history"
    assert len(month) == 4  # ineligible rows are flagged, never dropped


def test_thin_months_dropped_reported_and_skipped_on_resume(tmp_path: Path) -> None:
    args = (
        ["X.US"],
        _Prices(_spy_and_x()),
        _Funds(),
        "US",
        date(2023, 6, 1),
        date(2023, 8, 31),
    )
    prog = _drive(build_dataset_iter(*args, root=tmp_path, min_cross_section=2))
    assert len(prog.dropped) == 3  # one eligible name < floor of 2, every month
    with pytest.raises(FileNotFoundError):
        load_panel("US", tmp_path)  # nothing silently kept
    meta = json.loads(meta_path("US", tmp_path).read_text())
    assert meta["dropped_months"] == prog.dropped  # dropped and *reported*
    prog2 = _drive(build_dataset_iter(*args, root=tmp_path, min_cross_section=2))
    assert prog2.total_months == 0  # dropped months aren't rebuilt forever


def test_resume_skips_freezes_features_and_refreshes_labels(tmp_path: Path) -> None:
    full = {"SPY.US": _ohlcv_geo("SPY.US", 650, 0.0005), "X.US": _ohlcv_geo("X.US", 650, 0.001)}
    short = {sym: df.iloc[:420] for sym, df in full.items()}
    filed = _fund_row("X.US", "revenue", "2022-12-31", "2023-02-15", 123.0)

    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(short),
            _Funds({"X.US": pd.DataFrame([filed])}),
            "US",
            date(2023, 3, 1),
            date(2023, 7, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    before = load_panel("US", tmp_path)
    t_last = before["date"].max()
    assert pd.isna(before.loc[before["date"] == t_last, "fwd_6m"].iloc[0])

    # Run 2: longer history AND a restated value (999). History must keep 123 —
    # features are frozen at first write; only the missing labels get filled.
    restated = dict(filed, value=999.0)
    prog2 = _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(full),
            _Funds({"X.US": pd.DataFrame([restated])}),
            "US",
            date(2023, 3, 1),
            date(2023, 10, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    after = load_panel("US", tmp_path)
    assert prog2.total_months == 3  # Aug–Oct only; Mar–Jul were skipped
    old = after[after["date"] == t_last].iloc[0]
    assert old["revenue"] == 123.0  # the restatement did NOT rewrite history
    assert pd.notna(old["fwd_6m"])  # the completed window DID get filled
    assert prog2.relabeled > 0
    assert (after.loc[after["date"] > t_last, "revenue"] == 999.0).all()


def test_meta_sidecar_contents(tmp_path: Path) -> None:
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(_spy_and_x()),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 8, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    meta = json.loads(meta_path("US", tmp_path).read_text())
    assert meta["survivorship"] == "current_universe (optimistic)"  # the honesty stamp
    assert meta["market"] == "US" and meta["universe_size"] == 1
    assert len(meta["months"]) == 3
    assert set(meta["eligible_per_month"]) == set(meta["months"])


# --- roadmap 11.2: TW monthly-revenue momentum, panel integration -------------
# The pure-function tests for revenue_momentum_features itself live in
# tests/test_snapshot.py (it moved to factors.metrics, shared with the live
# snapshot); these test build_dataset_iter's wiring of the injected stream.


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


def test_panel_carries_pit_revenue_features_for_tw(tmp_path: Path) -> None:
    frames = {
        "0050.TW": _ohlcv_geo("0050.TW", 700, 0.0005),
        "AAA.TW": _ohlcv_geo("AAA.TW", 700, 0.0),  # NT$100, NT$100M/day → eligible
    }
    rev = _rev_frame(_REV_SERIES)
    _drive(
        build_dataset_iter(
            ["AAA.TW"],
            _Prices(frames),
            _Funds(),
            "Taiwan",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            monthly_revenue=lambda sym, s, e: rev,
        )
    )
    panel = load_panel("Taiwan", tmp_path).set_index("date")
    june, july = panel.loc[pd.Timestamp("2024-06-28")], panel.loc[pd.Timestamp("2024-07-31")]
    assert june["rev_mom_yoy"] == pytest.approx(0.10)  # June's 150 not filed until 7/10
    assert july["rev_mom_yoy"] == pytest.approx(0.50)  # …then it is
    assert july["rev_mom_accel"] == pytest.approx((0.10 + 0.10 + 0.50) / 3 - 0.10)
    assert pd.isna(june["rev_mom_accel"])  # Dec-2023 YoY has no 2022 base → window poisoned


def test_us_panel_has_no_revenue_columns_without_the_stream(tmp_path: Path) -> None:
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(_spy_and_x()),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 7, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    assert "rev_mom_yoy" not in load_panel("US", tmp_path).columns


# --- roadmap 11.3: TW chip/flow features (+1 trading-day PIT shift) -----------


def _chips_frame(
    dates: pd.DatetimeIndex,
    foreign: list[float],
    trust: list[float],
    hold: list[float],
    margin: list[float],
    margin_short: list[float] | None = None,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "AAA.TW",
            "date": dates,
            "foreign_net_shares": foreign,
            "trust_net_shares": trust,
            "foreign_hold_ratio": hold,
            "margin_balance": margin,
            "margin_short_balance": margin_short
            if margin_short is not None
            else [float("nan")] * len(dates),
            "currency": "TWD",
            "provider": "finmind",
            "fetched_at": pd.Timestamp("2024-05-01"),
        }
    )


def _lending_frame(dates: pd.DatetimeIndex, sbl: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "AAA.TW",
            "date": dates,
            "sbl_short_balance": sbl,
            "currency": "TWD",
            "provider": "finmind",
            "fetched_at": pd.Timestamp("2024-05-01"),
        }
    )


def _flat_price(
    dates: pd.DatetimeIndex, close: float = 100.0, volume: float = 1_000_000.0
) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "close": close, "volume": volume})


def test_flow_features_known_answer_and_shift() -> None:
    from heimdall.research.dataset import _flow_features

    n = 80
    dates = pd.bdate_range("2024-01-01", periods=n)
    k, tk, v, c = 100_000.0, 40_000.0, 1_000_000.0, 100.0
    # The final row is dated as_of itself: it must be EXCLUDED (the +1-day shift).
    # Absurd spikes there prove a leak would be caught, not silently absorbed.
    chips = _chips_frame(
        dates,
        foreign=[k] * (n - 1) + [9e12],
        trust=[tk] * (n - 1) + [9e12],
        hold=[20.0 + 0.01 * i for i in range(n - 1)] + [9999.0],
        margin=[10_000.0 * 1.001**i for i in range(n - 1)] + [9e12],
        margin_short=[5_000.0 * 1.002**i for i in range(n - 1)] + [9e12],
    )
    out = _flow_features(chips, _flat_price(dates, c, v), dates[-1])
    # Σ(net shares × close) over the window ÷ its median dollar volume = n_window × k / v.
    assert out["foreign_net_buy_21d"] == pytest.approx(21 * k / v)
    assert out["foreign_net_buy_63d"] == pytest.approx(63 * k / v)
    assert out["trust_net_buy_21d"] == pytest.approx(21 * tk / v)
    # ratio ramps 0.01pp/day → 63-day pp change = 0.63; margin +0.1%/day → 1.001**21 − 1.
    assert out["foreign_hold_delta_63d"] == pytest.approx(0.63)
    assert out["margin_delta_21d"] == pytest.approx(1.001**21 - 1)
    # margin_short_delta_21d (roadmap 17.1): +0.2%/day → 1.002**21 − 1.
    assert out["margin_short_delta_21d"] == pytest.approx(1.002**21 - 1)


def test_flow_features_guards() -> None:
    from heimdall.research.dataset import _flow_features

    at = pd.Timestamp("2024-06-01")
    empty = _flow_features(pd.DataFrame(), _flat_price(pd.bdate_range("2024-01-01", periods=1)), at)
    assert all(pd.isna(x) for x in empty.values())

    # Only 10 usable days (the 11th is the excluded as_of row): every window is short → NaN.
    dates = pd.bdate_range("2024-01-01", periods=11)
    chips = _chips_frame(dates, [1.0] * 11, [1.0] * 11, [20.0] * 11, [100.0] * 11)
    short = _flow_features(chips, _flat_price(dates), dates[-1])
    assert all(pd.isna(x) for x in short.values())

    # A single gap slides the window (uses the last 21 *available* rows), not NaN,
    # as long as enough observations remain — daily gaps are noise, not a leak.
    dates = pd.bdate_range("2024-01-01", periods=30)
    foreign = [1.0] * 30
    foreign[10] = float("nan")  # a hole; 28 usable rows remain ≥ 21
    chips = _chips_frame(dates, foreign, [1.0] * 30, [20.0] * 30, [100.0] * 30)
    slid = _flow_features(chips, _flat_price(dates), dates[-1])
    assert slid["foreign_net_buy_21d"] == pytest.approx(21 * 1.0 / 1_000_000.0)
    # …but too few available rows → NaN (fewer than 21 non-NaN in the window).
    foreign = [float("nan")] * 15 + [1.0] * 15
    chips = _chips_frame(dates, foreign, [1.0] * 30, [20.0] * 30, [100.0] * 30)
    thin = _flow_features(chips, _flat_price(dates), dates[-1])
    assert pd.isna(thin["foreign_net_buy_21d"])

    # Zero dollar volume → no division by zero, just NaN.
    dates = pd.bdate_range("2024-01-01", periods=30)
    chips = _chips_frame(dates, [1.0] * 30, [1.0] * 30, [20.0] * 30, [100.0] * 30)
    zero_vol = _flow_features(chips, _flat_price(dates, volume=0.0), dates[-1])
    assert pd.isna(zero_vol["foreign_net_buy_21d"])


def test_lending_features_known_answer_and_shift() -> None:
    """roadmap 17.1: sell-side (借券賣出) short-balance delta features."""
    from heimdall.research.dataset import _lending_features

    n = 80
    dates = pd.bdate_range("2024-01-01", periods=n)
    base, step, v = 1_000_000.0, 5_000.0, 1_000_000.0
    # An ARITHMETIC ramp: the delta over any window of length w is exactly step*w,
    # regardless of where the window sits — makes the hand answer exact. The final
    # row is dated as_of itself: it must be EXCLUDED (the +1-day shift) — an absurd
    # spike there proves a leak would be caught, not silently absorbed.
    sbl = [base + step * i for i in range(n - 1)] + [9e12]
    lending = _lending_frame(dates, sbl)
    out = _lending_features(lending, _flat_price(dates), dates[-1])
    # Δ(sbl) × close ÷ median(close×volume) — with flat price this simplifies to
    # Δ(sbl) / volume (the close cancels, exactly like `_net_buy`'s flat-price case).
    assert out["sbl_short_delta_21d"] == pytest.approx(21 * step / v)
    assert out["sbl_short_delta_63d"] == pytest.approx(63 * step / v)


def test_lending_features_guards() -> None:
    from heimdall.research.dataset import _lending_features

    at = pd.Timestamp("2024-06-01")
    empty = _lending_features(
        pd.DataFrame(), _flat_price(pd.bdate_range("2024-01-01", periods=1)), at
    )
    assert all(pd.isna(x) for x in empty.values())

    # 21 usable days (the 22nd is the excluded as_of row): the 21-day feature needs
    # n+1=22 usable observations to express a 21-trading-day delta → NaN.
    dates = pd.bdate_range("2024-01-01", periods=22)
    lending = _lending_frame(dates, [1_000_000.0 + 1_000.0 * i for i in range(22)])
    short = _lending_features(lending, _flat_price(dates), dates[-1])
    assert pd.isna(short["sbl_short_delta_21d"])

    # 22 usable days (23rd excluded) is exactly enough → not NaN.
    dates = pd.bdate_range("2024-01-01", periods=23)
    lending = _lending_frame(dates, [1_000_000.0 + 1_000.0 * i for i in range(23)])
    enough = _lending_features(lending, _flat_price(dates), dates[-1])
    assert not pd.isna(enough["sbl_short_delta_21d"])

    # Zero dollar volume → no division by zero, just NaN.
    zero_vol = _lending_features(lending, _flat_price(dates, volume=0.0), dates[-1])
    assert pd.isna(zero_vol["sbl_short_delta_21d"])


def _insider_row(
    filed_at: str,
    code: str,
    shares: float,
    price: float,
    owner: str,
    *,
    officer: bool = True,
    director: bool = False,
    ten_pct: bool = False,
) -> dict[str, object]:
    """One canonical Form 4 transaction row (roadmap 12.4/13.3 shape)."""
    return {
        "symbol": "X.US",
        "filed_at": pd.Timestamp(filed_at),
        "txn_date": pd.Timestamp(filed_at) - pd.Timedelta(days=2),
        "owner_cik": owner,
        "owner_name": owner,
        "is_officer": officer,
        "is_director": director,
        "is_ten_pct": ten_pct,
        "txn_code": code,
        "acquired_disposed": "A" if code == "P" else "D",
        "shares": float(shares),
        "price_per_share": float(price),
        "currency": "USD",
        "provider": "form4",
        "fetched_at": pd.Timestamp("2024-07-01"),
    }


def test_insider_features_known_answer_pit_and_role_filter() -> None:
    from heimdall.research.dataset import _insider_features

    as_of = pd.Timestamp("2024-06-28")  # window = (2024-03-30, 2024-06-28]
    frame = pd.DataFrame(
        [
            _insider_row("2024-04-01", "P", 100, 10.0, "A"),  # +$1000
            _insider_row("2024-05-01", "P", 100, 10.0, "B"),  # +$1000
            _insider_row("2024-06-01", "P", 100, 10.0, "C", officer=False, director=True),  # +$1000
            _insider_row("2024-06-10", "S", 50, 10.0, "A"),  # −$500
            # A 10%-owner-only buy: excluded (not an officer/director).
            _insider_row("2024-06-20", "P", 1000, 10.0, "E", officer=False, ten_pct=True),
            # PIT leak: filed AFTER as_of — must not move the row.
            _insider_row("2024-07-15", "P", 100_000, 10.0, "F"),
            # Before the 90-day window opens — excluded.
            _insider_row("2024-01-01", "P", 100_000, 10.0, "G"),
        ]
    )
    out = _insider_features(frame, as_of, market_cap=1_000_000.0)
    assert out["insider_net_buy_90d"] == pytest.approx((3000.0 - 500.0) / 1_000_000.0)
    assert out["insider_cluster_buy"] == 1.0  # A, B, C = 3 distinct officer/director buyers


def test_insider_features_guards() -> None:
    from heimdall.research.dataset import _insider_features

    at = pd.Timestamp("2024-06-28")
    # Empty stream (no data at all) → both NaN, so the column is genuinely absent.
    empty = _insider_features(pd.DataFrame(), at, market_cap=1_000_000.0)
    assert pd.isna(empty["insider_net_buy_90d"]) and pd.isna(empty["insider_cluster_buy"])

    # Populated stream but no open-market trade in the window → a real 0, not NaN.
    quiet = pd.DataFrame([_insider_row("2024-06-01", "M", 100, 10.0, "A")])  # option exercise
    q = _insider_features(quiet, at, market_cap=1_000_000.0)
    assert q["insider_net_buy_90d"] == 0.0 and q["insider_cluster_buy"] == 0.0

    # Two buyers < the 3-buyer cluster threshold.
    two = pd.DataFrame(
        [
            _insider_row("2024-06-01", "P", 100, 10.0, "A"),
            _insider_row("2024-06-02", "P", 1, 1.0, "B"),
        ]
    )
    assert _insider_features(two, at, market_cap=1_000_000.0)["insider_cluster_buy"] == 0.0

    # Unusable market-cap denominator → net NaN, but the cluster flag still computes.
    bad = _insider_features(two, at, market_cap=float("nan"))
    assert pd.isna(bad["insider_net_buy_90d"]) and bad["insider_cluster_buy"] == 0.0


def _q_eps(fiscal_end: str, filed_at: str, value: float) -> pd.DataFrame:
    """One quarterly ``eps_diluted`` fundamental row (13.4 PEAD input)."""
    return pd.DataFrame(
        [
            {
                "symbol": "X.US",
                "metric": "eps_diluted",
                "statement": "income",
                "period": "quarter",
                "fiscal_end": pd.Timestamp(fiscal_end),
                "filed_at": pd.Timestamp(filed_at),
                "value": float(value),
                "currency": "USD",
                "provider": "test",
                "fetched_at": pd.Timestamp("2024-01-01"),
            }
        ]
    )


_EMPTY_FUND = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)


def test_pead_sue_known_answer_seasonal_alignment_and_pit() -> None:
    from heimdall.research.dataset import _pead_features

    # 4 years × 3 discrete quarters (US files no discrete Q4). YoY of the same
    # fiscal quarter a year earlier is +1 every quarter except the final Q3 (+5),
    # so the seasonal-surprise series ends [1,1,1,1,1,1,1,5] over its last 8.
    rows = []
    base = {"03-31": 10.0, "06-30": 20.0, "09-30": 30.0}
    filed_month = {"03-31": "05-14", "06-30": "08-14", "09-30": "11-14"}
    for yr in (2019, 2020, 2021, 2022):
        for md, b in base.items():
            bump = (yr - 2019) * 1.0
            if yr == 2022 and md == "09-30":
                bump += 4.0  # the final surprise is +5 vs +1
            rows.append(_q_eps(f"{yr}-{md}", f"{yr}-{filed_month[md]}", b + bump))
    q = pd.concat(rows, ignore_index=True)
    as_of = pd.Timestamp("2022-12-31")

    out = _pead_features(_EMPTY_FUND, q, pd.DataFrame(), pd.Series(dtype=float), as_of)
    expected = 5.0 / float(np.std([1, 1, 1, 1, 1, 1, 1, 5]))
    assert out["sue"] == pytest.approx(expected)

    # PIT: a quarter filed AFTER as_of (absurd value) must not move sue.
    leaked = pd.concat([q, _q_eps("2023-03-31", "2023-05-15", 9999.0)], ignore_index=True)
    assert _pead_features(_EMPTY_FUND, leaked, pd.DataFrame(), pd.Series(dtype=float), as_of)[
        "sue"
    ] == pytest.approx(expected)

    # Fewer than 8 seasonal surprises → NaN.
    thin = pd.concat(
        [_q_eps("2021-03-31", "2021-05-14", 1.0), _q_eps("2022-03-31", "2022-05-14", 2.0)],
        ignore_index=True,
    )
    assert pd.isna(
        _pead_features(_EMPTY_FUND, thin, pd.DataFrame(), pd.Series(dtype=float), as_of)["sue"]
    )


def test_pead_earn_gap_known_answer_and_recency() -> None:
    from heimdall.research.dataset import _pead_features

    filed = pd.Timestamp("2022-11-14")
    q = _q_eps("2022-09-30", "2022-11-14", 1.0)  # latest eps filing = 2022-11-14

    dates = pd.bdate_range("2022-10-03", "2022-12-30")
    b = int(next(i for i, d in enumerate(dates) if d >= filed))
    close = pd.Series(100.0, index=range(len(dates)))
    close.iloc[b:] = 110.0  # +10% jump on the first bar ≥ the filing, then flat
    price = pd.DataFrame({"date": dates, "adj_close": close.to_numpy()})
    bench = pd.Series(50.0, index=dates)  # flat benchmark → 0 benchmark return

    out = _pead_features(_EMPTY_FUND, q, price, bench, dates[-1])
    assert out["earn_gap"] == pytest.approx(0.10)  # 110/100 − 1 − 0

    # Recency: the same filing seen from far in the future (> 65 trading bars later)
    # is stale drift → NaN, not a re-measured jump.
    far = pd.bdate_range("2022-10-03", "2023-06-30")
    fb = int(next(i for i, d in enumerate(far) if d >= filed))
    fclose = pd.Series(100.0, index=range(len(far)))
    fclose.iloc[fb:] = 110.0
    fprice = pd.DataFrame({"date": far, "adj_close": fclose.to_numpy()})
    fbench = pd.Series(50.0, index=far)
    assert pd.isna(_pead_features(_EMPTY_FUND, q, fprice, fbench, far[-1])["earn_gap"])


def test_issuance_quality_features_known_answer_and_pit() -> None:
    from heimdall.research.dataset import _issuance_quality_features

    fund = pd.DataFrame(
        [
            _fund_row("X.US", "shares_outstanding", "2021-12-31", "2022-02-01", 1000),
            _fund_row("X.US", "shares_outstanding", "2022-12-31", "2023-02-01", 1100),  # +10%
            _fund_row("X.US", "assets", "2021-12-31", "2022-02-01", 5000),
            _fund_row("X.US", "assets", "2022-12-31", "2023-02-01", 6000),  # +20%
            _fund_row("X.US", "gross_profit", "2022-12-31", "2023-02-01", 1500),  # /6000 = 0.25
        ]
    )
    as_of = pd.Timestamp("2023-06-30")
    out = _issuance_quality_features(fund, as_of)
    assert out["net_issuance_12m"] == pytest.approx(0.10)
    assert out["asset_growth"] == pytest.approx(0.20)
    assert out["gross_profitability"] == pytest.approx(0.25)

    # PIT: a later annual filed after as_of must not move the YoY figure.
    leaked = pd.DataFrame(
        [
            _fund_row("X.US", "shares_outstanding", "2021-12-31", "2022-02-01", 1000),
            _fund_row("X.US", "shares_outstanding", "2022-12-31", "2023-02-01", 1100),
            _fund_row(
                "X.US", "shares_outstanding", "2023-12-31", "2024-02-01", 5000
            ),  # after as_of
        ]
    )
    assert _issuance_quality_features(leaked, as_of)["net_issuance_12m"] == pytest.approx(0.10)

    # No GrossProfit tag → NaN (never derived from revenue − COGS).
    no_gp = pd.DataFrame([_fund_row("X.US", "assets", "2022-12-31", "2023-02-01", 6000)])
    assert pd.isna(_issuance_quality_features(no_gp, as_of)["gross_profitability"])


def _q_income(metric: str, fiscal_end: str, filed_at: str, value: float) -> dict[str, object]:
    """One quarterly income-statement fundamental row (17.4 acceleration input)."""
    return {
        "symbol": "X.US",
        "metric": metric,
        "statement": "income",
        "period": "quarter",
        "fiscal_end": pd.Timestamp(fiscal_end),
        "filed_at": pd.Timestamp(filed_at),
        "value": float(value),
        "currency": "USD",
        "provider": "test",
        "fetched_at": pd.Timestamp("2024-01-01"),
    }


def test_accel_rev_known_answer_seasonal_and_pit() -> None:
    from heimdall.research.dataset import _accel_features

    # 4 years × 3 discrete quarters (US files no discrete Q4). Revenue grows +10%
    # YoY every quarter except the final 2022-Sep (+20%), so the seasonal YoY series
    # is [.10×8, .20] and rev_accel_q = .20 − mean(.10, .10, .10, .10) = +0.10.
    rows: list[dict[str, object]] = []
    md_filed = {"03-31": "05-14", "06-30": "08-14", "09-30": "11-14"}
    level = {2019: 100.0, 2020: 110.0, 2021: 121.0, 2022: 133.1}
    for yr in (2019, 2020, 2021, 2022):
        for md, fm in md_filed.items():
            val = level[yr]
            if yr == 2022 and md == "09-30":
                val = 121.0 * 1.20  # +20% vs 2021-Sep instead of +10%
            rows.append(_q_income("revenue", f"{yr}-{md}", f"{yr}-{fm}", val))
    q = pd.DataFrame(rows)
    as_of = pd.Timestamp("2022-12-31")

    out = _accel_features(_EMPTY_FUND, q, as_of)
    assert out["rev_accel_q"] == pytest.approx(0.10)

    # PIT: a quarter filed after as_of (absurd value) must not move the acceleration.
    leaked = pd.concat(
        [q, pd.DataFrame([_q_income("revenue", "2022-12-31", "2023-02-15", 9999.0)])],
        ignore_index=True,
    )
    assert _accel_features(_EMPTY_FUND, leaked, as_of)["rev_accel_q"] == pytest.approx(0.10)

    # Fewer than 9 usable quarterly revenue observations → NaN.
    thin = pd.DataFrame(rows[:6])
    assert pd.isna(_accel_features(_EMPTY_FUND, thin, as_of)["rev_accel_q"])


def test_accel_q4_derivation_arithmetic_and_filed_at() -> None:
    from heimdall.research.dataset import _discrete_quarters

    annual = pd.DataFrame([_fund_row("X.US", "revenue", "2021-12-31", "2022-02-15", 1000.0)])
    quarter = pd.DataFrame(
        [
            _q_income("revenue", "2021-03-31", "2021-05-01", 200.0),
            _q_income("revenue", "2021-06-30", "2021-08-01", 250.0),
            _q_income("revenue", "2021-09-30", "2021-11-01", 280.0),
        ]
    )
    out = _discrete_quarters(annual, quarter, "revenue", pd.Timestamp("2022-06-30"))
    q4 = out[out["fiscal_end"] == pd.Timestamp("2021-12-31")]
    assert len(q4) == 1
    assert float(q4["value"].iloc[0]) == pytest.approx(1000.0 - (200.0 + 250.0 + 280.0))  # 270
    assert q4["filed_at"].iloc[0] == pd.Timestamp("2022-02-15")  # the FY row's date (PIT)

    # A real discrete Q4 is never synthesized over.
    with_q4 = pd.concat(
        [quarter, pd.DataFrame([_q_income("revenue", "2021-12-31", "2022-02-14", 300.0)])],
        ignore_index=True,
    )
    out2 = _discrete_quarters(annual, with_q4, "revenue", pd.Timestamp("2022-06-30"))
    q4b = out2[out2["fiscal_end"] == pd.Timestamp("2021-12-31")]
    assert float(q4b["value"].iloc[0]) == pytest.approx(300.0)  # the reported quarter, not 270

    # PIT: with the FY row filed after as_of, no Q4 is derived (residual not yet knowable).
    out3 = _discrete_quarters(annual, quarter, "revenue", pd.Timestamp("2022-01-31"))
    assert (out3["fiscal_end"] == pd.Timestamp("2021-12-31")).sum() == 0


def test_accel_gross_margin_delta_known_answer_and_missing_gp() -> None:
    from heimdall.research.dataset import _accel_features

    q = pd.DataFrame(
        [
            _q_income("revenue", "2021-09-30", "2021-11-14", 100.0),
            _q_income("gross_profit", "2021-09-30", "2021-11-14", 40.0),  # gm 40%
            _q_income("revenue", "2022-09-30", "2022-11-14", 100.0),
            _q_income("gross_profit", "2022-09-30", "2022-11-14", 42.0),  # gm 42%
        ]
    )
    out = _accel_features(_EMPTY_FUND, q, pd.Timestamp("2022-12-31"))
    assert out["gross_margin_delta_q"] == pytest.approx(2.0)  # +2 percentage points YoY

    # No GrossProfit tag anywhere → NaN (never derived from revenue − COGS).
    rev_only = q[q["metric"] == "revenue"].reset_index(drop=True)
    assert pd.isna(
        _accel_features(_EMPTY_FUND, rev_only, pd.Timestamp("2022-12-31"))["gross_margin_delta_q"]
    )


def _tdcc_week(symbol: str, data_date: str, level_pcts: dict[int, float]) -> pd.DataFrame:
    """One TDCC weekly file's rows for one symbol (roadmap 13.9's canonical
    shape), ``available_at`` = data_date + the provider's real 14-day lag."""
    from heimdall.data.providers.tdcc import AVAILABILITY_LAG

    dd = pd.Timestamp(data_date)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "data_date": dd,
            "available_at": dd + AVAILABILITY_LAG,
            "level": list(level_pcts),
            "pct_of_custody": list(level_pcts.values()),
        }
    )


def test_big_holder_features_known_answer_over_the_last_4_available_weeks() -> None:
    from heimdall.research.dataset import _big_holder_features

    # 5 weeks, all big-holder pct on level 15 for simplicity: 40, 42, 44, 46, 48.
    weeks = pd.concat(
        [
            _tdcc_week("AAA.TW", "2024-01-05", {15: 40.0}),
            _tdcc_week("AAA.TW", "2024-01-12", {15: 42.0}),
            _tdcc_week("AAA.TW", "2024-01-19", {15: 44.0}),
            _tdcc_week("AAA.TW", "2024-01-26", {15: 46.0}),
            _tdcc_week("AAA.TW", "2024-02-02", {15: 48.0}),
        ],
        ignore_index=True,
    )
    as_of = pd.Timestamp("2024-02-02") + pd.Timedelta(days=15)  # every week is available by now
    out = _big_holder_features(weeks, "AAA.TW", as_of)
    # Last 4 of the 5 weeks: 42 -> 48, delta = 6.0 (the oldest week, 40, is dropped).
    assert out["big_holder_ratio_delta_4w"] == pytest.approx(6.0)


def test_big_holder_features_sums_all_four_big_holder_levels() -> None:
    from heimdall.research.dataset import _big_holder_features

    # Split across levels 12-15 (all "big holder") plus a non-big level (11, must
    # be excluded from the sum).
    weeks = pd.concat(
        [
            _tdcc_week("AAA.TW", "2024-01-05", {11: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 30.0}),
            _tdcc_week("AAA.TW", "2024-01-12", {11: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 32.0}),
            _tdcc_week("AAA.TW", "2024-01-19", {11: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 34.0}),
            _tdcc_week("AAA.TW", "2024-01-26", {11: 5.0, 12: 1.0, 13: 1.0, 14: 1.0, 15: 36.0}),
        ],
        ignore_index=True,
    )
    as_of = pd.Timestamp("2024-01-26") + pd.Timedelta(days=15)
    out = _big_holder_features(weeks, "AAA.TW", as_of)
    # Week 1 big-holder sum = 1+1+1+30 = 33 (level 11 excluded); week 4 = 1+1+1+36 = 39.
    assert out["big_holder_ratio_delta_4w"] == pytest.approx(39.0 - 33.0)


def test_big_holder_features_pit_leak_excludes_not_yet_available_weeks() -> None:
    from heimdall.research.dataset import _big_holder_features

    weeks = pd.concat(
        [
            _tdcc_week("AAA.TW", "2024-01-05", {15: 40.0}),
            _tdcc_week("AAA.TW", "2024-01-12", {15: 42.0}),
            _tdcc_week("AAA.TW", "2024-01-19", {15: 44.0}),
            _tdcc_week("AAA.TW", "2024-01-26", {15: 46.0}),
            # A 5th week with an absurd spike, published AFTER as_of — must be invisible.
            _tdcc_week("AAA.TW", "2024-02-02", {15: 9999.0}),
        ],
        ignore_index=True,
    )
    # as_of sits between week 4's and week 5's availability — exactly 4 weeks knowable.
    as_of = pd.Timestamp("2024-01-26") + pd.Timedelta(days=14, hours=1)
    out = _big_holder_features(weeks, "AAA.TW", as_of)
    assert out["big_holder_ratio_delta_4w"] == pytest.approx(46.0 - 40.0)  # not the 9999 spike


def test_big_holder_features_guards() -> None:
    from heimdall.research.dataset import _big_holder_features

    at = pd.Timestamp("2024-06-01")
    assert pd.isna(_big_holder_features(pd.DataFrame(), "AAA.TW", at)["big_holder_ratio_delta_4w"])

    # A real cache with data for a DIFFERENT symbol only.
    weeks = _tdcc_week("BBB.TW", "2024-01-05", {15: 40.0})
    assert pd.isna(_big_holder_features(weeks, "AAA.TW", at)["big_holder_ratio_delta_4w"])

    # Fewer than 4 available weeks for this symbol → NaN.
    three = pd.concat(
        [
            _tdcc_week("AAA.TW", "2024-01-05", {15: 40.0}),
            _tdcc_week("AAA.TW", "2024-01-12", {15: 42.0}),
            _tdcc_week("AAA.TW", "2024-01-19", {15: 44.0}),
        ],
        ignore_index=True,
    )
    as_of = pd.Timestamp("2024-01-19") + pd.Timedelta(days=15)
    assert pd.isna(_big_holder_features(three, "AAA.TW", as_of)["big_holder_ratio_delta_4w"])


def test_panel_carries_pit_big_holder_features_for_tw(tmp_path: Path) -> None:
    frames = {
        "0050.TW": _ohlcv_geo("0050.TW", 700, 0.0005),
        "AAA.TW": _ohlcv_geo("AAA.TW", 700, 0.0),  # flat NT$100, NT$100M/day → eligible
    }
    weeks = pd.concat(
        [
            _tdcc_week("AAA.TW", "2024-05-03", {15: 40.0}),
            _tdcc_week("AAA.TW", "2024-05-10", {15: 42.0}),
            _tdcc_week("AAA.TW", "2024-05-17", {15: 44.0}),
            _tdcc_week("AAA.TW", "2024-05-24", {15: 46.0}),
        ],
        ignore_index=True,
    )
    _drive(
        build_dataset_iter(
            ["AAA.TW"],
            _Prices(frames),
            _Funds(),
            "Taiwan",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            tdcc_weeks=weeks,
        )
    )
    june = load_panel("Taiwan", tmp_path).set_index("date").loc[pd.Timestamp("2024-06-28")]
    assert june["big_holder_ratio_delta_4w"] == pytest.approx(46.0 - 40.0)


def test_panel_carries_pit_flow_features_for_tw(tmp_path: Path) -> None:
    frames = {
        "0050.TW": _ohlcv_geo("0050.TW", 700, 0.0005),
        "AAA.TW": _ohlcv_geo("AAA.TW", 700, 0.0),  # flat NT$100, NT$100M/day → eligible
    }
    cd = pd.bdate_range("2023-06-01", "2024-08-31")
    k, tk, v = 100_000.0, 40_000.0, 1_000_000.0
    chips = _chips_frame(
        cd,
        foreign=[k] * len(cd),
        trust=[tk] * len(cd),
        hold=[20.0 + 0.01 * i for i in range(len(cd))],
        margin=[10_000.0 * 1.001**i for i in range(len(cd))],
    )
    _drive(
        build_dataset_iter(
            ["AAA.TW"],
            _Prices(frames),
            _Funds(),
            "Taiwan",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            daily_chips=lambda sym, s, e: chips,
        )
    )
    june = load_panel("Taiwan", tmp_path).set_index("date").loc[pd.Timestamp("2024-06-28")]
    assert june["foreign_net_buy_21d"] == pytest.approx(21 * k / v)
    assert june["foreign_net_buy_63d"] == pytest.approx(63 * k / v)
    assert june["trust_net_buy_21d"] == pytest.approx(21 * tk / v)
    assert june["foreign_hold_delta_63d"] == pytest.approx(0.63)
    assert june["margin_delta_21d"] == pytest.approx(1.001**21 - 1)


def test_panel_carries_pit_lending_features_for_tw(tmp_path: Path) -> None:
    """roadmap 17.1: the injected ``daily_lending`` callable feeds the panel."""
    frames = {
        "0050.TW": _ohlcv_geo("0050.TW", 700, 0.0005),
        "AAA.TW": _ohlcv_geo("AAA.TW", 700, 0.0),  # flat NT$100, NT$100M/day → eligible
    }
    cd = pd.bdate_range("2023-06-01", "2024-08-31")
    base, step, v = 1_000_000.0, 5_000.0, 1_000_000.0
    lending = _lending_frame(cd, [base + step * i for i in range(len(cd))])
    _drive(
        build_dataset_iter(
            ["AAA.TW"],
            _Prices(frames),
            _Funds(),
            "Taiwan",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            daily_lending=lambda sym, s, e: lending,
        )
    )
    june = load_panel("Taiwan", tmp_path).set_index("date").loc[pd.Timestamp("2024-06-28")]
    assert june["sbl_short_delta_21d"] == pytest.approx(21 * step / v)
    assert june["sbl_short_delta_63d"] == pytest.approx(63 * step / v)


def test_panel_carries_pit_insider_features_for_us(tmp_path: Path) -> None:
    """roadmap 12.4/13.3: the injected ``insider`` callable feeds the US panel."""
    frames = {
        "SPY.US": _ohlcv_geo("SPY.US", 700, 0.0005),
        "X.US": _ohlcv_geo("X.US", 700, 0.0, s0=100.0),  # flat $100
    }
    # shares_outstanding = 1000 → market_cap = $100 × 1000 = $100,000.
    funds = _Funds(
        {
            "X.US": pd.DataFrame(
                [_fund_row("X.US", "shares_outstanding", "2023-12-31", "2024-02-01", 1000)]
            )
        }
    )
    # One officer buy of $1000 inside the June window → net = 1000 / 100000 = 0.01.
    frame = pd.DataFrame([_insider_row("2024-06-03", "P", 100, 10.0, "A")])
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(frames),
            funds,
            "US",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            insider=lambda sym, s, e: frame,
        )
    )
    june = load_panel("US", tmp_path).set_index("date").loc[pd.Timestamp("2024-06-28")]
    assert june["insider_net_buy_90d"] == pytest.approx(1000.0 / 100_000.0)
    assert june["insider_cluster_buy"] == 0.0  # a single buyer is not a cluster


def test_panel_carries_us_pead_and_issuance_features_when_quarterly_stream_present(
    tmp_path: Path,
) -> None:
    """roadmap 13.4/13.5: the injected ``quarterly_fundamentals`` callable switches
    on the US PEAD + issuance/quality columns; absent, they never appear."""
    frames = {
        "SPY.US": _ohlcv_geo("SPY.US", 700, 0.0005),
        "X.US": _ohlcv_geo("X.US", 700, 0.0, s0=100.0),
    }
    funds = _Funds(
        {
            "X.US": pd.DataFrame(
                [
                    _fund_row("X.US", "shares_outstanding", "2022-12-31", "2023-02-01", 1000),
                    _fund_row(
                        "X.US", "shares_outstanding", "2023-12-31", "2024-02-01", 1100
                    ),  # +10%
                ]
            )
        }
    )
    qeps = pd.concat(
        [_q_eps("2024-03-31", "2024-05-14", 1.5), _q_eps("2023-12-31", "2024-02-14", 1.2)],
        ignore_index=True,
    )
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(frames),
            funds,
            "US",
            date(2024, 6, 1),
            date(2024, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            quarterly_fundamentals=lambda sym, s, e: qeps,
        )
    )
    panel = load_panel("US", tmp_path)
    assert {
        "sue",
        "earn_gap",
        "net_issuance_12m",
        "asset_growth",
        "gross_profitability",
        "rev_accel_q",  # roadmap 17.4
        "gross_margin_delta_q",  # roadmap 17.4
    } <= set(panel.columns)
    june = panel.set_index("date").loc[pd.Timestamp("2024-06-28")]
    assert june["net_issuance_12m"] == pytest.approx(0.10)  # 1000 → 1100


def test_us_panel_has_no_flow_columns_without_the_stream(tmp_path: Path) -> None:
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(_spy_and_x()),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 7, 31),
            root=tmp_path,
            min_cross_section=0,
        )
    )
    cols = load_panel("US", tmp_path).columns
    assert "foreign_net_buy_21d" not in cols and "margin_delta_21d" not in cols
    assert "sbl_short_delta_21d" not in cols  # roadmap 17.1: no stream ⇒ no lending columns
    assert "big_holder_ratio_delta_4w" not in cols  # roadmap 13.9: no tdcc_weeks ⇒ no column
    assert "insider_net_buy_90d" not in cols  # roadmap 12.4/13.3: no insider stream ⇒ no column
    # roadmap 13.4/13.5/17.4: no quarterly stream ⇒ no US PEAD / issuance / acceleration columns
    assert (
        "sue" not in cols and "net_issuance_12m" not in cols and "gross_profitability" not in cols
    )
    assert "rev_accel_q" not in cols and "gross_margin_delta_q" not in cols


def test_panel_carries_static_sector_when_map_given(tmp_path: Path) -> None:
    """roadmap 17.5: ``sector_map`` stamps a static ``sector`` on every row ("Unknown"
    for a symbol absent from the map); omitted ⇒ no ``sector`` column at all."""
    frames = {
        "SPY.US": _ohlcv_geo("SPY.US", 500, 0.0005),
        "X.US": _ohlcv_geo("X.US", 500, 0.0),
        "Y.US": _ohlcv_geo("Y.US", 500, 0.0),
    }
    _drive(
        build_dataset_iter(
            ["X.US", "Y.US"],
            _Prices(frames),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 7, 31),
            root=tmp_path,
            min_cross_section=0,
            sector_map={"X.US": "Manufacturing"},  # Y.US deliberately absent
        )
    )
    panel = load_panel("US", tmp_path)
    assert "sector" in panel.columns
    assert set(panel[panel["symbol"] == "X.US"]["sector"]) == {"Manufacturing"}
    assert set(panel[panel["symbol"] == "Y.US"]["sector"]) == {"Unknown"}

    # Omitted map ⇒ no column (old callers/panels unaffected).
    _drive(
        build_dataset_iter(
            ["X.US"],
            _Prices(frames),
            _Funds(),
            "US",
            date(2023, 6, 1),
            date(2023, 7, 31),
            root=tmp_path / "no_map",
            min_cross_section=0,
        )
    )
    assert "sector" not in load_panel("US", tmp_path / "no_map").columns


def test_hygiene_constants_mirror_playbook() -> None:
    # docs/RESEARCH_PLAYBOOK.md §3 — changing either side alone must fail here.
    assert gates.MIN_PRICE == {"US": 2.0, "Taiwan": 10.0}
    assert gates.MIN_DOLLAR_VOL_21D == {"US": 5_000_000.0, "Taiwan": 50_000_000.0}
    assert gates.MIN_HISTORY_BARS == 252
    assert gates.MIN_CROSS_SECTION == 100
