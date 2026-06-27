"""Phase 0 vertical slice — one honest end-to-end backtest.

    uv run python -m heimdall.backtest.demo
    uv run python -m heimdall.backtest.demo --symbol MSFT.US --fast 20 --slow 50

Pipeline: yfinance → DuckDB/Parquet delta cache → SMA crossover (pandas-ta) →
vectorbt backtest with costs + next-bar-open fills → quantstats tear sheet. This
exercises the whole data→signal→backtest→report path on real data.
"""

from __future__ import annotations

import argparse
from datetime import date

from heimdall.backtest.costs import DEFAULT_COSTS
from heimdall.backtest.engine import run_backtest
from heimdall.backtest.report import tear_sheet
from heimdall.backtest.signals import sma_crossover_signals
from heimdall.data.cache import CachedProvider
from heimdall.data.providers import YFinanceProvider
from heimdall.data.store import query


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 0 SMA-crossover backtest demo")
    p.add_argument("--symbol", default="AAPL.US", help="canonical TICKER.MARKET")
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--fast", type=int, default=20)
    p.add_argument("--slow", type=int, default=50)
    p.add_argument("--output", default=None, help="tear sheet HTML path")
    args = p.parse_args(argv)

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    provider = CachedProvider(YFinanceProvider())

    print(f"Fetching {args.symbol} {start}..{end} (cached delta) ...")
    ohlcv = provider.get_ohlcv(args.symbol, start, end)
    if ohlcv.empty:
        print("No data returned (network/symbol issue). Aborting.")
        return 1
    print(f"  {len(ohlcv)} bars  {ohlcv['date'].min().date()}..{ohlcv['date'].max().date()}")

    # DuckDB reading the Parquet the cache just wrote — proves the storage path.
    coverage = query(
        "SELECT symbol, count(*) AS bars, min(date) AS lo, max(date) AS hi "
        "FROM {prices} GROUP BY 1 ORDER BY 1"
    )
    print("DuckDB cache coverage:\n", coverage.to_string(index=False))

    close = ohlcv["adj_close"].set_axis(ohlcv["date"].to_numpy())
    entries, exits = sma_crossover_signals(close, fast=args.fast, slow=args.slow)
    pf = run_backtest(ohlcv, entries, exits, costs=DEFAULT_COSTS)

    cost_desc = (
        f"{DEFAULT_COSTS.fees:.2%} fee + {DEFAULT_COSTS.slippage:.2%} slip, next-bar-open fills"
    )
    print(f"\n=== SMA({args.fast}/{args.slow}) on {args.symbol} ({cost_desc}) ===")
    print(pf.stats().to_string())

    out = args.output or f"reports/{args.symbol}_sma_{args.fast}_{args.slow}.html"
    path = tear_sheet(pf, out, title=f"{args.symbol} SMA({args.fast}/{args.slow})")
    print(f"\nTear sheet written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
