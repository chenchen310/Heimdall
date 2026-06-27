"""Technical indicator wrappers return canonical, sane outputs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from heimdall.factors.indicators import atr, bollinger, macd, rsi, sma


def _close() -> pd.Series:
    rng = np.random.default_rng(0)
    return pd.Series(100 + np.cumsum(rng.normal(0, 1, 300)))


def test_sma_named_and_lagged() -> None:
    out = sma(_close(), 50)
    assert out.name == "sma_50"
    assert out.iloc[:49].isna().all() and out.iloc[49:].notna().all()


def test_rsi_bounded_0_100() -> None:
    out = rsi(_close(), 14)
    assert out.name == "rsi_14"
    valid = out.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_macd_returns_three_aligned_series() -> None:
    line, signal, hist = macd(_close())
    assert (line.name, signal.name, hist.name) == ("macd", "macd_signal", "macd_hist")
    assert len(line) == len(signal) == len(hist) == 300


def test_atr_named_and_nonnegative() -> None:
    c = _close()
    out = atr(c + 1.0, c - 1.0, c, 14)
    assert out.name == "atr_14"
    assert (out.dropna() >= 0).all()


def test_bollinger_bands_ordered() -> None:
    upper, mid, lower = bollinger(_close(), 20)
    valid = upper.notna()
    assert (upper[valid] >= mid[valid]).all() and (mid[valid] >= lower[valid]).all()
