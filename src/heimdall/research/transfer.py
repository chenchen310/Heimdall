"""IC → selection transfer diagnostic (roadmap 18.17): DEV only, descriptive, never a gate.

The recurring US finding (RESEARCH_LOG 017/018) is real ranking IC without top-N selection
skill. This module measures *where along the ranking* a signal's alpha sits and how much of it a
long-only top-N book captures, so the construction options of card 18.18 are chosen on evidence:

- **rank-bucket profile**: score deciles D1…D10 plus the nested books top-{10, 20, 50, 100}. A
  bucket's alpha is its equal-weight mean label minus the equal-weight tier universe (the G3
  unit); 6m with a Newey–West t (lag 5), 1m with a plain t.
- **leg decomposition**: long leg = D10 − universe, short leg = universe − D1, both raw (never a
  ratio of two near-zero numbers). The two legs sum to the D10 − D1 spread.
- **book-size curve**: the F1 objective (annualized IR of the monthly net selection alpha at
  G4's per-side cost) of the equal-weight top-{10, 20, 50, 100} books, from the factory's own
  evaluator.
- **transfer coefficient**: per month, the cross-sectional correlation between book weights and
  scores over the scored pool (Clarke, de Silva & Thorley 2002, without a risk model; the
  constant benchmark weight 1/N drops out of a correlation).
- **size split**: the book's members by market-cap tercile of the tier universe, with each
  tercile's count share and 6m alpha contribution (the contributions sum to the book's alpha).

Existing gate math is imported, never re-implemented: G1/G3 through
:func:`heimdall.research.evaluate.evaluate`, the F1 series through
:func:`heimdall.research.factory.evaluate_fast`, book returns through ``certify._book_mean``.
**Only DEV rows are read** (dated ≤ 2019-12-31, asserted): the VAL window belongs to future
finalists' single looks and the vault to ``certify``. No trial is logged and the registry is
never touched.

    uv run python -m heimdall.research.transfer
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.data.store import data_root
from heimdall.research import construct, gates
from heimdall.research.certify import SURVIVORSHIP, _book_mean
from heimdall.research.dataset import load_panel
from heimdall.research.evaluate import WINDOWS, evaluate
from heimdall.research.factory import SearchConfig, evaluate_fast, prepare
from heimdall.research.spec import SignalSpec

DEV_START, DEV_END = WINDOWS["dev"]
VAL_START = WINDOWS["val"][0]
#: Nested equal-weight books of the profile and the book-size curve.
BOOK_SIZES: tuple[int, ...] = (10, 20, 50, 100)
N_DECILES = 10
TERCILES: tuple[str, ...] = ("small", "mid", "large", "n/a")  # n/a = no usable market cap

#: The card's pre-stated list, verbatim; nothing is added mid-session. The us-f1 trials are
#: their trial-ledger ``spec_json`` exactly (a test pins each canonical hash to the ledger's).
PRESTATED: dict[str, dict[str, object]] = {
    "us-f1 t148": {
        "name": "us-f1-t00148",
        "family": "us-factory-us-f1",
        "market": "US",
        "features": {"ps": -1.0, "fcf_yield": 1.0},
        "top_n": 20,
    },
    "us-f1 t1525": {
        "name": "us-f1-t01525",
        "family": "us-factory-us-f1",
        "market": "US",
        "features": {"roe": 1.0, "net_debt_to_ebitda": -1.0},
        "top_n": 10,
        "universe": "us_large",
        "weighting": "inverse_vol",
        "exit_rank": 20,
    },
    "us-f1 t1915": {
        "name": "us-f1-t01915",
        "family": "us-factory-us-f1",
        "market": "US",
        "features": {"accruals": -1.0, "net_debt_to_ebitda": -1.0},
        "top_n": 10,
        "universe": "us_large",
        "weighting": "inverse_vol",
        "exit_rank": 20,
    },
    "us-f1 t2074": {
        "name": "us-f1-t02074",
        "family": "us-factory-us-f1",
        "market": "US",
        "features": {"fcf_yield": 1.0},
        "top_n": 10,
        "universe": "us_large",
    },
    "us-f1 t1849": {
        "name": "us-f1-t01849",
        "family": "us-factory-us-f1",
        "market": "US",
        "features": {"fcf_yield": 1.0, "roe": 1.0},
        "top_n": 10,
        "universe": "us_large",
    },
    "fcf_yield (011)": {
        "name": "transfer-fcf-yield",
        "family": "diagnostic",
        "market": "US",
        "features": {"fcf_yield": 1.0},
    },
    "net_issuance_12m (016)": {
        "name": "transfer-net-issuance",
        "family": "diagnostic",
        "market": "US",
        "features": {"net_issuance_12m": -1.0},
    },
    "rev_accel_q (018)": {
        "name": "transfer-rev-accel",
        "family": "diagnostic",
        "market": "US",
        "features": {"rev_accel_q": 1.0},
    },
    "fcf_yield sector-neutral (018)": {
        "name": "transfer-fcf-yield-neutral",
        "family": "diagnostic",
        "market": "US",
        "features": {"fcf_yield": 1.0},
        "neutralize": "sector",
    },
}


def prestated_specs() -> list[tuple[str, SignalSpec]]:
    return [(label, SignalSpec.model_validate(p)) for label, p in PRESTATED.items()]


def bucket_labels() -> list[str]:
    return [f"D{d}" for d in range(1, N_DECILES + 1)] + [f"top{k}" for k in BOOK_SIZES]


@dataclass
class Diagnostic:
    """One spec's transfer read over DEV. Alphas are fractions (0.01 = 1%)."""

    label: str
    spec: dict[str, object]
    window: tuple[str, str]
    n_months: int
    ic_mean: float  # G1 (evaluate)
    ic_t: float
    alpha6_mean: float  # G3 of the spec as constructed (evaluate)
    alpha6_t: float
    turnover: float
    objective_ir: float  # F1 objective of the spec as constructed (evaluate_fast)
    coverage: float  # mean share of the tier universe with a finite score
    tc_book: float  # mean monthly transfer coefficient of the spec's own book
    buckets: list[dict[str, float | str]]  # bucket, alpha1_mean/_t, alpha6_mean/_t, months
    legs: dict[str, float]  # long1, long1_t, short1, short1_t, long6, long6_t, short6, short6_t
    book_size: list[dict[str, float]]  # top_n, objective_ir, alpha6_mean/_t, turnover, tc
    size_split: dict[str, dict[str, float]]  # tercile → count_share, alpha6_contrib

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def dev_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """The DEV slice (rows dated DEV_START…DEV_END) with parsed dates. Nothing later survives."""
    dates = pd.to_datetime(panel["date"])
    keep = (dates >= pd.Timestamp(DEV_START)) & (dates <= pd.Timestamp(DEV_END))
    dev = panel.loc[keep].assign(date=dates[keep]).reset_index(drop=True)
    if bool((dev["date"] >= pd.Timestamp(VAL_START)).any()):  # pragma: no cover - by construction
        raise AssertionError("the transfer diagnostic must never read a row ≥ VAL start")
    return dev


