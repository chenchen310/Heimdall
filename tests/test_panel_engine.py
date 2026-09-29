"""Daily portfolio engine (roadmap 18.3) — known answers, the look-ahead canary, reconciliation.

The canary is the most important test here: a name's jump on the close of the very day it is
selected must never reach the strategy (it is bought at the next open). The reconciliation test
proves the engine and the panel labels price the same book when ``open ≡ prev close``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.backtest import matrix, panel_engine, portfolio_stats
from heimdall.backtest.portfolio import backtest_portfolio
from heimdall.data.schema import OHLCV_COLUMNS
from heimdall.research import construct
from heimdall.research.spec import SignalSpec

D = pd.bdate_range("2024-01-01", periods=6)


def _mat(
    closes: dict[str, list[float]], opens: dict[str, dict[int, float]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.DataFrame(closes, index=D[: len(next(iter(closes.values())))])
    open_ = close.shift(1)  # default: open ≡ previous close
    for sym, per_day in opens.items():
        for i, v in per_day.items():
            open_.iloc[i, open_.columns.get_loc(sym)] = v
    return open_, close


def _known() -> tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, pd.Series]]:
    open_, close = _mat(
        {"A": [10, 11, 12, 12, 13.2, 13.2], "B": [20, 19, 19, 18, 18, 18]},
        {"A": {1: 10.5, 3: 12.6}, "B": {1: 20.0, 3: 19.0}},
    )
    targets = {D[0]: pd.Series({"A": 0.5, "B": 0.5}), D[2]: pd.Series({"A": 1.0})}
    return open_, close, targets


# --- known answers -------------------------------------------------------------


def test_known_answer_without_costs() -> None:
    open_, close, targets = _known()
    sim = panel_engine.simulate(targets, open_, close, cost_bps=0.0)
    eq = (1.0 + sim.returns).cumprod()
    d1 = 0.5 * 11 / 10.5 + 0.5 * 19 / 20  # bought at the d1 open, marked at the d1 close
    d2 = 0.5 * 11 / 10.5 * 12 / 11 + 0.5 * 19 / 20
    nav3 = 0.5 * 11 / 10.5 * 12 / 11 * 12.6 / 12 + 0.5 * 19 / 20  # the d3 open, pre-trade
    d3 = nav3 * 12 / 12.6  # all-in A at the d3 open
    assert eq.iloc[0] == 1.0  # decision day: still cash
    assert eq.iloc[1:4].tolist() == pytest.approx([d1, d2, d3])
    assert eq.iloc[-1] == pytest.approx(d3 * 1.1)
    assert sim.turnover.index.tolist() == [D[1], D[3]]
    assert sim.holdings["fill_date"].unique().tolist() == [D[1], D[3]]


def test_known_answer_with_costs() -> None:
    open_, close, targets = _known()
    sim = panel_engine.simulate(targets, open_, close, cost_bps=20.0)
    rate = 0.002
    nav1 = 1.0 - rate  # buying the whole book from cash trades 1.0 of NAV
    a3, b3 = nav1 * 0.5 * 11 / 10.5 * 12 / 11 * 12.6 / 12, nav1 * 0.5 * 19 / 20
    nav3 = a3 + b3
    traded = abs(nav3 - a3) + b3  # top A up to 100%, sell all of B
    after = nav3 - traded * rate
    eq = (1.0 + sim.returns).cumprod()
    assert eq.iloc[-1] == pytest.approx(after * 12 / 12.6 * 1.1)
    assert sim.trades["cost"].sum() == pytest.approx(rate + traded * rate / nav3)


def test_lookahead_canary_signal_day_jump_is_never_captured() -> None:
    # X jumps +50% on the close of the day it is selected (d2), then stays flat.
    open_, close = _mat({"X": [10, 10, 15, 15, 15, 15], "Y": [10, 10, 10, 10, 10, 10]}, {})
    targets = {D[0]: pd.Series({"Y": 1.0}), D[2]: pd.Series({"X": 1.0})}
    sim = panel_engine.simulate(targets, open_, close, cost_bps=0.0)
    assert (1.0 + sim.returns).prod() == pytest.approx(1.0)  # bought at the d3 open = 15
    # The same selection filled at the signal close would have "earned" nothing either —
    # the killer case is a fill *before* the jump: prove the fill date is after the decision.
    assert sim.holdings.loc[sim.holdings["symbol"] == "X", "fill_date"].tolist() == [D[3]]


def test_reconciles_with_panel_labels_when_open_equals_prev_close() -> None:
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2023-01-02", "2023-07-31")
    syms = [f"S{i}" for i in range(10)]
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0005, 0.02, (len(days), 10)), axis=0),
        index=days,
        columns=syms,
    )
    open_ = close.shift(1)
    month_ends = list(close.groupby(close.index.to_period("M")).tail(1).index)
    rows = []
    for k, t in enumerate(month_ends[:-1]):
        nxt = month_ends[k + 1]
        for s in syms:
            rows.append(
                {
                    "date": t,
                    "symbol": s,
                    "eligible": True,
                    "sig": float(rng.normal()),
                    "fwd_1m": float(close.loc[nxt, s] / close.loc[t, s] - 1.0),
                }
            )
    panel = pd.DataFrame(rows)
    spec = SignalSpec(name="r", family="r", market="US", features={"sig": 1.0}, top_n=3)
    sched = construct.book_schedule(spec, panel)
    sim = panel_engine.simulate(sched.targets, open_, close, cost_bps=0.0, end=month_ends[-1])
    for k, t in enumerate(month_ends[:-1]):
        nxt = month_ends[k + 1]
        window = sim.returns[(sim.returns.index > t) & (sim.returns.index <= nxt)]
        engine_month = float((1.0 + window).prod() - 1.0)
        book = sched.targets[t]
        cross = panel[panel["date"] == t].set_index("symbol")
        label_mean = float(cross.loc[list(book.index), "fwd_1m"].mean())
        assert engine_month == pytest.approx(label_mean, abs=1e-12)


def test_equal_weights_drift_and_rebalancing_costs() -> None:
    open_, close = _mat({"A": [10, 10, 20, 20, 20, 20], "B": [10, 10, 10, 10, 10, 10]}, {})
    same = pd.Series({"A": 0.5, "B": 0.5})
    sim = panel_engine.simulate({D[0]: same, D[2]: same}, open_, close, cost_bps=10.0)
    # after A doubles the book is 2/3 A: resetting to 50/50 trades 2 × 1/6 of NAV
    assert sim.turnover.loc[D[3]] == pytest.approx(1 / 6)


def test_delisted_name_is_liquidated_at_its_last_close_and_flagged() -> None:
    open_, close = _mat(
        {"A": [10, 10, 12, np.nan, np.nan, np.nan], "B": [10, 10, 10, 10, 10, 10]}, {}
    )
    sim = panel_engine.simulate({D[0]: pd.Series({"A": 0.5, "B": 0.5})}, open_, close, cost_bps=0.0)
    eq = (1.0 + sim.returns).cumprod()
    assert eq.iloc[-1] == pytest.approx(0.5 * 1.2 + 0.5)
    assert any("A price history ends" in f for f in sim.flags)


def test_untradable_target_is_held_as_cash() -> None:
    open_, close = _mat({"A": [10, 10, 11, 12, 13, 14], "Z": [np.nan] * 6}, {})
    sim = panel_engine.simulate({D[0]: pd.Series({"A": 0.5, "Z": 0.5})}, open_, close, cost_bps=0)
    eq = (1.0 + sim.returns).cumprod()
    assert eq.iloc[-1] == pytest.approx(0.5 + 0.5 * 1.4)
    assert any("not tradable" in f for f in sim.flags)


def test_run_overlay_benchmark_universe_and_sectors() -> None:
    open_, close = _mat(
        {"A": [10, 11, 12, 13, 14, 15], "B": [10, 10, 10, 10, 10, 10], "SPY": [1, 1, 2, 2, 2, 2]},
        {},
    )
    targets = {D[0]: pd.Series({"A": 1.0}), D[2]: pd.Series({"A": 1.0})}
    res = panel_engine.run(
        targets,
        open_,
        close,
        benchmark="SPY",
        cost_bps=0.0,
        overlay_cash=pd.Series({D[0]: False, D[2]: True}),
        universe_targets={D[0]: pd.Series({"A": 0.5, "B": 0.5})},
        sectors=pd.Series({"A": "Tech"}),
    )
    eq = res.equity
    assert eq["strategy"].iloc[-1] == pytest.approx(12 / 10)  # in cash from the d3 open
    assert eq["benchmark"].iloc[-1] == pytest.approx(2.0)  # bought at the d1 open (=1)
    assert eq["universe"].iloc[-1] == pytest.approx(0.5 * 15 / 10 + 0.5)
    assert res.sector_weights is not None
    assert res.sector_weights.loc[D[0], "Tech"] == pytest.approx(1.0)
    assert res.assumptions["overlay"] is True
    assert "current_universe" in str(res.assumptions["survivorship"])


# --- stats ---------------------------------------------------------------------


def test_portfolio_stats_known_answers() -> None:
    idx = pd.bdate_range("2020-01-01", periods=252)
    b = pd.Series(np.tile([0.01, -0.005], 126), index=idx)
    r = 2.0 * b
    st = portfolio_stats.portfolio_stats(r, b, universe=b)
    assert st["beta"] == pytest.approx(2.0)
    assert st["alpha_ann"] == pytest.approx(0.0, abs=1e-12)
    assert st["cagr"] == pytest.approx(float((1 + r).prod() - 1.0))  # exactly one year
    assert st["max_drawdown"] == pytest.approx(-0.01)
    assert st["max_drawdown_days"] == 1.0
    assert st["ir_vs_universe"] == pytest.approx(st["ir_vs_benchmark"])
    yr = portfolio_stats.yearly_returns(pd.DataFrame({"s": r}))
    assert yr.loc[2020, "s"] == pytest.approx(float((1 + r[r.index.year == 2020]).prod() - 1))


# --- matrices ------------------------------------------------------------------


def _write_cache(root: Path, ticker: str, days: pd.DatetimeIndex, px: list[float]) -> None:
    df = pd.DataFrame(
        {
            "symbol": f"{ticker}.US",
            "date": days,
            "open": [p * 0.99 for p in px],
            "high": px,
            "low": px,
            "close": px,
            "adj_close": [p / 2 for p in px],  # a 2:1 split-style adjustment
            "volume": 1000.0,
            "currency": "USD",
            "provider": "test",
            "fetched_at": pd.Timestamp("2024-01-01"),
        }
    )[OHLCV_COLUMNS]
    path = root / "prices" / "US" / f"{ticker}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_matrix_build_adjusts_opens_and_delta_appends(tmp_path: Path) -> None:
    days = pd.bdate_range("2024-01-01", periods=5)
    _write_cache(tmp_path, "AAA", days[:3], [10.0, 11.0, 12.0])
    rep = matrix.update_matrices(["AAA.US", "NOPE.US"], root=tmp_path)
    assert rep.missing == ["NOPE.US"] and rep.n_dates == 3
    m = matrix.load_matrices(root=tmp_path)
    assert m["adj_open"]["AAA.US"].tolist() == pytest.approx([4.95, 5.445, 5.94])
    # the cache grows by two days and a new symbol appears: only those rows are ingested
    _write_cache(tmp_path, "AAA", days, [10.0, 11.0, 12.0, 13.0, 14.0])
    _write_cache(tmp_path, "BBB", days, [1.0, 1.0, 1.0, 1.0, 1.0])
    rep2 = matrix.update_matrices(["AAA.US", "BBB.US"], root=tmp_path)
    m2 = matrix.load_matrices(root=tmp_path)
    assert m2["adj_close"].shape == (5, 2)
    assert m2["adj_close"]["AAA.US"].tolist() == pytest.approx([5, 5.5, 6, 6.5, 7])
    assert rep2.appended_rows == 2 + 5


# --- the Factors page (bt) fills after the selection date ------------------------


def test_factor_portfolio_trades_after_the_selection_date() -> None:
    """``backtest_portfolio`` rebalances on the first trading day of the next month, using the
    month-end selection carried forward — a fill *after* the signal bar, never on it.

    Canary: A is selected at the Feb month-end and jumps +50% on the next trading day's close.
    A same-bar (month-end close) fill would hold A through the jump; the real engine buys A at
    the post-jump close and earns nothing.
    """
    days = pd.bdate_range("2024-01-01", "2024-03-29")
    a = pd.Series(10.0, index=days)
    a[a.index > pd.Timestamp("2024-02-29")] = 15.0  # jump on 2024-03-01, the day after selection
    prices = pd.DataFrame({"A.US": a, "B.US": 10.0})
    jan_end, feb_end = pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")
    panel = pd.DataFrame(
        [
            {"date": jan_end, "symbol": "A.US", "composite_score": 0.0},
            {"date": jan_end, "symbol": "B.US", "composite_score": 1.0},
            {"date": feb_end, "symbol": "A.US", "composite_score": 1.0},
            {"date": feb_end, "symbol": "B.US", "composite_score": 0.0},
        ]
    )
    res = backtest_portfolio(prices, panel, n=1, commission_bps=0.0)
    assert res.equity["factor_topN"].iloc[-1] == pytest.approx(1.0)
