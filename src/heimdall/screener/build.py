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
from datetime import date

import pandas as pd
from dotenv import load_dotenv

from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.data.symbols import parse_symbol
from heimdall.screener.snapshot import (
    UNIVERSES,
    build_snapshot_iter,
    load_snapshot,
    snapshot_path,
)
from heimdall.screener.universe import tw_sector_map, tw_symbols, us_sector_map, vti_symbols

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
    # Always wired: --market all / custom --symbols can mix US and TW in one build,
    # and a non-TW fetch is a cheap no-op (raises NotSupported before any network
    # call — see FinMindProvider._require_market), so there is no US-only cost.
    from heimdall.data.providers import FinMindProvider

    monthly_revenue = FinMindProvider().monthly_revenue

    # Sector (roadmap 14.1): fetched once, up front, for the whole universe — never
    # per row. TW is one bulk FinMind call; US is incremental (cached) per-symbol
    # EDGAR lookups, so only symbols new to this build cost a request.
    markets = {s: parse_symbol(s).market for s in symbols}
    sector_map: dict[str, str] = {}
    if any(m in ("TW", "TWO") for m in markets.values()):
        sector_map.update(tw_sector_map())
    us_syms = [s for s, m in markets.items() if m == "US"]
    if us_syms:
        sector_map.update(us_sector_map(us_syms))

    # The resumable crawl + checkpointing lives in the core iterator; here we just
    # print the plan, checkpoint lines, and a final summary as it streams progress.
    progress = build_snapshot_iter(
        symbols,
        prices,
        fundamentals,
        as_of,
        resume=not args.rebuild,
        checkpoint_every=args.checkpoint_every,
        monthly_revenue=monthly_revenue,
        sector_map=sector_map,
    )
    last = next(progress)  # initial plan (done == 0)
    print(
        f"Universe: {len(symbols)} symbols | already built: {len(symbols) - last.total} "
        f"| to fetch: {last.total} | as of {as_of}"
    )
    for last in progress:
        if last.done and not last.finished and last.done % args.checkpoint_every == 0:
            print(
                f"  [{last.done}/{last.total}] built {last.built}, "
                f"skipped {last.done - last.built} — checkpoint saved"
            )

    try:
        df = load_snapshot()
    except FileNotFoundError:
        df = pd.DataFrame()
    if df.empty:
        print("Snapshot is empty (no data fetched).")
        return 1
    print(f"\nSaved {len(df)} rows -> {snapshot_path()}")
    fund_cols = [c for c in ("pe", "ps", "net_margin", "roe") if c in df.columns]
    if fund_cols:
        no_fund = int(df[fund_cols].isna().all(axis=1).sum())
        if no_fund:
            print(
                f"Price-only (no fundamentals): {no_fund} of {len(df)} "
                "— e.g. FinMind quota; set FINMIND_TOKEN and --rebuild to fill."
            )
    if last.failures:
        summary = ", ".join(f"{name}×{n}" for name, n in sorted(last.failures.items()))
        print(f"Skipped on error: {summary}")
    cols = [c for c in _PREVIEW_COLS if c in df.columns]
    print("\nPreview (first 15):")
    print(df[cols].head(15).round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
