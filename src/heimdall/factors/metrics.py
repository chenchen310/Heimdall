"""Per-symbol metric assembly — one row of technicals + point-in-time fundamentals.

Lives in ``factors`` (not ``screener``) because it computes indicators via
``factors.indicators``; placing it here keeps the dependency one-directional
(``screener`` → ``factors``) and lets both the snapshot builder and the factor
panel reuse the *same* computation. See ``docs/ARCHITECTURE.md`` §5–6.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from heimdall.factors.indicators import rsi, sma


def _safe_div(a: float, b: float) -> float:
    return a / b if b not in (0, 0.0) and pd.notna(a) and pd.notna(b) else float("nan")


def _latest_annual(fund: pd.DataFrame, as_of: date) -> dict[str, float]:
    """Most-recently-ended annual value per metric known on/before ``as_of``."""
    known = fund[fund["filed_at"] <= pd.Timestamp(as_of)]
    if known.empty:
        return {}
    latest = known.sort_values(["fiscal_end", "filed_at"]).groupby("metric").tail(1)
    return {str(m): float(v) for m, v in zip(latest["metric"], latest["value"], strict=True)}


def _revenue_growth_yoy(fund: pd.DataFrame, as_of: date) -> float:
    rev = fund[(fund["metric"] == "revenue") & (fund["filed_at"] <= pd.Timestamp(as_of))]
    if rev.empty:
        return float("nan")
    per_year = rev.sort_values(["fiscal_end", "filed_at"]).groupby("fiscal_end").tail(1)
    per_year = per_year.sort_values("fiscal_end")
    if len(per_year) < 2:
        return float("nan")
    return _safe_div(per_year["value"].iloc[-1], per_year["value"].iloc[-2]) - 1.0


def _technicals(ohlcv: pd.DataFrame) -> dict[str, float]:
    close = ohlcv["adj_close"].reset_index(drop=True)
    price = float(close.iloc[-1])

    def ret(n: int) -> float:
        return _safe_div(price, float(close.iloc[-1 - n])) - 1.0 if len(close) > n else float("nan")

    s200 = sma(close, 200).iloc[-1]
    return {
        "price": price,
        "sma_20": float(sma(close, 20).iloc[-1]),
        "sma_50": float(sma(close, 50).iloc[-1]),
        "sma_200": float(s200),
        "rsi_14": float(rsi(close, 14).iloc[-1]),
        "ret_3m": ret(63),
        "ret_6m": ret(126),
        "ret_12m": ret(252),
        "pct_above_sma_200": _safe_div(price, float(s200)) - 1.0,
    }


def snapshot_row(
    symbol: str, ohlcv: pd.DataFrame, fund: pd.DataFrame, as_of: date
) -> dict[str, object]:
    """One snapshot row: technicals (from ``ohlcv``) + point-in-time fundamentals.

    Reused by both the cross-section builder (``screener.snapshot``) and the
    historical factor panel (``factors.panel``) so the metrics are identical.
    """
    f = _latest_annual(fund, as_of)
    tech = _technicals(ohlcv)
    revenue, net_income = f.get("revenue", float("nan")), f.get("net_income", float("nan"))
    equity = f.get("equity", float("nan"))
    shares = f.get("shares_outstanding", float("nan"))
    fcf = f.get("cfo", float("nan")) - f.get("capex", float("nan"))
    market_cap = tech["price"] * shares if pd.notna(shares) else float("nan")

    return {
        "symbol": symbol,
        "as_of": pd.Timestamp(as_of),
        "currency": "USD",
        **tech,
        "market_cap": market_cap,
        "revenue": revenue,
        "net_income": net_income,
        "eps_diluted": f.get("eps_diluted", float("nan")),
        "equity": equity,
        "shares_outstanding": shares,
        "fcf": fcf,
        "pe": _safe_div(market_cap, net_income) if net_income > 0 else float("nan"),
        "ps": _safe_div(market_cap, revenue),
        "fcf_yield": _safe_div(fcf, market_cap),
        "net_margin": _safe_div(net_income, revenue),
        "gross_margin": _safe_div(f.get("gross_profit", float("nan")), revenue),
        "operating_margin": _safe_div(f.get("operating_income", float("nan")), revenue),
        "roe": _safe_div(net_income, equity),
        "debt_to_equity": _safe_div(f.get("liabilities", float("nan")), equity),
        "revenue_growth_yoy": _revenue_growth_yoy(fund, as_of),
        "fundamentals_asof": fund.loc[fund["filed_at"] <= pd.Timestamp(as_of), "filed_at"].max()
        if not fund.empty
        else pd.NaT,
    }
