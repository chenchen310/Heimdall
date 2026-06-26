"""Build and save the snapshot table.

    uv run python -m stockobserver.screener.build
    uv run python -m stockobserver.screener.build --symbols AAPL.US,MSFT.US

Fetches prices (yfinance, cached) + point-in-time fundamentals (SEC EDGAR) for a
universe and writes ``data/snapshot.parquet`` for the screener / UI to read.
Set ``SEC_EDGAR_USER_AGENT`` in ``.env`` (EDGAR fair-access policy).
"""

from __future__ import annotations

import argparse
from datetime import date

from dotenv import load_dotenv

from stockobserver.data.cache import CachedProvider
from stockobserver.data.providers import SecEdgarProvider, YFinanceProvider
from stockobserver.screener.snapshot import (
    DEFAULT_UNIVERSE,
    build_snapshot,
    save_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Build the screener snapshot table")
    p.add_argument("--symbols", default=None, help="comma-separated canonical symbols")
    p.add_argument("--as-of", default=date.today().isoformat())
    args = p.parse_args(argv)

    symbols = args.symbols.split(",") if args.symbols else DEFAULT_UNIVERSE
    as_of = date.fromisoformat(args.as_of)

    print(f"Building snapshot for {len(symbols)} symbols as of {as_of} ...")
    prices = CachedProvider(YFinanceProvider())
    fundamentals = SecEdgarProvider()
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
