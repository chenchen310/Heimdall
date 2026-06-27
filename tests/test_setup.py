"""Trade-setup risk/reward math."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heimdall.backtest.setup import trade_setup


def _ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 60)), dtype=float)
    high = close + 1.0
    low = close - 1.0
    dates = pd.bdate_range("2024-01-01", periods=60)
    return pd.DataFrame(
        {"date": dates, "open": close, "high": high, "low": low, "close": close, "adj_close": close}
    )


def test_stop_and_targets_are_consistent() -> None:
    ohlcv = _ohlcv()
    s = trade_setup(ohlcv, atr_mult=2.0, rr=(1.0, 2.0, 3.0))

    assert s.entry == pytest.approx(float(ohlcv["close"].iloc[-1]))
    assert s.stop == pytest.approx(s.entry - 2.0 * s.atr)
    assert s.risk == pytest.approx(s.entry - s.stop)
    # each target sits at its R-multiple of risk above entry
    for mult, target in zip(s.rr, s.targets, strict=True):
        assert target == pytest.approx(s.entry + mult * s.risk)


def test_higher_atr_multiple_widens_stop() -> None:
    ohlcv = _ohlcv()
    tight = trade_setup(ohlcv, atr_mult=1.0)
    wide = trade_setup(ohlcv, atr_mult=3.0)
    assert wide.stop < tight.stop < wide.entry
