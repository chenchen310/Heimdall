"""Spec → daily backtest (roadmap 18.3) — the one bridge from a ``SignalSpec`` to the engine.

:func:`heimdall.research.construct.book_schedule` turns a spec into dated target weights (the
exact books ``certify``/``evaluate`` price); :func:`heimdall.backtest.panel_engine.run` fills
them at the next open with costs and drift. Kept out of ``construct`` so the referee's modules
never import the (heavy) backtest package.
"""

from __future__ import annotations

import pandas as pd

from heimdall.backtest.panel_engine import EngineResult, run
from heimdall.research import construct, gates
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.spec import SignalSpec


def backtest_spec(
    spec: SignalSpec,
    panel: pd.DataFrame,
    matrices: dict[str, pd.DataFrame],
    *,
    benchmark_adj: pd.Series | None = None,
    cost_bps: float = gates.G4_COST_BPS,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> tuple[EngineResult, construct.BookSchedule]:
    """Run ``spec`` over the panel window through the daily engine.

    ``matrices`` = ``backtest.matrix.load_matrices()`` (must include the market benchmark
    symbol). ``benchmark_adj`` is only needed for an overlay spec; when omitted it is taken
    from the matrices' benchmark column.
    """
    bench_sym = BENCHMARK[spec.market]
    if spec.overlay and benchmark_adj is None:
        benchmark_adj = matrices["adj_close"][bench_sym].dropna()
    sched = construct.book_schedule(spec, panel, benchmark_adj, start=start, end=end)
    sectors = None
    if "sector" in panel.columns:
        sectors = panel.drop_duplicates("symbol", keep="last").set_index("symbol")["sector"]
    result = run(
        sched.targets,
        matrices["adj_open"],
        matrices["adj_close"],
        benchmark=bench_sym,
        cost_bps=cost_bps,
        overlay_cash=sched.overlay_cash if spec.overlay else None,
        universe_targets=sched.universe_targets,
        sectors=sectors,
        end=end,
    )
    return result, sched
