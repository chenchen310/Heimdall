"""Daily TW market-wide chip cache (roadmap 15.2) — per-date parquet, delta-only.

Bulk per-date FinMind queries (omit ``data_id``) are refused at the free
``register`` tier (probed 2026-07-08, reconfirmed live 2026-07-11 — a 400
"please update your user level" response; see
``FinMindProvider.bulk_institutional_by_date``). :func:`build_day` tries bulk
first — so a future paid tier unlocks it with no caller-side change — and falls
back to looping the caller's supplied universe (typically the current TW
snapshot's symbols: a bounded, quota-safe "cached-universe loop", per the
card's own fallback clause) through the existing per-symbol
``FinMindProvider.daily_chips``. Coverage (how many of the requested symbols
this actually reached) travels in :class:`BuildResult` and is meant to be
shown on-page, never silently assumed complete.

A multi-day backfill should reuse roadmap 13.7's paced-crawl infrastructure
once that lands, rather than reimplementing quota pacing here — this CLI
builds one date at a time.

    uv run python -m heimdall.research.flows_cache --date 2026-07-10
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider, ProviderError
from heimdall.data.providers.finmind import FinMindProvider
from heimdall.data.store import data_root

DAILY_COLUMNS: list[str] = [
    "symbol",
    "sector",
    "date",
    "foreign_net_shares",
    "trust_net_shares",
    "dealer_net_shares",
    "foreign_hold_ratio",
    "close",
]


def flows_cache_path(d: date, root: Path | None = None) -> Path:
    """The 14.2 contract: ``data/research/flows/institutional_{YYYY-MM-DD}.parquet``."""
    return (root or data_root()) / "research" / "flows" / f"institutional_{d.isoformat()}.parquet"


def _save_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


@dataclass
class BuildResult:
    date: date
    source: str  # "cached" | "bulk" | "loop"
    universe_size: int  # symbols the loop path was given (0 for bulk/cached)
    rows: int  # symbols actually present in the resulting cache


def _from_bulk(bulk: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame:
    """Bulk mode only reaches ``TaiwanStockInstitutionalInvestorsBuySell`` today
    (the one dataset actually probed) — ``close``/``foreign_hold_ratio`` need
    their own bulk endpoints, deferred until a paid tier makes bulk reachable
    at all; they are NaN on this path, never fabricated."""
    out = bulk.copy()
    out["symbol"] = out["stock_id"].astype(str) + ".TW"  # TPEX names need .TWO — bulk mode
    out["sector"] = out["symbol"].map(sector_map).fillna("Unknown")  # can't disambiguate; deferred
    out["close"] = float("nan")
    out["foreign_hold_ratio"] = float("nan")
    return out[DAILY_COLUMNS]


def _from_loop(
    d: date,
    universe: list[str],
    finmind: FinMindProvider,
    prices: DataProvider,
    sector_map: dict[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sym in universe:
        try:
            chips = finmind.daily_chips(sym, d - timedelta(days=1), d)
        except ProviderError:
            break  # quota exhausted or a hard API error — stop, don't burn through the rest
        except Exception:
            continue  # one bad symbol must not kill the whole day's build
        todays = chips[chips["date"] == pd.Timestamp(d)]
        if todays.empty:
            continue
        r = todays.iloc[-1]
        try:
            px = prices.get_ohlcv(sym, d - timedelta(days=7), d)
        except Exception:
            px = pd.DataFrame()
        close = float(px["close"].iloc[-1]) if not px.empty else float("nan")
        rows.append(
            {
                "symbol": sym,
                "sector": sector_map.get(sym, "Unknown"),
                "date": pd.Timestamp(d),
                "foreign_net_shares": r["foreign_net_shares"],
                "trust_net_shares": r["trust_net_shares"],
                "dealer_net_shares": r["dealer_net_shares"],
                "foreign_hold_ratio": r["foreign_hold_ratio"],
                "close": close,
            }
        )
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def build_day(
    d: date,
    universe: list[str],
    finmind: FinMindProvider,
    prices: DataProvider,
    sector_map: dict[str, str],
    *,
    root: Path | None = None,
    refresh: bool = False,
) -> BuildResult:
    """Build (or reuse) one day's market-wide chip cache.

    Tries :meth:`FinMindProvider.bulk_institutional_by_date` first; on refusal
    (``None``) falls back to looping ``universe`` via ``daily_chips``. Delta:
    an existing, non-``refresh`` file is reused untouched (never re-fetched).
    """
    path = flows_cache_path(d, root)
    if not refresh and path.exists():
        existing = pd.read_parquet(path)
        return BuildResult(d, "cached", len(universe), len(existing))

    bulk = finmind.bulk_institutional_by_date(d)
    if bulk is not None and not bulk.empty:
        df = _from_bulk(bulk, sector_map)
        source = "bulk"
    else:
        df = _from_loop(d, universe, finmind, prices, sector_map)
        source = "loop"

    _save_atomic(df, path)
    return BuildResult(d, source, len(universe), len(df))


def load_window(end: date, n_sessions: int, root: Path | None = None) -> pd.DataFrame:
    """Concatenate up to ``n_sessions`` most-recently-cached days on/before
    ``end`` — whichever calendar days actually have a built cache file; a
    weekend/holiday/never-built day is simply absent, never fabricated. Walks
    back at most ``n_sessions × 3`` calendar days (generous slack for
    weekends/holidays) before giving up.
    """
    frames: list[pd.DataFrame] = []
    d, tries = end, 0
    while len(frames) < n_sessions and tries < n_sessions * 3:
        path = flows_cache_path(d, root)
        if path.exists():
            frames.append(pd.read_parquet(path))
        d -= timedelta(days=1)
        tries += 1
    if not frames:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description="Build one day's TW market-wide chip cache")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--rebuild", action="store_true", help="ignore any existing cache for the day")
    args = p.parse_args(argv)
    d = date.fromisoformat(args.date)

    from heimdall.data import router
    from heimdall.data.cache import CachedProvider
    from heimdall.screener.snapshot import load_snapshot, split_by_region
    from heimdall.screener.universe import tw_sector_map

    try:
        tw = split_by_region(load_snapshot()).get("Taiwan")
    except FileNotFoundError:
        tw = None
    universe = list(tw["symbol"]) if tw is not None and not tw.empty else []
    if not universe:
        print("No TW snapshot — build one first (uv run python -m heimdall.screener.build).")
        return 1

    finmind = FinMindProvider()
    prices = CachedProvider(router.price_provider())
    sector_map = tw_sector_map()

    result = build_day(d, universe, finmind, prices, sector_map, refresh=args.rebuild)
    print(
        f"{result.date.isoformat()}: source={result.source} "
        f"rows={result.rows}/{result.universe_size} -> {flows_cache_path(d)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
