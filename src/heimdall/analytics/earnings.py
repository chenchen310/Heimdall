"""JPM earnings module — surprise history, beat rate, and next-quarter consensus.

Consumes the canonical earnings frame (estimates vs actuals). Consensus estimates
are genuinely paid data, so the live path is gated on FMP (``FMP_API_KEY``); this
module is provider-agnostic and computes the decision summary from whatever frame
it is given. Options-implied vol needs an options feed and is out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class EarningsReport:
    symbol: str
    next_date: pd.Timestamp | None
    next_eps_estimate: float
    next_revenue_estimate: float
    beat_rate: float  # share of past quarters EPS beat estimate
    avg_surprise: float  # mean EPS surprise % (last ~8)
    recent: pd.DataFrame  # date, eps_actual, eps_estimate, surprise (last ~6)


def earnings_report(symbol: str, earnings: pd.DataFrame) -> EarningsReport:
    """Compute the earnings decision summary from a canonical earnings frame."""
    empty = EarningsReport(
        symbol, None, float("nan"), float("nan"), float("nan"), float("nan"), pd.DataFrame()
    )
    if earnings.empty:
        return empty
    df = earnings.copy()
    df["date"] = pd.to_datetime(df["date"])

    past = df[(~df["is_future"]) & df["eps_actual"].notna() & df["eps_estimate"].notna()]
    past = past.sort_values("date").copy()
    if not past.empty:
        past["surprise"] = (past["eps_actual"] - past["eps_estimate"]) / past["eps_estimate"].abs()
    beat_rate = (
        float((past["eps_actual"] > past["eps_estimate"]).mean())
        if not past.empty
        else float("nan")
    )
    avg_surprise = float(past["surprise"].tail(8).mean()) if not past.empty else float("nan")

    future = df[df["is_future"]].sort_values("date")
    nxt = future.iloc[0] if not future.empty else None
    recent_cols = ["date", "eps_actual", "eps_estimate", "surprise"]
    return EarningsReport(
        symbol=symbol,
        next_date=nxt["date"] if nxt is not None else None,
        next_eps_estimate=float(nxt["eps_estimate"])
        if nxt is not None and pd.notna(nxt["eps_estimate"])
        else float("nan"),
        next_revenue_estimate=float(nxt["revenue_estimate"])
        if nxt is not None and pd.notna(nxt["revenue_estimate"])
        else float("nan"),
        beat_rate=beat_rate,
        avg_surprise=avg_surprise,
        recent=past[recent_cols].tail(6) if not past.empty else pd.DataFrame(columns=recent_cols),
    )
