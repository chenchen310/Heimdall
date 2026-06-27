"""Reporting — quantstats tear sheets from a vectorbt portfolio.

Pairs point estimates with drawdown/Monte-Carlo context. Treat all output as an
optimistic upper bound (``.claude/rules/backtest-honesty.md``).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import cast

import pandas as pd
import quantstats as qs
import vectorbt as vbt

_TRADING_DAYS = 252


def daily_returns(pf: vbt.Portfolio) -> pd.Series:
    """Portfolio daily returns as a datetime-indexed Series."""
    r = pf.returns()
    if isinstance(r, pd.DataFrame):
        r = r.iloc[:, 0]
    r = r.copy()
    r.index = pd.to_datetime(r.index)
    return cast("pd.Series", r)


def equity_curve(pf: vbt.Portfolio) -> pd.Series:
    """Cumulative growth of $1 (computed from returns, so it's engine-agnostic)."""
    return (1.0 + daily_returns(pf)).cumprod()


def drawdown_series(pf: vbt.Portfolio) -> pd.Series:
    eq = equity_curve(pf)
    return eq / eq.cummax() - 1.0


def quick_metrics(pf: vbt.Portfolio) -> dict[str, float]:
    """Cheap headline metrics from the return stream — fast enough for sweeps."""
    r = daily_returns(pf)
    n = int(r.shape[0])
    if n == 0:
        return {
            "total_return": 0.0,
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "max_drawdown": float("nan"),
            "n_trades": 0,
        }
    eq = (1.0 + r).cumprod()
    final = float(eq.iloc[-1])
    years = n / _TRADING_DAYS
    vol = float(r.std())
    return {
        "total_return": final - 1.0,
        "cagr": final ** (1 / years) - 1.0 if years > 0 and final > 0 else float("nan"),
        "sharpe": float(r.mean()) / vol * math.sqrt(_TRADING_DAYS) if vol > 0 else float("nan"),
        "max_drawdown": float((eq / eq.cummax() - 1.0).min()),
        "n_trades": int(len(pf.trades.records_readable)),
    }


def summary_metrics(pf: vbt.Portfolio) -> dict[str, float]:
    """Headline metrics plus win rate / profit factor / Sortino for the detail view."""
    m = quick_metrics(pf)
    r = daily_returns(pf)
    trades = pf.trades.records_readable
    pnl = trades["PnL"] if "PnL" in trades else pd.Series(dtype="float64")
    gains, losses = float(pnl[pnl > 0].sum()), float(-pnl[pnl < 0].sum())
    downside = float(r[r < 0].std())
    m["win_rate"] = float((pnl > 0).mean()) if len(pnl) else float("nan")
    m["profit_factor"] = gains / losses if losses > 0 else float("nan")
    m["sortino"] = (
        float(r.mean()) / downside * math.sqrt(_TRADING_DAYS) if downside > 0 else float("nan")
    )
    return m


def tear_sheet(pf: vbt.Portfolio, output: str | Path, title: str = "Heimdall strategy") -> Path:
    """Write a full quantstats HTML tear sheet; return the path."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(daily_returns(pf), output=str(out), title=title)
    return out
