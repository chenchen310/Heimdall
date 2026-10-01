"""The Strategy Factory (roadmap 18.5) — the platform generates its own candidates.

A **search run** is a declared, hash-committed :class:`SearchConfig` (playbook §12.2): a feature
pool with a-priori directions and a few construction menus. The factory enumerates the space in
two stages, evaluates every candidate on **DEV rows only**, appends each to an append-only
**trial ledger**, and ranks them on a leaderboard that carries the run's trial count N, each
candidate's Deflated Sharpe Ratio and the run's PBO (F1/F2, ``backtest.overfit``).

- **Stage 1** — every 1…``max_features`` feature subset (equal weights, sign = the a-priori
  direction) × each universe, on the default construction (the first entry of every menu).
- **Stage 2** — the stage-1 top ``stage2_top_k`` by the DEV objective × the product of the
  construction menus (top_n, weighting, rank buffer, sector neutralization). Duplicates of a
  stage-1 spec are not re-tried.
- **Overlay** variants are *not* selection trials: playbook §12.4 scores selection on the
  un-overlaid book, so an overlay twin has identical F1–F3 numbers. They are reported for
  finalists at promotion (18.7), never counted here.

The fast evaluator reproduces ``research.evaluate`` (G1 IC, G2 spread, G3 selection alpha,
G6 turnover) in numpy on precomputed per-month z-scores; a test pins the two to 1e-10. The
**DEV objective** and F1 series is the monthly **net selection alpha**: the book's ``fwd_1m_rel``
minus G4's per-side cost on its traded fraction minus the EW tier universe's ``fwd_1m_rel``.

    uv run python -m heimdall.research.factory run signals/search/<id>/config.json --log-entry 0NN
    uv run python -m heimdall.research.factory leaderboard <run_id>
    uv run python -m heimdall.research.factory engine <run_id> --top 10
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from heimdall.backtest.overfit import dsr_from_moments, moments, pbo_cscv
from heimdall.data.store import data_root
from heimdall.research import composites, construct, gates, registry
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.certify import _cagr, _sharpe, traded_fractions
from heimdall.research.dataset import load_panel
from heimdall.research.evaluate import WINDOWS, evaluate
from heimdall.research.spec import (
    NEUTRALIZATIONS,
    OVERLAYS,
    UNIVERSES,
    WEIGHTINGS,
    SignalSpec,
    count_free_params,
    term_z,
)

#: Search reads rows on/before this date only; VAL starts the next day (playbook §4).
DEV_END: str = WINDOWS["dev"][1]
VAL_START: str = WINDOWS["val"][0]
_Arr = npt.NDArray[np.float64]


# --- the declared search space ----------------------------------------------------


class SearchConfig(BaseModel):
    """One search run's whole space, fixed before it runs (playbook §12.2)."""

    run_id: str
    market: str = "US"
    feature_pool: dict[str, int]  # feature → a-priori direction (+1 / −1), never searched
    max_features: int = Field(default=2, ge=1, le=3)
    weight_menu: list[str] = ["equal"]
    universes: list[str] = [""]
    top_n_menu: list[int] = [20]
    weighting_menu: list[str] = [""]
    exit_rank_multiples: list[int | None] = [None]  # exit_rank = multiple × top_n
    neutralize_menu: list[str] = [""]
    overlay_menu: list[str] = [""]  # reported for finalists (18.7), not searched
    stage2_top_k: int = Field(default=50, ge=0)
    max_trials: int = Field(default=gates.FACTORY_MAX_TRIALS, ge=1)
    seed: int = 0
    description: str = ""  # prose; excluded from the hash

    @field_validator("run_id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", v):
            raise ValueError(f"run_id must be a lowercase slug, got {v!r}")
        return v

    @field_validator("feature_pool")
    @classmethod
    def _directions(cls, v: dict[str, int]) -> dict[str, int]:
        if len(v) < 1:
            raise ValueError("the feature pool is empty")
        for feat, sign in v.items():
            if feat.startswith("fwd_"):
                raise ValueError(f"label leakage: {feat!r} is a forward label")
            if sign not in (1, -1):
                raise ValueError(f"{feat!r}: a direction is +1 or −1, got {sign!r}")
            if composites.is_composite(feat):  # 18.22: directions live inside the composite
                try:
                    composites.get(feat)
                except KeyError as exc:
                    raise ValueError(str(exc)) from None
                if sign != 1:
                    raise ValueError(f"{feat!r}: a composite's pool direction is +1")
        return v

    @model_validator(mode="after")
    def _menus(self) -> SearchConfig:
        if self.weight_menu != ["equal"]:
            raise ValueError("weight_menu supports only ['equal'] (NORTH_STAR: no optimizers)")
        if not set(self.universes) <= set(UNIVERSES) or not self.universes:
            raise ValueError(f"universes ⊆ {UNIVERSES}")
        if not set(self.top_n_menu) <= {10, 20} or not self.top_n_menu:
            raise ValueError("top_n_menu ⊆ {10, 20} (NORTH_STAR usage: hold 10–20)")
        if not set(self.weighting_menu) <= set(WEIGHTINGS) or not self.weighting_menu:
            raise ValueError(f"weighting_menu ⊆ {WEIGHTINGS}")
        if not set(self.neutralize_menu) <= set(NEUTRALIZATIONS) or not self.neutralize_menu:
            raise ValueError(f"neutralize_menu ⊆ {NEUTRALIZATIONS}")
        if not set(self.overlay_menu) <= set(OVERLAYS) or not self.overlay_menu:
            raise ValueError(f"overlay_menu ⊆ {OVERLAYS}")
        if not self.exit_rank_multiples or any(
            m is not None and m < 2 for m in self.exit_rank_multiples
        ):
            raise ValueError("exit_rank_multiples: None or an integer ≥ 2")
        if self.max_trials > gates.FACTORY_MAX_TRIALS:
            raise ValueError(f"max_trials ≤ F6 ({gates.FACTORY_MAX_TRIALS})")
        if self.max_features > gates.FACTORY_MAX_PARAMS:
            raise ValueError(f"max_features ≤ F5 ({gates.FACTORY_MAX_PARAMS})")
        return self

    def canonical_hash(self) -> str:
        payload = self.model_dump(exclude={"description"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def family(self) -> str:
        return f"{self.market.lower()}-factory-{self.run_id}"

    def _spec(self, trial_id: int, feats: tuple[str, ...], **construction: object) -> SignalSpec:
        return SignalSpec.model_validate(
            {
                "name": f"{self.run_id}-t{trial_id:05d}",
                "family": self.family,
                "market": self.market,
                "features": {f: float(self.feature_pool[f]) for f in feats},
                **construction,
            }
        )

    def stage1(self) -> list[SignalSpec]:
        """Every feature subset × universe on the default construction (menu heads)."""
        out: list[SignalSpec] = []
        pool = list(self.feature_pool)
        for k in range(1, self.max_features + 1):
            for feats in itertools.combinations(pool, k):
                for uni in self.universes:
                    out.append(self._spec(len(out), feats, **self._construction(uni)))
        return out

    def _construction(
        self,
        universe: str,
        top_n: int | None = None,
        weighting: str | None = None,
        multiple: int | None | str = "head",
        neutralize: str | None = None,
    ) -> dict[str, object]:
        n = self.top_n_menu[0] if top_n is None else top_n
        mult = self.exit_rank_multiples[0] if multiple == "head" else multiple
        return {
            "universe": universe,
            "top_n": n,
            "weighting": self.weighting_menu[0] if weighting is None else weighting,
            "exit_rank": None if mult is None else int(mult) * n,
            "neutralize": self.neutralize_menu[0] if neutralize is None else neutralize,
        }

    def stage2(self, winners: list[SignalSpec], first_id: int) -> list[SignalSpec]:
        """The construction menus over the stage-1 winners (recipe = features + universe)."""
        out: list[SignalSpec] = []
        for base in winners:
            feats = tuple(base.features)
            for n, wt, mult, nz in itertools.product(
                self.top_n_menu,
                self.weighting_menu,
                self.exit_rank_multiples,
                self.neutralize_menu,
            ):
                c = self._construction(base.universe, n, wt, mult, nz)
                if c == self._construction(base.universe):
                    continue  # the stage-1 trial itself
                out.append(self._spec(first_id + len(out), feats, **c))
        return out

    def trial_budget(self) -> int:
        """Upper bound on N for this config (stage 1 + every stage-2 combination)."""
        s1 = sum(math.comb(len(self.feature_pool), k) for k in range(1, self.max_features + 1))
        s1 *= len(self.universes)
        combos = (
            len(self.top_n_menu)
            * len(self.weighting_menu)
            * len(self.exit_rank_multiples)
            * len(self.neutralize_menu)
        )
        return s1 + min(self.stage2_top_k, s1) * max(combos - 1, 0)


def load_config(path: Path) -> SearchConfig:
    return SearchConfig.model_validate(json.loads(Path(path).read_text()))


def check_declared(config: SearchConfig, entry_id: str, log_path: Path) -> None:
    """Refuse unless RESEARCH_LOG entry ``entry_id`` contains the config's sha256 (§12.2)."""
    text = log_path.read_text()
    marker = f"## {entry_id} —"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(f"no RESEARCH_LOG entry {marker!r} — declare the search first (§12.2)")
    nxt = text.find("\n## ", idx + len(marker))
    if config.canonical_hash() not in text[idx : nxt if nxt != -1 else len(text)]:
        raise ValueError(
            f"RESEARCH_LOG entry {entry_id} does not contain this config's sha256 "
            f"({config.canonical_hash()[:12]}…) — a changed config is a new run (§12.2)"
        )


# --- the DEV arrays ----------------------------------------------------------------


@dataclass
class DevPanel:
    """DEV rows (eligible only), sorted by month, with z-scores precomputed per pool feature."""

    months: list[pd.Timestamp]
    bounds: list[tuple[int, int]]  # row slice of each month
    symbols: npt.NDArray[np.object_]
    fwd1_rel: _Arr
    fwd6_rel: _Arr
    fwd1: _Arr
    vol: _Arr
    sector: npt.NDArray[np.object_]
    tier: dict[str, npt.NDArray[np.bool_]]  # universe → row mask
    z: dict[tuple[str, str, str], _Arr]  # (universe, neutralize, feature) → z-scores
    frames: list[pd.DataFrame] = field(default_factory=list)  # per-month rows (weights/caps)


def prepare(panel: pd.DataFrame, config: SearchConfig) -> DevPanel:
    """Slice DEV, drop ineligible rows (they never rank nor enter a universe), precompute z."""
    dates = pd.to_datetime(panel["date"])
    in_dev = dates <= pd.Timestamp(DEV_END)
    dev = panel.loc[in_dev].copy()
    dev["date"] = dates[in_dev]
    if bool((dev["date"] >= pd.Timestamp(VAL_START)).any()):  # pragma: no cover - by construction
        raise AssertionError("the search must never read a row ≥ VAL start")
    if "eligible" in dev.columns:
        dev = dev[dev["eligible"].astype(bool)]
    missing = sorted(set(composites.columns(list(config.feature_pool))) - set(dev.columns))
    if missing:
        raise KeyError(f"pool features absent from the panel: {missing}")
    # Stable by date only: within a month the panel's own row order is kept, because
    # evaluate()'s tie-breaks (sort_values, rank(method="first")) depend on it.
    dev = dev.sort_values("date", kind="mergesort").reset_index(drop=True)
    months = sorted(pd.Timestamp(t) for t in dev["date"].unique())
    starts = dev["date"].searchsorted(months, side="left")
    ends = dev["date"].searchsorted(months, side="right")
    bounds = [(int(a), int(b)) for a, b in zip(starts, ends, strict=True)]

    tier: dict[str, npt.NDArray[np.bool_]] = {}
    frames: list[pd.DataFrame] = []
    for uni in config.universes:
        spec = SignalSpec(
            name="tier", family="x", market=config.market, features={"_": 1.0}, universe=uni
        )
        mask = np.zeros(len(dev), dtype=bool)
        for a, b in bounds:
            mask[a:b] = construct.universe_mask(spec, dev.iloc[a:b]).to_numpy()
        tier[uni] = mask
    for a, b in bounds:
        cols = [c for c in ("symbol", "vol_63d", "sector", "market_cap") if c in dev.columns]
        frames.append(dev.iloc[a:b][cols].reset_index(drop=True))

    z: dict[tuple[str, str, str], _Arr] = {}
    has_sector = "sector" in dev.columns
    for uni, nz, feat in itertools.product(
        config.universes, config.neutralize_menu, config.feature_pool
    ):
        if nz != "" and not has_sector:
            raise KeyError("sector")
        out = np.full(len(dev), np.nan)
        for a, b in bounds:
            rows = np.flatnonzero(tier[uni][a:b]) + a
            if not len(rows):
                continue
            pool = dev.iloc[rows]
            out[rows] = term_z(feat, pool, nz).to_numpy(dtype=float)
        z[(uni, nz, feat)] = out

    def col(name: str) -> _Arr:
        return dev[name].to_numpy(dtype=float) if name in dev.columns else np.full(len(dev), np.nan)

    return DevPanel(
        months=months,
        bounds=bounds,
        symbols=dev["symbol"].astype(str).to_numpy(dtype=object),
        fwd1_rel=col("fwd_1m_rel"),
        fwd6_rel=col("fwd_6m_rel"),
        fwd1=col("fwd_1m"),
        vol=col("vol_63d"),
        sector=dev["sector"].to_numpy(dtype=object) if has_sector else np.full(len(dev), None),
        tier=tier,
        z=z,
        frames=frames,
    )


# --- the fast evaluator --------------------------------------------------------------


def _avg_rank(x: _Arr) -> _Arr:
    """Average ranks (ties share the mean rank) — scipy/pandas Spearman semantics."""
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    ends = np.cumsum(cnt)
    return ((ends - cnt + 1 + ends) / 2.0)[inv]


def _spearman(a: _Arr, b: _Arr) -> float:
    ra, rb = _avg_rank(a), _avg_rank(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = math.sqrt(float(ra @ ra) * float(rb @ rb))
    return float(ra @ rb) / den if den > 0 else float("nan")


def _rank_desc(values: _Arr) -> npt.NDArray[np.intp]:
    """Positions of ``values`` best-first, exactly as pandas ``sort_values(ascending=False)``
    orders them (reverse, quicksort, reverse) — so ties break as ``certify``'s ranking does."""
    idx = np.arange(len(values))[::-1]
    return np.asarray(idx[values[::-1].argsort(kind="quicksort")][::-1], dtype=np.intp)


def _spread(score: _Arr, fwd: _Arr, q: int = 5) -> float | None:
    """Top-minus-bottom quintile mean of ``fwd`` — ``certify._monthly_spread`` for one month."""
    n = len(score)
    if n < q:
        return None
    ranks = np.empty(n)
    ranks[np.argsort(score, kind="mergesort")] = np.arange(1, n + 1)  # rank(method="first")
    edges = np.quantile(ranks, np.linspace(0, 1, q + 1))
    bucket = np.clip(np.searchsorted(edges, ranks, side="left") - 1, 0, q - 1)
    return float(fwd[bucket == q - 1].mean() - fwd[bucket == 0].mean())


@dataclass
class TrialMetrics:
    ic_mean: float
    ic_t: float
    ic_months: int
    spread_mean: float
    spread_share: float
    alpha_mean: float
    alpha_t: float
    n_cohorts: int
    turnover: float
    g4_cagr: float
    g4_sharpe: float
    bench_cagr: float
    bench_sharpe: float
    net_alpha: list[float]  # per DEV month (NaN where a leg is missing) — the F1 series
    ic_by_month: list[float] = field(default_factory=list)  # G1 input per month (NaN = skipped)
    alpha6_by_month: list[float] = field(default_factory=list)  # G3 cohort per month (NaN = none)

    @property
    def sr(self) -> float:
        return moments(self.net_alpha)[0]

    @property
    def objective(self) -> float:
        """Annualized IR of the net selection alpha vs the EW tier universe (DEV)."""
        sr = self.sr
        return sr * math.sqrt(12.0) if math.isfinite(sr) else float("nan")


def _weights(spec: SignalSpec, dp: DevPanel, m: int, names: list[str]) -> pd.Series:
    return construct.weights_for(spec, dp.frames[m], names)


def evaluate_fast(spec: SignalSpec, dp: DevPanel) -> TrialMetrics:
    """``research.evaluate`` on the DEV window, in numpy (plus the F1 series and G4 view)."""
    uni, nz = spec.universe, spec.neutralize
    if spec.filters:
        raise ValueError("the factory does not search filters (no filter menu in v1)")
    composite: _Arr = np.zeros(len(dp.symbols))
    for feat, w in spec.features.items():
        composite = np.asarray(composite + w * dp.z[(uni, nz, feat)], dtype=float)
    equal = construct.is_equal_weight(spec)
    rate = gates.G4_COST_BPS / 1e4

    ics: list[float] = []
    spreads: list[float] = []
    alphas: list[float] = []
    net_alpha: list[float] = []
    ic_by_month = [float("nan")] * len(dp.bounds)
    alpha6_by_month = [float("nan")] * len(dp.bounds)
    sets: list[set[str]] = []
    books: list[pd.Series] = []
    gross: list[float] = []
    bench: list[float] = []
    traded_g4: list[float] = []
    prev: set[str] | None = None
    prev_book = pd.Series(dtype=float)
    for m, (a, b) in enumerate(dp.bounds):
        sc = composite[a:b]
        fin = np.isfinite(sc)
        f1r, f6r = dp.fwd1_rel[a:b], dp.fwd6_rel[a:b]
        both = fin & np.isfinite(f1r)
        if both.any() and len(np.unique(sc[both])) >= 3:
            ic = _spearman(sc[both], f1r[both])
            if math.isfinite(ic):
                ics.append(ic)
                ic_by_month[m] = ic
        sp = _spread(sc[both], f1r[both])
        if sp is not None:
            spreads.append(sp)

        order = np.flatnonzero(fin)[_rank_desc(sc[fin])]
        syms = dp.symbols[a:b]
        if spec.exit_rank is None or not prev:
            member_pos = order[: spec.top_n]
            names = [str(s) for s in syms[member_pos]]
        else:
            names = construct.buffered_members(
                [str(s) for s in syms[order]], prev, spec.top_n, spec.exit_rank
            )
            pos_of = {str(s): i for i, s in enumerate(syms)}
            member_pos = np.array([pos_of[s] for s in names], dtype=np.intp)
        prev = set(names)
        sets.append(prev)
        book = (
            pd.Series(1.0 / len(names), index=names)
            if equal and names
            else _weights(spec, dp, m, names)
        )
        books.append(book)

        univ = dp.tier[uni][a:b]
        u6 = f6r[univ]
        u6 = u6[np.isfinite(u6)]
        b6 = f6r[member_pos]
        if equal:
            b6 = b6[np.isfinite(b6)]
            book6 = float(b6.mean()) if len(b6) else float("nan")
        else:
            w_book: _Arr = np.asarray(book.to_numpy(), dtype=np.float64)
            book6 = _weighted(w_book, np.asarray(b6, dtype=np.float64))
        if math.isfinite(book6) and len(u6):
            alphas.append(book6 - float(u6.mean()))
            alpha6_by_month[m] = alphas[-1]

        # F1 series: 1m book − cost on the traded fraction − EW tier universe (all rel).
        if equal:
            traded = 1.0 if m == 0 else 2.0 * _set_turnover(sets[-2], sets[-1])
        else:
            both_idx = prev_book.index.union(book.index)
            traded = float(
                (
                    book.reindex(both_idx, fill_value=0.0)
                    - prev_book.reindex(both_idx, fill_value=0.0)
                )
                .abs()
                .sum()
            )
        prev_book = book
        b1 = f1r[member_pos]
        book1 = _mean_or_weighted(equal, book, b1)
        u1 = f1r[univ]
        u1 = u1[np.isfinite(u1)]
        net_alpha.append(
            book1 - traded * rate - float(u1.mean())
            if math.isfinite(book1) and len(u1)
            else float("nan")
        )
        g = _mean_or_weighted(equal, book, dp.fwd1[a:b][member_pos])
        bm = dp.fwd1[a:b] - f1r
        bm = bm[np.isfinite(bm)]
        if math.isfinite(g) and len(bm):
            gross.append(g)
            bench.append(float(bm[0]))
            traded_g4.append(traded)

    ic_arr = np.asarray(ics)
    ic_sd = float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else 0.0
    turn = (
        [_set_turnover(p, c) for p, c in zip(sets, sets[1:], strict=False)]
        if equal
        else [
            0.5
            * float(
                (
                    c.reindex(p.index.union(c.index), fill_value=0.0)
                    - p.reindex(p.index.union(c.index), fill_value=0.0)
                )
                .abs()
                .sum()
            )
            for p, c in zip(books, books[1:], strict=False)
        ]
    )
    net_g4 = [g - t * rate for g, t in zip(gross, traded_g4, strict=True)]
    return TrialMetrics(
        ic_mean=float(ic_arr.mean()) if len(ic_arr) else float("nan"),
        ic_t=float(ic_arr.mean() / (ic_sd / math.sqrt(len(ic_arr)))) if ic_sd > 0 else float("nan"),
        ic_months=len(ic_arr),
        spread_mean=float(np.mean(spreads)) if spreads else float("nan"),
        spread_share=float(np.mean([s > 0 for s in spreads])) if spreads else float("nan"),
        alpha_mean=float(np.mean(alphas)) if alphas else float("nan"),
        alpha_t=gates.nw_tstat(alphas, null=0.0, lag=gates.NW_LAG) if alphas else float("nan"),
        n_cohorts=len(alphas),
        turnover=float(np.mean(turn)) if turn else float("nan"),
        g4_cagr=_cagr(net_g4),
        g4_sharpe=_sharpe(net_g4),
        bench_cagr=_cagr(bench),
        bench_sharpe=_sharpe(bench),
        net_alpha=net_alpha,
        ic_by_month=ic_by_month,
        alpha6_by_month=alpha6_by_month,
    )


def _set_turnover(prev: set[str], cur: set[str]) -> float:
    return 1.0 - len(cur & prev) / max(len(cur), 1)


def _weighted(w: _Arr, r: _Arr) -> float:
    ok = np.isfinite(r)
    if not ok.any():
        return float("nan")
    ret = float((w[ok] * r[ok]).sum() / w[ok].sum())
    invested = float(w.sum())
    return ret * invested if invested < 1.0 - 1e-9 else ret


def _mean_or_weighted(equal: bool, book: pd.Series, r: _Arr) -> float:
    if equal:
        r = r[np.isfinite(r)]
        return float(r.mean()) if len(r) else float("nan")
    return _weighted(np.asarray(book.to_numpy(), dtype=np.float64), r)


# --- the trial ledger ------------------------------------------------------------------


def _signals_root(root: Path | None) -> Path:
    return root if root is not None else registry.registry_path().parent.parent


def run_dir(run_id: str, root: Path | None = None) -> Path:
    return _signals_root(root) / "signals" / "search" / run_id


def ledger_path(run_id: str, root: Path | None = None) -> Path:
    return run_dir(run_id, root) / "trials.parquet"


#: Per-month series kept for every trial (months × trial_id), so any window can be re-scored
#: without re-evaluating: the F1 net alpha, the G1 monthly IC, the G3 6m cohort alpha.
SERIES_KINDS: dict[str, str] = {
    "net": "series.parquet",
    "ic": "series_ic.parquet",
    "alpha6": "series_alpha6.parquet",
}


def series_path(run_id: str, root: Path | None = None, kind: str = "net") -> Path:
    return run_dir(run_id, root) / SERIES_KINDS[kind]


def load_trials(run_id: str, root: Path | None = None) -> pd.DataFrame:
    path = ledger_path(run_id, root)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def load_series(run_id: str, root: Path | None = None, kind: str = "net") -> pd.DataFrame:
    path = series_path(run_id, root, kind)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(tmp)
    os.replace(tmp, path)


def _append(
    run_id: str,
    rows: list[dict[str, object]],
    series: dict[str, dict[str, list[float]]],
    months: list[pd.Timestamp],
    root: Path | None,
) -> None:
    """Append-only: existing rows are re-written unchanged, new rows go after them."""
    old = load_trials(run_id, root)
    new = pd.DataFrame(rows)
    trials = pd.concat([old, new], ignore_index=True) if len(old) else new
    _atomic_parquet(trials, ledger_path(run_id, root))
    for kind in SERIES_KINDS:
        old_s = load_series(run_id, root, kind)
        s_new = pd.DataFrame(series[kind], index=pd.DatetimeIndex(months, name="month"))
        ser = pd.concat([old_s, s_new], axis=1) if len(old_s) else s_new
        _atomic_parquet(ser, series_path(run_id, root, kind))


def _row(trial_id: int, stage: int, spec: SignalSpec, met: TrialMetrics) -> dict[str, object]:
    n_params, structural = count_free_params(spec)
    d = asdict(met)
    for key in ("net_alpha", "ic_by_month", "alpha6_by_month"):
        d.pop(key)
    return {
        "trial_id": trial_id,
        "stage": stage,
        "spec_hash": spec.canonical_hash(),
        "spec_json": spec.model_dump_json(),
        "features": ",".join(f"{'+' if w > 0 else '-'}{f}" for f, w in spec.features.items()),
        "universe": spec.universe or "all",
        "top_n": spec.top_n,
        "weighting": spec.weighting or "equal",
        "exit_rank": spec.exit_rank if spec.exit_rank is not None else 0,
        "neutralize": spec.neutralize or "none",
        "n_params": n_params,
        "structural": json.dumps(structural, sort_keys=True),
        **d,
        "sr": met.sr,
        "objective": met.objective,
        "evaluated_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }


def run_search(
    config: SearchConfig,
    panel: pd.DataFrame,
    *,
    log_entry: str,
    log_path: Path,
    root: Path | None = None,
    batch: int = 50,
    progress: bool = False,
) -> pd.DataFrame:
    """Declared-run check → DEV-only evaluation of both stages → the trial ledger.

    Resumable: trials already in the ledger (by spec hash) are skipped, so a killed run
    continues without re-evaluating anything. Returns the full ledger.
    """
    check_declared(config, log_entry, log_path)
    budget = config.trial_budget()
    if budget > config.max_trials:
        raise ValueError(f"this config can reach {budget} trials > max_trials {config.max_trials}")
    cfg_path = run_dir(config.run_id, root) / "config.json"
    if cfg_path.exists():
        if load_config(cfg_path).canonical_hash() != config.canonical_hash():
            raise ValueError(f"{cfg_path} holds a different config — a changed config is a new run")
    else:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(config.model_dump_json(indent=2) + "\n")

    dp = prepare(panel, config)

    def _evaluate(specs: list[SignalSpec], stage: int) -> None:
        done = set(load_trials(config.run_id, root).get("spec_hash", pd.Series(dtype=str)))
        todo = [s for s in specs if s.canonical_hash() not in done]
        t0 = time.time()
        for lo in range(0, len(todo), batch):
            rows: list[dict[str, object]] = []
            series: dict[str, dict[str, list[float]]] = {k: {} for k in SERIES_KINDS}
            for spec in todo[lo : lo + batch]:
                tid = int(spec.name.rsplit("-t", 1)[1])
                met = evaluate_fast(spec, dp)
                rows.append(_row(tid, stage, spec, met))
                series["net"][str(tid)] = met.net_alpha
                series["ic"][str(tid)] = met.ic_by_month
                series["alpha6"][str(tid)] = met.alpha6_by_month
            _append(config.run_id, rows, series, dp.months, root)
            if progress:
                n = lo + len(rows)
                print(f"stage {stage}: {n}/{len(todo)} ({n / max(time.time() - t0, 1e-9):.1f}/s)")

    s1 = config.stage1()
    _evaluate(s1, 1)
    trials = load_trials(config.run_id, root)
    s1_rows = trials[trials["stage"] == 1].sort_values(
        "objective", ascending=False, na_position="last"
    )
    by_id = {int(s.name.rsplit("-t", 1)[1]): s for s in s1}
    winners = [by_id[int(t)] for t in s1_rows["trial_id"].head(config.stage2_top_k)]
    _evaluate(config.stage2(winners, first_id=len(s1)), 2)
    return load_trials(config.run_id, root)


# --- the leaderboard -------------------------------------------------------------------


@dataclass
class Leaderboard:
    table: pd.DataFrame  # one row per trial, best objective first, with DSR + gate flags
    n_trials: int
    sr_variance: float
    pbo: float
    run_passes_f2: bool


def leaderboard(run_id: str, root: Path | None = None) -> Leaderboard:
    """Every trial with its DSR (deflated by the run's N) and the run's PBO (F1/F2/F3/F5)."""
    trials = load_trials(run_id, root)
    series = load_series(run_id, root)
    if trials.empty:
        raise FileNotFoundError(f"no trials for run {run_id!r}")
    n = len(trials)
    srs = trials["sr"].to_numpy(dtype=float)
    finite = srs[np.isfinite(srs)]
    var = float(np.var(finite, ddof=1)) if len(finite) > 1 else 0.0
    dsrs: list[float] = []
    for tid in trials["trial_id"]:
        sr, k, skew, kurt = moments(series[str(int(tid))].to_numpy())
        dsrs.append(dsr_from_moments(sr, k, skew, kurt, n, var))
    mat = series[[str(int(t)) for t in trials["trial_id"]]].to_numpy(dtype=float)
    blocks = gates.FACTORY_PBO_BLOCKS
    pbo = pbo_cscv(mat, s=blocks).pbo if n >= 2 and mat.shape[0] >= blocks else float("nan")
    run_ok = bool(pbo <= gates.FACTORY_MAX_PBO)
    table = trials.assign(
        dsr=dsrs,
        f1_dsr=[bool(d >= gates.FACTORY_MIN_DSR) for d in dsrs],
        f3_skill=(trials["alpha_t"] >= gates.FACTORY_MIN_ALPHA_T)
        & (trials["ic_t"] >= gates.FACTORY_MIN_IC_T),
        f5_params=trials["n_params"] <= gates.FACTORY_MAX_PARAMS,
    )
    table["candidate"] = table["f1_dsr"] & table["f3_skill"] & table["f5_params"] & run_ok
    table = table.sort_values("objective", ascending=False, na_position="last").reset_index(
        drop=True
    )
    return Leaderboard(table=table, n_trials=n, sr_variance=var, pbo=pbo, run_passes_f2=run_ok)


# --- engine evidence for the Lab ---------------------------------------------------------


def engine_dir(run_id: str, data: Path | None = None) -> Path:
    """Derived daily backtests (large, regenerable) live under the gitignored data root."""
    return (data if data is not None else data_root()) / "research" / "factory" / run_id


def cache_engine_backtests(
    run_id: str,
    panel: pd.DataFrame,
    matrices: dict[str, pd.DataFrame],
    *,
    top_k: int = 10,
    root: Path | None = None,
    data: Path | None = None,
) -> list[Path]:
    """Run the 18.3 daily engine for the leaderboard's top ``top_k`` over **DEV only** and
    store each one's daily returns (strategy / benchmark / universe) for the Strategy Lab."""
    from heimdall.research.spec_backtest import backtest_spec  # heavy: backtest engine

    board = leaderboard(run_id, root)
    dates = pd.to_datetime(panel["date"])
    dev = panel.loc[dates <= pd.Timestamp(DEV_END)]
    out: list[Path] = []
    for _, row in board.table.head(top_k).iterrows():
        spec = SignalSpec.model_validate_json(str(row["spec_json"]))
        result, _ = backtest_spec(spec, dev, matrices, end=pd.Timestamp(DEV_END))
        stem = engine_dir(run_id, data) / f"engine_t{int(row['trial_id']):05d}"
        path = stem.with_suffix(".parquet")
        _atomic_parquet(result.returns, path)
        # The Lab's detail view also needs the historical books (DEV only — never today's).
        _atomic_parquet(result.holdings, stem.parent / f"{stem.name}_holdings.parquet")
        _atomic_parquet(result.trades, stem.parent / f"{stem.name}_trades.parquet")
        if result.sector_weights is not None:
            sw = result.sector_weights.copy()
            sw.columns = [str(c) for c in sw.columns]
            _atomic_parquet(sw, stem.parent / f"{stem.name}_sectors.parquet")
        out.append(path)
    return out


# --- promotion: the single VAL look → incubating → pre-registration draft (18.7) ------------


def val_looks_path(run_id: str, root: Path | None = None) -> Path:
    """The run's VAL-look record. Its existence closes the run's VAL budget (one look per
    finalist, once) and unlocks 18.6's post-selection VAL extension."""
    return run_dir(run_id, root) / "val_looks.json"


def g4_view(
    spec: SignalSpec, panel: pd.DataFrame, benchmark_adj: pd.Series | None
) -> dict[str, float]:
    """DEV G4-style numbers (label-based, certify's cost model) for a spec **with its overlay
    applied** — so an overlay twin can be shown beside its base without a new selection trial.
    Months where the overlay is in cash earn 0 and pay for both switches."""
    dates = pd.to_datetime(panel["date"])
    dev = panel.loc[dates <= pd.Timestamp(DEV_END)].assign(
        date=dates[dates <= pd.Timestamp(DEV_END)]
    )
    sched = construct.book_schedule(spec, dev, benchmark_adj)
    equal = construct.is_equal_weight(spec)
    gross: list[float] = []
    bench: list[float] = []
    held: list[pd.Series] = []
    for t, book in sorted(sched.targets.items()):
        cross = dev[dev["date"] == t].set_index("symbol")
        rows = cross.loc[[s for s in book.index if s in cross.index]]
        r = rows["fwd_1m"].to_numpy(dtype=float)
        ok = np.isfinite(r)
        if not ok.any():
            continue
        if equal:
            g = float(r[ok].mean())
        else:
            g = _weighted(np.asarray(book.reindex(rows.index).to_numpy(), dtype=np.float64), r)
        bm = (cross["fwd_1m"] - cross["fwd_1m_rel"]).dropna()
        if not len(bm):
            continue
        cash = bool(sched.overlay_cash.get(t, False))
        gross.append(0.0 if cash else g)
        held.append(pd.Series(dtype=float) if cash else book)
        bench.append(float(bm.iloc[0]))
    net = [
        g - t * gates.G4_COST_BPS / 1e4 for g, t in zip(gross, traded_fractions(held), strict=True)
    ]
    return {
        "cagr": _cagr(net),
        "sharpe": _sharpe(net),
        "bench_cagr": _cagr(bench),
        "bench_sharpe": _sharpe(bench),
        "cash_months": float(sum(1 for h in held if h.empty)),
    }


@dataclass
class PromotionReport:
    run_id: str
    n_trials: int
    pbo: float
    run_passes_f2: bool
    looks: list[dict[str, object]]  # one per finalist: VAL report, F4 verdict, promotion, overlays
    promoted: list[str]  # spec names now `incubating`
    skipped: list[dict[str, object]]  # finalists refused before any look (duplicate hash, …)


def promote(
    run_id: str,
    panel: pd.DataFrame,
    *,
    finalists: list[int] | None = None,
    benchmark_adj: pd.Series | None = None,
    root: Path | None = None,
) -> PromotionReport:
    """Spend the run's VAL looks (≤ ``FACTORY_MAX_VAL_FINALISTS``, once) and move F4 passers to
    ``incubating``. Refuses a second call for the same run. An F2-failing run takes no look and
    promotes nothing, but still closes its VAL budget (the record is written either way)."""
    if val_looks_path(run_id, root).exists():
        raise FileExistsError(f"run {run_id!r} has already spent its VAL looks (§12.2)")
    cfg = load_config(run_dir(run_id, root) / "config.json")
    board = leaderboard(run_id, root)
    table = board.table
    looks: list[dict[str, object]] = []
    promoted: list[str] = []
    skipped: list[dict[str, object]] = []
    if board.run_passes_f2:
        if finalists is None:
            chosen = table[table["candidate"]].head(gates.FACTORY_MAX_VAL_FINALISTS)
        else:
            if len(finalists) > gates.FACTORY_MAX_VAL_FINALISTS:
                raise ValueError(
                    f"at most {gates.FACTORY_MAX_VAL_FINALISTS} finalists per run (F4)"
                )
            chosen = table[table["trial_id"].isin(finalists)]
            bad = chosen.loc[~chosen["candidate"], "trial_id"].tolist()
            if bad or len(chosen) != len(set(finalists)):
                raise ValueError(f"finalists must be leaderboard candidates (F1/F3/F5): {bad}")
        known = _registry_recipes(root)
        needs_bench = any(o for o in cfg.overlay_menu)
        if needs_bench and benchmark_adj is None:
            raise ValueError("the config's overlay menu needs benchmark_adj for the overlay views")
        for _, row in chosen.iterrows():
            spec = SignalSpec.model_validate_json(str(row["spec_json"]))
            if spec.recipe_hash() in known:
                skipped.append(
                    {"trial_id": int(row["trial_id"]), "reason": "recipe already in registry"}
                )
                continue
            rep = evaluate(spec, panel, WINDOWS["val"])  # the single VAL look
            f4 = bool(
                rep.selection_alpha_mean > 0
                and rep.ic_mean > 0
                and rep.mean_turnover <= gates.FACTORY_VAL_MAX_TURNOVER
            )
            overlays = {
                o: g4_view(spec.model_copy(update={"overlay": o}), panel, benchmark_adj)
                for o in cfg.overlay_menu
                if o
            }
            if overlays:
                overlays[""] = g4_view(spec, panel, benchmark_adj)
            look: dict[str, object] = {
                "trial_id": int(row["trial_id"]),
                "spec_name": spec.name,
                "spec_hash": spec.canonical_hash(),
                "dsr": float(row["dsr"]),
                "dev_objective": float(row["objective"]),
                "val": rep.to_dict(),
                "f4_pass": f4,
                "overlay_views_dev": overlays,
                "promoted": False,
            }
            if f4:
                _write_incubating(spec, run_id, board, row, root)
                look["promoted"] = True
                promoted.append(spec.name)
            looks.append(look)
    record = {
        "run_id": run_id,
        "n_trials": board.n_trials,
        "pbo": board.pbo,
        "run_passes_f2": board.run_passes_f2,
        "looks": looks,
        "skipped": skipped,
        "written_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    path = val_looks_path(run_id, root)
    path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    return PromotionReport(
        run_id, board.n_trials, board.pbo, board.run_passes_f2, looks, promoted, skipped
    )


def _registry_recipes(root: Path | None) -> set[str]:
    """Recipe hashes of every spec the registry knows (§12.3 no-respin check)."""
    out: set[str] = set()
    for e in cast_entries(registry.load_registry(root)["signals"]):
        p = Path(str(e["spec_path"]))
        path = p if p.is_absolute() else _signals_root(root) / p
        try:
            out.add(SignalSpec.model_validate_json(path.read_text()).recipe_hash())
        except (OSError, ValueError):
            continue
    return out


def cast_entries(value: object) -> list[dict[str, object]]:
    return list(value) if isinstance(value, list) else []


def cast_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _write_incubating(
    spec: SignalSpec, run_id: str, board: Leaderboard, row: pd.Series, root: Path | None
) -> None:
    described = spec.model_copy(
        update={
            "description": (
                f"Strategy Factory run {run_id}, trial {int(row['trial_id'])}: N = "
                f"{board.n_trials} trials, run PBO {board.pbo:.3f}, DSR {float(row['dsr']):.3f}. "
                "Incubating — uncertified (playbook §12.3)."
            )
        }
    )
    rel = Path("signals") / "specs" / "factory" / f"{spec.name}.json"
    out = _signals_root(root) / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(described.model_dump_json(indent=2) + "\n")
    registry.add(described, str(rel), root=root)
    registry.transition(spec.name, spec.version, "incubating", root=root)


def vault_touches(market: str, root: Path | None = None) -> int:
    """How many specs of ``market`` have ever been evaluated on the vault (certified or
    rejected) — the §12.3 disclosure every factory pre-registration carries."""
    return sum(
        1
        for e in cast_entries(registry.load_registry(root)["signals"])
        if e.get("cert_report")
        and str(e.get("status")) in {"certified", "rejected", "under_review", "retired"}
        and _entry_market(e, root) == market
    )


def _entry_market(entry: dict[str, object], root: Path | None) -> str:
    p = Path(str(entry["spec_path"]))
    path = p if p.is_absolute() else _signals_root(root) / p
    try:
        return str(json.loads(path.read_text())["market"])
    except (OSError, KeyError, ValueError):
        return ""


def draft_preregistration(run_id: str, spec_name: str, root: Path | None = None) -> str:
    """The RESEARCH_LOG entry text (playbook §8 + §12.3 disclosures) for one incubating finalist.

    Prints; never commits, never certifies — the user's go/no-go and commit come first (§4).
    Refuses if the run already has a pre-registered spec (≤ 1 per run).
    """
    reg = registry.load_registry(root)
    entries = cast_entries(reg["signals"])
    cfg = load_config(run_dir(run_id, root) / "config.json")
    fam = [e for e in entries if e.get("family") == cfg.family]
    already = [e for e in fam if e.get("status") in {"registered", "certified", "rejected"}]
    if len(already) >= gates.FACTORY_MAX_PREREG_PER_RUN:
        raise ValueError(
            f"run {run_id!r} already pre-registered {already[0]['name']} (≤ 1 per run)"
        )
    entry = next((e for e in fam if e.get("name") == spec_name), None)
    if entry is None or entry.get("status") != "incubating":
        raise ValueError(f"{spec_name} is not an incubating finalist of run {run_id!r}")
    record = json.loads(val_looks_path(run_id, root).read_text())
    look = next(x for x in record["looks"] if x["spec_name"] == spec_name)
    trials = load_trials(run_id, root).set_index("trial_id")
    t = trials.loc[int(look["trial_id"])]
    val = look["val"]
    wf = engine_dir(run_id) / "walkforward_top1.json"
    wf_line = "see " + str(wf) if wf.exists() else "<run `walkforward` first and summarize here>"
    return "\n".join(
        [
            f"## <id> — {cfg.family} / {spec_name} v1   "
            f"({pd.Timestamp.now():%Y-%m-%d}, model: <who>)",
            "- Hypothesis: <one falsifiable sentence>",
            f"- Spec: {entry['spec_path']}   sha256: {entry['spec_hash']}",
            f"- Factory run: {run_id} (config sha256 {cfg.canonical_hash()}), "
            f"N = {record['n_trials']} trials, run PBO {record['pbo']:.3f}, this trial's DSR "
            f"{look['dsr']:.3f}",
            f"- Construction: {t['structural']}",
            f"- Dev result (2010–2019): IC {t['ic_mean']:+.4f} (t {t['ic_t']:+.2f}), selection "
            f"alpha {t['alpha_mean']:+.2%} (NW-t {t['alpha_t']:+.2f}), "
            f"turnover {t['turnover']:.0%}",
            f"- Validation result (2020–2022, the single look): IC {val['ic_mean']:+.4f} "
            f"(t {val['ic_t']:+.2f}), selection alpha {val['selection_alpha_mean']:+.2%} "
            f"(NW-t {val['selection_alpha_t']:+.2f}), turnover {val['mean_turnover']:.0%}",
            f"- Walk-forward (18.6, descriptive): {wf_line}",
            f"- OOS attempt: 1 of 3 (family {cfg.family}; ≤ 1 pre-registration per factory run)",
            f"- Cumulative {cfg.market} vault touches before this one: "
            f"{vault_touches(cfg.market, root)}",
            "- OOS verdict: pending",
            "- Registry status change: incubating → registered (on certify)",
        ]
    )


# --- CLI -----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The Strategy Factory (playbook §12)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a declared search (DEV only)")
    r.add_argument("config")
    r.add_argument("--log-entry", required=True, help="the RESEARCH_LOG 'search declared' entry id")
    r.add_argument("--log", default=None)
    lb = sub.add_parser("leaderboard", help="print a run's leaderboard")
    lb.add_argument("run_id")
    lb.add_argument("--top", type=int, default=20)
    pr = sub.add_parser("promote", help="spend the run's VAL looks; F4 passers → incubating")
    pr.add_argument("run_id")
    pr.add_argument("--finalists", type=int, nargs="*", default=None)
    dr = sub.add_parser("draft", help="print a pre-registration draft for an incubating finalist")
    dr.add_argument("run_id")
    dr.add_argument("spec_name")
    en = sub.add_parser("engine", help="cache DEV daily-engine backtests of the top trials")
    en.add_argument("run_id")
    en.add_argument("--top", type=int, default=10)
    args = p.parse_args(argv)

    if args.cmd == "promote":
        cfg = load_config(run_dir(args.run_id) / "config.json")
        bench_adj = None
        if any(cfg.overlay_menu):
            from heimdall.backtest.matrix import load_matrices

            bench_adj = load_matrices()["adj_close"][BENCHMARK[cfg.market]].dropna()
        rep = promote(
            args.run_id, load_panel(cfg.market), finalists=args.finalists, benchmark_adj=bench_adj
        )
        print(f"run {rep.run_id}: N {rep.n_trials}, PBO {rep.pbo:.3f}, F2 {rep.run_passes_f2}")
        for look in rep.looks:
            val = cast_dict(look["val"])
            ic_v = float(str(val["ic_mean"]))
            alpha_v = float(str(val["selection_alpha_mean"]))
            verdict = "PASS" if look["f4_pass"] else "fail"
            print(f"  {look['spec_name']}: VAL IC {ic_v:+.4f}, alpha {alpha_v:+.2%} → F4 {verdict}")
        print(f"incubating: {rep.promoted or 'none'}  → {val_looks_path(rep.run_id)}")
        return 0
    if args.cmd == "draft":
        print(draft_preregistration(args.run_id, args.spec_name))
        return 0
    if args.cmd == "engine":
        from heimdall.backtest.matrix import load_matrices

        cfg = load_config(run_dir(args.run_id) / "config.json")
        paths = cache_engine_backtests(
            args.run_id, load_panel(cfg.market), load_matrices(), top_k=args.top
        )
        print(f"{len(paths)} engine backtests → {engine_dir(args.run_id)}")
        return 0

    if args.cmd == "run":
        cfg = load_config(Path(args.config))
        log = Path(args.log) if args.log else _signals_root(None) / "docs" / "RESEARCH_LOG.md"
        t0 = time.time()
        trials = run_search(
            cfg, load_panel(cfg.market), log_entry=args.log_entry, log_path=log, progress=True
        )
        print(f"{len(trials)} trials in {time.time() - t0:.0f}s → {ledger_path(cfg.run_id)}")
        return 0
    board = leaderboard(args.run_id)
    print(
        f"run {args.run_id}: N = {board.n_trials} trials, PBO = {board.pbo:.3f} "
        f"({'passes' if board.run_passes_f2 else 'FAILS'} F2 ≤ {gates.FACTORY_MAX_PBO})"
    )
    cols = [
        "trial_id",
        "features",
        "universe",
        "top_n",
        "weighting",
        "exit_rank",
        "neutralize",
        "objective",
        "dsr",
        "ic_t",
        "alpha_mean",
        "alpha_t",
        "turnover",
        "candidate",
    ]
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(board.table[cols].head(args.top).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
