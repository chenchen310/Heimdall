"""Certification harness — the referee (roadmap 8.2).

``certify()`` is the pure engine: spec + panel + benchmark series in, a
:class:`CertReport` with every gate's value/threshold/verdict out. Real runs go
through :func:`certify_and_record` (or the CLI), which enforce the institution
in this order: immutable-report check → committed pre-registration check
(``docs/RESEARCH_LOG.md`` must contain the spec's sha256 under the given entry
id) → **spend the family's OOS attempt** → only then evaluate the vault. A
refusal never costs an attempt; an evaluation always does — peeking is
spending (playbook §4).

G4 note: the top-N backtest is derived directly from the panel's own ``fwd_1m``
labels (gross = mean pick return per rebalance, minus per-side costs on traded
value). That keeps every gate on the *same* calendar windows as the labels —
no second pricing path to disagree with them.

    uv run python -m heimdall.research.certify signals/specs/<f>.json --log-entry <id>
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.factors.validate import information_coefficient
from heimdall.research import construct, gates, registry
from heimdall.research.benchmark import BENCHMARK, window_return
from heimdall.research.dataset import load_panel
from heimdall.research.spec import SignalSpec, count_free_params, load_spec

SURVIVORSHIP = "current_universe (optimistic)"
_SCORE = "signal_score"


@dataclass
class GateResult:
    gate: str
    value: float
    threshold: float
    passed: bool
    note: str = ""


@dataclass
class CertReport:
    spec_name: str
    spec_version: int
    spec_hash: str
    market: str
    window_start: str
    window_end: str
    n_months: int
    verdict: str  # "CERTIFIED" | "REJECTED"
    gates: list[GateResult]
    # DISPLAYED probability: fraction of cohorts whose EW top-N book beat the benchmark over 6m.
    portfolio_beat_rate: float
    portfolio_beat_ci95: tuple[float, float]
    # G3 skill: mean per-cohort selection alpha (book 6m − equal-weight-universe 6m), and its NW-t.
    selection_alpha_mean: float
    selection_alpha_t: float
    cohorts: list[dict[str, object]]  # {date, book_rel_6m, alpha_6m, n_picks} per rebalance
    mean_turnover: float
    survivorship: str = SURVIVORSHIP
    generated_at: str = ""
    # Non-default construction choices (18.1), disclosed on every report; {} = the plain book.
    construction: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# --- small, hand-testable pieces ------------------------------------------------


def cohort_turnover(cohorts: list[set[str]]) -> list[float]:
    """One-way turnover per rebalance: the fraction of the book replaced."""
    out: list[float] = []
    for prev, cur in zip(cohorts, cohorts[1:], strict=False):
        out.append(1.0 - len(cur & prev) / max(len(cur), 1))
    return out


def weight_turnover(books: list[pd.Series]) -> list[float]:
    """One-way turnover between consecutive weighted books: ½ Σ|Δw| (18.2).

    For two equal-weight books of the same size this equals :func:`cohort_turnover`;
    weighted books (inverse-vol, sector-capped) need it because a reweight is a trade.
    """
    out: list[float] = []
    for prev, cur in zip(books, books[1:], strict=False):
        both = prev.index.union(cur.index)
        diff = cur.reindex(both, fill_value=0.0) - prev.reindex(both, fill_value=0.0)
        out.append(0.5 * float(diff.abs().sum()))
    return out


def traded_fractions(held: list[pd.Series]) -> list[float]:
    """Σ|Δw| per period of a held-weights sequence, starting from cash (both trade sides).

    The overlay's cost basis (18.2): a switch to cash sells the whole book (1.0), the switch
    back buys it (1.0), and an ordinary rebalance trades 2 × its one-way turnover.
    """
    out: list[float] = []
    prev = pd.Series(dtype=float)
    for cur in held:
        both = prev.index.union(cur.index)
        diff = cur.reindex(both, fill_value=0.0) - prev.reindex(both, fill_value=0.0)
        out.append(float(diff.abs().sum()))
        prev = cur
    return out


def apply_costs_traded(gross: list[float], traded: list[float], cost_bps: float) -> list[float]:
    """Net returns given the traded fraction (Σ|Δw|) of each period."""
    rate = cost_bps / 1e4
    return [g - t * rate for g, t in zip(gross, traded, strict=True)]


def apply_costs(gross: list[float], turnovers: list[float], cost_bps: float) -> list[float]:
    """Net returns: month 0 buys the whole book (one side); later months trade
    both sides of the replaced fraction (sell + buy = 2 × turnover)."""
    rate = cost_bps / 1e4
    net: list[float] = []
    for i, g in enumerate(gross):
        traded = 1.0 if i == 0 else 2.0 * turnovers[i - 1]
        net.append(g - traded * rate)
    return net


def _cagr(monthly: list[float]) -> float:
    if not monthly:
        return float("nan")
    total = float(np.prod([1.0 + r for r in monthly]))
    if total <= 0:
        return -1.0
    return float(total ** (12.0 / len(monthly)) - 1.0)


def _sharpe(monthly: list[float]) -> float:
    arr = np.asarray(monthly, dtype=float)
    if len(arr) < 2 or float(arr.std(ddof=1)) == 0.0:
        return float("nan")
    return float(arr.mean() / arr.std(ddof=1) * np.sqrt(12.0))


def _monthly_spread(df: pd.DataFrame, q: int = 5) -> list[float]:
    """Per-month top-minus-bottom quantile mean of ``fwd_1m_rel`` by score."""
    out: list[float] = []
    for _, grp in df.groupby("date"):
        g = grp.dropna(subset=[_SCORE, "fwd_1m_rel"])
        if len(g) < q:
            continue
        buckets = pd.qcut(g[_SCORE].rank(method="first"), q, labels=False)
        means = g.groupby(buckets)["fwd_1m_rel"].mean()
        out.append(float(means.iloc[-1] - means.iloc[0]))
    return out


def _book_rows(scored: pd.DataFrame, book: pd.Series) -> pd.DataFrame:
    """The book's rows, in the book's (rank) order — the order the legacy ``head`` used."""
    by_sym = scored.set_index("symbol")
    return by_sym.loc[[s for s in book.index if s in by_sym.index]]


def _book_mean(scored: pd.DataFrame, book: pd.Series, col: str, equal: bool) -> float:
    """The book's return on ``col``: a plain mean for equal-weight books (bit-for-bit the
    legacy ``head(top_n)[col].dropna().mean()``), else Σ w·r renormalized over names with a
    label, scaled by the invested fraction (an infeasible sector cap leaves cash at 0).
    NaN when no member has a label."""
    vals = _book_rows(scored, book)[col]
    if equal:
        present = vals.dropna()
        return float(present.mean()) if len(present) else float("nan")
    ok = vals.notna().to_numpy()
    if not ok.any():
        return float("nan")
    w = book.reindex(vals.index).to_numpy()[ok]
    r = vals.to_numpy()[ok]
    invested = float(book.sum())
    ret = float((w * r).sum() / w.sum())
    return ret * invested if invested < 1.0 - 1e-9 else ret


def _book_minus_universe(
    scored: pd.DataFrame,
    top_n: int,
    *,
    book: pd.Series | None = None,
    universe: pd.Series | None = None,
    equal: bool = True,
) -> tuple[float, float] | None:
    """From a scored cross-section: (book 6m `fwd_6m_rel`, EW universe 6m `fwd_6m_rel`).

    The shared G3 selection unit — used by :func:`certify`, :mod:`heimdall.research.evaluate`
    and :mod:`heimdall.research.monitor` so the certified metric has exactly one home. With no
    ``book`` it is the pre-18.2 computation (EW top-N of the score column vs the EW eligible
    universe); with a constructed ``book`` (18.2) the book leg is that book and the universe leg
    is ``universe`` (the spec's tier — eligible rows when omitted). None if either leg is empty.
    """
    if book is None:
        ranked = scored.dropna(subset=[_SCORE]).sort_values(_SCORE, ascending=False)
        book6 = ranked.head(top_n)["fwd_6m_rel"].dropna()
        pool = scored[scored["eligible"].astype(bool)] if "eligible" in scored.columns else scored
        univ6 = pool["fwd_6m_rel"].dropna()
        if not len(book6) or not len(univ6):
            return None
        return float(book6.mean()), float(univ6.mean())
    book_ret = _book_mean(scored, book, "fwd_6m_rel", equal)
    if universe is not None:
        pool = scored[universe]
    elif "eligible" in scored.columns:
        pool = scored[scored["eligible"].astype(bool)]
    else:
        pool = scored
    univ6 = pool["fwd_6m_rel"].dropna()
    if np.isnan(book_ret) or not len(univ6):
        return None
    return book_ret, float(univ6.mean())


def cohort_book(
    spec: SignalSpec, cross: pd.DataFrame, prev: set[str] | None = None
) -> tuple[pd.Series, tuple[float, float] | None]:
    """Construct one cross-section's book (18.1) and its (book 6m, EW-universe 6m) returns.

    ``prev`` = last month's members, for a rank-buffered spec; callers replaying a sequence
    thread the returned book's index forward.
    """
    scored = cross.assign(**{_SCORE: construct.pool_scores(spec, cross)})
    book = construct.select(spec, scored, scored[_SCORE], prev)
    bu = _book_minus_universe(
        scored,
        spec.top_n,
        book=book,
        universe=construct.universe_mask(spec, scored),
        equal=construct.is_equal_weight(spec),
    )
    return book, bu


def cohort_alpha(
    spec: SignalSpec, cross: pd.DataFrame, prev: set[str] | None = None
) -> tuple[float, float] | None:
    """Score one cross-section and return its (book 6m, equal-weight-universe 6m) relative returns.

    The drift monitor's input (12.2): both legs are benchmark-relative, so the benchmark cancels
    in ``book − universe``, leaving the selection skill G3 certifies — no benchmark fetch needed.
    """
    return cohort_book(spec, cross, prev)[1]


# --- the referee ----------------------------------------------------------------


def certify(spec: SignalSpec, panel: pd.DataFrame, benchmark_adj: pd.Series) -> CertReport:
    """Evaluate every gate on the OOS window and return the full evidence.

    Pure computation — the pre-registration/attempt enforcement lives in
    :func:`certify_and_record`; never call this on the real vault outside it.
    """
    months_all = sorted(pd.Timestamp(t) for t in panel["date"].unique())
    next_of = {
        t: (months_all[i + 1] if i + 1 < len(months_all) else None)
        for i, t in enumerate(months_all)
    }
    oos = [
        t
        for t in months_all
        if t >= pd.Timestamp(gates.OOS_START)
        and bool(panel.loc[panel["date"] == t, "fwd_6m"].notna().any())
    ]
    if not oos:
        raise ValueError(f"panel has no OOS months (≥ {gates.OOS_START}) with complete 6m labels")

    # Score each OOS cross-section and construct its book (18.1/18.2: universe tier, filters,
    # weighting, sector cap, rank buffer — a default spec is the pre-18.2 EW top-N exactly).
    equal = construct.is_equal_weight(spec)
    frames: list[pd.DataFrame] = []
    cohorts_sets: list[set[str]] = []
    books: list[pd.Series] = []
    held: list[pd.Series] = []  # the overlaid book behind each G4 month (empty = cash)
    cohort_rows: list[dict[str, object]] = []
    portfolio_beats: list[
        float
    ] = []  # per cohort: did the EW top-N book beat the benchmark over 6m?
    selection_alphas: list[float] = []  # per cohort: book 6m − equal-weight-universe 6m (skill)
    gross_returns: list[float] = []
    bench_returns: list[float] = []
    prev: set[str] | None = None
    for t in oos:
        cross = panel[panel["date"] == t].copy()
        cross[_SCORE] = construct.pool_scores(spec, cross)
        frames.append(cross)
        book = construct.select(spec, cross, cross[_SCORE], prev)
        prev = set(book.index)
        books.append(book)
        cohorts_sets.append(set(book.index))
        # Selection skill: the book vs the equal-weight universe of the spec's tier (a real
        # alternative, ~an equal-weight ETF). The benchmark cancels in book − universe. The
        # overlay never touches this leg (playbook §12.4: timing is not stock-picking).
        bu = _book_minus_universe(
            cross,
            spec.top_n,
            book=book,
            universe=construct.universe_mask(spec, cross),
            equal=equal,
        )
        if bu is not None:
            book_ret, univ_ret = bu
            portfolio_beats.append(float(book_ret > 0))
            selection_alphas.append(book_ret - univ_ret)
            cohort_rows.append(
                {
                    "date": t.date().isoformat(),
                    "book_rel_6m": book_ret,
                    "alpha_6m": book_ret - univ_ret,
                    "n_picks": int(_book_rows(cross, book)["fwd_6m_rel"].notna().sum()),
                }
            )
        nxt = next_of.get(t)
        gross = _book_mean(cross, book, "fwd_1m", equal)
        if nxt is not None and not np.isnan(gross):
            bench = window_return(benchmark_adj, t, nxt)
            if pd.notna(bench):
                cash = construct.overlay_cash(spec, benchmark_adj, t)
                gross_returns.append(0.0 if cash else gross)
                held.append(pd.Series(dtype=float) if cash else book)
                bench_returns.append(float(bench))
    scored = pd.concat(frames, ignore_index=True)

    results: list[GateResult] = []

    # G1 — monthly rank IC of the score vs next-window benchmark-relative return.
    ic = information_coefficient(scored, factor_col=_SCORE, fwd_col="fwd_1m_rel")
    results.append(
        GateResult("G1_ic", ic.mean_ic, gates.G1_MIN_IC, bool(ic.mean_ic >= gates.G1_MIN_IC))
    )
    results.append(GateResult("G1_t", ic.t_stat, gates.G1_MIN_T, bool(ic.t_stat >= gates.G1_MIN_T)))
    results.append(
        GateResult(
            "G1_months",
            float(ic.n_periods),
            float(gates.G1_MIN_MONTHS),
            ic.n_periods >= gates.G1_MIN_MONTHS,
        )
    )

    # G2 — quintile spread: positive on average and in most months.
    spreads = _monthly_spread(scored)
    spread_mean = float(np.mean(spreads)) if spreads else float("nan")
    spread_share = float(np.mean([s > 0 for s in spreads])) if spreads else float("nan")
    results.append(GateResult("G2_mean", spread_mean, 0.0, bool(spread_mean > 0)))
    results.append(
        GateResult(
            "G2_share",
            spread_share,
            gates.G2_MIN_POSITIVE_SHARE,
            bool(spread_share >= gates.G2_MIN_POSITIVE_SHARE),
        )
    )

    # G3 — selection skill: per-cohort alpha (book − equal-weight universe), NW-t vs 0. This is the
    # gate; the equal-weight/breadth premium cancels, so it credits stock-picking, not the EW tilt.
    alpha_arr = np.asarray(selection_alphas)
    alpha_mean = float(np.mean(alpha_arr)) if selection_alphas else float("nan")
    alpha_t = (
        gates.nw_tstat(alpha_arr, null=0.0, lag=gates.NW_LAG) if selection_alphas else float("nan")
    )
    results.append(GateResult("G3_alpha", alpha_mean, 0.0, bool(alpha_mean > 0)))
    results.append(
        GateResult(
            "G3_alpha_t", alpha_t, gates.G3_MIN_SKILL_T, bool(alpha_t >= gates.G3_MIN_SKILL_T)
        )
    )

    # Displayed probability (not a gate): the portfolio-cohort beat rate vs the benchmark + NW CI.
    beat_arr = np.asarray(portfolio_beats)
    port_rate = float(np.mean(beat_arr)) if portfolio_beats else float("nan")
    port_ci = (
        gates.nw_ci95(beat_arr, lag=gates.NW_LAG)
        if portfolio_beats
        else (float("nan"), float("nan"))
    )

    # G6 turnover (computed before G4 so the cost branch is known) — of the un-overlaid book.
    turnovers = cohort_turnover(cohorts_sets) if equal else weight_turnover(books)
    mean_turnover = float(np.mean(turnovers)) if turnovers else float("nan")

    def _net(cost_bps: float) -> list[float]:
        # An overlaid book pays for its cash switches (Σ|Δw| of the held sequence); otherwise
        # the pre-18.2 cost path, bit-for-bit.
        if spec.overlay:
            return apply_costs_traded(gross_returns, traded_fractions(held), cost_bps)
        return apply_costs(gross_returns, turnovers, cost_bps)

    # G4 — cost-aware book vs the benchmark, on the panel's own fwd_1m windows (overlaid).
    net = _net(gates.G4_COST_BPS)
    port_cagr, port_sharpe = _cagr(net), _sharpe(net)
    bench_cagr, bench_sharpe = _cagr(bench_returns), _sharpe(bench_returns)
    results.append(GateResult("G4_cagr", port_cagr, bench_cagr, bool(port_cagr > bench_cagr)))
    results.append(
        GateResult("G4_sharpe", port_sharpe, bench_sharpe, bool(port_sharpe > bench_sharpe))
    )

    # G5 — stability across OOS halves + parameter count.
    half = len(oos) // 2
    first, second = set(oos[:half]), set(oos[half:])
    ic1 = information_coefficient(
        scored[scored["date"].isin(first)], factor_col=_SCORE, fwd_col="fwd_1m_rel"
    )
    ic2 = information_coefficient(
        scored[scored["date"].isin(second)], factor_col=_SCORE, fwd_col="fwd_1m_rel"
    )
    results.append(GateResult("G5_ic_h1", ic1.mean_ic, 0.0, bool(ic1.mean_ic > 0)))
    results.append(GateResult("G5_ic_h2", ic2.mean_ic, 0.0, bool(ic2.mean_ic > 0)))
    results.append(
        GateResult(
            "G5_params",
            float(len(spec.features)),
            float(gates.G5_MAX_PARAMS),
            len(spec.features) <= gates.G5_MAX_PARAMS,
        )
    )

    # G6 — ≤40% passes; 40–60% must also survive G4 at the stress cost; >60% rejects.
    # Band edges tolerate float noise: 3-of-5 swaps mean exactly 0.60, and an ulp of
    # error (0.6000000000000001) must not flip a verdict.
    eps = 1e-9
    if mean_turnover <= gates.G6_MAX_TURNOVER + eps:
        results.append(GateResult("G6_turnover", mean_turnover, gates.G6_MAX_TURNOVER, True))
    elif mean_turnover <= gates.G6_STRESS_TURNOVER + eps:
        stress_net = _net(gates.G6_STRESS_COST_BPS)
        s_cagr, s_sharpe = _cagr(stress_net), _sharpe(stress_net)
        stress_ok = bool(s_cagr > bench_cagr and s_sharpe > bench_sharpe)
        results.append(
            GateResult(
                "G6_turnover",
                mean_turnover,
                gates.G6_STRESS_TURNOVER,
                stress_ok,
                note="stress band: G4 re-run at stress cost",
            )
        )
        results.append(GateResult("G6_stress_cagr", s_cagr, bench_cagr, bool(s_cagr > bench_cagr)))
        results.append(
            GateResult("G6_stress_sharpe", s_sharpe, bench_sharpe, bool(s_sharpe > bench_sharpe))
        )
    else:
        results.append(
            GateResult(
                "G6_turnover",
                mean_turnover,
                gates.G6_STRESS_TURNOVER,
                False,
                note="turnover above the stress band",
            )
        )

    verdict = "CERTIFIED" if all(g.passed for g in results) else "REJECTED"
    return CertReport(
        spec_name=spec.name,
        spec_version=spec.version,
        spec_hash=spec.canonical_hash(),
        market=spec.market,
        window_start=oos[0].date().isoformat(),
        window_end=oos[-1].date().isoformat(),
        n_months=len(oos),
        verdict=verdict,
        gates=results,
        portfolio_beat_rate=port_rate,
        portfolio_beat_ci95=port_ci,
        selection_alpha_mean=alpha_mean,
        selection_alpha_t=alpha_t,
        cohorts=cohort_rows,
        mean_turnover=mean_turnover,
        generated_at=datetime.now(UTC).isoformat(),
        construction=count_free_params(spec)[1],
    )


# --- institution enforcement ------------------------------------------------------


def check_preregistration(spec: SignalSpec, entry_id: str, log_path: Path) -> None:
    """Refuse unless RESEARCH_LOG has entry ``id`` containing this spec's sha256."""
    text = log_path.read_text()
    marker = f"## {entry_id} —"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(
            f"no RESEARCH_LOG entry {marker!r} in {log_path} — pre-register first (playbook §4)"
        )
    nxt = text.find("\n## ", idx + len(marker))
    section = text[idx : nxt if nxt != -1 else len(text)]
    if spec.canonical_hash() not in section:
        raise ValueError(
            f"RESEARCH_LOG entry {entry_id} does not contain this spec's sha256 "
            f"({spec.canonical_hash()[:12]}…) — pre-register the exact spec (playbook §4)"
        )


def report_path(spec: SignalSpec, root: Path | None = None) -> Path:
    base = root if root is not None else registry.registry_path().parent.parent
    return base / "signals" / "certifications" / f"{spec.name}_v{spec.version}.json"


def certify_and_record(
    spec: SignalSpec,
    panel: pd.DataFrame,
    benchmark_adj: pd.Series,
    *,
    log_entry: str,
    log_path: Path,
    root: Path | None = None,
    spend: bool = True,
) -> CertReport:
    """The guarded flow: refuse cheaply, spend the attempt, evaluate, record.

    Order matters: the immutable-report and pre-registration checks cost
    nothing; once they pass, the family's OOS attempt is spent **before** the
    vault is evaluated, and the outcome (certified/rejected) is written to the
    registry with its immutable report either way.

    ``spend=False`` is the playbook §4-rule-4 **void-and-rerun**: when a gate
    change (e.g. 12.5 replacing G3) voids an existing family attempt, re-running
    that same idea under the corrected gate is a *re-run*, not a new attempt, so
    it must not consume a fresh one. It still requires a committed
    pre-registration and a prior attempt to re-run — and, per the rule, a user
    sign-off recorded in ``docs/RESEARCH_LOG.md``. Every other guard is intact.
    """
    rpath = report_path(spec, root)
    if rpath.exists():
        raise FileExistsError(
            f"{rpath} already exists — certification reports are immutable; "
            "new evidence = a new spec version (signal-certification rule)"
        )
    check_preregistration(spec, log_entry, log_path)
    entry = registry.get(spec.name, spec.version, root=root)
    status = str(entry["status"])
    # A valid committed log entry IS the registration — for a hand-made draft, or for an
    # incubating factory finalist the user sent to the vault (playbook §12).
    if status in {"draft", "incubating"}:
        registry.transition(spec.name, spec.version, "registered", root=root)
    elif status != "registered":
        raise ValueError(
            f"{spec.name} v{spec.version} is {status!r}; "
            "only draft/incubating/registered specs can run"
        )
    if spend:
        attempt = registry.spend_attempt(spec.family, root=root)  # peeking is spending
    else:
        prior = registry.family_attempts(spec.family, root=root)
        if prior < 1:
            raise ValueError(
                f"void-and-rerun needs a prior attempt to re-run, but family {spec.family!r} "
                "has none — a first OOS attempt spends (spend=True, playbook §4 rule 4)"
            )
        attempt = prior  # re-run the existing attempt; the family counter is untouched

    report = certify(spec, panel, benchmark_adj)

    rpath.parent.mkdir(parents=True, exist_ok=True)
    tmp = rpath.with_name(f"{rpath.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    os.replace(tmp, rpath)
    registry.transition(
        spec.name,
        spec.version,
        "certified" if report.verdict == "CERTIFIED" else "rejected",
        cert_report=str(rpath),
        oos_attempt=attempt,
        root=root,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Certify a signal spec against the OOS vault")
    p.add_argument("spec", help="path to the spec JSON under signals/specs/")
    p.add_argument("--log-entry", required=True, help="pre-registered RESEARCH_LOG entry id")
    p.add_argument("--log", default=None, help="override the RESEARCH_LOG path (testing)")
    p.add_argument(
        "--void-and-rerun",
        action="store_true",
        help="§4 rule-4: re-run an existing family attempt under a changed gate WITHOUT spending a "
        "new one (requires a prior attempt + a user sign-off logged in RESEARCH_LOG)",
    )
    args = p.parse_args(argv)

    spec = load_spec(Path(args.spec))
    log_path = (
        Path(args.log)
        if args.log
        else registry.registry_path().parent.parent / "docs" / "RESEARCH_LOG.md"
    )

    panel = load_panel(spec.market)
    from heimdall.data import router  # lazy: pulls provider deps
    from heimdall.data.cache import CachedProvider

    prices = CachedProvider(router.price_provider())
    start = pd.Timestamp(panel["date"].min()).date() - timedelta(days=10)
    bench = prices.get_ohlcv(BENCHMARK[spec.market], start, datetime.now(UTC).date())
    benchmark_adj = bench.set_index("date")["adj_close"]

    report = certify_and_record(
        spec,
        panel,
        benchmark_adj,
        log_entry=args.log_entry,
        log_path=log_path,
        spend=not args.void_and_rerun,
    )
    if args.void_and_rerun:
        print("(void-and-rerun: re-ran an existing family attempt; no new attempt spent)")
    print(f"{spec.name} v{spec.version} — {report.verdict}")
    print(f"OOS window {report.window_start} → {report.window_end} ({report.n_months} months)")
    for g in report.gates:
        flag = "PASS" if g.passed else "FAIL"
        note = f"  ({g.note})" if g.note else ""
        print(f"  [{flag}] {g.gate:16s} value={g.value:+.4f} vs {g.threshold:+.4f}{note}")
    lo, hi = report.portfolio_beat_ci95
    print(
        f"Portfolio beat rate {report.portfolio_beat_rate:.1%} "
        f"(95% CI {lo:.1%}–{hi:.1%}, {len(report.cohorts)} cohorts)"
    )
    print(
        f"Selection skill vs equal-weight universe (G3): "
        f"{report.selection_alpha_mean:+.2%} (NW-t {report.selection_alpha_t:+.2f})"
    )
    print(f"Survivorship: {report.survivorship}")
    print(f"Report: {report_path(spec)}")
    if report.verdict == "REJECTED":
        print(
            "A rejected spec is a completed experiment — log it and close the card (playbook §4)."
        )
    return 0 if report.verdict == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
