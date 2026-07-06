"""Benchmark map + the forward-return primitive behind every label.

One sanctioned place answering "which benchmark, and what did it return over my
window". Both a stock and its benchmark are labelled through the same
:func:`forward_return`, which is what guarantees the two legs of a ``*_rel``
label cover identical calendar windows (``docs/RESEARCH_PLAYBOOK.md`` §2).

Pure functions only — callers fetch and pass series in; nothing here touches a
provider or the network.
"""

from __future__ import annotations

import pandas as pd

# Region (``Symbol.region``) → benchmark symbol, per the frozen decisions in
# docs/NORTH_STAR.md: success is measured against the market you could have
# bought instead. Extend only alongside MARKET_REGION in data/symbols.py.
BENCHMARK: dict[str, str] = {
    "US": "SPY.US",
    "Taiwan": "0050.TW",
}


def forward_return(adj: pd.Series, start: pd.Timestamp, bars: int) -> float:
    """Total return over ``bars`` trading bars, entering at the first bar ≥ ``start``.

    ``adj`` is a date-indexed, ascending adjusted-close series. Entry is the
    close of the first bar on/after ``start`` (a weekend/holiday ``start``
    aligns forward); exit is the close ``bars`` bars later. Returns NaN when
    there is no bar ≥ ``start`` or the forward window is incomplete — a partial
    window must never yield a partial return (playbook §2). A NaN entry/exit
    price propagates to NaN rather than being skipped over.
    """
    if not adj.index.is_monotonic_increasing:
        raise ValueError("adjusted-close series must be sorted ascending by date")
    i = int(adj.index.searchsorted(pd.Timestamp(start)))
    j = i + bars
    if j >= len(adj):
        return float("nan")
    entry, exit_ = float(adj.iloc[i]), float(adj.iloc[j])
    return exit_ / entry - 1.0 if entry > 0 else float("nan")
