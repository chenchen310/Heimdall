"""JPM earnings: surprise history, beat rate, next-quarter consensus."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.analytics.earnings import earnings_report
from heimdall.data.schema import EARNINGS_COLUMNS


def _earnings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "date": pd.to_datetime(["2024-02-01", "2024-05-01", "2024-08-01", "2024-11-01"]),
            "eps_actual": [1.0, 1.2, 1.1, None],  # last row not yet reported
            "eps_estimate": [0.9, 1.0, 1.2, 1.3],
            "revenue_actual": [100.0, 110, 108, None],
            "revenue_estimate": [95.0, 105, 110, 120],
            "is_future": [False, False, False, True],
        }
    )


def test_summary() -> None:
    rep = earnings_report("X.US", _earnings())
    assert rep.next_date == pd.Timestamp("2024-11-01")
    assert rep.next_eps_estimate == pytest.approx(1.3)
    # past beats: 1.0>0.9 ✓, 1.2>1.0 ✓, 1.1>1.2 ✗ → 2/3
    assert rep.beat_rate == pytest.approx(2 / 3)
    assert len(rep.recent) == 3


def test_empty() -> None:
    rep = earnings_report("X.US", pd.DataFrame(columns=EARNINGS_COLUMNS))
    assert rep.next_date is None
    assert pd.isna(rep.beat_rate)
