"""Daily portfolio backtest engine (roadmap 18.3) — target weights in, a daily equity out.

Generic and spec-agnostic: it knows nothing about signals, only a schedule of **target
weights decided at a date** and the wide adjusted open/close matrices (``backtest.matrix``).
``heimdall.research.spec_backtest`` is the one bridge from a ``SignalSpec`` to this module.

The honesty mechanism (``.claude/rules/backtest-honesty.md``):

- a target decided at *D* (using data through *D*'s close) is **filled at the open of the
  first trading day after D** — never at *D*'s close;
- every fill pays ``cost_bps`` per side on the traded notional (Σ|Δvalue|), deducted from NAV
  at the open; the book then **drifts** with prices until the next fill (no free rebalancing);
- weight not invested (a sum < 1, an overlay's cash month, a name with no price) is cash at 0;
- a held name whose price history ends is liquidated at its last close and flagged — the
  current universe is survivorship-biased, but the engine never fabricates a price.

Daily return on a fill day = overnight gap of the old book (prev close → open) × costs × the
new book's open → close move; any other day = close → close. With ``open ≡ prev close`` the
engine's monthly-compounded gross returns equal the panel's ``fwd_1m`` book means exactly (a
test pins this); on real data the difference is the one-day entry timing, reported not hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd

SURVIVORSHIP = "current_universe (optimistic)"


@dataclass
class SimResult:
    """One simulated book."""

    returns: pd.Series  # daily, index = trading days from the first decision on
    holdings: pd.DataFrame  # decision_date, fill_date, symbol, weight (post-cost, at the open)
    trades: pd.DataFrame  # fill_date, symbol, side, dweight (of pre-trade NAV), cost (of NAV)
    turnover: pd.Series  # one-way ½Σ|Δw| per fill date
    flags: list[str] = field(default_factory=list)


def _fill_dates(decisions: list[pd.Timestamp], index: pd.DatetimeIndex) -> dict[int, pd.Timestamp]:
    """Position of each decision's fill day (first bar strictly after it) → decision date."""
    out: dict[int, pd.Timestamp] = {}
    for d in decisions:
        pos = int(index.searchsorted(d, side="right"))
        if pos < len(index):
            out[pos] = d  # a later decision mapping to the same bar wins
    return out


def simulate(
    targets: dict[pd.Timestamp, pd.Series],
    adj_open: pd.DataFrame,
    adj_close: pd.DataFrame,
    *,
    cost_bps: float,
    end: pd.Timestamp | None = None,
) -> SimResult:
    """Simulate one book from its decision schedule; see the module docstring for the rules."""
    decisions = sorted(pd.Timestamp(d) for d in targets)
    if not decisions:
        raise ValueError("no target weights to simulate")
    syms = sorted({str(s) for w in targets.values() for s in w.index})
    flags: list[str] = []
    absent = [s for s in syms if s not in adj_close.columns]
    if absent:
        flags.append(f"no price history for {len(absent)} symbol(s): {absent[:5]}")
    cols = [s for s in syms if s in adj_close.columns]

    index = pd.DatetimeIndex(adj_close.index)
    last_day = pd.Timestamp(end) if end is not None else index.max()
    index = index[(index >= decisions[0]) & (index <= last_day)]
    close = adj_close.reindex(index=index, columns=cols).to_numpy(dtype=float)
    open_ = adj_open.reindex(index=index, columns=cols).to_numpy(dtype=float)
    closef = pd.DataFrame(close).ffill().to_numpy()
    valid = np.isfinite(close)
    first_valid = np.where(valid.any(axis=0), valid.argmax(axis=0), len(index))
    last_valid = np.where(valid.any(axis=0), len(index) - 1 - valid[::-1].argmax(axis=0), -1)
    col_of = {s: i for i, s in enumerate(cols)}
    fills = _fill_dates(decisions, index)
    rate = cost_bps / 1e4

    pos: npt.NDArray[np.float64] = np.zeros(len(cols))
    cash = 1.0
    nav_prev = 1.0
    rets = np.zeros(len(index))
    hold_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    turnover: dict[pd.Timestamp, float] = {}
    ended_flagged: set[int] = set()

    for i in range(1, len(index)):
        # A held name whose history has ended: liquidate at its last close (already marked).
        dead = (pos != 0) & (last_valid < i)
        if dead.any():
            for j in np.flatnonzero(dead):
                if j not in ended_flagged:
                    flags.append(f"{cols[j]} price history ends {index[last_valid[j]].date()}")
                    ended_flagged.add(int(j))
            cash += float(pos[dead].sum())
            pos[dead] = 0.0

        prev_c = closef[i - 1]
        cur_c = closef[i]
        if i in fills:
            d = fills[i]
            o = np.where(np.isfinite(open_[i]), open_[i], prev_c)  # no open ⇒ assume prev close
            gap = np.where(np.isfinite(o) & np.isfinite(prev_c) & (prev_c > 0), o / prev_c, 1.0)
            pos = np.asarray(pos * gap, dtype=float)
            nav = float(pos.sum()) + cash
            w = np.zeros(len(cols))
            tradable = (first_valid <= i) & (last_valid >= i) & np.isfinite(o) & (o > 0)
            untradable: list[str] = []
            for sym, wt in targets[d].items():
                j = col_of.get(str(sym))
                if j is None:
                    continue
                if tradable[j]:
                    w[j] = float(wt)
                elif float(wt) > 0:
                    untradable.append(str(sym))
            if untradable:
                flags.append(
                    f"{len(untradable)} target name(s) not tradable on {index[i].date()} "
                    f"(weight held as cash): {untradable[:3]}"
                )
            desired = w * nav
            delta = desired - pos
            traded = float(np.abs(delta).sum())
            cost = traded * rate
            nav_after = nav - cost
            pos = np.asarray(w * nav_after, dtype=float)
            cash = nav_after - float(pos.sum())
            turnover[index[i]] = 0.5 * traded / nav if nav > 0 else 0.0
            for j in np.flatnonzero(np.abs(delta) > 1e-15):
                trade_rows.append(
                    {
                        "fill_date": index[i],
                        "symbol": cols[j],
                        "side": "buy" if delta[j] > 0 else "sell",
                        "dweight": float(delta[j] / nav),
                        "cost": float(abs(delta[j]) * rate / nav),
                    }
                )
            for j in np.flatnonzero(w):
                hold_rows.append(
                    {
                        "decision_date": d,
                        "fill_date": index[i],
                        "symbol": cols[j],
                        "weight": float(pos[j] / nav_after) if nav_after > 0 else 0.0,
                    }
                )
            intraday = np.where(np.isfinite(cur_c) & (o > 0) & np.isfinite(o), cur_c / o, 1.0)
            pos = np.asarray(pos * intraday, dtype=float)
        else:
            move = np.where(
                np.isfinite(cur_c) & np.isfinite(prev_c) & (prev_c > 0), cur_c / prev_c, 1.0
            )
            pos = np.asarray(pos * move, dtype=float)
        nav_now = float(pos.sum()) + cash
        rets[i] = nav_now / nav_prev - 1.0
        nav_prev = nav_now

    return SimResult(
        returns=pd.Series(rets, index=index, name="return"),
        holdings=pd.DataFrame(
            hold_rows, columns=["decision_date", "fill_date", "symbol", "weight"]
        ),
        trades=pd.DataFrame(trade_rows, columns=["fill_date", "symbol", "side", "dweight", "cost"]),
        turnover=pd.Series(turnover, name="turnover", dtype=float),
        flags=flags,
    )


