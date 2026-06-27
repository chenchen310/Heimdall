"""Build and save the snapshot table.

    uv run python -m heimdall.screener.build
    uv run python -m heimdall.screener.build --market tw
    uv run python -m heimdall.screener.build --symbols AAPL.US,2330.TW

Fetches prices (yfinance, cached) + point-in-time fundamentals (EDGAR for US,
FinMind for Taiwan — routed by the symbol's market) for a universe and writes
``data/snapshot.parquet`` for the screener / UI to read. Set
``SEC_EDGAR_USER_AGENT`` in ``.env`` (EDGAR fair-access policy); Taiwan needs no
key (set ``FINMIND_TOKEN`` for a higher quota).
"""

from __future__ import annotations

import argparse
from datetime import date

from dotenv import load_dotenv

from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.screener.snapshot import (
    UNIVERSES,
    build_snapshot,
    save_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Build the screener snapshot table")
    p.add_argument("--symbols", default=None, help="comma-separated canonical symbols")
    p.add_argument(
        "--market", default="us", choices=sorted(UNIVERSES), help="built-in universe to use"
    )
    p.add_argument("--as-of", default=date.today().isoformat())
    args = p.parse_args(argv)

    symbols = args.symbols.split(",") if args.symbols else UNIVERSES[args.market]
    as_of = date.fromisoformat(args.as_of)

    print(f"Building snapshot for {len(symbols)} symbols as of {as_of} ...")
    prices = CachedProvider(router.price_provider())
    fundamentals = router.fundamentals_provider()
    df = build_snapshot(symbols, prices, fundamentals, as_of)

    if df.empty:
        print("Snapshot is empty (no data fetched).")
        return 1
    path = save_snapshot(df)
    cols = ["symbol", "price", "pe", "ps", "net_margin", "roe", "revenue_growth_yoy", "rsi_14"]
    print(df[cols].round(3).to_string(index=False))
    print(f"\nSaved {len(df)} rows -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
