"""Construction as data (roadmap 18.1) — spec + one month's cross-section → a weighted book.

The single home of every construction choice the Strategy Factory searches, so ``certify``,
``evaluate``, ``monitor``, ``today``, the daily engine and the factory can never disagree on
what "the book" is. Pipeline, in order:

1. **universe** — eligible rows (playbook §3 hygiene) ∩ the spec's tier (``us_large`` = the
   top ``gates.US_LARGE_N`` eligible names by ``market_cap`` at *t*, point-in-time);
2. **filters** — screener predicates (missing data fails, never passes);
3. **score** — :func:`heimdall.research.spec.score` over that pool (z-scores within it);
4. **membership** — plain top-N, or the ``exit_rank`` rank buffer given last month's book;
5. **weights** — equal, inverse ``vol_63d``, or rank-linear (18.18);
6. **sector cap** — ``max_sector_weight`` per ``sector``, excess redistributed pro-rata.

The G3 comparison universe is step 1 only (eligible ∩ tier): filters are part of the selection
being judged, the tier is the investable set it is judged against.

A default spec reproduces the pre-18.1 book **bit-for-bit**: the pool is the eligible set, the
ranking is the identical ``dropna → sort_values`` call ``certify`` always used, and membership
is its ``head(top_n)`` at equal weight. The regime ``overlay`` is carried on the spec but applied
by consumers at book level (playbook §12.4) via :func:`overlay_cash`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from heimdall.research import gates
from heimdall.research.spec import SignalSpec, score
from heimdall.screener.engine import _mask

_SCORE = "signal_score"
#: The overlay's moving-average window, in trading bars.
OVERLAY_SMA_BARS: int = 200
#: Sector label used for rows whose sector is missing (they still count against a cap).
UNKNOWN_SECTOR: str = "Unknown"


def is_equal_weight(spec: SignalSpec) -> bool:
    """Equal-weight books take the legacy unweighted-mean paths downstream (bit-for-bit)."""
    return spec.weighting == "" and spec.max_sector_weight is None


def universe_mask(spec: SignalSpec, cross: pd.DataFrame) -> pd.Series:
    """Rows in the spec's investable universe: eligible ∩ tier (the G3 comparison set)."""
    if "eligible" in cross.columns:
        elig = cross["eligible"].astype(bool)
    else:
        elig = pd.Series(True, index=cross.index)
    if spec.universe == "":
        return elig
    if spec.universe == "us_large":
        if "market_cap" not in cross.columns:
            raise KeyError("market_cap")  # the tier needs it; never guess a universe
        cap = cross["market_cap"].where(elig)
        rank = cap.rank(ascending=False, method="first")  # NaN cap ⇒ NaN rank ⇒ excluded
        return elig & (rank <= gates.US_LARGE_N)
    raise ValueError(f"unknown universe {spec.universe!r}")  # pragma: no cover - validated


def pool_mask(spec: SignalSpec, cross: pd.DataFrame) -> pd.Series:
    """The scoring pool: :func:`universe_mask` ∩ every filter predicate."""
    mask = universe_mask(spec, cross)
    for pred in spec.filters:
        mask = mask & _mask(cross, pred)
    return mask


def pool_scores(spec: SignalSpec, cross: pd.DataFrame) -> pd.Series:
    """Spec scores with z-scores computed inside the pool; rows outside it score NaN."""
    return score(spec, cross.assign(eligible=pool_mask(spec, cross)))


def ranked_symbols(cross: pd.DataFrame, scores: pd.Series) -> list[str]:
    """Scored symbols, best first — the exact ``dropna → sort_values`` ``certify`` used."""
    scored = cross.assign(**{_SCORE: scores})
    ranked = scored.dropna(subset=[_SCORE]).sort_values(_SCORE, ascending=False)
    return [str(s) for s in ranked["symbol"]]


