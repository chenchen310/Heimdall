"""FinMind paced crawler — pre-warm the full ~2,130-name TW streams to disk (roadmap 13.7).

The 11.4 constraint (RESEARCH_LOG entry 004): FinMind's free tier serves ~600
requests/hour, enforced as a ~26-minute IP ban (403 ``ip banned``) then 402
``quota reached``. A full TW panel needs ~7 calls/symbol (fundamentals 3 + revenue
1 + chips 3, +1 lending) → ~15k calls ≈ **9+ quota-hours** for 2,130 names — not a
one-session build. This module makes that a **resumable background chore**: a
paced pre-warmer that calls the same ``FinMindProvider`` methods the panel uses
and persists each ``(symbol, dataset)`` result to a disk **stream cache**, with a
per-``(symbol, dataset)`` ledger so an interrupt-then-rerun makes **zero**
duplicate calls, and quota/ban backoff that sleeps until the window resets rather
than crashing.

**Layer note:** the card's suggested path was ``data/finmind_crawl.py``, but its
own Step 2 iterates ``screener.universe.tw_symbols()`` — and ``data/`` may never
import ``screener`` (the one-way rule in ``heimdall/CLAUDE.md``; no ``data/``
module does). Universe-iterating provider-orchestrators already live in
``research/`` (``build_dataset.py``, ``tdcc_cache.py``), so this lives here too.

There is **one** stream-cache format (never a second): one Parquet per
``(dataset, symbol)`` under ``data/research/streams/{dataset}/`` — the canonical
schema each provider method already returns — plus ``streams/_ledger.json``.
:func:`load_cached_stream` reads it back with a provider-method-shaped signature
so a later full-panel build (roadmap 13.8) can wire the cache in place of live
FinMind calls.

    uv run python -m heimdall.research.finmind_crawl --datasets revenue,chips \
        --budget-per-hour 550           # detached / overnight / across days
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from heimdall.data.base import ProviderError
from heimdall.data.providers import FinMindProvider
from heimdall.data.store import data_root
from heimdall.data.symbols import parse_symbol
from heimdall.screener.universe import tw_symbols

# Dataset → nominal FinMind calls (for hourly-budget pacing). Mirrors the 11.4
# measurement: fundamentals fans out to 3 statement datasets, chips to 3
# (institutional + shareholding + margin); revenue and lending are 1 each.
DATASET_CALLS: dict[str, int] = {"revenue": 1, "chips": 3, "fundamentals": 3, "lending": 1}
DATASETS: tuple[str, ...] = tuple(DATASET_CALLS)

_DEFAULT_START = date(2010, 1, 1)  # deep enough for every feature's warm-up
_HOUR_S = 3600.0
_DEFAULT_BAN_S = 1600.0  # ~26-min window reset (11.4); operator-tunable


def streams_root(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "research" / "streams"


def stream_cache_path(dataset: str, canonical: str, root: Path | None = None) -> Path:
    """One Parquet per (dataset, symbol): ``streams/{dataset}/{TICKER_MARKET}.parquet``."""
    return streams_root(root) / dataset / f"{canonical.replace('.', '_')}.parquet"


def ledger_path(root: Path | None = None) -> Path:
    return streams_root(root) / "_ledger.json"


def _load_ledger(root: Path | None) -> dict[str, dict[str, object]]:
    path = ledger_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def _save_ledger(ledger: dict[str, dict[str, object]], root: Path | None) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True))
    os.replace(tmp, path)


def _fetch(
    provider: FinMindProvider, dataset: str, symbol: str, start: date, end: date
) -> pd.DataFrame:
    """Dispatch to the provider method that owns ``dataset`` (the live network call)."""
    if dataset == "revenue":
        return provider.monthly_revenue(symbol, start, end)
    if dataset == "chips":
        return provider.daily_chips(symbol, start, end)
    if dataset == "fundamentals":
        return provider.get_fundamentals(symbol, "all", "annual")
    if dataset == "lending":
        return provider.daily_lending(symbol, start, end)
    raise ValueError(f"unknown dataset {dataset!r}; expected one of {DATASETS}")


def _is_quota_error(exc: Exception) -> bool:
    """True for a FinMind quota/ban rejection (402 quota, 403 ip-ban) — the retryable
    ones — vs a genuine failure (a broken symbol, a 500) that should not spin forever.
    Matches the messages ``FinMindProvider._get`` raises."""
    if not isinstance(exc, ProviderError):
        return False
    msg = str(exc).lower()
    return any(marker in msg for marker in ("quota", "banned", "402", "403"))


def load_cached_stream(
    dataset: str,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    root: Path | None = None,
) -> pd.DataFrame:
    """Read one crawled stream back (roadmap 13.8's offline substrate). Signature
    mirrors the provider methods (``symbol, start, end``) so it is a drop-in for a
    live ``monthly_revenue``/``daily_chips`` callable; ``start``/``end`` are accepted
    for that compatibility but not applied — the cache holds full history and the
    panel's feature functions do their own point-in-time windowing. Missing cache →
    an empty frame (the symbol simply was not crawled)."""
    path = stream_cache_path(dataset, parse_symbol(symbol).canonical, root)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


@dataclass
class CrawlProgress:
    """Mutated and re-yielded per item — read live, don't collect (build_dataset mould)."""

    total: int
    done: int = 0  # items reaching a terminal state this run (ok + empty + failed)
    cached: int = 0  # skipped: already in the ledger
    ok: int = 0  # fetched with rows
    empty: int = 0  # fetched, no rows (still recorded, never re-fetched)
    failed: int = 0  # non-quota error (recorded, not retried)
    calls: int = 0  # nominal FinMind calls spent this run
    bans: int = 0  # quota/ban backoffs waited out
    current: str = ""
    finished: bool = False


def crawl(
    symbols: list[str],
    provider: FinMindProvider,
    *,
    datasets: tuple[str, ...] = DATASETS,
    start: date = _DEFAULT_START,
    end: date | None = None,
    root: Path | None = None,
    budget_per_hour: int = 550,
    ban_seconds: float = _DEFAULT_BAN_S,
    refresh: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Iterator[CrawlProgress]:
    """Crawl ``symbols × datasets``, caching each result, yielding progress per item.

    Resumable: an item already in the ledger is skipped (``refresh=True`` re-fetches
    everything). Paced: at most ``budget_per_hour`` nominal FinMind calls per rolling
    hour. Resilient: a 402/403 quota-ban sleeps ``ban_seconds`` (resetting the budget
    window) and **retries the same item** — it is never marked done until it truly
    completes, so an interrupt loses no progress and repeats no completed call.
    ``sleep``/``monotonic`` are injected so tests run offline with no real waits.
    """
    end = end or date.today()
    ledger = _load_ledger(root)
    worklist = [(s, d) for s in symbols for d in datasets]
    prog = CrawlProgress(total=len(worklist))

    window_start = monotonic()
    calls_window = 0

    for symbol, dataset in worklist:
        key = f"{symbol}::{dataset}"
        prog.current = key
        if not refresh and key in ledger:
            prog.cached += 1
            yield prog
            continue

        cost = DATASET_CALLS[dataset]
        # Budget gate: if this item would breach the hourly cap, wait out the window.
        if calls_window + cost > budget_per_hour:
            elapsed = monotonic() - window_start
            if elapsed < _HOUR_S:
                sleep(_HOUR_S - elapsed)
            window_start = monotonic()
            calls_window = 0

        # Fetch with quota/ban backoff — retry the SAME item until it resolves.
        while True:
            try:
                df = _fetch(provider, dataset, symbol, start, end)
            except Exception as exc:  # noqa: BLE001 — classify, then retry or record
                if _is_quota_error(exc):
                    prog.bans += 1
                    yield prog  # surface the wait before blocking on it
                    sleep(ban_seconds)
                    window_start = monotonic()  # the ban IS a window reset
                    calls_window = 0
                    continue
                # A genuine failure (broken symbol, unsupported, 5xx): record, move on.
                ledger[key] = {"status": "failed", "error": type(exc).__name__}
                _save_ledger(ledger, root)
                prog.failed += 1
                prog.done += 1
                break
            calls_window += cost
            prog.calls += cost
            path = stream_cache_path(dataset, parse_symbol(symbol).canonical, root)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
            n = len(df)
            ledger[key] = {"status": "ok" if n else "empty", "rows": n}
            _save_ledger(ledger, root)
            prog.ok += 1 if n else 0
            prog.empty += 0 if n else 1
            prog.done += 1
            break
        yield prog

    prog.finished = True
    prog.current = ""
    yield prog


def _parse_datasets(s: str) -> tuple[str, ...]:
    chosen = tuple(d.strip() for d in s.split(",") if d.strip())
    bad = [d for d in chosen if d not in DATASET_CALLS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown dataset(s) {bad}; choose from {list(DATASETS)}")
    return chosen


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description="Pre-warm the full TW FinMind streams to disk (13.7)")
    p.add_argument("--datasets", type=_parse_datasets, default=DATASETS, help=f"{list(DATASETS)}")
    p.add_argument("--symbols", default=None, help="comma-separated canonical symbols (override)")
    p.add_argument("--limit", type=int, default=None, help="cap the universe (testing/batching)")
    p.add_argument("--budget-per-hour", type=int, default=550, help="nominal FinMind calls/hour")
    p.add_argument("--refresh", action="store_true", help="ignore the ledger; re-fetch everything")
    args = p.parse_args(argv)

    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else tw_symbols()
    )
    if args.limit:
        symbols = symbols[: args.limit]
    datasets = args.datasets if isinstance(args.datasets, tuple) else _parse_datasets(args.datasets)

    print(
        f"Crawling {len(symbols)} symbols × {len(datasets)} datasets "
        f"({len(symbols) * len(datasets)} items) at ≤{args.budget_per_hour} calls/hr → "
        f"{streams_root()}"
    )
    last = CrawlProgress(total=0)
    for last in crawl(
        symbols,
        FinMindProvider(),
        datasets=datasets,
        budget_per_hour=args.budget_per_hour,
        refresh=args.refresh,
    ):
        if last.finished:
            break
        seen = last.done + last.cached
        if seen % 50 == 0 or last.bans:
            print(
                f"  [{seen}/{last.total}] {last.current} "
                f"ok={last.ok} empty={last.empty} failed={last.failed} "
                f"cached={last.cached} calls={last.calls} bans={last.bans}",
                flush=True,
            )
    print(
        f"\nDone. ok={last.ok} empty={last.empty} failed={last.failed} "
        f"cached(skipped)={last.cached} FinMind calls this run={last.calls} bans={last.bans}"
        f"\nStreams on disk: {streams_root()} — resumable; re-run to continue."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
