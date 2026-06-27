"""Build and save the snapshot table.

    uv run python -m heimdall.screener.build                 # small US default (15)
    uv run python -m heimdall.screener.build --market vti    # whole US market (~3.4k, VTI)
    uv run python -m heimdall.screener.build --market tw     # Taiwan large caps
    uv run python -m heimdall.screener.build --symbols AAPL.US,2330.TW

Fetches prices (yfinance, cached) + point-in-time fundamentals (EDGAR for US — or
FMP if ``FMP_API_KEY`` is set — and FinMind for Taiwan, routed by the symbol's
market) and writes ``data/snapshot.parquet`` for the screener / UI to read.

Large universes (``--market vti``) are a long, **resumable** one-time crawl: the
build checkpoints to disk and, on a re-run, skips symbols already in the snapshot
(prices are cached too). A symbol that errors or has no data is skipped, not fatal.
Use ``--rebuild`` to start a fresh snapshot. Set ``SEC_EDGAR_USER_AGENT`` in
``.env`` (EDGAR fair-access); Taiwan needs no key (``FINMIND_TOKEN`` raises quota).
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import date

import pandas as pd
from dotenv import load_dotenv

from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.screener.snapshot import (
    UNIVERSES,
    build_row,
    load_snapshot,
    save_snapshot,
)
from heimdall.screener.universe import tw_symbols, vti_symbols

_PREVIEW_COLS = ["symbol", "price", "pe", "ps", "net_margin", "roe", "revenue_growth_yoy", "rsi_14"]


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.market == "vti":
        return vti_symbols(refresh=args.refresh_universe)
    if args.market == "tw-all":
        return tw_symbols(refresh=args.refresh_universe)
    return UNIVERSES[args.market]


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Build the screener snapshot table")
    p.add_argument("--symbols", default=None, help="comma-separated canonical symbols")
    p.add_argument(
        "--market",
        default="us",
        choices=[*sorted(UNIVERSES), "vti", "tw-all"],
        help="built-in universe (vti = whole US market ~3.4k; tw-all = all TWSE+TPEX ~2.1k)",
    )
    p.add_argument("--limit", type=int, default=None, help="cap the universe (testing/batching)")
    p.add_argument("--as-of", default=date.today().isoformat())
    p.add_argument("--rebuild", action="store_true", help="ignore any existing snapshot")
    p.add_argument(
        "--refresh-universe", action="store_true", help="re-fetch the VTI / TW holdings list"
    )
    p.add_argument("--checkpoint-every", type=int, default=50, help="flush to disk every N symbols")
    args = p.parse_args(argv)

    symbols = _resolve_symbols(args)
    if args.limit:
        symbols = symbols[: args.limit]
    as_of = date.fromisoformat(args.as_of)

    prices = CachedProvider(router.price_provider())
    fundamentals = router.fundamentals_provider()

    # Resume: keep existing rows, only fetch symbols not yet in the snapshot.
    existing = pd.DataFrame()
    if not args.rebuild:
        with contextlib.suppress(FileNotFoundError):
            existing = load_snapshot()
    done = set(existing["symbol"]) if not existing.empty else set()
    todo = [s for s in symbols if s not in done]
    print(
        f"Universe: {len(symbols)} symbols | already built: {len(done & set(symbols))} "
        f"| to fetch: {len(todo)} | as of {as_of}"
    )

    rows: list[dict[str, object]] = (
        existing.to_dict("records") if not existing.empty else []  # type: ignore[assignment]
    )
    built = 0
    failures: dict[str, int] = {}
    for i, symbol in enumerate(todo, start=1):
        try:
            row = build_row(symbol, prices, fundamentals, as_of)
        except Exception as exc:  # network/provider hiccup — skip, don't abort the crawl
            failures[type(exc).__name__] = failures.get(type(exc).__name__, 0) + 1
            row = None
        if row is not None:
            rows.append(row)
            built += 1
        if i % args.checkpoint_every == 0:
            save_snapshot(pd.DataFrame(rows))
            print(f"  [{i}/{len(todo)}] built {built}, skipped {i - built} — checkpoint saved")

    df = pd.DataFrame(rows)
    if df.empty:
        print("Snapshot is empty (no data fetched).")
        return 1
    path = save_snapshot(df)
    print(f"\nSaved {len(df)} rows -> {path}")
    fund_cols = [c for c in ("pe", "ps", "net_margin", "roe") if c in df.columns]
    if fund_cols:
        no_fund = int(df[fund_cols].isna().all(axis=1).sum())
        if no_fund:
            print(
                f"Price-only (no fundamentals): {no_fund} of {len(df)} "
                "— e.g. FinMind quota; set FINMIND_TOKEN and --rebuild to fill."
            )
    if failures:
        summary = ", ".join(f"{name}×{n}" for name, n in sorted(failures.items()))
        print(f"Skipped on error: {summary}")
    cols = [c for c in _PREVIEW_COLS if c in df.columns]
    print("\nPreview (first 15):")
    print(df[cols].head(15).round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
