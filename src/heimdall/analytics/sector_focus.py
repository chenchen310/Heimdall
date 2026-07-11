"""Sector-focus aggregation (roadmap 14.2) — descriptive lens, NOT a signal.

Turns a snapshot (with its 14.1 ``sector`` column) plus recent price history into the
daily/weekly/monthly "which industries lead, and who inside them" view. Pure pandas —
reads canonical data passed in, never a provider; no LLM is involved; Today's Picks
never imports this.
"""

from __future__ import annotations

import pandas as pd

SECTOR_TABLE_COLUMNS: list[str] = [
    "sector",
    "n_members",
    "n_priced",
    "ret",
    "ret_vs_benchmark",
    "breadth",
]


def trailing_return(adj: pd.Series, window: int) -> float:
    """Total return over the last ``window`` trading bars of a date-sorted,
    ascending adjusted-close series. NaN if fewer than ``window + 1`` bars (not
    enough history to span the window) or a non-positive entry price.
    """
    if len(adj) < window + 1:
        return float("nan")
    entry, exit_ = float(adj.iloc[-1 - window]), float(adj.iloc[-1])
    return exit_ / entry - 1.0 if entry > 0 else float("nan")


def sector_table(
    snapshot: pd.DataFrame, member_returns: dict[str, float], benchmark_return: float
) -> pd.DataFrame:
    """One row per sector: equal-weight window return, vs-benchmark, breadth.

    ``member_returns`` is ``{symbol: trailing_return}``; a symbol absent from it
    (or NaN) still counts toward ``n_members`` but not ``n_priced``/``ret`` — a
    member the market simply has no fresh price for doesn't silently vanish
    from the roster, it just doesn't move the sector's return. ``breadth`` is
    the share of *priced* members with ``pct_above_sma_200 > 0`` (from the
    snapshot). Sorted by ``ret_vs_benchmark`` descending — the "which
    industries lead" ranking this page exists for.
    """
    if snapshot.empty or "sector" not in snapshot.columns:
        return pd.DataFrame(columns=SECTOR_TABLE_COLUMNS)
    rows: list[dict[str, object]] = []
    for sector, grp in snapshot.groupby("sector"):
        rets = grp["symbol"].map(member_returns)
        priced = rets.dropna()
        mean_ret = float(priced.mean()) if len(priced) else float("nan")
        if "pct_above_sma_200" in grp.columns:
            breadth_pool = grp.loc[rets.notna(), "pct_above_sma_200"]
            breadth = float((breadth_pool > 0).mean()) if len(breadth_pool) else float("nan")
        else:
            breadth = float("nan")
        rows.append(
            {
                "sector": sector,
                "n_members": len(grp),
                "n_priced": len(priced),
                "ret": mean_ret,
                "ret_vs_benchmark": mean_ret - benchmark_return,
                "breadth": breadth,
            }
        )
    out = pd.DataFrame(rows, columns=SECTOR_TABLE_COLUMNS)
    return out.sort_values("ret_vs_benchmark", ascending=False, na_position="last").reset_index(
        drop=True
    )


def member_table(
    snapshot: pd.DataFrame, member_returns: dict[str, float], sector: str
) -> pd.DataFrame:
    """Drill-down: one sector's members ranked by window return, with relative
    strength against the sector's own equal-weight mean (``rs_vs_sector`` —
    positive means this name led its sector over the window)."""
    grp = snapshot.loc[snapshot["sector"] == sector, ["symbol"]].copy()
    grp["ret"] = grp["symbol"].map(member_returns)
    mean_ret = float(grp["ret"].dropna().mean()) if grp["ret"].notna().any() else float("nan")
    grp["rs_vs_sector"] = grp["ret"] - mean_ret
    return grp.sort_values("ret", ascending=False, na_position="last").reset_index(drop=True)
