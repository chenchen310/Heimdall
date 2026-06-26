"""Reporting — quantstats tear sheets from a vectorbt portfolio.

Pairs point estimates with drawdown/Monte-Carlo context. Treat all output as an
optimistic upper bound (``.claude/rules/backtest-honesty.md``).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import quantstats as qs
import vectorbt as vbt


def daily_returns(pf: vbt.Portfolio) -> pd.Series:
    """Portfolio daily returns as a datetime-indexed Series."""
    r = pf.returns()
    if isinstance(r, pd.DataFrame):
        r = r.iloc[:, 0]
    r = r.copy()
    r.index = pd.to_datetime(r.index)
    return cast("pd.Series", r)


def tear_sheet(
    pf: vbt.Portfolio, output: str | Path, title: str = "Stock Observer strategy"
) -> Path:
    """Write a full quantstats HTML tear sheet; return the path."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(daily_returns(pf), output=str(out), title=title)
    return out
