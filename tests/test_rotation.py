"""Citadel sector rotation: ranking order, offense/defense tilt, leaders."""

from __future__ import annotations

import numpy as np
import pandas as pd

from stockobserver.analytics.rotation import sector_rotation


def _ohlcv(drift: float, n: int = 160) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = pd.Series(100 * np.exp(drift * np.arange(n)), dtype=float)
    return pd.DataFrame({"date": dates, "adj_close": close})


def test_ranking_and_offense_tilt() -> None:
    etfs = {
        "XLK.US": _ohlcv(0.002),  # tech, strong (offense)
        "XLF.US": _ohlcv(0.001),  # financials, up (offense)
        "XLP.US": _ohlcv(-0.001),  # staples, down (defense)
    }
    rep = sector_rotation(etfs)
    assert rep.ranks.index[0] == "XLK.US"  # strongest momentum ranks first
    assert list(rep.ranks["rank"]) == [1, 2, 3]
    assert rep.tilt == "offense"  # cyclicals leading defensives
    assert "XLK.US" in rep.leaders and "XLP.US" in rep.laggards
