"""Cross-sectional factor scoring: bounds, direction, composite, NaN tolerance."""

from __future__ import annotations

import numpy as np
import pandas as pd

from heimdall.factors.scoring import FACTOR_NAMES, factor_scores


def _cross() -> pd.DataFrame:
    # A dominates every factor (cheapest, highest quality/momentum/growth); D is worst.
    return pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "pe": [10.0, 20, 30, 40],
            "ps": [1.0, 2, 3, 4],
            "fcf_yield": [0.08, 0.06, 0.04, 0.02],
            "roe": [0.30, 0.20, 0.10, 0.05],
            "net_margin": [0.30, 0.20, 0.10, 0.05],
            "gross_margin": [0.50, 0.40, 0.30, 0.20],
            "debt_to_equity": [0.5, 1.0, 1.5, 2.0],
            "ret_3m": [0.20, 0.10, 0.0, -0.10],
            "ret_6m": [0.30, 0.20, 0.10, 0.0],
            "ret_12m": [0.40, 0.30, 0.20, 0.10],
            "revenue_growth_yoy": [0.30, 0.20, 0.10, 0.0],
        }
    )


def test_scores_bounded_and_present() -> None:
    out = factor_scores(_cross())
    for f in [*FACTOR_NAMES, "composite"]:
        assert f"{f}_score" in out.columns
    s = out["composite_score"].dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_value_direction_cheaper_scores_higher() -> None:
    out = factor_scores(_cross()).set_index("symbol")
    assert out.loc["A", "value_score"] == out["value_score"].max()  # cheapest
    assert out.loc["D", "value_score"] == out["value_score"].min()  # priciest


def test_composite_ranks_dominant_name_first() -> None:
    out = factor_scores(_cross()).sort_values("composite_score", ascending=False)
    assert out["symbol"].iloc[0] == "A"
    assert out["symbol"].iloc[-1] == "D"


def test_missing_metric_is_tolerated() -> None:
    cross = _cross()
    cross.loc[0, "pe"] = np.nan  # A loses one value input
    out = factor_scores(cross)
    assert out["composite_score"].notna().any()  # no raise; still scores from other inputs
