"""``CachedProvider`` — wraps a provider with a delta-fetching Parquet cache.

Once a date range is on disk we never re-fetch it: only the missing head/tail
ranges are requested from the underlying provider, then appended. This is the
main defense against provider rate limits. See ``.claude/rules/data-discipline.md``
(delta-only) and ``docs/ARCHITECTURE.md`` §4.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider
from heimdall.data.schema import OHLCV_COLUMNS, validate_ohlcv
from heimdall.data.store import data_root, prices_path
from heimdall.data.symbols import parse_symbol

_DAY = timedelta(days=1)


class CachedProvider(DataProvider):
    """Persistence/delta layer around any :class:`DataProvider`.

    The wrapped provider stays stateless about caching; this class owns the
    on-disk Parquet store and decides what (if anything) needs fetching.
    """

    def __init__(self, provider: DataProvider, root: Path | None = None) -> None:
        self._provider = provider
        self._root = root if root is not None else data_root()

    @property
    def markets(self) -> frozenset[str]:  # type: ignore[override]
        return self._provider.markets

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        sym = parse_symbol(symbol)
        path = prices_path(self._root, sym)
        cached = _read(path)

        for lo, hi in _missing_ranges(cached, start, end):
            fetched = self._provider.get_ohlcv(symbol, lo, hi)
            cached = _merge(cached, fetched)

        if not cached.empty:
            _write(path, cached)

        return _slice(cached, start, end)


# --- pure helpers (no I/O state) -------------------------------------------
def _read(path: Path) -> pd.DataFrame:
    if path.exists():
        return validate_ohlcv(pd.read_parquet(path))
    return pd.DataFrame(columns=OHLCV_COLUMNS)


def _write(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _missing_ranges(cached: pd.DataFrame, start: date, end: date) -> list[tuple[date, date]]:
    """Head/tail gaps in ``[start, end]`` not already covered by ``cached``.

    Assumes the cache is contiguous between its min and max date (true for EOD
    daily pulls); interior trading-day gaps are not re-fetched.
    """
    if cached.empty:
        return [(start, end)]
    have_lo = cached["date"].min().date()
    have_hi = cached["date"].max().date()
    ranges: list[tuple[date, date]] = []
    if start < have_lo:
        ranges.append((start, min(end, have_lo - _DAY)))
    if end > have_hi:
        ranges.append((max(start, have_hi + _DAY), end))
    return ranges


def _merge(cached: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    if fetched.empty:
        return cached
    if cached.empty:  # avoid concat with an all-NA empty frame (pandas 2.x warning)
        return validate_ohlcv(fetched)
    combined = pd.concat([cached, fetched], ignore_index=True)
    combined = combined.drop_duplicates(subset="date", keep="last")
    return validate_ohlcv(combined)


def _slice(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    return df.loc[mask].reset_index(drop=True)
