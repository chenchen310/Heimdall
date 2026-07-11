"""Descriptive chip aggregation (roadmap 11.5) — cumulative-flow known answers."""

from __future__ import annotations

import pandas as pd

from heimdall.analytics import cumulative_flows


def test_cumulative_flows_running_sum_sorts_and_zero_fills() -> None:
    chips = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03", "2024-01-02", "2024-01-04"]),  # unsorted
            "foreign_net_shares": [100.0, 200.0, float("nan")],  # a gap on the last day
            "trust_net_shares": [10.0, float("nan"), 30.0],
        }
    )
    out = cumulative_flows(chips)
    assert out["date"].is_monotonic_increasing  # sorted ascending first
    # sorted order: 01-02 (f=200, t=nan) → 01-03 (f=100, t=10) → 01-04 (f=nan, t=30)
    assert out["foreign_cum_net"].tolist() == [200.0, 300.0, 300.0]  # a NaN day counts as 0 flow
    assert out["trust_cum_net"].tolist() == [0.0, 10.0, 40.0]


def test_cumulative_flows_empty_in_empty_out() -> None:
    empty = pd.DataFrame(columns=["date", "foreign_net_shares", "trust_net_shares"])
    out = cumulative_flows(empty)
    assert out.empty
    assert "foreign_cum_net" not in out.columns  # nothing fabricated on empty input
