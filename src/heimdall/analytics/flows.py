"""TW market-wide money-flow aggregation (roadmap 15.2) — descriptive lens, NOT a signal.

Turns the daily per-symbol chip cache (``research.flows_cache``) into "where did TW
money go" views: market-wide net-buy by investor type, a by-sector rollup, top-N
net-buy/-sell rankings by NT$ value, 投信 (trust) streak ranking, and foreign
holding-ratio Δ ranking. Pure pandas — reads canonical data passed in, never a
provider; no LLM is involved; Today's Picks never imports this.
"""

from __future__ import annotations

import pandas as pd

_TYPE_COLS: dict[str, str] = {
    "foreign": "foreign_net_shares",
    "trust": "trust_net_shares",
    "dealer": "dealer_net_shares",
}


def _ntd(days: pd.DataFrame, col: str) -> pd.Series:
    """Net shares × close, NaN-safe (a symbol/day missing either leg contributes 0
    via pandas' default skipna sum downstream, never poisoning the whole total)."""
    return days[col] * days["close"]


def market_totals(days: pd.DataFrame) -> dict[str, float]:
    """Market-wide net-buy in NT$ per investor type, summed over every symbol/day
    in ``days`` (a concatenation of the daily per-symbol cache over one window)."""
    if days.empty:
        return dict.fromkeys(_TYPE_COLS, float("nan"))
    return {key: float(_ntd(days, col).sum()) for key, col in _TYPE_COLS.items()}


def sector_rollup(days: pd.DataFrame) -> pd.DataFrame:
    """Sum foreign/trust/dealer net-buy (NT$) per sector over the window, sorted by
    foreign net-buy descending (foreign flow is the most-watched of the three)."""
    cols = ["sector", "foreign_ntd", "trust_ntd", "dealer_ntd"]
    if days.empty or "sector" not in days.columns:
        return pd.DataFrame(columns=cols)
    d = days.assign(
        foreign_ntd=_ntd(days, "foreign_net_shares"),
        trust_ntd=_ntd(days, "trust_net_shares"),
        dealer_ntd=_ntd(days, "dealer_net_shares"),
    )
    out = d.groupby("sector")[["foreign_ntd", "trust_ntd", "dealer_ntd"]].sum().reset_index()
    return out.sort_values("foreign_ntd", ascending=False).reset_index(drop=True)[cols]


def top_net_buy_sell(days: pd.DataFrame, investor_type: str, n: int = 10) -> pd.DataFrame:
    """Top-``n`` net buyers and top-``n`` net sellers (by NT$, summed over the
    window) for one investor type ("foreign" | "trust" | "dealer"). Returns
    ``[symbol, ntd, side]`` with ``side`` in {"buy", "sell"}, buyers first.
    """
    cols = ["symbol", "ntd", "side"]
    col = _TYPE_COLS.get(investor_type)
    if days.empty or col is None:
        return pd.DataFrame(columns=cols)
    ntd = days.assign(_ntd=_ntd(days, col)).groupby("symbol")["_ntd"].sum()
    buyers = ntd.sort_values(ascending=False).head(n)
    sellers = ntd.sort_values(ascending=True).head(n)
    return pd.DataFrame(
        {
            "symbol": [*buyers.index, *sellers.index],
            "ntd": [*buyers.to_numpy(), *sellers.to_numpy()],
            "side": ["buy"] * len(buyers) + ["sell"] * len(sellers),
        }
    )[cols]


def trust_streak(days: pd.DataFrame) -> pd.DataFrame:
    """Per symbol, the current consecutive-day streak of 投信 (trust) net buying
    or net selling, ending on that symbol's latest available date in ``days``.
    "主動資金代理" — the active-money proxy the user chose over per-ETF PCF
    scraping. Returns ``[symbol, streak_days, direction]``, longest streak
    first (``direction`` in {"buy", "sell", "flat"}; "flat" means the latest
    day is exactly zero or missing, so ``streak_days`` is 0).
    """
    cols = ["symbol", "streak_days", "direction"]
    if days.empty:
        return pd.DataFrame(columns=cols)
    rows: list[dict[str, object]] = []
    for symbol, grp in days.sort_values("date").groupby("symbol"):
        series = grp["trust_net_shares"].dropna()
        if series.empty:
            continue
        latest = float(series.iloc[-1])
        if latest == 0:
            rows.append({"symbol": symbol, "streak_days": 0, "direction": "flat"})
            continue
        latest_sign = 1 if latest > 0 else -1
        streak = 0
        for v in series.iloc[::-1]:  # walk backward from the latest day
            sign = 1 if v > 0 else (-1 if v < 0 else 0)
            if sign != latest_sign:
                break
            streak += 1
        rows.append(
            {
                "symbol": symbol,
                "streak_days": streak,
                "direction": "buy" if latest_sign > 0 else "sell",
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("streak_days", ascending=False).reset_index(drop=True)


def holding_ratio_delta(days: pd.DataFrame) -> pd.DataFrame:
    """Per symbol, Δ in ``foreign_hold_ratio`` (percentage points) between the
    window's first and last *available* date — needs at least two observations.
    Returns ``[symbol, delta_pp]``, largest increase first.
    """
    cols = ["symbol", "delta_pp"]
    if days.empty:
        return pd.DataFrame(columns=cols)
    rows: list[dict[str, object]] = []
    for symbol, grp in days.sort_values("date").groupby("symbol"):
        ratio = grp["foreign_hold_ratio"].dropna()
        if len(ratio) < 2:
            continue
        rows.append({"symbol": symbol, "delta_pp": float(ratio.iloc[-1] - ratio.iloc[0])})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("delta_pp", ascending=False).reset_index(drop=True)
