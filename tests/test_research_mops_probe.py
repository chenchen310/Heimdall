"""MOPS live-observation mechanism (roadmap 17.9) — pure logic, no network.

Covers the two load-bearing properties: recording is idempotent (a re-run with the same
snapshot never rewrites an already-observed first-appearance date) and the deadline math
matches the §36 10th-of-next-month rule (including the December year-roll).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from heimdall.research.mops_probe import (
    load_store,
    observation_path,
    save_store,
    summarize,
    tracked_symbols,
    update_observations,
)

# --- update_observations ----------------------------------------------------------


def test_update_observations_records_first_appearance() -> None:
    store: dict[str, dict[str, str]] = {}
    latest = {"2330.TW": "2026-07", "2317.TW": "2026-07"}
    store, newly = update_observations(store, latest, date(2026, 8, 6))
    assert store == {"2330.TW": {"2026-07": "2026-08-06"}, "2317.TW": {"2026-07": "2026-08-06"}}
    assert set(newly) == {("2330.TW", "2026-07"), ("2317.TW", "2026-07")}


def test_update_observations_is_idempotent() -> None:
    # A re-run on a LATER day with the SAME latest month must not move the recorded date —
    # the whole point is capturing the true first-appearance date, once.
    store = {"2330.TW": {"2026-07": "2026-08-06"}}
    latest = {"2330.TW": "2026-07"}
    store2, newly = update_observations(store, latest, date(2026, 8, 10))
    assert store2["2330.TW"]["2026-07"] == "2026-08-06"  # untouched
    assert newly == []  # nothing new recorded


def test_update_observations_new_month_is_recorded_alongside_old() -> None:
    store = {"2330.TW": {"2026-07": "2026-08-06"}}
    latest = {"2330.TW": "2026-08"}  # a new revenue month has appeared
    store2, newly = update_observations(store, latest, date(2026, 9, 5))
    assert store2["2330.TW"] == {"2026-07": "2026-08-06", "2026-08": "2026-09-05"}
    assert newly == [("2330.TW", "2026-08")]


def test_update_observations_skips_none_and_does_not_mutate_input() -> None:
    store = {"A.TW": {"2026-07": "2026-08-06"}}
    store2, newly = update_observations(store, {"B.TW": None}, date(2026, 8, 6))
    assert newly == []
    assert "B.TW" not in store2
    assert store == {"A.TW": {"2026-07": "2026-08-06"}}  # original dict untouched


# --- summarize ---------------------------------------------------------------------


def test_summarize_days_vs_10th_and_late_flag() -> None:
    store = {
        "EARLY.TW": {"2026-07": "2026-08-08"},  # 2 days before the 10th
        "ONTIME.TW": {"2026-07": "2026-08-10"},  # exactly on the deadline
        "LATE.TW": {"2026-07": "2026-08-15"},  # 5 days after
        "OTHER_MONTH.TW": {"2026-06": "2026-07-09"},  # different month, excluded
    }
    df = summarize(store, "2026-07").set_index("symbol")
    assert df.loc["EARLY.TW", "days_vs_10th"] == -2
    assert df.loc["EARLY.TW", "late"] == False  # noqa: E712
    assert df.loc["ONTIME.TW", "days_vs_10th"] == 0
    assert df.loc["ONTIME.TW", "late"] == False  # noqa: E712
    assert df.loc["LATE.TW", "days_vs_10th"] == 5
    assert df.loc["LATE.TW", "late"] == True  # noqa: E712
    assert "OTHER_MONTH.TW" not in df.index
    assert len(df) == 3


def test_summarize_handles_december_year_roll() -> None:
    # December revenue is disclosed by Jan 10 of the FOLLOWING year.
    store = {"X.TW": {"2025-12": "2026-01-09"}}
    df = summarize(store, "2025-12")
    assert df.iloc[0]["days_vs_10th"] == -1


def test_summarize_empty_store() -> None:
    assert summarize({}, "2026-07").empty


# --- tracked_symbols ----------------------------------------------------------------


def test_tracked_symbols_spreads_across_the_sorted_universe() -> None:
    fake_universe = [f"{i:04d}.TW" for i in range(300)]  # synthetic, sorted-shape only
    picked = tracked_symbols(n=30, universe=lambda: fake_universe)
    assert len(picked) == 30
    assert picked == sorted(picked)  # still sorted (evenly spread, not shuffled)
    assert picked[0] == "0000.TW"  # spread starts at the low end (large/old-economy proxy)
    assert len(set(picked)) == 30  # no duplicates


def test_tracked_symbols_returns_whole_universe_when_smaller_than_n() -> None:
    small = ["A.TW", "B.TW"]
    assert tracked_symbols(n=30, universe=lambda: small) == sorted(small)


# --- store persistence (atomic write) -----------------------------------------------


def test_store_round_trips_atomically(tmp_path: Path) -> None:
    assert load_store(tmp_path) == {}  # no file yet ⇒ empty, not an error
    store = {"2330.TW": {"2026-07": "2026-08-06"}}
    save_store(store, tmp_path)
    assert load_store(tmp_path) == store
    assert observation_path(tmp_path).exists()
    assert not list(observation_path(tmp_path).parent.glob("*.tmp"))  # no leftover temp file
