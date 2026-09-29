"""Technical-rule factory (roadmap 18.8) — daily entry/exit rules, judged across a universe.

**Research-only** (playbook §12.5): 「研究工具・持有期 < 1 個月，不在認證範圍」. The NORTH_STAR
one-month horizon floor keeps these rules out of every tier; nothing here touches the registry,
the ledgers, or the research panel, and its results may not inform any factory search config
(*config-shopping*, playbook §10).

For each symbol × rule, parameters are chosen by **rolling walk-forward**: fit on the trailing
``fit_years`` (the grid point with the best in-sample Sharpe), then trade the next calendar year
with those parameters — every traded year is out-of-sample relative to its own choice. Fills are
the vectorbt engine's next-bar open with costs (``backtest.engine``); a year starts flat.
Every (symbol × rule × grid point) is a counted trial, and each walk-forward series carries a
Deflated Sharpe Ratio against that total (``backtest.overfit``) — a rule that "works" on a few
names out of hundreds is exactly what DSR exists to catch.

    uv run python -m heimdall.backtest.tech_factory --top 100
"""

from __future__ import annotations

import argparse
import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.backtest.costs import DEFAULT_COSTS, Costs
from heimdall.backtest.engine import run_backtest
from heimdall.backtest.overfit import dsr_from_moments, moments
from heimdall.backtest.strategies import STRATEGIES
from heimdall.data.store import data_root

LABEL = (
    "研究工具・持有期 < 1 個月，不在認證範圍 (research tool — horizon < 1 month, never certified)"
)

#: The fixed per-rule grids (small on purpose: every point is a trial).
GRIDS: dict[str, list[dict[str, float]]] = {
    "sma_crossover": [
        {"fast": f, "slow": s} for f, s in itertools.product((10, 20, 50), (50, 100, 200)) if f < s
    ],
    "breakout": [
        {"entry": e, "exit": x} for e, x in itertools.product((20, 55, 100), (10, 20, 50))
    ],
    "rsi_reversion": [
        {"length": n, "lower": lo, "upper": up}
        for n, lo, up in itertools.product((2, 14), (20, 30), (70, 80))
    ],
    "macd_cross": [
        {"fast": 12, "slow": 26, "signal": 9},
        {"fast": 8, "slow": 17, "signal": 9},
        {"fast": 5, "slow": 35, "signal": 5},
    ],
    "bollinger_reversion": [
        {"length": n, "mult": k} for n, k in itertools.product((20, 50), (2.0, 2.5))
    ],
}


@dataclass
class RuleResult:
    """One symbol × rule walk-forward."""

    symbol: str
    rule: str
    returns: pd.Series  # daily walk-forward returns over the traded years
    buy_hold: pd.Series  # the symbol's own daily returns over the same days
    chosen: dict[int, dict[str, float]]  # traded year → parameters fitted on the prior window


@dataclass
class TechFactoryResult:
    label: str
    n_trials: int  # symbols × rules × grid points
    per_pair: pd.DataFrame  # one row per symbol × rule
    per_rule: pd.DataFrame  # the aggregate per rule
    notes: list[str] = field(default_factory=list)


def _returns(ohlcv: pd.DataFrame, entries: pd.Series, exits: pd.Series, costs: Costs) -> pd.Series:
    pf = run_backtest(ohlcv, entries, exits, costs=costs)
    r = pf.returns()
    if isinstance(r, pd.DataFrame):
        r = r.iloc[:, 0]
    return pd.Series(r.to_numpy(dtype=float), index=pd.DatetimeIndex(ohlcv["date"]))


def _sharpe(r: pd.Series) -> float:
    sd = float(r.std())
    return float(r.mean()) / sd * math.sqrt(252) if sd > 0 else float("nan")


def _signals(
    rule: str, ohlcv: pd.DataFrame, params: dict[str, float]
) -> tuple[pd.Series, pd.Series] | None:
    kw = {k: int(v) if float(v).is_integer() else v for k, v in params.items()}
    try:
        return STRATEGIES[rule].signals(ohlcv, **kw)
    except ValueError:
        return None


