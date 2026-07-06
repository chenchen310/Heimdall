"""The persisted research panel — one row per (rebalance month-end, symbol).

This is the dataset every experiment reads (``docs/ROADMAP_V2.md`` 7.3): all
``snapshot_row`` fields (point-in-time by construction), eligibility flags per
``docs/RESEARCH_PLAYBOOK.md`` §3, and forward labels ``fwd_1m/3m/6m`` plus their
benchmark-relative ``*_rel`` variants (§2). Signals never compute here — specs
score this panel later (8.x).

Honesty invariants baked in:

- **PIT**: rows are built by ``factors.metrics.snapshot_row`` with ``as_of`` =
  the rebalance date, so fundamentals are keyed on ``filed_at`` — the machinery
  is reused, not duplicated.
- **Labels**: both the stock and the benchmark leg go through the same
  ``research.benchmark`` primitives, so a ``*_rel`` subtraction covers one
  identical calendar window; incomplete windows are NaN, never partial.
- **Resume never rewrites history**: existing months are skipped (feature
  values are frozen at first write — later vendor restatements must not leak
  in, per ``data-discipline.md``), but still-NaN *labels* are refreshed, since
  they are pure future-price lookups that simply hadn't completed yet.
- **Thin months are dropped and reported** (``meta.dropped_months``), and every
  artifact carries the ``current_universe (optimistic)`` survivorship stamp.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pandas as pd

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.store import data_root
from heimdall.factors.metrics import snapshot_row
from heimdall.factors.panel import _prices_wide, _rebalance_dates
from heimdall.research import gates
from heimdall.research.benchmark import BENCHMARK, forward_return, window_return

LABEL_COLS: list[str] = ["fwd_1m", "fwd_3m", "fwd_6m", "fwd_1m_rel", "fwd_3m_rel", "fwd_6m_rel"]
_MARKET_KEY: dict[str, str] = {"US": "us", "Taiwan": "tw"}


def panel_path(market: str, root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "research" / f"panel_{_MARKET_KEY[market]}.parquet"


def meta_path(market: str, root: Path | None = None) -> Path:
    p = panel_path(market, root)
    return p.with_name(f"{p.stem}.meta.json")


def load_panel(market: str, root: Path | None = None) -> pd.DataFrame:
    path = panel_path(market, root)
    if not path.exists():
        raise FileNotFoundError(f"no research panel at {path}; build one first")
    return pd.read_parquet(path)


def _save_atomic(df: pd.DataFrame, path: Path) -> None:
    """Temp + rename so a concurrent reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


@dataclass
class DatasetProgress:
    """Mutated and re-yielded per month — read live, don't collect."""

    total_months: int
    done_months: int = 0
    month: pd.Timestamp | None = None
    rows: int = 0
    eligible: int = 0
    dropped: list[str] = field(default_factory=list)  # thin months (ISO dates), this run
    relabeled: int = 0  # previously-NaN labels filled on resume
    failures: dict[str, int] = field(default_factory=dict)  # fetch errors, by exception name
    finished: bool = False


def _labels(
    adj: pd.Series, bench_adj: pd.Series, t: pd.Timestamp, next_t: pd.Timestamp | None
) -> dict[str, float]:
    nan = float("nan")
    f1 = window_return(adj, t, next_t) if next_t is not None else nan
    b1 = window_return(bench_adj, t, next_t) if next_t is not None else nan
    f3, b3 = forward_return(adj, t, 63), forward_return(bench_adj, t, 63)
    f6, b6 = forward_return(adj, t, 126), forward_return(bench_adj, t, 126)
    return {
        "fwd_1m": f1,
        "fwd_3m": f3,
        "fwd_6m": f6,
        "fwd_1m_rel": f1 - b1,
        "fwd_3m_rel": f3 - b3,
        "fwd_6m_rel": f6 - b6,
    }


def _eligibility(market: str, n_bars: int, raw_close: float, dollar_vol: float) -> tuple[bool, str]:
    """Playbook §3 hygiene; first failing reason wins. NaN inputs fail their check."""
    if n_bars < gates.MIN_HISTORY_BARS:
        return False, "history"
    if not raw_close >= gates.MIN_PRICE[market]:  # NaN-safe: not (NaN >= x) → ineligible
        return False, "price"
    if not dollar_vol >= gates.MIN_DOLLAR_VOL_21D[market]:
        return False, "liquidity"
    return True, ""


