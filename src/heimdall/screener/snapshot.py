"""Snapshot table — one row per symbol with every screenable metric.

Per-symbol assembly lives in ``factors.metrics.snapshot_row`` (shared with the
factor panel); this module builds the universe-wide cross-section and persists
it. The screener evaluates predicates over this table. See ``docs/ARCHITECTURE.md``
§5–6.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.store import data_root
from heimdall.data.symbols import MARKET_REGION, parse_symbol
from heimdall.factors.metrics import snapshot_row

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

# Small liquid Taiwan universe (Phase 6) — TWSE large caps. Prices via yfinance,
# fundamentals via FinMind (both keyed off the .TW market suffix by the router).
TW_UNIVERSE: list[str] = [
    "2330.TW",  # TSMC
    "2317.TW",  # Hon Hai (Foxconn)
    "2454.TW",  # MediaTek
    "2308.TW",  # Delta Electronics
    "2412.TW",  # Chunghwa Telecom
    "2882.TW",  # Cathay Financial
    "2881.TW",  # Fubon Financial
    "2303.TW",  # UMC
    "3008.TW",  # Largan Precision
    "1301.TW",  # Formosa Plastics
]

# Named universes for the snapshot builder's --market flag.
UNIVERSES: dict[str, list[str]] = {
    "us": DEFAULT_UNIVERSE,
    "tw": TW_UNIVERSE,
    "all": DEFAULT_UNIVERSE + TW_UNIVERSE,
}


def build_row(
    symbol: str,
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date,
) -> dict[str, object] | None:
    """One snapshot row, or ``None`` if the symbol has no price data.

    A symbol whose fundamentals a provider cannot serve (e.g. a VTI holding with
    no SEC CIK) degrades to **price-only** — the row still carries technicals
    rather than being dropped, which keeps the screener's universe wide. Network
    and unexpected errors propagate so the caller can decide (the build CLI skips
    and records them).
    """
    price_start = as_of - timedelta(days=500)  # enough history for SMA-200
    ohlcv = prices.get_ohlcv(symbol, price_start, as_of)
    if ohlcv.empty:
        return None
    try:
        fund = fundamentals.get_fundamentals(symbol, "all", "annual")
    except (ProviderError, NotSupported):
        fund = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    return snapshot_row(symbol, ohlcv, fund, as_of)


def build_snapshot(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Build the snapshot table for ``symbols`` as known on ``as_of`` (default today)."""
    as_of = as_of or date.today()
    rows = [
        row
        for symbol in symbols
        if (row := build_row(symbol, prices, fundamentals, as_of)) is not None
    ]
    return pd.DataFrame(rows)


@dataclass
class BuildProgress:
    """Live progress of a snapshot build — mutated and re-yielded per symbol."""

    total: int  # symbols to fetch this run (excludes those already built, on resume)
    done: int = 0  # symbols processed so far this run
    built: int = 0  # rows successfully built (``done`` minus skips/errors)
    failures: dict[str, int] = field(default_factory=dict)  # exception name -> count
    last_symbol: str = ""
    finished: bool = False


def build_snapshot_iter(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date,
    *,
    resume: bool = True,
    checkpoint_every: int = 50,
    root: Path | None = None,
) -> Iterator[BuildProgress]:
    """Resumable, checkpointed build that yields progress after each symbol.

    The same crawl the ``build`` CLI runs, exposed as an iterator so the UI can
    drive a progress bar and the CLI can print — the loop lives in one place. On
    ``resume`` (default) existing rows are kept and symbols already in the snapshot
    are skipped; the table is flushed to disk every ``checkpoint_every`` symbols and
    once more at the end. A per-symbol error is tallied, never fatal.

    Yields an initial ``BuildProgress`` (``done == 0``) once the plan is known, one
    after each symbol, and a final one with ``finished=True``. The yielded object is
    reused (mutated) across iterations — read it live, don't collect it into a list.
    """
    existing = pd.DataFrame()
    if resume:
        with contextlib.suppress(FileNotFoundError):
            existing = load_snapshot(root)
    done_syms = set(existing["symbol"]) if not existing.empty else set()
    todo = [s for s in symbols if s not in done_syms]
    rows: list[dict[str, object]] = (
        existing.to_dict("records") if not existing.empty else []  # type: ignore[assignment]
    )

    prog = BuildProgress(total=len(todo))
    yield prog  # initial plan, before any fetch
    if not todo:
        prog.finished = True
        yield prog
        return

    for i, symbol in enumerate(todo, start=1):
        try:
            row = build_row(symbol, prices, fundamentals, as_of)
        except Exception as exc:  # network/provider hiccup — skip, don't abort the crawl
            prog.failures[type(exc).__name__] = prog.failures.get(type(exc).__name__, 0) + 1
            row = None
        if row is not None:
            rows.append(row)
            prog.built += 1
        prog.done, prog.last_symbol = i, symbol
        if i % checkpoint_every == 0:
            save_snapshot(pd.DataFrame(rows), root)
        yield prog

    save_snapshot(pd.DataFrame(rows), root)
    prog.finished = True
    yield prog


def split_by_region(snap: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Partition a snapshot into per-region tables (``US`` first, then ``Taiwan``).

    Reporting currency differs by market (USD vs TWD), so a single mixed table makes
    the price/market-cap columns non-comparable and any sort across them meaningless.
    The UI shows one region — hence one currency — at a time. Region is derived from
    each symbol's canonical market suffix, so it stays correct even against an older
    snapshot whose stored ``currency`` column predates the per-market fix.
    """
    if snap.empty or "symbol" not in snap.columns:
        return {}
    region = snap["symbol"].map(lambda s: parse_symbol(str(s)).region)
    order = list(dict.fromkeys(MARKET_REGION.values()))  # US, Taiwan — definition order
    return {r: snap[region == r].reset_index(drop=True) for r in order if (region == r).any()}


def snapshot_path(root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "snapshot.parquet"


def save_snapshot(df: pd.DataFrame, root: Path | None = None) -> Path:
    """Write atomically (temp file + rename) so a concurrent reader — the UI polling
    progress mid-build — sees either the old snapshot or the new one, never a
    half-written file. The ``pid`` in the temp name keeps a background build and an
    in-app build from clobbering each other's temp."""
    path = snapshot_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return path


def load_snapshot(root: Path | None = None) -> pd.DataFrame:
    path = snapshot_path(root)
    if not path.exists():
        raise FileNotFoundError(f"no snapshot at {path}; build one first")
    return pd.read_parquet(path)
