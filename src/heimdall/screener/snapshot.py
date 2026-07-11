"""Snapshot table — one row per symbol with every screenable metric.

Per-symbol assembly lives in ``factors.metrics.snapshot_row`` (shared with the
factor panel); this module builds the universe-wide cross-section and persists
it. The screener evaluates predicates over this table. See ``docs/ARCHITECTURE.md``
§5–6.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.store import data_root
from heimdall.data.symbols import MARKET_REGION, parse_symbol
from heimdall.factors.metrics import snapshot_row

#: Warm-up for TW revenue-momentum: rev_mom_accel needs ~19 known months (mirrors
#: research.dataset's build warm-up so a snapshot row and a panel row agree).
_MONTHLY_REVENUE_LOOKBACK = timedelta(days=650)

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

# Snapshot columns denominated in the symbol's currency (USD for US, TWD for TW).
# A threshold on these is market-specific — ``market_cap > 1e9`` means very different
# things in USD vs TWD — so the UI labels them with the active currency and warns when a
# screen using them is loaded under a different market. Ratios (pe, roe, margins, …) and
# returns are unit-free and omitted.
MONETARY_FIELDS: frozenset[str] = frozenset(
    {
        "price",
        "sma_20",
        "sma_50",
        "sma_200",
        "market_cap",
        "ev",
        "net_debt",
        "ebitda",
        "revenue",
        "net_income",
        "eps_diluted",
        "equity",
        "fcf",
        "dollar_vol_21d",
    }
)

# Snapshot columns stored as a decimal fraction (0.15 == 15%). Typing a threshold in the
# screener's editor as a raw fraction is an easy-to-miss trap (a user wanting "ROE above
# 15%" naturally types 15, not 0.15) — the UI converts to/from percentage points at the
# editing boundary for exactly these fields, so the number on screen always matches the
# number a human would say out loud.
PERCENT_FIELDS: frozenset[str] = frozenset(
    {
        "ret_3m",
        "ret_6m",
        "ret_12m",
        "ret_12_1",
        "vol_63d",
        "pct_above_sma_200",
        "fcf_yield",
        "net_margin",
        "gross_margin",
        "operating_margin",
        "fcf_margin",
        "roe",
        "roic",
        "revenue_growth_yoy",
        "eps_growth_yoy",
        "share_dilution_yoy",
        "buyback_yield",
        "rev_mom_yoy",
        "rev_mom_accel",
    }
)

# Unitless ratios/multiples (e.g. "22.4x") — not a percentage, not currency, so the UI
# suffixes them with "×" rather than "%" to avoid the two being confused for each other.
MULTIPLE_FIELDS: frozenset[str] = frozenset(
    {
        "pe",
        "ps",
        "peg",
        "ev_ebitda",
        "ev_fcf",
        "debt_to_equity",
        "net_debt_to_ebitda",
        "interest_coverage",
    }
)


def build_row(
    symbol: str,
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date,
    *,
    monthly_revenue: Callable[[str, date, date], pd.DataFrame] | None = None,
    sector_map: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """One snapshot row, or ``None`` if the symbol has no price data.

    A symbol whose fundamentals a provider cannot serve (e.g. a VTI holding with
    no SEC CIK) degrades to **price-only** — the row still carries technicals
    rather than being dropped, which keeps the screener's universe wide. Network
    and unexpected errors propagate so the caller can decide (the build CLI skips
    and records them).

    ``monthly_revenue`` is the same injectable TW-revenue callable
    ``research.dataset.build_dataset_iter`` takes (roadmap 11.2); a snapshot may
    mix US and TW symbols in one call (``--market all``, or pasted custom
    symbols), so — unlike the single-market research panel — it is always safe
    to pass this for every build: a non-TW symbol's fetch raises
    ``NotSupported``/``ProviderError``, caught here and treated as "no monthly
    revenue" (the row still gets the ``rev_mom_*`` columns, as NaN), so the
    resulting table has one consistent schema regardless of market mix.

    ``sector_map`` (roadmap 14.1) is a plain ``{symbol: sector}`` lookup — the
    network fetch happens once, up front, for the whole universe (see
    ``screener.universe``), not per row. When given, every row gets a
    ``sector`` string, "Unknown" for a symbol missing from the map (never a
    dropped row); when omitted entirely, the column is omitted entirely — the
    same opt-in-or-absent convention as ``monthly_revenue``'s ``rev_mom_*``.
    """
    price_start = as_of - timedelta(days=500)  # enough history for SMA-200
    ohlcv = prices.get_ohlcv(symbol, price_start, as_of)
    if ohlcv.empty:
        return None
    try:
        fund = fundamentals.get_fundamentals(symbol, "all", "annual")
    except (ProviderError, NotSupported):
        fund = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    monthly = None
    if monthly_revenue is not None:
        try:
            monthly = monthly_revenue(symbol, as_of - _MONTHLY_REVENUE_LOOKBACK, as_of)
        except (ProviderError, NotSupported):
            monthly = pd.DataFrame()
    row = snapshot_row(symbol, ohlcv, fund, as_of, monthly=monthly)
    if sector_map is not None:
        row["sector"] = sector_map.get(symbol, "Unknown")
    return row


def build_snapshot(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date | None = None,
    *,
    monthly_revenue: Callable[[str, date, date], pd.DataFrame] | None = None,
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Build the snapshot table for ``symbols`` as known on ``as_of`` (default today)."""
    as_of = as_of or date.today()
    rows = [
        row
        for symbol in symbols
        if (
            row := build_row(
                symbol,
                prices,
                fundamentals,
                as_of,
                monthly_revenue=monthly_revenue,
                sector_map=sector_map,
            )
        )
        is not None
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
    monthly_revenue: Callable[[str, date, date], pd.DataFrame] | None = None,
    sector_map: dict[str, str] | None = None,
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
            row = build_row(
                symbol,
                prices,
                fundamentals,
                as_of,
                monthly_revenue=monthly_revenue,
                sector_map=sector_map,
            )
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
