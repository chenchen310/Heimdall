"""Two Sigma macro outlook — key FRED indicators and a rough regime read.

Pulls a handful of macro series, computes the latest level and its 12-month
change, and derives plain-language signals (yield-curve inversion, hot inflation,
rising unemployment, restrictive policy). Needs ``FRED_API_KEY`` (the provider
raises ``NotSupported`` without it). The regime label is a heuristic, not a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from heimdall.data.base import MacroProvider

# series_id -> label. CPI/GDP are index levels (YoY %); the rest are rates (pp change).
KEY_SERIES: dict[str, str] = {
    "CPIAUCSL": "CPI (inflation index)",
    "UNRATE": "Unemployment rate (%)",
    "FEDFUNDS": "Fed funds rate (%)",
    "T10Y2Y": "10Y–2Y spread (pp)",
    "DGS10": "10-Year Treasury yield (%)",
    "GDPC1": "Real GDP (index)",
}
_PERCENT_SERIES = {"CPIAUCSL", "GDPC1"}  # report change as a YoY %


@dataclass(frozen=True)
class MacroIndicator:
    series_id: str
    label: str
    latest: float
    change_yoy: float  # YoY % for index series, else level change in percentage points
    as_of: pd.Timestamp


@dataclass(frozen=True)
class MacroReport:
    indicators: list[MacroIndicator]
    signals: list[str]
    regime: str


def macro_dashboard(macro: MacroProvider, lookback_years: int = 3) -> MacroReport:
    end = date.today()
    start = end - timedelta(days=365 * lookback_years + 60)
    cutoff = pd.Timestamp(end) - pd.DateOffset(years=1)
    indicators: list[MacroIndicator] = []
    latest_by_id: dict[str, float] = {}

    for sid, label in KEY_SERIES.items():
        df = macro.get_series(sid, start, end)
        if df.empty:
            continue
        df = df.sort_values("date")
        latest = float(df["value"].iloc[-1])
        prior = df[df["date"] <= cutoff]
        prior_val = float(prior["value"].iloc[-1]) if not prior.empty else float("nan")
        if sid in _PERCENT_SERIES:
            change = latest / prior_val - 1.0 if prior_val and prior_val > 0 else float("nan")
        else:
            change = latest - prior_val
        indicators.append(MacroIndicator(sid, label, latest, change, df["date"].iloc[-1]))
        latest_by_id[sid] = latest

    signals = _signals(latest_by_id, indicators)
    return MacroReport(
        indicators=indicators, signals=signals, regime=_regime(latest_by_id, signals)
    )


def _signals(latest: dict[str, float], indicators: list[MacroIndicator]) -> list[str]:
    out: list[str] = []
    change = {i.series_id: i.change_yoy for i in indicators}
    if latest.get("T10Y2Y", 1.0) < 0:
        out.append(
            f"Yield curve inverted (10Y–2Y = {latest['T10Y2Y']:.2f}) — elevated recession risk"
        )
    cpi = change.get("CPIAUCSL")
    if cpi is not None and pd.notna(cpi) and cpi > 0.03:
        out.append(f"Inflation running hot (CPI YoY {cpi:.1%})")
    unrate_chg = change.get("UNRATE")
    if unrate_chg is not None and pd.notna(unrate_chg) and unrate_chg > 0.3:
        out.append(f"Unemployment rising (+{unrate_chg:.1f}pp YoY) — slowing labor market")
    if latest.get("FEDFUNDS", 0.0) > 4.0:
        out.append(f"Restrictive policy (fed funds {latest['FEDFUNDS']:.2f}%)")
    return out


def _regime(latest: dict[str, float], signals: list[str]) -> str:
    inverted = latest.get("T10Y2Y", 1.0) < 0
    restrictive = latest.get("FEDFUNDS", 0.0) > 4.0
    if inverted and restrictive:
        return "Late cycle / slowdown risk"
    if not inverted and not restrictive:
        return "Expansion / accommodative"
    return "Mixed signals"