@dataclass
class EngineResult:
    """A strategy's full daily evidence, beside its two comparisons."""

    returns: pd.DataFrame  # daily: strategy, benchmark, universe (when given)
    holdings: pd.DataFrame
    trades: pd.DataFrame
    turnover: pd.Series
    sector_weights: pd.DataFrame | None  # decision_date × sector (None without a sector map)
    flags: list[str]
    assumptions: dict[str, object]

    @property
    def equity(self) -> pd.DataFrame:
        """Growth of $1 per column."""
        return (1.0 + self.returns).cumprod()


def run(
    target_weights: dict[pd.Timestamp, pd.Series],
    adj_open: pd.DataFrame,
    adj_close: pd.DataFrame,
    *,
    benchmark: str,
    cost_bps: float,
    overlay_cash: pd.Series | None = None,
    universe_targets: dict[pd.Timestamp, pd.Series] | None = None,
    sectors: pd.Series | None = None,
    end: pd.Timestamp | None = None,
) -> EngineResult:
    """Simulate a strategy, the buy-and-hold ``benchmark`` symbol, and (optionally) the
    equal-weight universe rebalanced on the same dates at the same cost.

    ``overlay_cash`` (bool by decision date) replaces that decision's target with cash — the
    regime overlay is applied here, at book level (playbook §12.4).
    """
    targets = dict(target_weights)
    if overlay_cash is not None:
        for d, cash_on in zip(overlay_cash.index, overlay_cash.to_numpy(), strict=True):
            if bool(cash_on) and pd.Timestamp(d) in targets:
                targets[pd.Timestamp(d)] = pd.Series(dtype=float)
    strat = simulate(targets, adj_open, adj_close, cost_bps=cost_bps, end=end)
    first = min(pd.Timestamp(d) for d in targets)
    bench = simulate(
        {first: pd.Series({benchmark: 1.0})}, adj_open, adj_close, cost_bps=0.0, end=end
    )
    cols = {"strategy": strat.returns, "benchmark": bench.returns}
    flags = list(strat.flags)
    if universe_targets:
        univ = simulate(universe_targets, adj_open, adj_close, cost_bps=cost_bps, end=end)
        cols["universe"] = univ.returns
    returns = pd.DataFrame(cols).dropna()

    sector_weights = None
    if sectors is not None and not strat.holdings.empty:
        h = strat.holdings.assign(
            sector=strat.holdings["symbol"].map(sectors).fillna("Unknown").astype(str)
        )
        sector_weights = h.pivot_table(
            index="decision_date", columns="sector", values="weight", aggfunc="sum"
        ).fillna(0.0)

    return EngineResult(
        returns=returns,
        holdings=strat.holdings,
        trades=strat.trades,
        turnover=strat.turnover,
        sector_weights=sector_weights,
        flags=flags,
        assumptions={
            "fill": "next trading day's open after each decision date",
            "cost_bps_per_side": cost_bps,
            "benchmark": benchmark,
            "universe_comparison": bool(universe_targets),
            "overlay": overlay_cash is not None and bool(overlay_cash.any()),
            "period": (str(returns.index.min().date()), str(returns.index.max().date()))
            if len(returns)
            else ("", ""),
            "survivorship": SURVIVORSHIP,
        },
    )
