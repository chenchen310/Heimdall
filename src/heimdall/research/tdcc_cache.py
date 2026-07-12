"""TDCC weekly cache orchestration (roadmap 13.9) — the cross-layer wiring.

``data.providers.tdcc`` stays layer-pure (never imports ``screener/``); this
module builds the ``stock_id -> market`` map from ``screener.universe.tw_symbols()``
and calls the provider, mirroring how ``screener/build.py`` wires FinMind +
``screener.snapshot`` together as a CLI while ``data/providers/finmind.py``
itself stays layer-pure.

No historical backfill exists (the open-data endpoint only ever serves "the
current week") — run this **once a week**, over real calendar time, to build
up history. Same operational shape as ``research.mops_probe`` (roadmap 17.9).

    uv run python -m heimdall.research.tdcc_cache
"""

from __future__ import annotations

import argparse

import pandas as pd

from heimdall.data.providers import tdcc
from heimdall.data.symbols import parse_symbol
from heimdall.screener.universe import tw_symbols


def market_by_id() -> dict[str, str]:
    """``{bare stock_id: "TW"|"TWO"}`` for every common-stock TW symbol —
    TDCC's bulk file carries no market-type field of its own (see
    ``tdcc.normalize``'s docstring)."""
    out: dict[str, str] = {}
    for sym in tw_symbols():
        parsed = parse_symbol(sym)
        out[parsed.ticker] = parsed.market
    return out


def refresh(*, rebuild: bool = False) -> pd.DataFrame:
    """Fetch + cache the current week, resolving symbols against the live TW
    universe. Returns the (possibly empty, e.g. weekend/holiday) week."""
    return tdcc.fetch_and_cache_latest_week(market_by_id(), refresh=rebuild)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch + cache this week's TDCC shareholding file")
    p.add_argument("--rebuild", action="store_true", help="re-fetch even if this week is cached")
    args = p.parse_args(argv)

    week = refresh(rebuild=args.rebuild)
    if week.empty:
        print("No data returned (unexpected — check the endpoint).")
        return 1
    data_date = pd.Timestamp(week["data_date"].iloc[0]).date()
    n_symbols = week["symbol"].nunique()
    path = tdcc.cache_path(data_date)
    print(f"{data_date.isoformat()}: {n_symbols} symbols, {len(week)} rows -> {path}")
    history = tdcc.load_cached_weeks()
    n_weeks = history["data_date"].nunique() if not history.empty else 0
    print(f"Total accumulated weeks on disk: {n_weeks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
