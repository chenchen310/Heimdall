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
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "AAA.TW",
            "date": dates,
            "foreign_net_shares": foreign,
            "trust_net_shares": trust,
            "foreign_hold_ratio": hold,
            "margin_balance": margin,
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
    )
    out = _flow_features(chips, _flat_price(dates, c, v), dates[-1])
    # Σ(net shares × close) over the window ÷ its median dollar volume = n_window × k / v.
    assert out["foreign_net_buy_21d"] == pytest.approx(21 * k / v)
    assert out["foreign_net_buy_63d"] == pytest.approx(63 * k / v)
    assert out["trust_net_buy_21d"] == pytest.approx(21 * tk / v)
    # ratio ramps 0.01pp/day → 63-day pp change = 0.63; margin +0.1%/day → 1.001**21 − 1.
    assert out["foreign_hold_delta_63d"] == pytest.approx(0.63)
    assert out["margin_delta_21d"] == pytest.approx(1.001**21 - 1)


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


def test_hygiene_constants_mirror_playbook() -> None:
    # docs/RESEARCH_PLAYBOOK.md §3 — changing either side alone must fail here.
    assert gates.MIN_PRICE == {"US": 2.0, "Taiwan": 10.0}
    assert gates.MIN_DOLLAR_VOL_21D == {"US": 5_000_000.0, "Taiwan": 50_000_000.0}
    assert gates.MIN_HISTORY_BARS == 252
    assert gates.MIN_CROSS_SECTION == 100
