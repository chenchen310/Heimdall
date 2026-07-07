"""Benchmark map + forward-return primitive (roadmap 7.2).

``forward_return`` is the atom every research label is built from; a windowing
bug here silently corrupts every downstream IC/beat-rate, so entry alignment
and the incomplete-window NaN are pinned as known answers.
"""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.data.symbols import MARKET_REGION
from heimdall.research.benchmark import BENCHMARK, forward_return, window_return


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series([float(v) for v in values], index=pd.bdate_range(start, periods=len(values)))


def test_benchmark_map_covers_every_region() -> None:
    # Every UI region must have a benchmark, or its `_rel` labels can't exist.
    assert set(BENCHMARK) == set(MARKET_REGION.values())
    assert BENCHMARK["US"] == "SPY.US"
    assert BENCHMARK["Taiwan"] == "0050.TW"


def test_forward_return_known_answer() -> None:
    s = _series([100.0, 110.0, 121.0, 133.1])  # +10% per bar
    assert forward_return(s, s.index[0], 1) == pytest.approx(0.10)
    assert forward_return(s, s.index[0], 3) == pytest.approx(0.331)
    assert forward_return(s, s.index[1], 2) == pytest.approx(133.1 / 110.0 - 1.0)


def test_start_aligns_forward_to_first_bar_on_or_after() -> None:
    # Mon 2024-01-01 .. Fri 2024-01-05, then Mon 2024-01-08 (bdate skips the weekend).
    s = _series([100.0, 101.0, 102.0, 103.0, 104.0, 200.0])
    saturday = pd.Timestamp("2024-01-06")
    # Entry aligns to Monday's 200 close; one bar later doesn't exist → NaN...
    assert pd.isna(forward_return(s, saturday, 1))
    # ...but with the window shortened to 0-bar entry==exit sanity: use an earlier start.
    # From the Saturday, entry = Mon(200); prove alignment via a series with one more bar.
    s2 = _series([100.0, 101.0, 102.0, 103.0, 104.0, 200.0, 220.0])
    assert forward_return(s2, saturday, 1) == pytest.approx(0.10)  # 220/200, not from Friday


def test_incomplete_window_is_nan() -> None:
    s = _series([100.0, 110.0, 121.0])
    assert pd.isna(forward_return(s, s.index[0], 3))  # needs a 4th bar
    assert pd.isna(forward_return(s, s.index[-1], 1))  # nothing after the last bar
    beyond = s.index[-1] + pd.offsets.BDay(5)
    assert pd.isna(forward_return(s, beyond, 1))  # start past the series entirely


def test_nan_prices_propagate_not_skip() -> None:
    s = _series([100.0, float("nan"), 120.0, 130.0])
    assert pd.isna(forward_return(s, s.index[1], 1))  # NaN entry
    assert pd.isna(forward_return(s, s.index[0], 1))  # NaN exit
    assert forward_return(s, s.index[2], 1) == pytest.approx(130.0 / 120.0 - 1.0)


def test_non_positive_entry_is_nan() -> None:
    assert pd.isna(forward_return(_series([0.0, 10.0]), pd.Timestamp("2024-01-01"), 1))


def test_unsorted_series_raises() -> None:
    s = _series([100.0, 110.0, 120.0]).iloc[::-1]
    with pytest.raises(ValueError, match="sorted"):
        forward_return(s, pd.Timestamp("2024-01-01"), 1)


def test_window_return_known_answer_and_alignment() -> None:
    s = _series([100.0, 110.0, 121.0, 133.1])
    assert window_return(s, s.index[0], s.index[2]) == pytest.approx(0.21)
    # A non-trading start aligns forward, same as forward_return.
    day_before = s.index[0] - pd.offsets.Day(2)  # a Saturday
    assert window_return(s, day_before, s.index[1]) == pytest.approx(0.10)


def test_window_return_empty_or_incomplete_window_is_nan() -> None:
    s = _series([100.0, 110.0, 121.0])
    assert pd.isna(window_return(s, s.index[0], s.index[0]))  # no elapsed bar
    assert pd.isna(window_return(s, s.index[1], s.index[0]))  # end before start
    beyond = s.index[-1] + pd.offsets.BDay(2)
    assert pd.isna(window_return(s, s.index[0], beyond))  # end past the series
