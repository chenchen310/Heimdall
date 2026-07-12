"""TW big-holder (大戶) concentration aggregation (roadmap 15.3) — descriptive
lens, NOT a signal.

Turns TDCC's accumulated weekly cache (``data.providers.tdcc.load_cached_weeks``)
into "who's accumulating/distributing" views on its honest **weekly** cadence —
never interpolated to daily. Pure pandas — reads canonical data passed in, never
a provider; no LLM is involved; Today's Picks never imports this.
"""

from __future__ import annotations

import pandas as pd

from heimdall.data.providers.tdcc import BIG_HOLDER_LEVELS

BIG_HOLDER_PCT_COLUMNS: list[str] = ["symbol", "data_date", "available_at", "big_holder_pct"]
_RANKING_COLUMNS: list[str] = ["symbol", "delta_pp", "latest_pct"]


def big_holder_pct(tdcc_weeks: pd.DataFrame) -> pd.DataFrame:
    """Per (symbol, data_date), the summed ≥400-lot (大戶) share of TDCC custody.

    ``tdcc_weeks`` is ``data.providers.tdcc.load_cached_weeks()`` output (every
    accumulated weekly file, all symbols, concatenated). Returns
    ``[symbol, data_date, available_at, big_holder_pct]``, one row per available
    week per symbol.
    """
    if tdcc_weeks.empty:
        return pd.DataFrame(columns=BIG_HOLDER_PCT_COLUMNS)
    big = tdcc_weeks[tdcc_weeks["level"].isin(BIG_HOLDER_LEVELS)]
    out = (
        big.groupby(["symbol", "data_date", "available_at"])["pct_of_custody"]
        .sum()
        .reset_index()
        .rename(columns={"pct_of_custody": "big_holder_pct"})
    )
    return out.sort_values(["symbol", "data_date"]).reset_index(drop=True)[BIG_HOLDER_PCT_COLUMNS]


def weekly_delta_ranking(
    tdcc_weeks: pd.DataFrame, as_of: pd.Timestamp, n_weeks: int = 4
) -> pd.DataFrame:
    """Per symbol: Δ in big-holder % from the oldest to the newest of the last
    ``n_weeks`` *available* weekly files (available_at ≤ ``as_of``). Mirrors
    ``research.dataset._big_holder_features``'s exact windowing so the page and
    the panel feature always agree. Returns ``[symbol, delta_pp, latest_pct]``,
    sorted by ``delta_pp`` descending (risers first, fallers last).
    """
    pct = big_holder_pct(tdcc_weeks)
    if pct.empty:
        return pd.DataFrame(columns=_RANKING_COLUMNS)
    known = pct[pct["available_at"] <= as_of]
    rows: list[dict[str, object]] = []
    for symbol, grp in known.groupby("symbol"):
        if len(grp) < n_weeks:
            continue
        last_n = grp.tail(n_weeks)
        rows.append(
            {
                "symbol": symbol,
                "delta_pp": float(
                    last_n["big_holder_pct"].iloc[-1] - last_n["big_holder_pct"].iloc[0]
                ),
                "latest_pct": float(last_n["big_holder_pct"].iloc[-1]),
            }
        )
    out = pd.DataFrame(rows, columns=_RANKING_COLUMNS)
    return out.sort_values("delta_pp", ascending=False).reset_index(drop=True)


def monthly_delta_ranking(tdcc_weeks: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per symbol: change in *mean* big-holder % between the last 4 available
    weekly files and the prior 4 (8 weeks total needed) — "trailing 4 files vs
    the prior 4", per the card (a coarser, less noisy view than the weekly
    single-to-single delta). Returns ``[symbol, delta_pp, latest_pct]``, sorted
    with the largest increase first.
    """
    pct = big_holder_pct(tdcc_weeks)
    if pct.empty:
        return pd.DataFrame(columns=_RANKING_COLUMNS)
    known = pct[pct["available_at"] <= as_of]
    rows: list[dict[str, object]] = []
    for symbol, grp in known.groupby("symbol"):
        if len(grp) < 8:
            continue
        last8 = grp.tail(8)["big_holder_pct"]
        recent4, prior4 = float(last8.tail(4).mean()), float(last8.head(4).mean())
        rows.append(
            {"symbol": symbol, "delta_pp": recent4 - prior4, "latest_pct": float(last8.iloc[-1])}
        )
    out = pd.DataFrame(rows, columns=_RANKING_COLUMNS)
    return out.sort_values("delta_pp", ascending=False).reset_index(drop=True)


def symbol_history(tdcc_weeks: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """One symbol's full big-holder-% weekly time series, ascending by date —
    the per-symbol chips-dashboard overlay (roadmap 15.3 step 2). Returns
    ``[data_date, big_holder_pct]``; never interpolated, callers plot discrete
    weekly points only.
    """
    pct = big_holder_pct(tdcc_weeks)
    mine = pct[pct["symbol"] == symbol]
    return mine[["data_date", "big_holder_pct"]].reset_index(drop=True)
