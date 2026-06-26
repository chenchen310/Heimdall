"""The most important test in the repo: a hand-verifiable backtest that locks
down look-ahead behavior. A signal from bar t's close must execute at bar t+1's
OPEN — never the signal bar's own price — and costs must reduce performance.

See ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from stockobserver.backtest.costs import DEFAULT_COSTS, ZERO_COSTS
from stockobserver.backtest.engine import run_backtest
from stockobserver.backtest.signals import sma_crossover_signals


def _fixture() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    # 10 business days; a clean up-then-down move gives one entry and one exit.
    dates = pd.bdate_range("2024-01-01", periods=10)
    close = pd.Series([10, 10, 10, 10, 12, 13, 14, 13, 11, 10], index=dates, dtype=float)
    open_ = close - 0.5  # distinct from close so the fill bar is identifiable
    ohlcv = pd.DataFrame({"date": dates, "open": open_.to_numpy(), "adj_close": close.to_numpy()})
    entries, exits = sma_crossover_signals(close, fast=2, slow=3)
    return ohlcv, entries, exits


def test_signals_fire_on_expected_bars() -> None:
    _, entries, exits = _fixture()
    assert [d.date() for d in entries[entries].index] == [date(2024, 1, 5)]
    assert [d.date() for d in exits[exits].index] == [date(2024, 1, 11)]


def test_fills_on_next_bar_open_not_signal_bar() -> None:
    ohlcv, entries, exits = _fixture()
    pf = run_backtest(ohlcv, entries, exits, costs=ZERO_COSTS)
    trade = pf.trades.records_readable.iloc[0]

    # entry signal is 2024-01-05 → fill at 2024-01-08 open (12.5), NOT the 05 bar
    assert pd.Timestamp(trade["Entry Timestamp"]).date() == date(2024, 1, 8)
    assert pd.Timestamp(trade["Entry Timestamp"]).date() != date(2024, 1, 5)
    assert trade["Avg Entry Price"] == pytest.approx(12.5)

    # exit signal 2024-01-11 → fill at 2024-01-12 open (9.5)
    assert pd.Timestamp(trade["Exit Timestamp"]).date() == date(2024, 1, 12)
    assert trade["Avg Exit Price"] == pytest.approx(9.5)


def test_costs_reduce_performance() -> None:
    ohlcv, entries, exits = _fixture()
    zero = run_backtest(ohlcv, entries, exits, costs=ZERO_COSTS)
    costed = run_backtest(ohlcv, entries, exits, costs=DEFAULT_COSTS)

    total_zero = float((1 + zero.returns()).prod())
    total_costed = float((1 + costed.returns()).prod())
    assert total_costed < total_zero  # frictions always cost something

    fees = costed.trades.records_readable
    assert (fees["Entry Fees"] + fees["Exit Fees"]).sum() > 0
    assert zero.trades.records_readable["Entry Fees"].sum() == pytest.approx(0.0)
