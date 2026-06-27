"""Technical dashboard payload: fields, trend, support/resistance, setup."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heimdall.analytics.technical import technical_report


def _ohlcv(n: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = pd.Series(100 + np.linspace(0, 30, n) + 3 * np.sin(np.arange(n) / 10), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "adj_close": close,
        }
    )


def test_report_fields_and_uptrend() -> None:
    tr = technical_report("X.US", _ohlcv())
    assert set(tr.trend) == {"short", "medium", "long"}
    assert 0 <= tr.rsi_14 <= 100
    assert {"0.0%", "100.0%"} <= set(tr.fibonacci)
    assert tr.setup.entry == pytest.approx(tr.price)
    assert tr.trend["long"] == "up"  # steady uptrend → 50MA above 200MA


def test_support_below_price_resistance_above() -> None:
    tr = technical_report("X.US", _ohlcv())
    assert all(s < tr.price for s in tr.support)
    assert all(r > tr.price for r in tr.resistance)
