"""Goldman fundamental dashboard — a computed payload from canonical fundamentals.

Multi-year revenue/margin/FCF history, a valuation snapshot, a transparent
rating heuristic, bull/bear bullets, and illustrative PE-band scenarios. Provider-
agnostic: it reads the canonical tidy-long fundamentals (EDGAR today, FMP later).
Pure computation — the optional ``personas`` layer renders the prose report.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_NAN = float("nan")


@dataclass(frozen=True)
class FundamentalReport:
    symbol: str
    history: pd.DataFrame  # fiscal_end-indexed: revenue, margins, fcf, roe, debt_to_equity
    valuation: dict[str, float]  # pe, ps, fcf_yield, market_cap
    growth: dict[str, float]  # revenue_cagr, latest_revenue_growth
    rating: str  # Buy / Hold / Sell
    rating_score: float  # 0–100
    bull: list[str]
    bear: list[str]
    scenarios: dict[str, float]  # bear / base / bull price


def _f(series: pd.Series, key: str) -> float:
    v = series.get(key)
    return float(v) if v is not None and pd.notna(v) else _NAN


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x)) if pd.notna(x) else _NAN


def _annual_frame(fund: pd.DataFrame) -> pd.DataFrame:
    """Pivot annual fundamentals to fiscal_end × metric (latest filing per period)."""
    annual = fund[fund["period"] == "annual"]
    if annual.empty:
        return pd.DataFrame()
    latest = annual.sort_values("filed_at").groupby(["fiscal_end", "metric"]).tail(1)
    piv = latest.pivot_table(index="fiscal_end", columns="metric", values="value").sort_index()

    if "revenue" in piv:
        for margin, num in [
            ("gross_margin", "gross_profit"),
            ("operating_margin", "operating_income"),
            ("net_margin", "net_income"),
        ]:
            if num in piv:
                piv[margin] = piv[num] / piv["revenue"]
    if {"cfo", "capex"} <= set(piv.columns):
        piv["fcf"] = piv["cfo"] - piv["capex"]
    if {"net_income", "equity"} <= set(piv.columns):
        piv["roe"] = piv["net_income"] / piv["equity"]
    if {"liabilities", "equity"} <= set(piv.columns):
        piv["debt_to_equity"] = piv["liabilities"] / piv["equity"]
    return piv


def _rating(latest: pd.Series, pe: float, cagr: float, fcf: float) -> tuple[float, list[str]]:
    parts: list[float] = []
    if pd.notna(_f(latest, "net_margin")):
        parts.append(_clip01(_f(latest, "net_margin") / 0.20))
    if pd.notna(cagr):
        parts.append(_clip01(cagr / 0.15))
    if pd.notna(_f(latest, "debt_to_equity")):
        parts.append(_clip01(1.0 - _f(latest, "debt_to_equity") / 3.0))
    if pd.notna(fcf):
        parts.append(1.0 if fcf > 0 else 0.0)
    if pd.notna(pe) and pe > 0:
        parts.append(_clip01((40.0 - pe) / 30.0))
    score = 100.0 * (sum(parts) / len(parts)) if parts else _NAN
    return score, []


def _bull_bear(
    latest: pd.Series, pe: float, cagr: float, fcf: float
) -> tuple[list[str], list[str]]:
    bull, bear = [], []
    nm, de, roe = _f(latest, "net_margin"), _f(latest, "debt_to_equity"), _f(latest, "roe")
    if nm > 0.15:
        bull.append(f"High net margin ({nm:.0%})")
    if cagr > 0.10:
        bull.append(f"Double-digit revenue CAGR ({cagr:.0%})")
    if fcf > 0:
        bull.append("Positive free cash flow")
    if roe > 0.20:
        bull.append(f"Strong ROE ({roe:.0%})")
    if de > 2.0:
        bear.append(f"Elevated leverage (liabilities/equity {de:.1f}×)")
    if pd.notna(pe) and pe > 35:
        bear.append(f"Rich valuation (P/E {pe:.0f})")
    if pd.notna(fcf) and fcf < 0:
        bear.append("Negative free cash flow")
    if nm < 0.05 and pd.notna(nm):
        bear.append(f"Thin net margin ({nm:.0%})")
    return bull, bear


def fundamental_report(symbol: str, fund: pd.DataFrame, price: float) -> FundamentalReport:
    """Compute the fundamental dashboard payload for ``symbol``."""
    hist = _annual_frame(fund)
    empty = FundamentalReport(symbol, hist, {}, {}, "n/a", _NAN, [], [], {})
    if hist.empty:
        return empty

    latest = hist.iloc[-1]
    shares, revenue, net_income = (
        _f(latest, "shares_outstanding"),
        _f(latest, "revenue"),
        _f(latest, "net_income"),
    )
    fcf, eps = _f(latest, "fcf"), _f(latest, "eps_diluted")
    market_cap = price * shares

    pe = market_cap / net_income if net_income > 0 else _NAN
    valuation = {
        "market_cap": market_cap,
        "pe": pe,
        "ps": market_cap / revenue if revenue > 0 else _NAN,
        "fcf_yield": fcf / market_cap if market_cap > 0 else _NAN,
    }

    revs = hist["revenue"].dropna() if "revenue" in hist else pd.Series(dtype="float64")
    n = len(revs)
    cagr = (
        (revs.iloc[-1] / revs.iloc[0]) ** (1 / (n - 1)) - 1 if n >= 2 and revs.iloc[0] > 0 else _NAN
    )
    growth = {
        "revenue_cagr": cagr,
        "latest_revenue_growth": revs.iloc[-1] / revs.iloc[-2] - 1 if n >= 2 else _NAN,
    }

    score, _ = _rating(latest, pe, cagr, fcf)
    rating = (
        "Buy" if score >= 66 else "Hold" if score >= 40 else "Sell" if pd.notna(score) else "n/a"
    )
    bull, bear = _bull_bear(latest, pe, cagr, fcf)
    scenarios = (
        {"bear": 15 * eps, "base": 22 * eps, "bull": 30 * eps}
        if pd.notna(eps) and eps > 0
        else {"bear": price * 0.8, "base": price, "bull": price * 1.25}
    )

    return FundamentalReport(symbol, hist, valuation, growth, rating, score, bull, bear, scenarios)
