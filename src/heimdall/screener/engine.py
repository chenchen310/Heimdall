"""Screen evaluation — vectorized predicate masks over the snapshot table.

NaN handling is deliberate: a comparison against a missing metric is ``False``,
so a stock lacking (say) a P/E simply fails a ``pe < 15`` filter rather than
erroring. Missing data therefore excludes, never silently includes.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """Return the snapshot rows passing every *enabled* predicate, sorted/limited.

    A predicate with ``enabled=False`` is skipped — it stays on the screen but does
    not constrain — so the UI can toggle a criterion off to widen the result set.
    """
    mask = pd.Series(True, index=snapshot.index)
    for predicate in screen.predicates:
        if not predicate.enabled:
            continue
        mask &= _mask(snapshot, predicate)

    out = snapshot[mask]
    if screen.sort_by:
        out = out.sort_values(screen.sort_by, ascending=screen.ascending, na_position="last")
    if screen.limit is not None:
        out = out.head(screen.limit)
    return out.reset_index(drop=True)


@dataclass(frozen=True)
class FunnelStep:
    """One enabled predicate's effect, in screen order.

    ``alone`` is how many rows pass this predicate by itself; ``remaining`` is how many
    are left once it's AND-ed with every enabled predicate before it. Comparing the two
    across steps shows which condition narrowed the result the most — the thing a user
    widening a 0-match screen needs to see first.
    """

    predicate: Predicate
    alone: int
    remaining: int


def funnel(screen: Screen, snapshot: pd.DataFrame) -> list[FunnelStep]:
    """Per-condition pass counts, in screen order, for enabled predicates only.

    Disabled predicates are skipped, mirroring :func:`evaluate` — they don't constrain
    the result, so they have no cumulative effect to report.
    """
    cumulative = pd.Series(True, index=snapshot.index)
    steps = []
    for predicate in screen.predicates:
        if not predicate.enabled:
            continue
        alone_mask = _mask(snapshot, predicate)
        cumulative &= alone_mask
        steps.append(
            FunnelStep(
                predicate=predicate,
                alone=int(alone_mask.sum()),
                remaining=int(cumulative.sum()),
            )
        )
    return steps
