"""FinMind provider — Taiwan market data (TWSE ``.TW`` + TPEX ``.TWO``).

A ``DataProvider`` like any other: it normalizes FinMind's JSON into the **same**
canonical schema as EDGAR/FMP, so the screener, factors, analytics, and
dashboards work for Taiwan unchanged. Free and key-less by default (FinMind
allows anonymous access at a low hourly quota); set ``FINMIND_TOKEN`` in ``.env``
for a higher quota. Normalization is pure and golden-tested without the network.
See ``docs/DATA_SOURCES.md``.

Two Taiwan-specific cadence traps are handled here so downstream code never sees
them (see ``.claude/rules/data-discipline.md``):

* The income statement is reported **standalone per quarter**, so an annual
  figure is the **sum** of the four quarters.
* The cash-flow statement is reported **cumulative year-to-date**, so the annual
  figure is the **year-end** value (never summed). The balance sheet is
  point-in-time, also taken at year-end.

FinMind carries no filing date, so ``filed_at`` is synthesized as a conservative
lag after the fiscal-period end (Taiwan annual reports are due ~90 days out).
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.schema import (
    FUNDAMENTALS_COLUMNS,
    OHLCV_COLUMNS,
    validate_fundamentals,
    validate_ohlcv,
)
from heimdall.data.symbols import Symbol, parse_symbol

_BASE = "https://api.finmindtrade.com/api/v4/data"

# Conservative point-in-time lag when no filing date is available (TW annual
# reports are due within ~3 months of fiscal-year end).
_ANNUAL_FILING_LAG = timedelta(days=90)
# How far back get_fundamentals reaches to build annual history (FinMind needs a
# range; EDGAR/FMP return all history).
_FUNDAMENTALS_LOOKBACK_YEARS = 8

# Canonical metric -> FinMind ``type`` code(s); first present wins per period.
# Income lines are STANDALONE quarterly -> summed to an annual figure.
_INCOME_FIELDS: dict[str, list[str]] = {
    "revenue": ["Revenue"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncome"],
    "net_income": ["IncomeAfterTaxes"],
    "eps_diluted": ["EPS"],
}
# Cash-flow lines are CUMULATIVE YTD -> the year-end value is the annual figure.
_CASHFLOW_FIELDS: dict[str, list[str]] = {
    "cfo": ["NetCashInflowFromOperatingActivities", "CashFlowsFromOperatingActivities"],
    "capex": ["PropertyAndPlantAndEquipment"],
}
# Balance lines are point-in-time stocks -> the year-end value is the annual figure.
_BALANCE_FIELDS: dict[str, list[str]] = {
    "assets": ["TotalAssets"],
    "liabilities": ["Liabilities"],
    "equity": ["Equity"],
    "cash": ["CashAndCashEquivalents"],
}
_DATASET: dict[str, str] = {
    "income": "TaiwanStockFinancialStatements",
    "balance": "TaiwanStockBalanceSheet",
    "cashflow": "TaiwanStockCashFlowsStatement",
}
# FinMind reports capex as a negative cash outflow; canonical capex is a positive
# magnitude (EDGAR convention) so ``fcf = cfo - capex`` is consistent everywhere.
_ABS_METRICS = frozenset({"capex"})

_PRICE_RENAME: dict[str, str] = {
    "max": "high",
    "min": "low",
    "Trading_Volume": "volume",
}


class FinMindProvider(DataProvider):
    """Taiwan prices + fundamentals + monthly revenue via the FinMind API."""

    markets = frozenset({"TW", "TWO"})

    def __init__(self, token: str | None = None, min_interval_s: float = 0.3) -> None:
        self._token = token or os.environ.get("FINMIND_TOKEN")
        self._min_interval_s = min_interval_s
        self._last_call = 0.0

    # -- public API ----------------------------------------------------------
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Canonical OHLCV for a Taiwan symbol.

        FinMind's free price series is **unadjusted** (no split/dividend
        adjustment), so ``adj_close`` mirrors ``close``. For adjusted Taiwan
        prices the app routes through yfinance; this remains a usable raw source.
        """
        sym = self._require_market(symbol)
        raw = self._get("TaiwanStockPrice", sym.ticker, start, end)
        return _normalize_ohlcv(raw, sym)

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        """Canonical annual fundamentals, aggregated from FinMind's quarterly feed.

        ``statement`` is ``all`` / ``income`` / ``balance`` / ``cashflow``. Only
        annual rows are produced (the cadence traps make a clean quarterly view
        non-trivial), so ``period == "quarter"`` returns an empty frame.
        """
        sym = self._require_market(symbol)
        if period == "quarter":
            return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
        wanted = ["income", "balance", "cashflow"] if statement == "all" else [statement]
        end = date.today()
        start = end.replace(year=end.year - _FUNDAMENTALS_LOOKBACK_YEARS, month=1, day=1)
        statements = {s: self._get(_DATASET[s], sym.ticker, start, end) for s in wanted}
        return _normalize_fundamentals(statements, sym)

    def monthly_revenue(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Taiwan monthly revenue (月營收) — a signature TW signal with no US analogue.

        Returns ``[symbol, month, revenue, currency, provider, fetched_at]`` where
        ``month`` is the revenue period's first day. YoY is left to the caller.
        """
        sym = self._require_market(symbol)
        raw = self._get("TaiwanStockMonthRevenue", sym.ticker, start, end)
        return _normalize_month_revenue(raw, sym)

    # -- internals -----------------------------------------------------------
    def _require_market(self, symbol: str) -> Symbol:
        sym = parse_symbol(symbol)
        if sym.market not in self.markets:
            raise NotSupported(f"{self.name} does not serve market {sym.market}")
        return sym

    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, dataset: str, data_id: str, start: date, end: date) -> list[dict[str, Any]]:
        import requests

        self._throttle()
        params: dict[str, str] = {
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        if self._token:
            params["token"] = self._token
        resp = requests.get(_BASE, params=params, timeout=30)
        if resp.status_code == 402:
            raise ProviderError(
                "FinMind quota reached — set FINMIND_TOKEN in .env for a higher limit"
            )
        if resp.status_code != 200:
            raise ProviderError(f"FinMind {resp.status_code} for {dataset}")
        payload = resp.json()
        if payload.get("status") != 200:
            raise ProviderError(f"FinMind error for {dataset}: {payload.get('msg')}")
        data: list[dict[str, Any]] = payload.get("data", [])
        return data


# --- pure normalizers (no network — the unit of the golden tests) -----------
def _normalize_ohlcv(raw: list[dict[str, Any]], sym: Symbol) -> pd.DataFrame:
    """FinMind ``TaiwanStockPrice`` rows → canonical OHLCV (unadjusted)."""
    if not raw:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    df = pd.DataFrame(raw).rename(columns=_PRICE_RENAME)
    df["date"] = pd.to_datetime(df["date"])
    df["adj_close"] = df["close"]  # FinMind free prices are unadjusted
    df["symbol"] = sym.canonical
    df["currency"] = sym.currency
    df["provider"] = "finmind"
    df["fetched_at"] = datetime.now(UTC).replace(tzinfo=None)
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            df[col] = float("nan")
    return validate_ohlcv(df[OHLCV_COLUMNS])


def _collect(
    rows: list[dict[str, Any]], fields: dict[str, list[str]]
) -> dict[str, dict[pd.Timestamp, float]]:
    """``{metric: {fiscal_end: value}}`` from FinMind statement rows.

    When several candidate ``type`` codes map to one metric, the earliest in the
    candidate list wins (priority by index).
    """
    priority: dict[str, tuple[str, int]] = {
        code: (metric, i) for metric, codes in fields.items() for i, code in enumerate(codes)
    }
    best: dict[str, dict[pd.Timestamp, tuple[int, float]]] = defaultdict(dict)
    for row in rows:
        hit = priority.get(row.get("type", ""))
        value = row.get("value")
        end = row.get("date")
        if hit is None or value is None or end is None:
            continue
        metric, rank = hit
        ts = pd.Timestamp(end)
        current = best[metric].get(ts)
        if current is None or rank < current[0]:
            best[metric][ts] = (rank, float(value))
    return {metric: {ts: v for ts, (_, v) in by_ts.items()} for metric, by_ts in best.items()}


def _by_year(series: dict[pd.Timestamp, float]) -> dict[int, dict[int, float]]:
    """Regroup ``{fiscal_end: value}`` into ``{year: {month: value}}``."""
    out: dict[int, dict[int, float]] = defaultdict(dict)
    for ts, value in series.items():
        out[ts.year][ts.month] = value
    return out


def _annual_row(
    sym: Symbol, metric: str, statement: str, year: int, value: float, fetched_at: datetime
) -> dict[str, Any]:
    fiscal_end = pd.Timestamp(year, 12, 31)
    return {
        "symbol": sym.canonical,
        "metric": metric,
        "statement": statement,
        "period": "annual",
        "fiscal_end": fiscal_end,
        "filed_at": fiscal_end + _ANNUAL_FILING_LAG,
        "value": value,
        "currency": sym.currency,
        "provider": "finmind",
        "fetched_at": fetched_at,
    }


def _normalize_fundamentals(
    statements: dict[str, list[dict[str, Any]]], sym: Symbol
) -> pd.DataFrame:
    """FinMind quarterly statements → canonical **annual** tidy-long fundamentals.

    Income flows are summed over the four standalone quarters; cash-flow flows
    and balance stocks are taken at year-end (cash flow is cumulative YTD).
    """
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    income = _collect(statements.get("income", []), _INCOME_FIELDS)
    cash = _collect(statements.get("cashflow", []), _CASHFLOW_FIELDS)
    balance = _collect(statements.get("balance", []), _BALANCE_FIELDS)

    rows: list[dict[str, Any]] = []
    # Income: sum the four standalone quarters into an annual figure.
    annual_income: dict[str, dict[int, float]] = defaultdict(dict)
    for metric, series in income.items():
        for year, by_month in _by_year(series).items():
            if {3, 6, 9, 12} <= by_month.keys():
                total = sum(by_month[m] for m in (3, 6, 9, 12))
                annual_income[metric][year] = total
                rows.append(_annual_row(sym, metric, "income", year, total, fetched_at))
    # Cash flow: cumulative YTD — the year-end value is the annual figure.
    for metric, series in cash.items():
        for year, by_month in _by_year(series).items():
            if 12 in by_month:
                value = by_month[12]
                rows.append(
                    _annual_row(
                        sym,
                        metric,
                        "cashflow",
                        year,
                        abs(value) if metric in _ABS_METRICS else value,
                        fetched_at,
                    )
                )
    # Balance: point-in-time — the year-end value is the annual snapshot.
    for metric, series in balance.items():
        for year, by_month in _by_year(series).items():
            if 12 in by_month:
                rows.append(_annual_row(sym, metric, "balance", year, by_month[12], fetched_at))
    # Derived shares outstanding = annual net income / annual EPS (par-independent).
    for year, net_income in annual_income.get("net_income", {}).items():
        eps = annual_income.get("eps_diluted", {}).get(year)
        if eps:
            shares = net_income / eps
            rows.append(_annual_row(sym, "shares_outstanding", "balance", year, shares, fetched_at))

    if not rows:
        return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    df = pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)
    df["fiscal_end"] = pd.to_datetime(df["fiscal_end"])
    df["filed_at"] = pd.to_datetime(df["filed_at"])
    return validate_fundamentals(df)


def _normalize_month_revenue(raw: list[dict[str, Any]], sym: Symbol) -> pd.DataFrame:
    """FinMind ``TaiwanStockMonthRevenue`` rows → ``[symbol, month, revenue, …]``."""
    cols = ["symbol", "month", "revenue", "currency", "provider", "fetched_at"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "symbol": sym.canonical,
            "month": pd.to_datetime(
                dict(year=df["revenue_year"], month=df["revenue_month"], day=1)
            ),
            "revenue": df["revenue"].astype(float),
            "currency": sym.currency,
            "provider": "finmind",
            "fetched_at": datetime.now(UTC).replace(tzinfo=None),
        }
    )
    return out.sort_values("month").reset_index(drop=True)[cols]


__all__ = ["FinMindProvider"]