def build_dataset_iter(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    market: str,
    start: date,
    end: date,
    *,
    root: Path | None = None,
    resume: bool = True,
    min_cross_section: int = gates.MIN_CROSS_SECTION,
    checkpoint_every: int = 6,
) -> Iterator[DatasetProgress]:
    """Build (or extend) the panel month by month, yielding progress per month.

    Fetches each symbol's full price/fundamental history once (delta-cached by
    the providers), then computes only the rebalance months not already in the
    parquet. Yields an initial plan row, one row per month, and a final
    ``finished=True`` row after the label-refresh pass and meta write.
    """
    bench_adj = prices.get_ohlcv(BENCHMARK[market], start - timedelta(days=500), end).set_index(
        "date"
    )["adj_close"]

    price_hist: dict[str, pd.DataFrame] = {}
    adj_by_sym: dict[str, pd.Series] = {}
    fund_data: dict[str, pd.DataFrame] = {}
    failures: dict[str, int] = {}
    for sym in symbols:
        try:
            ohlcv = prices.get_ohlcv(sym, start - timedelta(days=500), end)
        except Exception as exc:  # a broken symbol must not kill a long crawl
            failures[type(exc).__name__] = failures.get(type(exc).__name__, 0) + 1
            continue
        if ohlcv.empty:
            continue
        price_hist[sym] = ohlcv
        adj_by_sym[sym] = ohlcv.set_index("date")["adj_close"]
        try:
            fund_data[sym] = fundamentals.get_fundamentals(sym, "all", "annual")
        except (ProviderError, NotSupported):
            fund_data[sym] = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)

    # Existing panel + meta: resume skips computed months AND previously-dropped ones.
    existing = pd.DataFrame()
    old_meta: dict[str, object] = {}
    if resume:
        with contextlib.suppress(FileNotFoundError):
            existing = load_panel(market, root)
        if meta_path(market, root).exists():
            old_meta = json.loads(meta_path(market, root).read_text())
    prior_dropped = set(cast("list[str]", old_meta.get("dropped_months", [])))
    have = set(existing["date"]) if not existing.empty else set()

    # Rebalance calendar over the union of trading days; extend back to the earliest
    # existing month so the label-refresh pass can find every month's successor.
    wide = _prices_wide(price_hist) if price_hist else pd.DataFrame()
    cal_start = min([start, *[d.date() for d in have]]) if have else start
    rebal = (
        _rebalance_dates(wide.index, cal_start, end, "ME")  # type: ignore[arg-type]
        if not wide.empty
        else []
    )
    next_of: dict[pd.Timestamp, pd.Timestamp | None] = {
        t: (rebal[i + 1] if i + 1 < len(rebal) else None) for i, t in enumerate(rebal)
    }
    todo = [
        t
        for t in rebal
        if pd.Timestamp(t) >= pd.Timestamp(start)
        and t not in have
        and t.date().isoformat() not in prior_dropped
    ]

    prog = DatasetProgress(total_months=len(todo), failures=failures)
    yield prog

    frames: list[pd.DataFrame] = [existing] if not existing.empty else []
    for i, t in enumerate(todo, start=1):
        rows: list[dict[str, object]] = []
        for sym, ohlcv in price_hist.items():
            hist = ohlcv[ohlcv["date"] <= t]
            if hist.empty:
                continue
            row = snapshot_row(sym, hist, fund_data[sym], t.date())
            row.update(_labels(adj_by_sym[sym], bench_adj, t, next_of[t]))
            ok, why = _eligibility(
                market,
                len(hist),
                float(hist["close"].iloc[-1]),
                float(row["dollar_vol_21d"]),  # type: ignore[arg-type]
            )
            row["date"] = t
            row["eligible"] = ok
            row["inelig_reason"] = why
            rows.append(row)

        n_eligible = sum(1 for r in rows if r["eligible"])
        prog.done_months, prog.month, prog.rows, prog.eligible = i, t, len(rows), n_eligible
        if n_eligible < min_cross_section:
            prog.dropped.append(t.date().isoformat())  # dropped and reported, never kept
            yield prog
            continue
        frames.append(pd.DataFrame(rows))
        if i % checkpoint_every == 0 and frames:
            _save_atomic(pd.concat(frames, ignore_index=True), panel_path(market, root))
        yield prog

    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # Label refresh: fill labels that were NaN because their forward window hadn't
    # completed. Labels only — feature columns stay frozen at first write (PIT).
    if not panel.empty:
        stale = panel["fwd_6m"].isna() | panel["fwd_1m"].isna()
        for idx in panel.index[stale]:
            sym = str(panel.loc[idx, "symbol"])
            if sym not in adj_by_sym:
                continue  # symbol gone from the provider — keep what we have
            t = pd.Timestamp(panel.loc[idx, "date"])
            fresh = _labels(adj_by_sym[sym], bench_adj, t, next_of.get(t))
            for col in LABEL_COLS:
                if pd.isna(panel.loc[idx, col]) and pd.notna(fresh[col]):
                    panel.loc[idx, col] = fresh[col]
                    prog.relabeled += 1
        panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
        _save_atomic(panel, panel_path(market, root))
    if not panel.empty or prog.dropped or prior_dropped:
        # Meta is written even when every month was dropped — the dropped record is
        # what lets a resume skip those months instead of rebuilding them forever.
        _write_meta(panel, market, root, symbols, prior_dropped | set(prog.dropped), prog)

    prog.finished = True
    yield prog


def _write_meta(
    panel: pd.DataFrame,
    market: str,
    root: Path | None,
    symbols: list[str],
    dropped: set[str],
    prog: DatasetProgress,
) -> None:
    if panel.empty:
        months: list[str] = []
        per_month: dict[str, int] = {}
    else:
        counts = panel.groupby("date")["eligible"].sum()
        months = [cast("pd.Timestamp", d).date().isoformat() for d in counts.index]
        per_month = {cast("pd.Timestamp", d).date().isoformat(): int(n) for d, n in counts.items()}
    meta = {
        "built_at": datetime.now(UTC).isoformat(),
        "market": market,
        "months": months,
        "eligible_per_month": per_month,
        "dropped_months": sorted(dropped),
        "universe_size": len(symbols),
        "labels_refreshed": prog.relabeled,
        # Today's constituents only — certified numbers built on this are optimistic
        # upper bounds and must carry this stamp (docs/NORTH_STAR.md).
        "survivorship": "current_universe (optimistic)",
    }
    path = meta_path(market, root)
    path.parent.mkdir(parents=True, exist_ok=True)  # no parquet is written when all months drop
    path.write_text(json.dumps(meta, indent=2))