def walk_forward_rule(
    ohlcv: pd.DataFrame,
    symbol: str,
    rule: str,
    *,
    fit_years: int = 3,
    first_year: int | None = None,
    last_year: int | None = None,
    costs: Costs = DEFAULT_COSTS,
) -> RuleResult | None:
    """Rolling walk-forward for one symbol × rule; ``None`` if there is no traded year."""
    df = ohlcv.sort_values("date").reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    years = sorted(set(dates.year))
    start = (years[0] + fit_years) if first_year is None else max(first_year, years[0] + fit_years)
    stop = years[-1] if last_year is None else min(last_year, years[-1])
    grid = GRIDS[rule]
    # Signals are causal (each bar uses only bars ≤ it), so they are computed once on the
    # whole history and sliced; a slice's backtest starts flat on its first bar.
    signals = {i: _signals(rule, df, p) for i, p in enumerate(grid)}
    parts: list[pd.Series] = []
    chosen: dict[int, dict[str, float]] = {}
    for year in range(start, stop + 1):
        fit = (dates.year >= year - fit_years) & (dates.year <= year - 1)
        trade = dates.year == year
        if not fit.any() or not trade.any():
            continue
        best_i, best_sr = None, float("-inf")
        for i, sig in signals.items():
            if sig is None:
                continue
            sr = _sharpe(_returns(df[fit], sig[0][fit], sig[1][fit], costs))
            if math.isfinite(sr) and sr > best_sr:  # no trades ⇒ no Sharpe ⇒ never chosen
                best_i, best_sr = i, sr
        if best_i is None:
            continue
        ent, ex = signals[best_i]  # type: ignore[misc]
        parts.append(_returns(df[trade], ent[trade], ex[trade], costs))
        chosen[year] = grid[best_i]
    if not parts:
        return None
    wf = pd.concat(parts)
    close = pd.Series(df["adj_close"].to_numpy(dtype=float), index=dates)
    bh = close.pct_change().reindex(wf.index).fillna(0.0)
    return RuleResult(symbol, rule, wf, bh, chosen)


def _cagr(r: pd.Series) -> float:
    growth = float(np.prod(1.0 + r.to_numpy(dtype=float)))
    return growth ** (252 / len(r)) - 1.0 if len(r) and growth > 0 else float("nan")


