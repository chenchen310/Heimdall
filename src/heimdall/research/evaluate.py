"""Windowed in-sample evaluation (roadmap 13.1) — the sanctioned dev/validation lens.

:func:`heimdall.research.certify.certify` is the OOS referee; :func:`evaluate` runs the
**same** gate statistics over an arbitrary *in-sample* window so development and validation
reads stop being per-session throwaway scripts. The formulas are **imported, never forked**:

- G1 rank IC — :func:`heimdall.factors.validate.information_coefficient`
- G2 quintile spread — :func:`heimdall.research.certify._monthly_spread`
- G3 selection alpha — :func:`heimdall.research.certify._book_minus_universe` + ``gates.nw_tstat``
- G6 turnover — :func:`heimdall.research.certify.cohort_turnover`
- displayed beat rate / CI — the per-cohort book-vs-benchmark hit + ``gates.nw_ci95``

There is deliberately **no G4/G5/G6-cost path**: an in-sample lens needs the ranking + skill
read to decide whether a candidate advances, not the cost-aware vault backtest (that is the
vault's job). :func:`evaluate` **refuses any window reaching the OOS vault**
(``end >= gates.OOS_START``) — the vault is :func:`certify`'s alone (playbook §4).

    uv run python -m heimdall.research.evaluate signals/specs/<f>.json --window dev
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.factors.validate import information_coefficient
from heimdall.research import gates
from heimdall.research.certify import (
    _SCORE,
    _book_minus_universe,
    _monthly_spread,
    cohort_turnover,
)
from heimdall.research.dataset import load_panel
from heimdall.research.spec import SignalSpec, load_spec, score

# Development / validation windows mirror docs/RESEARCH_PLAYBOOK.md §4. The OOS vault
# (2023+, gates.OOS_START) is never a valid evaluate() window — it is certify()'s alone.
# A test pins these boundaries against the playbook and against OOS_START.
WINDOWS: dict[str, tuple[str, str]] = {
    "dev": ("2010-01-01", "2019-12-31"),
    "val": ("2020-01-01", "2022-12-31"),
}


@dataclass
class EvalReport:
    """One spec's in-sample read — the same quantities the RESEARCH_LOG tables report."""

    spec_name: str
    spec_version: int
    market: str
    window_start: str
    window_end: str
    n_months: int
    n_cohorts: int  # months with a complete 6m book & universe (the G3 sample)
    ic_mean: float
    ic_t: float
    ic_months: int
    spread_mean: float
    spread_positive_share: float
    selection_alpha_mean: float  # G3 unit: EW top-N book 6m_rel − EW eligible-universe 6m_rel
    selection_alpha_t: float  # Newey–West t (lag 5) of the per-cohort selection alpha
    portfolio_beat_rate: float  # displayed: fraction of cohorts whose book beat the benchmark
    portfolio_beat_ci95: tuple[float, float]
    mean_turnover: float

    @property
    def advances(self) -> bool:
        """Card 13.1 step 4: a candidate earns the single validation look only when the
        development ranking (G1 t) **and** selection skill (G3 NW-t) both clear their gate
        floors — the entry-010 precedent, so a strong-IC/zero-alpha or strong-alpha/zero-IC
        candidate does not consume a look."""
        return (
            not np.isnan(self.ic_t)
            and not np.isnan(self.selection_alpha_t)
            and self.ic_t >= gates.G1_MIN_T
            and self.selection_alpha_t >= gates.G3_MIN_SKILL_T
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate(spec: SignalSpec, panel: pd.DataFrame, window: tuple[str, str]) -> EvalReport:
    """Score ``spec`` over the panel rows in ``window`` and return the in-sample gate read.

    Mirrors :func:`certify.certify`'s scoring loop exactly (score → rank → top-N book →
    book-minus-universe alpha), minus the vault-only cost backtest, so a candidate's dev/val
    numbers are computed by the identical code that will judge it out-of-sample.
    """
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    if end >= pd.Timestamp(gates.OOS_START):
        raise ValueError(
            f"window end {end.date()} reaches the OOS vault (≥ {gates.OOS_START}); "
            "evaluate() is in-sample only — the vault is certify()'s (playbook §4)"
        )

    dates = pd.to_datetime(panel["date"])
    win = panel.loc[(dates >= start) & (dates <= end)].copy()
    win["date"] = pd.to_datetime(win["date"])
    months = sorted(pd.Timestamp(t) for t in win["date"].unique())

    frames: list[pd.DataFrame] = []
    cohort_sets: list[set[str]] = []
    selection_alphas: list[float] = []
    portfolio_beats: list[float] = []
    for t in months:
        cross = win[win["date"] == t].copy()
        cross[_SCORE] = score(spec, cross)
        frames.append(cross)
        ranked = cross.dropna(subset=[_SCORE]).sort_values(_SCORE, ascending=False)
        cohort_sets.append(set(ranked.head(spec.top_n)["symbol"]))
        bu = _book_minus_universe(cross, spec.top_n)  # cross already carries the score column
        if bu is not None:
            book_ret, univ_ret = bu
            portfolio_beats.append(float(book_ret > 0))
            selection_alphas.append(book_ret - univ_ret)
    scored = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # G1 — monthly rank IC of the score vs next-window benchmark-relative return.
    ic = information_coefficient(scored, factor_col=_SCORE, fwd_col="fwd_1m_rel")

    # G2 — quintile spread of fwd_1m_rel by score.
    spreads = _monthly_spread(scored)
    spread_mean = float(np.mean(spreads)) if spreads else float("nan")
    spread_share = float(np.mean([s > 0 for s in spreads])) if spreads else float("nan")

    # G3 — selection alpha (book − equal-weight universe), NW-t vs 0.
    alpha_arr = np.asarray(selection_alphas)
    alpha_mean = float(np.mean(alpha_arr)) if selection_alphas else float("nan")
    alpha_t = (
        gates.nw_tstat(alpha_arr, null=0.0, lag=gates.NW_LAG) if selection_alphas else float("nan")
    )

    # Displayed probability — portfolio-cohort beat rate vs the benchmark + NW CI.
    beat_arr = np.asarray(portfolio_beats)
    beat_rate = float(np.mean(beat_arr)) if portfolio_beats else float("nan")
    beat_ci = (
        gates.nw_ci95(beat_arr, lag=gates.NW_LAG)
        if portfolio_beats
        else (float("nan"), float("nan"))
    )

    # G6 — one-way turnover of the top-N set.
    turnovers = cohort_turnover(cohort_sets)
    mean_turnover = float(np.mean(turnovers)) if turnovers else float("nan")

    return EvalReport(
        spec_name=spec.name,
        spec_version=spec.version,
        market=spec.market,
        window_start=months[0].date().isoformat() if months else "",
        window_end=months[-1].date().isoformat() if months else "",
        n_months=len(months),
        n_cohorts=len(selection_alphas),
        ic_mean=ic.mean_ic,
        ic_t=ic.t_stat,
        ic_months=ic.n_periods,
        spread_mean=spread_mean,
        spread_positive_share=spread_share,
        selection_alpha_mean=alpha_mean,
        selection_alpha_t=alpha_t,
        portfolio_beat_rate=beat_rate,
        portfolio_beat_ci95=beat_ci,
        mean_turnover=mean_turnover,
    )


def _resolve_window(name: str) -> tuple[str, str]:
    if name in WINDOWS:
        return WINDOWS[name]
    parts = name.split(":", 1)
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError(
            f"{name!r}: use 'dev', 'val', or 'START:END' (YYYY-MM-DD:YYYY-MM-DD)"
        )
    return parts[0], parts[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evaluate a spec on an in-sample window (dev/val)")
    p.add_argument("spec", help="path to a spec JSON under signals/specs/")
    p.add_argument("--window", type=_resolve_window, default="dev", help="dev | val | START:END")
    args = p.parse_args(argv)

    spec = load_spec(Path(args.spec))
    window = args.window if isinstance(args.window, tuple) else _resolve_window(args.window)
    rep = evaluate(spec, load_panel(spec.market), window)
    lo, hi = rep.portfolio_beat_ci95
    print(f"{rep.spec_name} v{rep.spec_version} [{rep.market}] — window {window[0]}→{window[1]}")
    print(f"  months={rep.n_months} cohorts={rep.n_cohorts}")
    print(f"  G1 IC {rep.ic_mean:+.4f} (t {rep.ic_t:+.2f}, {rep.ic_months} mo)")
    print(f"  G2 spread {rep.spread_mean:+.4%}/mo (positive {rep.spread_positive_share:.0%})")
    print(
        f"  G3 selection alpha {rep.selection_alpha_mean:+.2%} (NW-t {rep.selection_alpha_t:+.2f})"
    )
    print(f"  displayed beat rate {rep.portfolio_beat_rate:.1%} (95% CI {lo:.1%}–{hi:.1%})")
    print(f"  turnover {rep.mean_turnover:.0%}")
    print(f"  advances to validation: {rep.advances}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
