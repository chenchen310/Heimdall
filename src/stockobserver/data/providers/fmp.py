"""Financial Modeling Prep provider — paid drop-in for deeper US fundamentals.

A ``DataProvider`` like any other: it normalizes FMP's JSON into the **same**
canonical schema as EDGAR, so swapping it in is transparent to the screener,
factors, analytics, and dashboards. Gated behind ``FMP_API_KEY`` — never a hard
dependency. Normalization is pure and golden-tested without a key/network.
See ``docs/DATA_SOURCES.md``.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import requests

from stockobserver.data.base import DataProvider, NotSupported, ProviderError
from stockobserver.data.schema import (
    EARNINGS_COLUMNS,
    FUNDAMENTALS_COLUMNS,
    OHLCV_COLUMNS,
    validate_fundamentals,
    validate_ohlcv,
)
from stockobserver.data.symbols import Symbol, parse_symbol

_BASE = "https://financialmodelingprep.com/api/v3"

# statement -> {canonical metric: FMP field}.
FMP_FIELDS: dict[str, dict[str, str]] = {
    "income": {
        "revenue": "revenue",
        "gross_profit": "grossProfit",
        "operating_income": "operatingIncome",
        "net_income": "netIncome",
        "eps_diluted": "epsdiluted",
        "shares_outstanding": "weightedAverageShsOutDil",
    },
    "balance": {
        "assets": "totalAssets",
        "liabilities": "totalLiabilities",
        "equity": "totalStockholdersEquity",
        "cash": "cashAndCashEquivalents",
        "long_term_debt": "longTermDebt",
    },
    "cashflow": {
        "cfo": "operatingCashFlow",
        "capex": "capitalExpenditure",
    },
}
_STATEMENT_PATH = {
    "income": "income-statement",
    "balance": "balance-sheet-statement",
    "cashflow": "cash-flow-statement",
}


class FmpProvider(DataProvider):
    """US prices + fundamentals via Financial Modeling Prep (requires FMP_API_KEY)."""

    markets = frozenset({"US"})

    def __init__(self, api_key: str | None = None, min_interval_s: float = 0.1) -> None:
        self._api_key = api_key or os.environ.get("FMP_API_KEY")
        self._min_interval_s = min_interval_s
        self._last_call = 0.0

    def _get(self, path: str, **params: Any) -> Any:
        if not self._api_key:
            raise NotSupported("FMP requires FMP_API_KEY (set it in .env)")
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        resp = requests.get(
            f"{_BASE}/{path}", params={**params, "apikey": self._api_key}, timeout=30
        )
        if resp.status_code != 200:
            raise ProviderError(f"FMP {resp.status_code} for {path}")
        return resp.json()

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        sym = parse_symbol(symbol)
        raw = self._get(
            f"historical-price-full/{sym.ticker}",
            **{"from": start.isoformat(), "to": end.isoformat()},
        )
        return _normalize_ohlcv(raw, sym)

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        sym = parse_symbol(symbol)
        per = "annual" if period in ("annual", "all") else "quarter"
        wanted = ["income", "balance", "cashflow"] if statement == "all" else [statement]
        data = {
            s: self._get(f"{_STATEMENT_PATH[s]}/{sym.ticker}", period=per, limit=40) for s in wanted
        }
        df = _normalize_fundamentals(data, sym)
        return df if period == "all" else df[df["period"] == period].reset_index(drop=True)

    def get_estimates(self, symbol: str) -> pd.DataFrame:
        sym = parse_symbol(symbol)
        raw = self._get(f"analyst-estimates/{sym.ticker}")
        return pd.DataFrame(raw)

    def get_earnings_dates(self, symbol: str) -> pd.DataFrame:
        sym = parse_symbol(symbol)
        raw = self._get(f"historical/earning_calendar/{sym.ticker}")
        return _normalize_earnings(raw, sym)


def _filed_at(row: dict[str, Any]) -> Any:
    return (
        row.get("fillingDate")
        or row.get("filingDate")
        or row.get("acceptedDate")
        or row.get("date")
    )


def _normalize_fundamentals(
    statements: dict[str, list[dict[str, Any]]], sym: Symbol
) -> pd.DataFrame:
    """FMP statement rows → canonical tidy-long fundamentals (pure; golden-tested)."""
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    rows: list[dict[str, Any]] = []
    for statement, statement_rows in statements.items():
        fields = FMP_FIELDS[statement]
        for row in statement_rows:
            filed, end = _filed_at(row), row.get("date")
            if filed is None or end is None:
                continue
            period = "annual" if row.get("period") in ("FY", None) else "quarter"
            for metric, field in fields.items():
                val = row.get(field)
                if val is None:
                    continue
                # FMP reports capex negative; canonical capex is a positive magnitude
                # (EDGAR convention) so fcf = cfo - capex is consistent across providers.
                value = abs(float(val)) if metric == "capex" else float(val)
                rows.append(
                    {
                        "symbol": sym.canonical,
                        "metric": metric,
                        "statement": statement,
                        "period": period,
                        "fiscal_end": end,
                        "filed_at": filed,
                        "value": value,
                        "currency": sym.currency,
                        "provider": "fmp",
                        "fetched_at": fetched_at,
                    }
                )
    if not rows:
        return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    df = pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)
    df["fiscal_end"] = pd.to_datetime(df["fiscal_end"])
    df["filed_at"] = pd.to_datetime(df["filed_at"])
    df = df.drop_duplicates(subset=["metric", "period", "fiscal_end", "filed_at"])
    return validate_fundamentals(df)


def _normalize_ohlcv(raw: dict[str, Any], sym: Symbol) -> pd.DataFrame:
    """FMP ``historical-price-full`` → canonical OHLCV (pure)."""
    historical = (raw or {}).get("historical", [])
    if not historical:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    df = pd.DataFrame(historical).rename(columns={"adjClose": "adj_close"})
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = sym.canonical
    df["currency"] = sym.currency
    df["provider"] = "fmp"
    df["fetched_at"] = datetime.now(UTC).replace(tzinfo=None)
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    return validate_ohlcv(df[OHLCV_COLUMNS])


def _normalize_earnings(raw: list[dict[str, Any]], sym: Symbol) -> pd.DataFrame:
    """FMP ``earning_calendar`` → canonical earnings frame (pure). FMP leaves
    ``eps`` null for not-yet-reported dates, which marks the future rows."""
    if not raw:
        return pd.DataFrame(columns=EARNINGS_COLUMNS)
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "symbol": sym.canonical,
            "date": pd.to_datetime(df["date"]),
            "eps_actual": df.get("eps"),
            "eps_estimate": df.get("epsEstimated"),
            "revenue_actual": df.get("revenue"),
            "revenue_estimate": df.get("revenueEstimated"),
        }
    )
    out["is_future"] = out["eps_actual"].isna()
    return out[EARNINGS_COLUMNS]


__all__ = ["FmpProvider"]