def run_tech_factory(
    prices: dict[str, pd.DataFrame],
    *,
    rules: list[str] | None = None,
    fit_years: int = 3,
    first_year: int | None = None,
    last_year: int | None = None,
    costs: Costs = DEFAULT_COSTS,
    progress: Callable[[int, int], None] | None = None,
) -> TechFactoryResult:
    """Walk every symbol × rule forward and aggregate per rule (research-only)."""
    rules = rules if rules is not None else list(GRIDS)
    n_trials = len(prices) * sum(len(GRIDS[r]) for r in rules)
    results: list[RuleResult] = []
    total, done = len(prices) * len(rules), 0
    for sym, ohlcv in prices.items():
        for rule in rules:
            res = walk_forward_rule(
                ohlcv,
                sym,
                rule,
                fit_years=fit_years,
                first_year=first_year,
                last_year=last_year,
                costs=costs,
            )
            if res is not None:
                results.append(res)
            done += 1
            if progress is not None:
                progress(done, total)

    rows: list[dict[str, object]] = []
    for res in results:
        sr, n, skew, kurt = moments(res.returns)
        rows.append(
            {
                "symbol": res.symbol,
                "rule": res.rule,
                "wf_cagr": _cagr(res.returns),
                "bh_cagr": _cagr(res.buy_hold),
                "wf_sharpe": _sharpe(res.returns),
                "bh_sharpe": _sharpe(res.buy_hold),
                "sr": sr,
                "n": n,
                "skew": skew,
                "kurt": kurt,
                "years": len(res.chosen),
            }
        )
    per_pair = pd.DataFrame(rows)
    notes = [LABEL]
    if per_pair.empty:
        return TechFactoryResult(LABEL, n_trials, per_pair, pd.DataFrame(), notes)
    per_pair["excess_cagr"] = per_pair["wf_cagr"] - per_pair["bh_cagr"]
    srs = per_pair["sr"].to_numpy(dtype=float)
    var = float(np.nanvar(srs, ddof=1)) if np.isfinite(srs).sum() > 1 else 0.0
    per_pair["dsr"] = [
        dsr_from_moments(float(sr), int(n), float(sk), float(ku), n_trials, var)
        for sr, n, sk, ku in zip(
            per_pair["sr"].to_numpy(dtype=float),
            per_pair["n"].to_numpy(dtype=int),
            per_pair["skew"].to_numpy(dtype=float),
            per_pair["kurt"].to_numpy(dtype=float),
            strict=True,
        )
    ]
    per_rule = (
        per_pair.groupby("rule")
        .agg(
            pairs=("symbol", "count"),
            mean_excess_cagr=("excess_cagr", "mean"),
            median_excess_cagr=("excess_cagr", "median"),
            pct_beating_buy_hold=("excess_cagr", lambda s: float((s > 0).mean())),
            median_wf_sharpe=("wf_sharpe", "median"),
            median_bh_sharpe=("bh_sharpe", "median"),
            pct_dsr_pass=("dsr", lambda s: float((s >= 0.95).mean())),
        )
        .reset_index()
    )
    notes.append(
        f"N = {n_trials} trials (symbols × rules × grid points); DSR per symbol × rule uses that N "
        "and the cross-pair Sharpe variance."
    )
    return TechFactoryResult(LABEL, n_trials, per_pair, per_rule, notes)


def load_cached_prices(symbols: list[str], root: Path | None = None) -> dict[str, pd.DataFrame]:
    """Canonical OHLCV for ``symbols`` from the local cache only (no network)."""
    from heimdall.data.cache import _read
    from heimdall.data.store import prices_path
    from heimdall.data.symbols import parse_symbol

    base = root if root is not None else data_root()
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        path = prices_path(base, parse_symbol(sym))
        if path.exists():
            df = _read(path)
            if len(df):
                out[sym] = df
    return out


def top_us_by_market_cap(n: int) -> list[str]:
    """The snapshot's current top-``n`` US names by market cap (price ≥ $2, $5M/day liquid).

    A *current* list — survivorship-biased by construction, like everything in this module.
    """
    from heimdall.screener.snapshot import load_snapshot

    snap = load_snapshot()
    us = snap[snap["symbol"].astype(str).str.endswith(".US")]
    us = us[(us["price"] >= 2.0) & (us["dollar_vol_21d"] >= 5e6)]
    return [str(s) for s in us.sort_values("market_cap", ascending=False)["symbol"].head(n)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Technical-rule factory — research only (18.8)")
    p.add_argument("--top", type=int, default=100, help="top-N US names by market cap")
    p.add_argument("--first-year", type=int, default=2013)
    p.add_argument("--rules", nargs="*", default=None, choices=list(GRIDS))
    args = p.parse_args(argv)
    prices = load_cached_prices(top_us_by_market_cap(args.top))

    def _progress(done: int, total: int) -> None:
        if done % 50 == 0 or done == total:
            print(f"{done}/{total}", flush=True)

    res = run_tech_factory(prices, rules=args.rules, first_year=args.first_year, progress=_progress)
    out = data_root() / "research" / "tech_factory"
    out.mkdir(parents=True, exist_ok=True)
    res.per_pair.to_parquet(out / "per_pair.parquet")
    res.per_rule.to_parquet(out / "per_rule.parquet")
    print(res.label)
    print(f"N = {res.n_trials} trials over {len(prices)} symbols")
    with pd.option_context("display.width", 200):
        print(res.per_rule.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
