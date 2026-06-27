"""Golden test: raw yfinance shape → canonical OHLCV (no network)."""

from __future__ import annotations

import pandas as pd

from heimdall.data.providers.yfinance import _normalize
from heimdall.data.schema import OHLCV_COLUMNS
from heimdall.data.symbols import Symbol


def _raw_yf_frame() -> pd.DataFrame:
    """Mimic ``yf.download`` for one ticker: (Price, Ticker) MultiIndex columns,
    ``Date`` index, intentionally unsorted to exercise normalization."""
    idx = pd.DatetimeIndex(["2024-01-03", "2024-01-02"], name="Date")
    cols = pd.MultiIndex.from_product(
        [["Adj Close", "Close", "High", "Low", "Open", "Volume"], ["AAPL"]]
    )
    data = [
        [182.1, 184.2, 185.8, 183.4, 184.2, 58_000_000],  # 2024-01-03
        [183.5, 185.6, 188.4, 183.8, 187.1, 82_000_000],  # 2024-01-02
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def test_normalize_to_canonical() -> None:
    out = _normalize(_raw_yf_frame(), Symbol("AAPL", "US"))

    assert list(out.columns) == OHLCV_COLUMNS
    assert out["symbol"].unique().tolist() == ["AAPL.US"]
    assert out["currency"].unique().tolist() == ["USD"]
    assert out["provider"].unique().tolist() == ["yfinance"]
    # sorted ascending by date despite unsorted input
    assert out["date"].is_monotonic_increasing
    # first row is 2024-01-02 with its raw (not adjusted) open
    first = out.iloc[0]
    assert first["date"] == pd.Timestamp("2024-01-02")
    assert first["open"] == 187.1
    assert first["adj_close"] == 183.5


def test_normalize_empty() -> None:
    out = _normalize(pd.DataFrame(), Symbol("AAPL", "US"))
    assert out.empty
    assert list(out.columns) == OHLCV_COLUMNS
