"""TW big-holder (大戶) aggregation (roadmap 15.3) — known-answer tests, no network."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.analytics import (
    big_holder_pct,
    monthly_delta_ranking,
    symbol_history,
    weekly_delta_ranking,
)


def _week(symbol: str, data_date: str, lag_days: int, level_pcts: dict[int, float]) -> pd.DataFrame:
    dd = pd.Timestamp(data_date)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "data_date": dd,
            "available_at": dd + pd.Timedelta(days=lag_days),
            "level": list(level_pcts),
            "pct_of_custody": list(level_pcts.values()),
        }
    )


def _weeks(
    symbol: str, dates: list[str], big_pcts: list[float], lag_days: int = 14
) -> pd.DataFrame:
    """One row of level 15 (a big-holder level) per date — the minimal shape
    that sums to exactly ``big_pcts[i]`` for ``big_holder_pct``."""
    return pd.concat(
        [_week(symbol, d, lag_days, {15: p}) for d, p in zip(dates, big_pcts, strict=True)],
        ignore_index=True,
    )


# --- big_holder_pct ------------------------------------------------------------


def test_big_holder_pct_sums_only_the_big_holder_levels() -> None:
    weeks = pd.concat(
        [
            _week("A.TW", "2024-01-05", 14, {11: 5.0, 12: 1.0, 13: 2.0, 14: 3.0, 15: 30.0}),
        ],
        ignore_index=True,
    )
    out = big_holder_pct(weeks)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["symbol"] == "A.TW"
    assert row["big_holder_pct"] == pytest.approx(1.0 + 2.0 + 3.0 + 30.0)  # level 11 excluded


def test_big_holder_pct_empty() -> None:
    out = big_holder_pct(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == ["symbol", "data_date", "available_at", "big_holder_pct"]


# --- weekly_delta_ranking --------------------------------------------------------


def test_weekly_delta_ranking_last_minus_oldest_of_4() -> None:
    four_dates = ["2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26"]
    weeks = pd.concat(
        [
            _weeks("A.TW", four_dates, [40, 42, 44, 50]),
            _weeks("B.TW", four_dates, [60, 55, 52, 48]),
        ],
        ignore_index=True,
    )
    as_of = pd.Timestamp("2024-01-26") + pd.Timedelta(days=15)
    out = weekly_delta_ranking(weeks, as_of).set_index("symbol")
    assert out.loc["A.TW", "delta_pp"] == pytest.approx(10.0)  # 50 - 40, a riser
    assert out.loc["B.TW", "delta_pp"] == pytest.approx(-12.0)  # 48 - 60, a faller
    # Sorted risers-first.
    assert weekly_delta_ranking(weeks, as_of)["symbol"].tolist() == ["A.TW", "B.TW"]


def test_weekly_delta_ranking_pit_leak_excludes_not_yet_available() -> None:
    weeks = _weeks(
        "A.TW",
        ["2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26", "2024-02-02"],
        [40, 42, 44, 46, 9999],  # the 5th week is an absurd spike, not yet available
    )
    as_of = pd.Timestamp("2024-01-26") + pd.Timedelta(days=14, hours=1)
    out = weekly_delta_ranking(weeks, as_of).set_index("symbol")
    assert out.loc["A.TW", "delta_pp"] == pytest.approx(6.0)  # 46 - 40, not the 9999 spike


def test_weekly_delta_ranking_fewer_than_n_weeks_excludes_the_symbol() -> None:
    weeks = _weeks("A.TW", ["2024-01-05", "2024-01-12", "2024-01-19"], [40, 42, 44])
    as_of = pd.Timestamp("2024-01-19") + pd.Timedelta(days=15)
    assert weekly_delta_ranking(weeks, as_of).empty


def test_weekly_delta_ranking_empty() -> None:
    assert weekly_delta_ranking(pd.DataFrame(), pd.Timestamp("2024-01-01")).empty


# --- monthly_delta_ranking -------------------------------------------------------


def test_monthly_delta_ranking_mean_of_last_4_vs_prior_4() -> None:
    # 8 weeks: prior 4 mean = (40+41+42+43)/4 = 41.5; recent 4 mean = (50+51+52+53)/4 = 51.5.
    dates = pd.date_range("2024-01-05", periods=8, freq="7D").strftime("%Y-%m-%d").tolist()
    pcts = [40, 41, 42, 43, 50, 51, 52, 53]
    weeks = _weeks("A.TW", dates, pcts)
    as_of = pd.Timestamp(dates[-1]) + pd.Timedelta(days=15)
    out = monthly_delta_ranking(weeks, as_of).set_index("symbol")
    assert out.loc["A.TW", "delta_pp"] == pytest.approx(51.5 - 41.5)
    assert out.loc["A.TW", "latest_pct"] == pytest.approx(53.0)


def test_monthly_delta_ranking_fewer_than_8_weeks_excludes_the_symbol() -> None:
    dates = pd.date_range("2024-01-05", periods=7, freq="7D").strftime("%Y-%m-%d").tolist()
    weeks = _weeks("A.TW", dates, [40, 41, 42, 43, 44, 45, 46])
    as_of = pd.Timestamp(dates[-1]) + pd.Timedelta(days=15)
    assert monthly_delta_ranking(weeks, as_of).empty


def test_monthly_delta_ranking_empty() -> None:
    assert monthly_delta_ranking(pd.DataFrame(), pd.Timestamp("2024-01-01")).empty


# --- symbol_history --------------------------------------------------------------


def test_symbol_history_returns_ascending_series_for_one_symbol() -> None:
    weeks = pd.concat(
        [
            _weeks("A.TW", ["2024-01-05", "2024-01-12"], [40, 42]),
            _weeks("B.TW", ["2024-01-05"], [99]),
        ],
        ignore_index=True,
    )
    out = symbol_history(weeks, "A.TW")
    assert list(out.columns) == ["data_date", "big_holder_pct"]
    assert out["big_holder_pct"].tolist() == [40.0, 42.0]
    assert "B.TW" not in weeks.loc[weeks["symbol"] == "A.TW", "symbol"].to_numpy()  # sanity


def test_symbol_history_unknown_symbol_is_empty() -> None:
    weeks = _weeks("A.TW", ["2024-01-05"], [40])
    assert symbol_history(weeks, "Z.TW").empty