def transfer_coefficient(weights: pd.Series, scores: pd.Series) -> float:
    """Correlation between book weight and score across the scored pool (symbol-indexed).

    Non-members weigh 0. A constant benchmark weight would only shift every active weight by the
    same amount, so it drops out. NaN when fewer than 3 names score or either side is constant.
    """
    s = scores.dropna().astype(float)
    w = weights.reindex(s.index, fill_value=0.0).astype(float)
    if len(s) < 3 or float(s.std()) == 0.0 or float(w.std()) == 0.0:
        return float("nan")
    return float(np.corrcoef(w.to_numpy(), s.to_numpy())[0, 1])


def size_split(
    cross: pd.DataFrame, book: pd.Series, universe: pd.Series
) -> dict[str, tuple[float, float]]:
    """{tercile: (count share, 6m alpha contribution)} for one month's book.

    Terciles are of ``market_cap`` over the tier universe (a missing or non-positive cap is
    ``n/a``). Weights are renormalized over members with a 6m label, so the contributions sum to
    Σ w·r − universe mean: the book's alpha for a fully invested book.
    """
    out = {g: (0.0, 0.0) for g in TERCILES}
    if book.empty:
        return out
    tier = cross[universe]
    cap = tier.set_index("symbol")["market_cap"].astype(float)
    cap = cap[cap > 0]
    group = pd.Series("n/a", index=book.index, dtype=object)
    if len(cap) >= len(TERCILES) - 1:
        cut = pd.qcut(cap.rank(method="first"), 3, labels=list(TERCILES[:3]))
        group = cut.astype(object).reindex(book.index).fillna("n/a")
    label = cross.set_index("symbol")["fwd_6m_rel"].astype(float).reindex(book.index)
    univ6 = tier["fwd_6m_rel"].dropna()
    ok = label.notna()
    w = book.astype(float)[ok]
    if not len(univ6) or not ok.any() or float(w.sum()) <= 0:
        return out
    w = w / float(w.sum())
    excess = (label[ok] - float(univ6.mean())) * w
    for g in TERCILES:
        in_g = group == g
        out[g] = (float(in_g.mean()), float(excess[in_g[ok]].sum()))
    return out


