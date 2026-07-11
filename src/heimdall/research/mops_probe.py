"""MOPS monthly-revenue announcement-date validation (roadmap 17.9).

NORTH_STAR accepted limitation 5 promised per-filing validation of the TW `filed_at` heuristic
(month-end + 10 days, the §36 statutory deadline) "if a TW family reaches pre-registration" —
`tw-revenue-momentum` is now **certified**, so the debt is due.

Three historical per-filing sources were probed live (2026-07-11) and each ruled out — see
`docs/RESEARCH_LOG.md` for the dated findings:

- FinMind's ``TaiwanStockMonthRevenue`` carries a ``create_time`` field, but it is empty for
  history (checked 2019) and, for recent months, uniform across many symbols for older periods
  (a batch-reprocessing timestamp, not a per-filing date) — unusable as a historical proxy.
- MOPS's compiled monthly-revenue archive (``t21sc03_*``) has no per-company date column at all.
- TWSE OpenAPI's ``t187ap05_L`` serves only the single latest period with one uniform
  report-generation date shared by every company — not historical, not per-company.

No historical per-filing source exists, so the card's fallback applies: **live observation**.
This module is the reusable mechanism — run it once a day during days 1–12 of a calendar month
to record, for ~30 tracked names spread across the TW universe, the date their latest revenue
month *first appears* in FinMind. The pure ``update_observations``/``summarize`` functions are
unit-tested without the network; the CLI wraps them with a live FinMind fetch.

    uv run python -m heimdall.research.mops_probe --record   # run once, daily, Aug 2026
    uv run python -m heimdall.research.mops_probe --summarize 2026-07  # after the window closes

**Binding rule (playbook discipline, mirrored here): if late filings exceed 2% of the sample,
stop and ask the user** before adjusting `filed_at` anywhere — a conservative bump is a
§4-rule-4-grade change requiring re-certification of the TW signal. This module never adjusts
`filed_at` itself.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from heimdall.data.store import data_root
from heimdall.screener.universe import tw_symbols

_DEFAULT_N = 30


def tracked_symbols(
    n: int = _DEFAULT_N, universe: Callable[[], list[str]] = tw_symbols
) -> list[str]:
    """~n names evenly spread across the sorted TW universe.

    Index-spread is a free, hallucination-free proxy for "across market-cap sizes" (no extra
    market-cap fetch): lower-numbered legacy tickers skew large/old-economy, higher-numbered /
    newer-format tickers skew smaller — sampling evenly across the sorted list touches both ends.
    """
    names = sorted(universe())
    if len(names) <= n:
        return names
    step = len(names) // n
    return names[::step][:n]


def observation_path(root: Path | None = None) -> Path:
    return (root or data_root()) / "research" / "mops_observation.json"


def load_store(root: Path | None = None) -> dict[str, dict[str, str]]:
    path = observation_path(root)
    if not path.exists():
        return {}
    raw: dict[str, dict[str, str]] = json.loads(path.read_text())
    return raw


def save_store(store: dict[str, dict[str, str]], root: Path | None = None) -> None:
    path = observation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True))
    os.replace(tmp, path)


def update_observations(
    store: dict[str, dict[str, str]],
    latest_month_by_symbol: dict[str, str | None],
    today: date,
) -> tuple[dict[str, dict[str, str]], list[tuple[str, str]]]:
    """Record first-seen dates for newly observed (symbol, revenue-month) pairs.

    Pure and idempotent: re-running with the same ``latest_month_by_symbol`` input never
    rewrites an existing entry (a later, unrelated FinMind revision must not silently move the
    empirically observed first-appearance date). Returns the updated store (a new object; the
    input is not mutated) and the list of ``(symbol, month)`` pairs newly recorded on this call.
    ``month`` is ``"YYYY-MM"``; ``None`` values (no revenue yet) are skipped.
    """
    new_store = {sym: dict(months) for sym, months in store.items()}
    newly_recorded: list[tuple[str, str]] = []
    for sym, month in latest_month_by_symbol.items():
        if month is None:
            continue
        months = new_store.setdefault(sym, {})
        if month not in months:
            months[month] = today.isoformat()
            newly_recorded.append((sym, month))
    return new_store, newly_recorded


def summarize(store: dict[str, dict[str, str]], month: str) -> pd.DataFrame:
    """First-seen dates for one revenue ``month`` (``"YYYY-MM"``) vs the §36 statutory
    10th-of-next-month deadline. ``days_vs_10th`` > 0 means observed *after* the deadline (a
    late filer under this empirical read); ``late`` mirrors that as a boolean.
    """
    y, m = (int(x) for x in month.split("-"))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    deadline = date(ny, nm, 10)
    rows: list[dict[str, object]] = []
    for sym, months in store.items():
        seen = months.get(month)
        if seen is None:
            continue
        seen_date = date.fromisoformat(seen)
        delta = (seen_date - deadline).days
        rows.append(
            {
                "symbol": sym,
                "month": month,
                "first_seen": seen,
                "days_vs_10th": delta,
                "late": delta > 0,
            }
        )
    return pd.DataFrame(rows, columns=["symbol", "month", "first_seen", "days_vs_10th", "late"])


def _latest_month(revenue: pd.DataFrame) -> str | None:
    if revenue.empty:
        return None
    latest = pd.Timestamp(revenue["month"].max())
    return f"{latest.year:04d}-{latest.month:02d}"


def _record(today: date) -> None:
    from heimdall.data.providers import FinMindProvider

    finmind = FinMindProvider()
    symbols = tracked_symbols()
    latest: dict[str, str | None] = {}
    for sym in symbols:
        try:
            revenue = finmind.monthly_revenue(sym, today - timedelta(days=70), today)
        except Exception as exc:  # a broken symbol must not kill the daily check
            print(f"  {sym}: fetch error ({type(exc).__name__}), skipped")
            continue
        latest[sym] = _latest_month(revenue)

    store = load_store()
    store, newly = update_observations(store, latest, today)
    save_store(store)
    print(f"{today.isoformat()}: {len(symbols)} tracked, {len(newly)} newly observed:")
    for sym, month in newly:
        print(f"  {sym} — {month}")


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", action="store_true", help="run today's daily observation check")
    g.add_argument("--summarize", metavar="YYYY-MM", help="report first-seen dates for a month")
    args = p.parse_args(argv)

    if args.record:
        _record(date.today())
        return 0

    df = summarize(load_store(), args.summarize)
    if df.empty:
        print(f"no observations recorded yet for {args.summarize}")
        return 1
    late_share = float(df["late"].mean())
    print(df.to_string(index=False))
    print(f"\n{len(df)} observations; late-filer share {late_share:.1%}")
    if late_share > 0.02:
        print(
            "⚠️  late filings exceed 2% of the sample — STOP and ask the user before adjusting "
            "filed_at anywhere (playbook §4-rule-4: a conservative bump needs re-certification)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
