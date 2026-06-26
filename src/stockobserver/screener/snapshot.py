"""Snapshot table — one row per symbol with every screenable metric.

Per-symbol assembly lives in ``factors.metrics.snapshot_row`` (shared with the
factor panel); this module builds the universe-wide cross-section and persists
it. The screener evaluates predicates over this table. See ``docs/ARCHITECTURE.md``
§5–6.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stockobserver.data.base import DataProvider
from stockobserver.data.store import data_root
from stockobserver.factors.metrics import snapshot_row

# Small default US universe for Phase 1 (extend freely; full index lists later).
DEFAULT_UNIVERSE: list[str] = [
    "AAPL.US",
    "MSFT.US",
    "NVDA.US",
    "GOOGL.US",
    "AMZN.US",
    "META.US",
    "TSLA.US",
    "JPM.US",
    "JNJ.US",
    "WMT.US",
    "XOM.US",
    "PG.US",
    "KO.US",
    "INTC.US",
    "CSCO.US",
]


def build_snapshot(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Build the snapshot table for ``symbols`` as known on ``as_of`` (default today)."""
    as_of = as_of or date.today()
    price_start = as_of - timedelta(days=500)  # enough history for SMA-200
    rows: list[dict[str, object]] = []

    for symbol in symbols:
        ohlcv = prices.get_ohlcv(symbol, price_start, as_of)
        if ohlcv.empty:
            continue
        fund = fundamentals.get_fundamentals(symbol, "all", "annual")
        rows.append(snapshot_row(symbol, ohlcv, fund, as_of))

    return pd.DataFrame(rows)


def snapshot_path(root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "snapshot.parquet"


def save_snapshot(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = snapshot_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_snapshot(root: Path | None = None) -> pd.DataFrame:
    path = snapshot_path(root)
    if not path.exists():
        raise FileNotFoundError(f"no snapshot at {path}; build one first")
    return pd.read_parquet(path)
