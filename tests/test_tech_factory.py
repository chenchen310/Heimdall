"""Technical-rule factory (roadmap 18.8) — research-only walk-forward across symbols.

Known answers on two synthetic markets (a mean-reverting oscillator where reversion rules beat
buy-and-hold, a steady trend where nothing does), point-in-time parameter choice, the trial
count behind every DSR, and the two new signal rules.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heimdall.backtest import tech_factory
from heimdall.backtest.costs import ZERO_COSTS
from heimdall.backtest.signals import bollinger_reversion_signals, macd_cross_signals
from heimdall.factors.indicators import bollinger, macd


def _ohlcv(close: np.ndarray, start: str = "2014-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(close))
    c = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "open": c.shift(1).fillna(c.iloc[0]),
            "high": c,
            "low": c,
            "close": c,
            "adj_close": c,
        }
    )


def _oscillator(n: int = 252 * 7, seed: int = 0) -> np.ndarray:
    t = np.arange(n)
    noise = np.random.default_rng(seed).normal(0, 0.4, n)
    return 100 + 8 * np.sin(2 * np.pi * t / 30) + noise


def _trend(n: int = 252 * 7, seed: int = 1) -> np.ndarray:
    rets = np.random.default_rng(seed).normal(0.0008, 0.003, n)
    return 100 * np.cumprod(1 + rets)


def test_reversion_rules_beat_buy_and_hold_on_an_oscillator() -> None:
    ohlcv = _ohlcv(_oscillator())
    for rule in ("rsi_reversion", "bollinger_reversion"):
        res = tech_factory.walk_forward_rule(ohlcv, "OSC.US", rule, costs=ZERO_COSTS)
        assert res is not None
        wf = float((1 + res.returns).prod() - 1)
        bh = float((1 + res.buy_hold).prod() - 1)
        assert wf > bh + 0.2, rule  # the oscillator has ~no drift; harvesting swings pays


def test_nothing_beats_buy_and_hold_on_a_steady_trend() -> None:
    ohlcv = _ohlcv(_trend())
    for rule in tech_factory.GRIDS:
        res = tech_factory.walk_forward_rule(ohlcv, "TRD.US", rule)
        assert res is not None
        wf = float((1 + res.returns).prod() - 1)
        bh = float((1 + res.buy_hold).prod() - 1)
        assert wf <= bh + 1e-9, rule  # timing a smooth trend only loses days and costs


def test_parameters_for_a_year_use_only_the_prior_window() -> None:
    base = _ohlcv(_oscillator())
    res = tech_factory.walk_forward_rule(base, "OSC.US", "rsi_reversion", costs=ZERO_COSTS)
    assert res is not None
    year = sorted(res.chosen)[1]
    changed = base.copy()
    late = pd.DatetimeIndex(changed["date"]).year >= year
    changed.loc[late, ["open", "close", "adj_close", "high", "low"]] *= np.linspace(
        1, 3, int(late.sum())
    )[:, None]
    res2 = tech_factory.walk_forward_rule(changed, "OSC.US", "rsi_reversion", costs=ZERO_COSTS)
    assert res2 is not None
    assert res2.chosen[year] == res.chosen[year]  # the fit window ends before the change
    assert min(res.chosen) == 2017  # 2014–2016 is the first fit window (fit_years = 3)


def test_run_counts_trials_and_deflates() -> None:
    prices = {"OSC.US": _ohlcv(_oscillator()), "TRD.US": _ohlcv(_trend())}
    res = tech_factory.run_tech_factory(prices, rules=["rsi_reversion", "sma_crossover"])
    assert res.n_trials == 2 * (
        len(tech_factory.GRIDS["rsi_reversion"]) + len(tech_factory.GRIDS["sma_crossover"])
    )
    assert set(res.per_pair["rule"]) == {"rsi_reversion", "sma_crossover"}
    assert {"dsr", "excess_cagr", "wf_sharpe", "bh_sharpe"} <= set(res.per_pair.columns)
    assert {"pct_beating_buy_hold", "pct_dsr_pass", "median_excess_cagr"} <= set(
        res.per_rule.columns
    )
    assert "不在認證範圍" in res.label and res.notes[0] == res.label


def test_macd_cross_signals_are_genuine_crossings() -> None:
    close = pd.Series(_oscillator(400), dtype=float)
    entries, exits = macd_cross_signals(close, 12, 26, 9)
    line, sig, _ = macd(close, 12, 26, 9)
    assert entries.any() and exits.any()
    for i in np.flatnonzero(entries.to_numpy()):
        assert line.iloc[i] > sig.iloc[i] and line.iloc[i - 1] <= sig.iloc[i - 1]
    with pytest.raises(ValueError):
        macd_cross_signals(close, 26, 12, 9)


def test_bollinger_reversion_signals_are_genuine_crossings() -> None:
    close = pd.Series(_oscillator(400), dtype=float)
    entries, exits = bollinger_reversion_signals(close, 20, 2.0)
    _, mid, lower = bollinger(close, 20, 2.0)
    assert entries.any() and exits.any()
    for i in np.flatnonzero(entries.to_numpy()):
        assert close.iloc[i] < lower.iloc[i] and close.iloc[i - 1] >= lower.iloc[i - 1]
    for i in np.flatnonzero(exits.to_numpy()):
        assert close.iloc[i] > mid.iloc[i] and close.iloc[i - 1] <= mid.iloc[i - 1]
