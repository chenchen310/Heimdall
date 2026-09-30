"""Walk-forward meta-backtest (roadmap 18.6) — was the factory itself any good?

A leaderboard's winner is the *best of many*; this backtests the **selection procedure**
instead. For each year Y the factory re-selects from its run's trials using only what was
knowable at the end of Y−1, then holds that choice through Y in the daily engine; the yearly
segments are stitched into one curve (the engine charges the switch costs).

Point-in-time is the whole point. At the end of Y−1:

- a month's F1 net-alpha and G1 IC use ``fwd_1m`` labels, complete only for months ≤ **Nov**
  of Y−1 (December's window closes in January);
- a month's G3 6m cohort alpha is complete only for months ≤ **June** of Y−1.

So selection at Y reads the ledger's per-month series (18.5) up to those cutoffs — a test pins
that nothing after them can move a choice. Eligible = trailing F3 (alpha NW-t ≥ 3.0 and IC t ≥
2.0) and F5; the pick is the highest trailing objective (annualized net-alpha IR). A year with
no eligible trial holds the benchmark (flagged): "the factory found nothing" is a real outcome.

DEV only (2014–2019 by default). The **VAL extension** (2020–2022) refuses to run until 18.7
has recorded the run's VAL looks, and it never re-selects on VAL data: the last DEV-based choice
is simply held, so those segments are post-selection display. **Descriptive, never a gate.**
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.backtest.panel_engine import EngineResult, run
from heimdall.backtest.portfolio_stats import portfolio_stats, yearly_returns
from heimdall.research import construct, factory, gates
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.spec import SignalSpec

DEV_YEARS: tuple[int, ...] = (2014, 2015, 2016, 2017, 2018, 2019)
VAL_YEARS: tuple[int, ...] = (2020, 2021, 2022)


def val_looks_path(run_id: str, root: Path | None = None) -> Path:
    """Written by 18.7's promotion step (``factory.promote``) once the run's VAL looks are spent."""
    return factory.val_looks_path(run_id, root)


@dataclass
class YearChoice:
    year: int
    trial_ids: list[int]  # [] ⇒ nothing eligible: the benchmark is held
    trailing_objective: list[float]
    reselected: bool  # False for VAL-extension years (the last DEV choice is held)


@dataclass
class WalkForwardResult:
    run_id: str
    mode: str  # "top1" | "top3"
    choices: list[YearChoice]
    returns: pd.DataFrame  # daily strategy / benchmark / universe, stitched
    stats: dict[str, float]
    yearly: pd.DataFrame  # calendar-year returns per column
    pct_years_beating_benchmark: float
    pct_years_beating_universe: float
    includes_val: bool
    flags: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "includes_val": self.includes_val,
            "choices": [c.__dict__ for c in self.choices],
            "stats": self.stats,
            "pct_years_beating_benchmark": self.pct_years_beating_benchmark,
            "pct_years_beating_universe": self.pct_years_beating_universe,
            "flags": self.flags,
        }


def cutoffs(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(last usable month for 1m-label series, last usable month for 6m-label series) when
    selecting at the end of ``year − 1``."""
    return pd.Timestamp(f"{year - 1}-11-30"), pd.Timestamp(f"{year - 1}-06-30")


