"""Screen evaluation — vectorized predicate masks over the snapshot table.

NaN handling is deliberate: a comparison against a missing metric is ``False``,
so a stock lacking (say) a P/E simply fails a ``pe < 15`` filter rather than
erroring. Missing data therefore excludes, never silently includes.
"""

from __future__ import annotations

from typing import cast

import pandas as pd

from heimdall.screener.model import Predicate, Screen


def _mask(df: pd.DataFrame, p: Predicate) -> pd.Series:
    if p.field not in df.columns:
        raise KeyError(f"screen field {p.field!r} not in snapshot columns; have {list(df.columns)}")
    col, v = df[p.field], p.value

    if p.op == "in":
        return col.isin(v)
    if p.op == "notna":
        return col.notna()

    if p.op == "<":
        m = col < v
    elif p.op == "<=":
        m = col <= v
    elif p.op == ">":
        m = col > v
    elif p.op == ">=":
        m = col >= v
    elif p.op == "==":
        m = col == v
    elif p.op == "!=":
        m = col != v
    elif p.op == "between":
        m = col.between(v[0], v[1])
    else:  # pragma: no cover - operators are validated on the model
        raise ValueError(f"unhandled operator {p.op!r}")
    return cast("pd.Series", m.fillna(False).astype(bool))


def evaluate(screen: Screen, snapshot: pd.DataFrame) -> pd.DataFrame:
    """Return the snapshot rows passing every predicate, sorted/limited per the screen."""
    mask = pd.Series(True, index=snapshot.index)
    for predicate in screen.predicates:
        mask &= _mask(snapshot, predicate)

    out = snapshot[mask]
    if screen.sort_by:
        out = out.sort_values(screen.sort_by, ascending=screen.ascending, na_position="last")
    if screen.limit is not None:
        out = out.head(screen.limit)
    return out.reset_index(drop=True)
