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


# --- roadmap 11.2: TW monthly-revenue momentum (PIT on filed_at) --------------


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


def test_revenue_features_known_answer_and_pit_flip() -> None:
    from heimdall.research.dataset import _revenue_features

    rev = _rev_frame(_REV_SERIES)
    # 2024-07-05: June (filed 7/10) is NOT yet knowable → latest known is May.
    before = _revenue_features(rev, pd.Timestamp("2024-07-05"))
    assert before["rev_mom_yoy"] == pytest.approx(0.10)  # May 110 / 100 − 1
    # 2024-07-10: June becomes knowable → the feature flips to June's YoY.
    after = _revenue_features(rev, pd.Timestamp("2024-07-10"))
    assert after["rev_mom_yoy"] == pytest.approx(0.50)  # June 150 / 100 − 1
    # accel = mean(Apr,May,Jun YoY) − mean(Jan,Feb,Mar YoY) = .2333 − .10
    assert after["rev_mom_accel"] == pytest.approx((0.10 + 0.10 + 0.50) / 3 - 0.10)


def test_revenue_features_guards() -> None:
    from heimdall.research.dataset import _revenue_features

    late = pd.Timestamp("2025-01-15")
    # Too little history: 10 months has no 12-month-ago base → NaN.
    short = _rev_frame([(f"2024-{m:02d}-01", 100.0) for m in range(1, 11)])
    out = _revenue_features(short, late)
    assert pd.isna(out["rev_mom_yoy"]) and pd.isna(out["rev_mom_accel"])
    # Non-positive year-ago base → NaN, never a fake percent.
    zero_base = _rev_frame([("2023-06-01", 0.0), ("2024-06-01", 150.0)])
    assert pd.isna(_revenue_features(zero_base, late)["rev_mom_yoy"])
    # A gap month poisons the windows it touches (contiguous-calendar rule):
    gapped = _rev_frame([r for r in _REV_SERIES if r[0] != "2024-03-01"])
    out = _revenue_features(gapped, late)
    assert out["rev_mom_yoy"] == pytest.approx(0.50)  # June itself is fine
    assert pd.isna(out["rev_mom_accel"])  # prior-3 window spans the hole
    # Empty frame → NaN dict.
    empty = _revenue_features(pd.DataFrame(), late)
    assert pd.isna(empty["rev_mom_yoy"]) and pd.isna(empty["rev_mom_accel"])


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


def test_hygiene_constants_mirror_playbook() -> None:
    # docs/RESEARCH_PLAYBOOK.md §3 — changing either side alone must fail here.
    assert gates.MIN_PRICE == {"US": 2.0, "Taiwan": 10.0}
    assert gates.MIN_DOLLAR_VOL_21D == {"US": 5_000_000.0, "Taiwan": 50_000_000.0}
    assert gates.MIN_HISTORY_BARS == 252
    assert gates.MIN_CROSS_SECTION == 100
