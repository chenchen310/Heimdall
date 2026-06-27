"""Factor validation: rank IC sign/magnitude and quantile spread direction."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.factors.validate import information_coefficient, quantile_spread


def _panel(sign: float) -> pd.DataFrame:
    """Panel where forward return is perfectly rank-(anti)correlated with the factor."""
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    rows = []
    for d in dates:
        for i in range(6):
            rows.append(
                {"date": d, "symbol": f"S{i}", "composite_score": i * 10.0, "fwd_return": sign * i}
            )
    return pd.DataFrame(rows)


def test_ic_is_one_for_perfect_predictor() -> None:
    ic = information_coefficient(_panel(+1.0))
    assert ic.mean_ic == pytest.approx(1.0)
    assert ic.hit_rate == pytest.approx(1.0)
    assert ic.n_periods == 3


def test_ic_is_negative_one_for_inverted_predictor() -> None:
    assert information_coefficient(_panel(-1.0)).mean_ic == pytest.approx(-1.0)


def test_quantile_spread_increases_with_factor() -> None:
    spread = quantile_spread(_panel(+1.0), q=3)
    assert list(spread.index) == ["Q1", "Q2", "Q3"]
    assert spread["Q3"] > spread["Q1"]  # top bucket out-returns bottom


def test_empty_when_no_overlap() -> None:
    panel = pd.DataFrame({"date": [], "symbol": [], "composite_score": [], "fwd_return": []})
    assert information_coefficient(panel).n_periods == 0
