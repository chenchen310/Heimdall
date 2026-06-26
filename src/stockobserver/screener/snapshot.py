"""Snapshot table — one row per symbol with every screenable metric.

Combines latest technicals (from prices) with **point-in-time** fundamentals
(only values filed on/before ``as_of``, taking the most recently ended fiscal
period) plus derived ratios. The screener evaluates predicates over this table.
See ``docs/ARCHITECTURE.md`` §5–6.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stockobserver.data.base import DataProvider
from stockobserver.data.store import data_root
from stockobserver.factors.indicators import rsi, sma

# Small default US universe for Phase 1 (extend freely; full index lists later).
DEFAULT_UNIVERSE: list[str] = [
    "AAPL.US",
    "MSFT.US",
    "NVDA.US",
    "GOOGL.US",
    "AMZN.US",
    "META.US",
    "TSLA.US",
    "JPM.US",
    "JNJ.US",
    "WMT.US",
    "XOM.US",
    "PG.US",
    "KO.US",
    "INTC.US",
    "CSCO.US",
]


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
        "pct_above_sma_200": _safe_div(price, float(s200)) - 1.0,
    }


def build_snapshot(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    as_of: date | None = None,
) -> pd.DataFrame:
    """Build the snapshot table for ``symbols`` as known on ``as_of`` (default today)."""
    as_of = as_of or date.today()
    price_start = as_of - timedelta(days=500)  # enough history for SMA-200
    rows: list[dict[str, object]] = []

    for symbol in symbols:
        ohlcv = prices.get_ohlcv(symbol, price_start, as_of)
        if ohlcv.empty:
            continue
        fund = fundamentals.get_fundamentals(symbol, "all", "annual")
        f = _latest_annual(fund, as_of)
        tech = _technicals(ohlcv)

        revenue, net_income = f.get("revenue", float("nan")), f.get("net_income", float("nan"))
        equity = f.get("equity", float("nan"))
        shares = f.get("shares_outstanding", float("nan"))
        fcf = f.get("cfo", float("nan")) - f.get("capex", float("nan"))
        market_cap = tech["price"] * shares if pd.notna(shares) else float("nan")

        rows.append(
            {
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
                "fundamentals_asof": fund.loc[
                    fund["filed_at"] <= pd.Timestamp(as_of), "filed_at"
                ].max()
                if not fund.empty
                else pd.NaT,
            }
        )

    return pd.DataFrame(rows)


def snapshot_path(root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "snapshot.parquet"


def save_snapshot(df: pd.DataFrame, root: Path | None = None) -> Path:
    path = snapshot_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_snapshot(root: Path | None = None) -> pd.DataFrame:
    path = snapshot_path(root)
    if not path.exists():
        raise FileNotFoundError(f"no snapshot at {path}; build one first")
    return pd.read_parquet(path)