def buffered_members(ranked: list[str], prev: set[str], top_n: int, exit_rank: int) -> list[str]:
    """Rank-buffer membership (the 17.10 mechanism), in rank order.

    Keep every previous member still ranked ≤ ``exit_rank``; fill up to ``top_n`` with the
    best-ranked names not kept. A previous member that no longer ranks at all is dropped.
    """
    rank_of = {sym: i + 1 for i, sym in enumerate(ranked)}
    keep = [s for s in ranked if s in prev and rank_of[s] <= exit_rank][:top_n]
    kept = set(keep)
    fill = [s for s in ranked if s not in kept][: max(top_n - len(keep), 0)]
    chosen = kept | set(fill)
    return [s for s in ranked if s in chosen]


def members(spec: SignalSpec, ranked: list[str], prev: set[str] | None) -> list[str]:
    """Plain top-N, or buffered membership when ``exit_rank`` is set and a prior book exists."""
    if spec.exit_rank is None or not prev:
        return ranked[: spec.top_n]
    return buffered_members(ranked, prev, spec.top_n, spec.exit_rank)


def _inverse_vol(cross: pd.DataFrame, names: list[str]) -> pd.Series:
    """Raw weights ∝ 1/vol_63d; a missing/non-positive vol gets the mean valid raw weight
    (an equal-weight fallback for that name). All missing ⇒ equal weight."""
    vol = cross.set_index("symbol").reindex(names)["vol_63d"].astype(float)
    raw = 1.0 / vol.where(vol > 0)
    raw = raw.fillna(float(raw.mean())) if raw.notna().any() else pd.Series(1.0, index=names)
    return raw / float(raw.sum())


def cap_sectors(weights: pd.Series, sectors: pd.Series, cap: float) -> pd.Series:
    """Cap each sector's total weight at ``cap``; the excess goes pro-rata to uncapped names.

    Iterates to convergence. When the cap is infeasible (too few sectors to hold 100% at
    ``cap`` each), every sector ends at ``cap`` and the book sums to < 1 — the remainder is
    cash earning 0, never silently re-inflated past the cap.
    """
    w = weights.astype(float).copy()
    sec = sectors.reindex(w.index).fillna(UNKNOWN_SECTOR).astype(str)
    eps = 1e-12
    capped: set[str] = set()
    for _ in range(len(set(sec)) + 1):
        totals = w.groupby(sec).sum()
        over = [s for s, tot in totals.items() if tot > cap + eps]
        if not over:
            break
        excess = 0.0
        for s in over:
            in_s = sec == s
            excess += float(w[in_s].sum()) - cap
            w[in_s] = w[in_s] * (cap / float(w[in_s].sum()))
            capped.add(str(s))
        free = ~sec.isin(capped)
        base = float(w[free].sum())
        if base <= eps:  # nobody left to absorb the excess: hold it as cash
            break
        w[free] = w[free] + excess * w[free] / base
    return w


def _rank_linear(names: list[str]) -> pd.Series:
    """Weights ∝ (m + 1 − r) over the m members in rank order (18.18): the best name gets m
    shares, the last one share. Ranked within the members, so a buffered member that has slipped
    below ``top_n`` still holds a positive weight. Parameter-free (structural)."""
    m = len(names)
    raw = pd.Series([float(m - i) for i in range(m)], index=names)
    return raw / float(raw.sum())


def weights_for(spec: SignalSpec, cross: pd.DataFrame, names: list[str]) -> pd.Series:
    """Weights over ``names`` (rank order): equal, inverse-vol or rank-linear, then the sector
    cap."""
    if not names:
        return pd.Series(dtype=float)
    if spec.weighting == "inverse_vol":
        w = _inverse_vol(cross, names)
    elif spec.weighting == "rank_linear":
        w = _rank_linear(names)
    else:
        w = pd.Series(1.0 / len(names), index=names)
    if spec.max_sector_weight is not None:
        if "sector" not in cross.columns:
            raise KeyError("sector")
        sectors = cross.set_index("symbol")["sector"]
        w = cap_sectors(w, sectors, spec.max_sector_weight)
    return w


def select(
    spec: SignalSpec, cross: pd.DataFrame, scores: pd.Series, prev: set[str] | None = None
) -> pd.Series:
    """Weights (symbol → weight, rank order) from already-computed pool scores."""
    names = members(spec, ranked_symbols(cross, scores), prev)
    return weights_for(spec, cross, names)


