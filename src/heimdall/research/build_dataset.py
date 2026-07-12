"""Build the research panel (labels + eligibility) for one market.

    uv run python -m heimdall.research.build_dataset --market us --start 2010-01
    uv run python -m heimdall.research.build_dataset --market tw --start 2015-01
    uv run python -m heimdall.research.build_dataset --market us --symbols AAPL.US,MSFT.US

Long, resumable crawl in the mould of ``screener.build``: prices are
delta-cached, months already in the parquet are skipped, and still-missing
forward labels are refreshed on every run. Output:
``data/research/panel_{us|tw}.parquet`` + a ``.meta.json`` sidecar carrying the
``current_universe (optimistic)`` survivorship stamp.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime

from dotenv import load_dotenv

from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.research import gates
from heimdall.research.dataset import build_dataset_iter, load_panel, panel_path
from heimdall.screener.universe import tw_symbols, vti_symbols

_MARKET = {"us": "US", "tw": "Taiwan"}


def _parse_month(s: str) -> date:
    for fmt in ("%Y-%m", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"{s!r} is not YYYY-MM or YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description="Build the research panel for one market")
    p.add_argument("--market", choices=sorted(_MARKET), default="us")
    p.add_argument("--symbols", default=None, help="comma-separated canonical symbols (override)")
    p.add_argument("--limit", type=int, default=None, help="cap the universe (testing/batching)")
    p.add_argument("--start", type=_parse_month, default=date(2010, 1, 1))
    p.add_argument("--end", type=_parse_month, default=date.today())
    p.add_argument("--rebuild", action="store_true", help="ignore any existing panel")
    p.add_argument(
        "--min-cross-section",
        type=int,
        default=gates.MIN_CROSS_SECTION,
        help="eligible-names floor per month (lower it only for small test universes)",
    )
    args = p.parse_args(argv)

    market = _MARKET[args.market]
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = vti_symbols() if args.market == "us" else tw_symbols()
    if args.limit:
        symbols = symbols[: args.limit]

    prices = CachedProvider(router.price_provider())
    fundamentals = router.fundamentals_provider()
    monthly_revenue = None
    daily_chips = None
    daily_lending = None
    tdcc_weeks = None
    if args.market == "tw":  # extra TW streams: 月營收 (11.2) + 法人籌碼 (11.3) + 借券/融券 (17.1)
        from heimdall.data.providers import FinMindProvider
        from heimdall.data.providers import tdcc as tdcc_provider

        finmind = FinMindProvider()
        monthly_revenue = finmind.monthly_revenue
        daily_chips = finmind.daily_chips
        daily_lending = finmind.daily_lending
        # 集保大戶 (roadmap 13.9): whatever's accumulated on disk so far — there is
        # no per-symbol fetch here (build/refresh the weekly cache separately via
        # `python -m heimdall.research.tdcc_cache`, once a week, over real time).
        tdcc_weeks = tdcc_provider.load_cached_weeks()

    progress = build_dataset_iter(
        symbols,
        prices,
        fundamentals,
        market,
        args.start,
        args.end,
        resume=not args.rebuild,
        min_cross_section=args.min_cross_section,
        monthly_revenue=monthly_revenue,
        daily_chips=daily_chips,
        daily_lending=daily_lending,
        tdcc_weeks=tdcc_weeks,
    )
    last = next(progress)  # the plan
    print(f"Universe: {len(symbols)} symbols | months to build: {last.total_months}")
    if last.failures:
        bad = ", ".join(f"{k}×{v}" for k, v in sorted(last.failures.items()))
        print(f"  fetch errors (skipped symbols): {bad}")
    for last in progress:
        if last.month is not None and not last.finished:
            note = (
                " — DROPPED (thin cross-section)"
                if (last.dropped and last.dropped[-1] == last.month.date().isoformat())
                else ""
            )
            print(
                f"  [{last.done_months}/{last.total_months}] {last.month.date()} "
                f"rows={last.rows} eligible={last.eligible}{note}"
            )

    try:
        panel = load_panel(market)
    except FileNotFoundError:
        print("Panel is empty (no data).")
        return 1
    print(
        f"\nSaved {len(panel)} rows -> {panel_path(market)}"
        f"\nLabels refreshed this run: {last.relabeled} | dropped months: {len(last.dropped)}"
        "\nSurvivorship: current_universe (optimistic) — see docs/NORTH_STAR.md."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
