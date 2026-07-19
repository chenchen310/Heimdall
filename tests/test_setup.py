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


def test_atr_fallback_puts_pullback_below_and_breakout_above_price() -> None:
    ohlcv = _ohlcv()
    s = trade_setup(ohlcv, entry_atr_mult=1.0)
    # No structural levels passed -> both entries default to an ATR offset off the close.
    assert s.pullback.entry == pytest.approx(s.entry - 1.0 * s.atr)
    assert s.breakout.entry == pytest.approx(s.entry + 1.0 * s.atr)
    assert s.pullback.entry < s.entry < s.breakout.entry


def test_passed_levels_anchor_the_two_entries() -> None:
    ohlcv = _ohlcv()
    price = float(ohlcv["close"].iloc[-1])
    support, resistance = price - 5.0, price + 4.0
    s = trade_setup(ohlcv, pullback_level=support, breakout_level=resistance)
    assert s.pullback.entry == pytest.approx(support)
    assert s.breakout.entry == pytest.approx(resistance)


def test_each_plan_stop_and_targets_measured_from_its_own_entry() -> None:
    ohlcv = _ohlcv()
    s = trade_setup(ohlcv, atr_mult=2.0, rr=(1.0, 2.0, 3.0))
    for plan in (s.pullback, s.breakout):
        assert plan.stop == pytest.approx(plan.entry - 2.0 * s.atr)
        assert plan.risk == pytest.approx(plan.entry - plan.stop)
        for mult, target in zip(s.rr, plan.targets, strict=True):
            assert target == pytest.approx(plan.entry + mult * plan.risk)
