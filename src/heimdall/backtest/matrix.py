"""Wide daily price matrices for portfolio backtests (roadmap 18.3).

The daily portfolio engine needs every name's adjusted **open** and **close** on one date axis.
These matrices (date × symbol) are derived from the local price cache only
(``data/prices/{market}/{ticker}.parquet``) — they never touch the network, so building them
costs no provider quota. ``adj_open = open × adj_close / close`` puts the open on the same
split/dividend basis as the adjusted close.

Delta-only, like the cache: :func:`update_matrices` appends dates after the stored last date for
known symbols and adds full history only for symbols it has never seen. Pass ``rebuild=True``
after a vendor re-adjustment. Ingest validation (``validate_ohlcv``) rejects negative prices;
the returned :class:`MatrixReport` lists missing caches and interior gaps instead of hiding them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.data.cache import _read
from heimdall.data.store import data_root, prices_path
from heimdall.data.symbols import parse_symbol

FIELDS: tuple[str, ...] = ("adj_open", "adj_close", "volume")


@dataclass
class MatrixReport:
    n_symbols: int
    n_dates: int
    missing: list[str] = field(default_factory=list)  # symbols with no cached prices
    gaps: dict[str, int] = field(default_factory=dict)  # interior missing closes per symbol
    appended_rows: int = 0


def matrix_path(fld: str, market_key: str = "us", root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "research" / "matrix" / f"{market_key}_{fld}.parquet"


def _symbol_rows(symbol: str, root: Path, since: pd.Timestamp | None) -> pd.DataFrame | None:
    """One symbol's cached bars as ``date, adj_open, adj_close, volume`` (after ``since``)."""
    path = prices_path(root, parse_symbol(symbol))
    if not path.exists():
        return None
    df = _read(path)  # validate_ohlcv: no negative prices/volume, sorted unique dates
    if since is not None:
        df = df[df["date"] > since]
    close = df["close"].astype(float)
    ratio = (df["adj_close"].astype(float) / close).where(close > 0)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "adj_open": df["open"].astype(float) * ratio,
            "adj_close": df["adj_close"].astype(float),
            "volume": df["volume"].astype(float),
        }
    )


def build_matrices(
    symbols: list[str], *, root: Path | None = None, since: pd.Timestamp | None = None
) -> tuple[dict[str, pd.DataFrame], MatrixReport]:
    """Wide ``{field: date × symbol}`` frames from the cache (rows after ``since`` only)."""
    base = root if root is not None else data_root()
    cols: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
    missing: list[str] = []
    for sym in symbols:
        rows = _symbol_rows(sym, base, since)
        if rows is None:
            missing.append(sym)
            continue
        idx = pd.DatetimeIndex(rows["date"])
        for f in FIELDS:
            cols[f][sym] = pd.Series(rows[f].to_numpy(), index=idx)
    out = {f: pd.DataFrame(cols[f]).sort_index() for f in FIELDS}
    close = out["adj_close"]
    report = MatrixReport(
        n_symbols=close.shape[1], n_dates=close.shape[0], missing=missing, gaps=_gaps(close)
    )
    return out, report


def _gaps(close: pd.DataFrame) -> dict[str, int]:
    """Interior NaN closes per symbol (between its first and last valid bar)."""
    out: dict[str, int] = {}
    for sym in close.columns:
        s = close[sym]
        first, last = s.first_valid_index(), s.last_valid_index()
        if first is None or last is None:
            continue
        n = int(s.loc[first:last].isna().sum())
        if n:
            out[str(sym)] = n
    return out


def load_matrices(market_key: str = "us", root: Path | None = None) -> dict[str, pd.DataFrame]:
    """The stored matrices; raises ``FileNotFoundError`` when not built yet."""
    out: dict[str, pd.DataFrame] = {}
    for f in FIELDS:
        path = matrix_path(f, market_key, root)
        if not path.exists():
            raise FileNotFoundError(f"no price matrix at {path}; run update_matrices first")
        out[f] = pd.read_parquet(path)
    return out


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(tmp)
    os.replace(tmp, path)


def update_matrices(
    symbols: list[str],
    *,
    market_key: str = "us",
    root: Path | None = None,
    rebuild: bool = False,
) -> MatrixReport:
    """Delta-update the stored matrices for ``symbols``; return what was ingested."""
    try:
        existing = None if rebuild else load_matrices(market_key, root)
    except FileNotFoundError:
        existing = None
    if existing is None:
        fresh, report = build_matrices(symbols, root=root)
        report.appended_rows = int(fresh["adj_close"].notna().sum().sum())
        for f in FIELDS:
            _write(fresh[f], matrix_path(f, market_key, root))
        return report

    last = pd.Timestamp(existing["adj_close"].index.max())
    known = [s for s in symbols if s in existing["adj_close"].columns]
    new = [s for s in symbols if s not in existing["adj_close"].columns]
    tail, rep_tail = build_matrices(known, root=root, since=last)
    head, rep_new = build_matrices(new, root=root)
    merged: dict[str, pd.DataFrame] = {}
    for f in FIELDS:
        dates = existing[f].index.union(tail[f].index).union(head[f].index)
        syms = list(existing[f].columns) + [s for s in head[f].columns]
        frame = existing[f].reindex(index=dates, columns=syms)
        if not tail[f].empty:
            frame.loc[tail[f].index, tail[f].columns] = tail[f].to_numpy()
        if not head[f].empty:
            frame.loc[head[f].index, head[f].columns] = head[f].to_numpy()
        merged[f] = frame.astype(float)
        _write(merged[f], matrix_path(f, market_key, root))
    close = merged["adj_close"]
    return MatrixReport(
        n_symbols=close.shape[1],
        n_dates=close.shape[0],
        missing=rep_tail.missing + rep_new.missing,
        gaps=_gaps(close),
        appended_rows=int(np.nansum(tail["adj_close"].notna().to_numpy()))
        + int(np.nansum(head["adj_close"].notna().to_numpy())),
    )