def _window(series: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    return series.loc[series.index <= end]


def trailing_scores(
    trials: pd.DataFrame,
    net: pd.DataFrame,
    ic: pd.DataFrame,
    alpha6: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """Per trial: the trailing objective and F3/F5 flags from data knowable at the end of Y−1."""
    end1, end6 = cutoffs(year)
    n_w, ic_w, a_w = _window(net, end1), _window(ic, end1), _window(alpha6, end6)
    rows: list[dict[str, object]] = []
    for tid, n_params in zip(trials["trial_id"], trials["n_params"], strict=True):
        key = str(int(tid))
        x = n_w[key].to_numpy(dtype=float)
        x = x[np.isfinite(x)]
        sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
        objective = float(x.mean()) / sd * math.sqrt(12.0) if sd > 0 else float("nan")
        ics = ic_w[key].to_numpy(dtype=float)
        ics = ics[np.isfinite(ics)]
        ic_sd = float(ics.std(ddof=1)) if len(ics) > 1 else 0.0
        ic_t = float(ics.mean() / (ic_sd / math.sqrt(len(ics)))) if ic_sd > 0 else float("nan")
        al = a_w[key].to_numpy(dtype=float)
        al = al[np.isfinite(al)]
        alpha_t = gates.nw_tstat(al, null=0.0, lag=gates.NW_LAG) if len(al) > 1 else float("nan")
        eligible = (
            math.isfinite(alpha_t)
            and math.isfinite(ic_t)
            and alpha_t >= gates.FACTORY_MIN_ALPHA_T
            and ic_t >= gates.FACTORY_MIN_IC_T
            and int(n_params) <= gates.FACTORY_MAX_PARAMS
        )
        rows.append(
            {
                "trial_id": int(tid),
                "objective": objective,
                "ic_t": ic_t,
                "alpha_t": alpha_t,
                "eligible": eligible,
            }
        )
    return pd.DataFrame(rows)


def choose(scores: pd.DataFrame, mode: str) -> tuple[list[int], list[float]]:
    k = 1 if mode == "top1" else 3
    ok = scores[scores["eligible"] & np.isfinite(scores["objective"])]
    top = ok.sort_values(["objective", "trial_id"], ascending=[False, True]).head(k)
    return [int(t) for t in top["trial_id"]], [float(o) for o in top["objective"]]


def _blend(books: list[pd.Series]) -> pd.Series:
    """Equal blend of several books (their weights averaged; a name in two books adds up)."""
    if not books:
        return pd.Series(dtype=float)
    both = pd.concat(books, axis=1).fillna(0.0)
    return both.sum(axis=1) / len(books)


def walk_forward(
    run_id: str,
    panel: pd.DataFrame,
    matrices: dict[str, pd.DataFrame],
    *,
    mode: str = "top1",
    include_val: bool = False,
    root: Path | None = None,
    years: tuple[int, ...] = DEV_YEARS,
) -> WalkForwardResult:
    """Re-select every year from the run's ledger (PIT cutoffs), hold, stitch, and score."""
    if mode not in ("top1", "top3"):
        raise ValueError("mode must be 'top1' or 'top3'")
    if include_val and not val_looks_path(run_id, root).exists():
        raise ValueError(
            "the VAL extension runs only after 18.7 has recorded the run's VAL looks "
            f"({val_looks_path(run_id, root)} is missing)"
        )
    if max(years) > int(factory.DEV_END[:4]):
        raise ValueError("walk-forward selection years are DEV years; use include_val for 2020–22")
    trials = factory.load_trials(run_id, root)
    if trials.empty:
        raise FileNotFoundError(f"no trials for run {run_id!r}")
    net = factory.load_series(run_id, root, "net")
    ic = factory.load_series(run_id, root, "ic")
    alpha6 = factory.load_series(run_id, root, "alpha6")
    specs = {
        int(t): SignalSpec.model_validate_json(str(j))
        for t, j in zip(trials["trial_id"], trials["spec_json"], strict=True)
    }
    market = next(iter(specs.values())).market
    bench_sym = BENCHMARK[market]

    dates = pd.to_datetime(panel["date"])
    all_years = list(years) + (list(VAL_YEARS) if include_val else [])
    targets: dict[pd.Timestamp, pd.Series] = {}
    universe: dict[pd.Timestamp, pd.Series] = {}
    choices: list[YearChoice] = []
    flags: list[str] = []
    held: tuple[list[int], list[float]] = ([], [])
    for year in all_years:
        if year in years:
            held = choose(trailing_scores(trials, net, ic, alpha6, year), mode)
            reselected = True
        else:
            reselected = False
        chosen, objs = held
        choices.append(YearChoice(year, chosen, objs, reselected))
        # This year's decisions: Dec 31 of Y−1 through Nov 30 of Y (fills land in Y).
        lo, hi = pd.Timestamp(f"{year - 1}-12-01"), pd.Timestamp(f"{year}-11-30")
        window = panel.loc[(dates >= lo) & (dates <= hi)]
        decision_dates = sorted(pd.Timestamp(d) for d in pd.to_datetime(window["date"]).unique())
        if not chosen:
            flags.append(f"{year}: no trial eligible on trailing F3/F5 — the benchmark is held")
            for d in decision_dates:
                targets[d] = pd.Series({bench_sym: 1.0})
                universe[d] = pd.Series({bench_sym: 1.0})
            continue
        scheds = [construct.book_schedule(specs[t], window) for t in chosen]
        for d in decision_dates:
            targets[d] = _blend([s.targets.get(d, pd.Series(dtype=float)) for s in scheds])
            universe[d] = _blend(
                [s.universe_targets.get(d, pd.Series(dtype=float)) for s in scheds]
            )

    if not targets:
        raise ValueError("no decision dates in the panel for the requested years")
    end = pd.Timestamp(f"{max(all_years)}-12-31")
    result: EngineResult = run(
        targets,
        matrices["adj_open"],
        matrices["adj_close"],
        benchmark=bench_sym,
        cost_bps=gates.G4_COST_BPS,
        universe_targets=universe,
        end=end,
    )
    flags.extend(result.flags)
    r = result.returns
    yearly = yearly_returns(r)
    yearly = yearly.loc[[y for y in yearly.index if y in all_years]]
    stats = portfolio_stats(r["strategy"], r["benchmark"], r.get("universe"))
    return WalkForwardResult(
        run_id=run_id,
        mode=mode,
        choices=choices,
        returns=r,
        stats=stats,
        yearly=yearly,
        pct_years_beating_benchmark=float((yearly["strategy"] > yearly["benchmark"]).mean()),
        pct_years_beating_universe=float((yearly["strategy"] > yearly["universe"]).mean())
        if "universe" in yearly
        else float("nan"),
        includes_val=include_val,
        flags=flags,
    )


def save(result: WalkForwardResult, data: Path | None = None) -> Path:
    """Persist the stitched curve (gitignored data root) + a JSON summary beside it."""
    out = factory.engine_dir(result.run_id, data)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"walkforward_{result.mode}{'_val' if result.includes_val else ''}"
    result.returns.to_parquet(out / f"{tag}.parquet")
    (out / f"{tag}.json").write_text(json.dumps(result.summary(), indent=2, default=str) + "\n")
    return out / f"{tag}.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Walk-forward meta-backtest of a factory run (18.6)")
    p.add_argument("run_id")
    p.add_argument("--mode", choices=["top1", "top3"], default="top1")
    p.add_argument("--include-val", action="store_true", help="2020–22 display (after 18.7)")
    args = p.parse_args(argv)

    from heimdall.backtest.matrix import load_matrices
    from heimdall.research.dataset import load_panel

    cfg = factory.load_config(factory.run_dir(args.run_id) / "config.json")
    res = walk_forward(
        args.run_id,
        load_panel(cfg.market),
        load_matrices(),
        mode=args.mode,
        include_val=args.include_val,
    )
    path = save(res)
    for c in res.choices:
        tag = "" if c.reselected else " (held; no re-selection on VAL)"
        print(f"{c.year}: trials {c.trial_ids or 'none → benchmark'}{tag}")
    s = res.stats
    print(
        f"CAGR {s['cagr']:+.2%} vs SPY {s['benchmark_cagr']:+.2%} vs EW universe "
        f"{s.get('universe_cagr', float('nan')):+.2%} | Sharpe {s['sharpe']:.2f} | max DD "
        f"{s['max_drawdown']:.1%} | years beating SPY {res.pct_years_beating_benchmark:.0%}"
    )
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