def _plain_t(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if len(arr) < 2:
        return float("nan")
    sd = float(arr.std(ddof=1))
    return float(arr.mean() / (sd / math.sqrt(len(arr)))) if sd > 0 else float("nan")


def _nw_t(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if len(arr) < 2:
        return float("nan")
    return gates.nw_tstat(arr, null=0.0, lag=gates.NW_LAG)


def _mean(values: list[float]) -> float:
    arr = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    return float(arr.mean()) if len(arr) else float("nan")


def _ew(names: list[str]) -> pd.Series:
    return pd.Series(1.0 / len(names), index=names) if names else pd.Series(dtype=float)


def _deciles(scored_syms: pd.Series) -> dict[str, list[str]]:
    """Score deciles of the scored pool: D1 lowest … D10 highest (``_monthly_spread``'s cut)."""
    if len(scored_syms) < N_DECILES:
        return {}
    cut = pd.qcut(scored_syms.rank(method="first"), N_DECILES, labels=False)
    return {f"D{d + 1}": [str(s) for s in cut.index[cut == d]] for d in range(N_DECILES)}


def _book_size_curve(spec: SignalSpec, dev: pd.DataFrame) -> tuple[float, list[dict[str, float]]]:
    """The spec's own F1 objective, and the EW top-K variants' (F1 objective, G3, turnover)."""
    pool = {f: (1 if w > 0 else -1) for f, w in spec.features.items()}
    cfg = SearchConfig(
        run_id="transfer",
        market=spec.market,
        feature_pool=pool,
        universes=[spec.universe],
        neutralize_menu=[spec.neutralize],
    )
    dp = prepare(dev, cfg)
    own = evaluate_fast(spec, dp).objective
    rows: list[dict[str, float]] = []
    for k in BOOK_SIZES:
        variant = SignalSpec.model_validate(
            {
                **spec.model_dump(),
                "top_n": k,
                "weighting": "",
                "exit_rank": None,
                "max_sector_weight": None,
            }
        )
        met = evaluate_fast(variant, dp)
        rows.append(
            {
                "top_n": float(k),
                "objective_ir": met.objective,
                "alpha6_mean": met.alpha_mean,
                "alpha6_t": met.alpha_t,
                "turnover": met.turnover,
            }
        )
    return own, rows


def diagnose(label: str, spec: SignalSpec, panel: pd.DataFrame) -> Diagnostic:
    """Run every diagnostic of the module docstring for one spec on the panel's DEV rows."""
    dev = dev_rows(panel)
    rep = evaluate(spec, dev, WINDOWS["dev"])
    own_ir, curve = _book_size_curve(spec, dev)

    names = bucket_labels()
    a1: dict[str, list[float]] = {b: [] for b in names}
    a6: dict[str, list[float]] = {b: [] for b in names}
    tc_book: list[float] = []
    tc_k: dict[int, list[float]] = {k: [] for k in BOOK_SIZES}
    coverage: list[float] = []
    share: dict[str, list[float]] = {g: [] for g in TERCILES}
    contrib: dict[str, list[float]] = {g: [] for g in TERCILES}
    prev: set[str] | None = None
    n_months = 0
    for _, cross in dev.groupby("date", sort=True):
        n_months += 1
        scores = construct.pool_scores(spec, cross)
        universe = construct.universe_mask(spec, cross)
        book = construct.select(spec, cross, scores, prev)
        prev = set(book.index)
        by_sym = pd.Series(scores.to_numpy(), index=cross["symbol"].astype(str))
        scored = by_sym.dropna()
        n_univ = int(universe.sum())
        coverage.append(len(scored) / n_univ if n_univ else float("nan"))

        uni_rows = cross[universe]
        u1 = uni_rows["fwd_1m_rel"].dropna()
        u6 = uni_rows["fwd_6m_rel"].dropna()
        ranked = construct.ranked_symbols(cross, scores)
        buckets: dict[str, list[str]] = _deciles(scored)
        for k in BOOK_SIZES:
            if len(ranked) >= k:
                buckets[f"top{k}"] = ranked[:k]
        for b in names:
            members = buckets.get(b)
            if not members:
                a1[b].append(float("nan"))
                a6[b].append(float("nan"))
                continue
            ew = _ew(members)
            r1 = _book_mean(cross, ew, "fwd_1m_rel", equal=True)
            r6 = _book_mean(cross, ew, "fwd_6m_rel", equal=True)
            a1[b].append(r1 - float(u1.mean()) if len(u1) else float("nan"))
            a6[b].append(r6 - float(u6.mean()) if len(u6) else float("nan"))

        tc_book.append(transfer_coefficient(book, scored))
        for k in BOOK_SIZES:
            top = ranked[:k] if len(ranked) >= k else []
            tc_k[k].append(transfer_coefficient(_ew(top), scored) if top else float("nan"))
        for g, (sh, ct) in size_split(cross, book, universe).items():
            share[g].append(sh)
            contrib[g].append(ct)

    bucket_rows: list[dict[str, float | str]] = [
        {
            "bucket": b,
            "alpha1_mean": _mean(a1[b]),
            "alpha1_t": _plain_t(a1[b]),
            "alpha6_mean": _mean(a6[b]),
            "alpha6_t": _nw_t(a6[b]),
            "months": float(sum(math.isfinite(v) for v in a6[b])),
        }
        for b in names
    ]
    short1 = [-v for v in a1["D1"]]
    short6 = [-v for v in a6["D1"]]
    legs = {
        "long1": _mean(a1[f"D{N_DECILES}"]),
        "long1_t": _plain_t(a1[f"D{N_DECILES}"]),
        "short1": _mean(short1),
        "short1_t": _plain_t(short1),
        "long6": _mean(a6[f"D{N_DECILES}"]),
        "long6_t": _nw_t(a6[f"D{N_DECILES}"]),
        "short6": _mean(short6),
        "short6_t": _nw_t(short6),
    }
    for row in curve:
        row["tc_mean"] = _mean(tc_k[int(row["top_n"])])
    return Diagnostic(
        label=label,
        spec=json.loads(spec.model_dump_json()),
        window=(DEV_START, DEV_END),
        n_months=n_months,
        ic_mean=rep.ic_mean,
        ic_t=rep.ic_t,
        alpha6_mean=rep.selection_alpha_mean,
        alpha6_t=rep.selection_alpha_t,
        turnover=rep.mean_turnover,
        objective_ir=own_ir,
        coverage=_mean(coverage),
        tc_book=_mean(tc_book),
        buckets=bucket_rows,
        legs=legs,
        book_size=curve,
        size_split={
            g: {"count_share": _mean(share[g]), "alpha6_contrib": _mean(contrib[g])}
            for g in TERCILES
        },
    )


# --- report -----------------------------------------------------------------------------


def _pct(x: float, nd: int = 2) -> str:
    return f"{x * 100:+.{nd}f}%" if math.isfinite(x) else "—"


def _num(x: float, nd: int = 2) -> str:
    return f"{x:+.{nd}f}" if math.isfinite(x) else "—"


def render_markdown(diags: list[Diagnostic]) -> str:
    """The RESEARCH_LOG tables: summary, 6m bucket profile, legs, book-size curve, size split."""
    lines = [
        "| spec | IC (t) | G3 α 6m (NW-t) | F1 IR | TC | coverage |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in diags:
        lines.append(
            f"| {d.label} | {d.ic_mean:+.4f} ({_num(d.ic_t)}) | {_pct(d.alpha6_mean)} "
            f"({_num(d.alpha6_t)}) | {_num(d.objective_ir)} | {_num(d.tc_book)} | "
            f"{d.coverage:.0%} |"
        )
    names = bucket_labels()
    lines += ["", "| spec | " + " | ".join(names) + " |", "| --- " * (len(names) + 1) + "|"]
    for d in diags:
        by = {str(r["bucket"]): r for r in d.buckets}
        cells = [_pct(float(by[b]["alpha6_mean"]), 1) for b in names]
        lines.append(f"| {d.label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "| spec | long 1m (t) | short 1m (t) | long 6m (NW-t) | short 6m (NW-t) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in diags:
        lg = d.legs
        lines.append(
            f"| {d.label} | {_pct(lg['long1'])} ({_num(lg['long1_t'])}) | "
            f"{_pct(lg['short1'])} ({_num(lg['short1_t'])}) | "
            f"{_pct(lg['long6'])} ({_num(lg['long6_t'])}) | "
            f"{_pct(lg['short6'])} ({_num(lg['short6_t'])}) |"
        )
    head = " | ".join(f"top {k}: IR / α6 (t) / turn / TC" for k in BOOK_SIZES)
    lines += ["", f"| spec | {head} |", "| --- " * (len(BOOK_SIZES) + 1) + "|"]
    for d in diags:
        cells = [
            f"{_num(r['objective_ir'])} / {_pct(r['alpha6_mean'], 1)} ({_num(r['alpha6_t'])}) / "
            f"{r['turnover']:.0%} / {_num(r['tc_mean'])}"
            for r in d.book_size
        ]
        lines.append(f"| {d.label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "| spec | " + " | ".join(f"{g}: share / α6" for g in TERCILES) + " |",
        "| --- " * (len(TERCILES) + 1) + "|",
    ]
    for d in diags:
        cells = [
            f"{d.size_split[g]['count_share']:.0%} / {_pct(d.size_split[g]['alpha6_contrib'])}"
            for g in TERCILES
        ]
        lines.append(f"| {d.label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def output_path(root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    stamp = datetime.now(UTC).date().isoformat()
    return base / "research" / "diagnostics" / f"transfer_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="18.17 IC → selection transfer diagnostic (DEV only)")
    p.add_argument("--out", type=Path, default=None, help="JSON path (default: data/research/…)")
    args = p.parse_args(argv)

    panel = load_panel("US")
    diags = [diagnose(label, spec, panel) for label, spec in prestated_specs()]
    out = args.out if args.out is not None else output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "card": "18.17",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "window": [DEV_START, DEV_END],
        "survivorship": SURVIVORSHIP,
        "cost_bps_per_side": gates.G4_COST_BPS,
        "diagnostics": [d.to_dict() for d in diags],
    }
    out.write_text(json.dumps(payload, indent=2, allow_nan=True))
    print(render_markdown(diags))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