def construct_book(
    spec: SignalSpec, cross: pd.DataFrame, prev: set[str] | None = None
) -> pd.Series:
    """The spec's book for one cross-section: symbol → weight (sums to 1, or < 1 only when a
    sector cap is infeasible — the rest is cash). ``prev`` = last month's members, for the
    rank buffer; ``None`` (or empty) ⇒ plain top-N."""
    return select(spec, cross, pool_scores(spec, cross), prev)


def overlay_cash(spec: SignalSpec, benchmark_adj: pd.Series, t: pd.Timestamp) -> bool:
    """Is the spec's regime overlay in cash for a decision at *t*?

    ``spy_sma200_cash``: the benchmark's adjusted close on the last bar ≤ *t* is below its
    ``OVERLAY_SMA_BARS``-bar simple moving average. Fewer bars than the window ⇒ invested
    (no signal is not a cash signal). Uses only bars ≤ *t* — knowable at the decision.
    """
    if spec.overlay == "":
        return False
    hist = benchmark_adj[benchmark_adj.index <= pd.Timestamp(t)].dropna()
    if len(hist) < OVERLAY_SMA_BARS:
        return False
    window = hist.iloc[-OVERLAY_SMA_BARS:]
    return bool(float(window.iloc[-1]) < float(window.mean()))


@dataclass
class BookSchedule:
    """A spec's decisions over a panel window — the input the daily engine needs (18.3)."""

    targets: dict[pd.Timestamp, pd.Series]  # decision date → the book's weights
    universe_targets: dict[pd.Timestamp, pd.Series]  # decision date → EW over the spec's tier
    overlay_cash: pd.Series  # bool by decision date (all False without an overlay)
    details: pd.DataFrame  # date, symbol, weight, score, rank, sector (the book's rows)


def book_schedule(
    spec: SignalSpec,
    panel: pd.DataFrame,
    benchmark_adj: pd.Series | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> BookSchedule:
    """Walk the panel's months in order (threading the rank buffer) and record every decision.

    ``benchmark_adj`` is needed only for a spec with an overlay (it decides the cash months).
    Pure: no engine, no network — ``heimdall.research.spec_backtest`` runs the result.
    """
    if spec.overlay and benchmark_adj is None:
        raise ValueError("an overlay spec needs benchmark_adj to decide its cash months")
    dates = pd.to_datetime(panel["date"])
    keep = pd.Series(True, index=panel.index)
    if start is not None:
        keep &= dates >= pd.Timestamp(start)
    if end is not None:
        keep &= dates <= pd.Timestamp(end)
    win = panel.loc[keep].assign(date=dates[keep])
    targets: dict[pd.Timestamp, pd.Series] = {}
    universe: dict[pd.Timestamp, pd.Series] = {}
    cash: dict[pd.Timestamp, bool] = {}
    rows: list[pd.DataFrame] = []
    prev: set[str] | None = None
    for t, cross in win.groupby("date", sort=True):
        ts = pd.Timestamp(str(t))
        scores = pool_scores(spec, cross)
        book = select(spec, cross, scores, prev)
        prev = set(book.index)
        targets[ts] = book
        tier = cross.loc[universe_mask(spec, cross), "symbol"].astype(str)
        universe[ts] = (
            pd.Series(1.0 / len(tier), index=list(tier)) if len(tier) else pd.Series(dtype=float)
        )
        cash[ts] = overlay_cash(spec, benchmark_adj, ts) if benchmark_adj is not None else False
        if len(book):
            by_sym = cross.assign(_score=scores).set_index("symbol")
            ranks = {s: i + 1 for i, s in enumerate(ranked_symbols(cross, scores))}
            detail = pd.DataFrame(
                {
                    "date": ts,
                    "symbol": list(book.index),
                    "weight": book.to_numpy(),
                    "score": by_sym.loc[list(book.index), "_score"].to_numpy(),
                    "rank": [ranks[s] for s in book.index],
                }
            )
            if "sector" in cross.columns:
                detail["sector"] = by_sym.loc[list(book.index), "sector"].to_numpy()
            rows.append(detail)
    details = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return BookSchedule(targets, universe, pd.Series(cash, dtype=bool), details)
