"""Sector-focus aggregation (roadmap 14.2) — known-answer tests, no network."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.analytics import member_table, sector_table, trailing_return

# --- trailing_return ---------------------------------------------------------


def test_trailing_return_known_answer() -> None:
    adj = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 110.0])  # 6 bars, index 0..5
    assert trailing_return(adj, 1) == pytest.approx(110.0 / 104.0 - 1.0)
    assert trailing_return(adj, 5) == pytest.approx(110.0 / 100.0 - 1.0)


def test_trailing_return_short_history_is_nan() -> None:
    adj = pd.Series([100.0, 101.0])  # only 1 bar of change; window 5 needs 6 points
    assert pd.isna(trailing_return(adj, 5))


def test_trailing_return_nonpositive_entry_is_nan() -> None:
    adj = pd.Series([0.0, 101.0, 102.0])
    assert pd.isna(trailing_return(adj, 2))


# --- sector_table --------------------------------------------------------------


def _snap(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """(symbol, sector, pct_above_sma_200) rows -> a minimal snapshot frame."""
    return pd.DataFrame(rows, columns=["symbol", "sector", "pct_above_sma_200"])


def test_sector_table_equal_weight_and_vs_benchmark() -> None:
    snap = _snap(
        [
            ("A", "Tech", 0.10),
            ("B", "Tech", -0.05),
            ("C", "Energy", 0.02),
        ]
    )
    returns = {"A": 0.10, "B": 0.20, "C": -0.10}  # Tech mean = 0.15, Energy mean = -0.10
    out = sector_table(snap, returns, benchmark_return=0.05).set_index("sector")
    assert out.loc["Tech", "ret"] == pytest.approx(0.15)
    assert out.loc["Tech", "ret_vs_benchmark"] == pytest.approx(0.10)
    assert out.loc["Tech", "n_members"] == 2 and out.loc["Tech", "n_priced"] == 2
    assert out.loc["Energy", "ret"] == pytest.approx(-0.10)
    # Sorted by ret_vs_benchmark descending: Tech (+0.10) before Energy (-0.15).
    assert out.index.tolist() == ["Tech", "Energy"]


def test_sector_table_breadth_only_counts_priced_members() -> None:
    snap = _snap(
        [
            ("A", "Tech", 1.0),  # above SMA200, priced
            ("B", "Tech", -1.0),  # below SMA200, priced
            ("C", "Tech", 1.0),  # above SMA200, but NOT priced — excluded from breadth
        ]
    )
    returns = {"A": 0.05, "B": 0.05}  # C absent -> unpriced
    out = sector_table(snap, returns, benchmark_return=0.0)
    row = out.iloc[0]
    assert row["n_members"] == 3 and row["n_priced"] == 2
    assert row["breadth"] == pytest.approx(0.5)  # 1 of 2 PRICED members above SMA200


def test_sector_table_unpriced_symbol_stays_on_roster_but_excluded_from_return() -> None:
    snap = _snap([("A", "Tech", 1.0), ("B", "Tech", 1.0)])
    out = sector_table(snap, {"A": 0.20}, benchmark_return=0.0)  # B has no return at all
    row = out.iloc[0]
    assert row["n_members"] == 2  # B still on the roster
    assert row["n_priced"] == 1  # but doesn't count toward the return
    assert row["ret"] == pytest.approx(0.20)


def test_sector_table_empty_snapshot() -> None:
    from heimdall.analytics.sector_focus import SECTOR_TABLE_COLUMNS

    out = sector_table(pd.DataFrame(), {}, benchmark_return=0.0)
    assert out.empty
    assert list(out.columns) == SECTOR_TABLE_COLUMNS


def test_sector_table_missing_sector_column_is_empty() -> None:
    out = sector_table(pd.DataFrame({"symbol": ["A"]}), {"A": 0.1}, benchmark_return=0.0)
    assert out.empty


# --- member_table ----------------------------------------------------------------


def test_member_table_ranks_and_computes_relative_strength() -> None:
    snap = _snap([("A", "Tech", 1.0), ("B", "Tech", 1.0), ("C", "Tech", 1.0)])
    returns = {"A": 0.30, "B": 0.10, "C": -0.10}  # mean = 0.10
    out = member_table(snap, returns, "Tech")
    assert out["symbol"].tolist() == ["A", "B", "C"]  # ranked by ret, descending
    assert out.set_index("symbol").loc["A", "rs_vs_sector"] == pytest.approx(0.20)
    assert out.set_index("symbol").loc["C", "rs_vs_sector"] == pytest.approx(-0.20)


def test_member_table_filters_to_the_named_sector() -> None:
    snap = _snap([("A", "Tech", 1.0), ("B", "Energy", 1.0)])
    out = member_table(snap, {"A": 0.1, "B": 0.2}, "Tech")
    assert out["symbol"].tolist() == ["A"]


def test_member_table_unpriced_members_sort_last() -> None:
    snap = _snap([("A", "Tech", 1.0), ("B", "Tech", 1.0)])
    out = member_table(snap, {"A": 0.1}, "Tech")  # B unpriced
    assert out["symbol"].tolist() == ["A", "B"]
    assert pd.isna(out.set_index("symbol").loc["B", "ret"])
