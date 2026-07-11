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

FinMind carries no filing date (verified 2026-07-08: no announcement-date dataset
exists — probed the API and the official docs), so ``filed_at`` is synthesized
from the statutory deadlines of the Securities and Exchange Act §36 (證交法36條):
annual reports within **3 months** of fiscal year end (Dec-FY ⇒ 3/31, which is
exactly ``fiscal_end + 90d``), and monthly revenue by the **10th of the following
month**. Deadlines are the *latest legal* availability, so on-time filers are
never seen early (no look-ahead); early filers only make us conservative; the
sole look-ahead exposure is late filers, which are rare and sanctioned.
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
# §36: annual report due within 3 months of FY end — 12/31 + 90d = 3/31, the statutory deadline.
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
    "pretax_income": ["PreTaxIncome"],
}
# Cash-flow lines are CUMULATIVE YTD -> the year-end value is the annual figure.
# ``dep_amort`` ≈ depreciation (FinMind reports it separately from amortization;
# depreciation dominates D&A for capital-intensive TW names — a conservative proxy).
_CASHFLOW_FIELDS: dict[str, list[str]] = {
    "cfo": ["NetCashInflowFromOperatingActivities", "CashFlowsFromOperatingActivities"],
    "capex": ["PropertyAndPlantAndEquipment"],
    "dep_amort": ["Depreciation"],
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

# --- daily chips / flows (roadmap 11.3) -------------------------------------
# ``TaiwanStockInstitutionalInvestorsBuySell`` ``name`` codes. 外資 (foreign) =
# the investor line + the foreign-dealer-self line (TWSE aggregates both); 投信 =
# the trust line; 自營商 (dealer) = the self + hedging lines combined. Dealer
# flows are carried as their own column but excluded from every *panel feature*
# on purpose — they are hedging noise, not a directional signal (see the 11.3
# card's priors) — roadmap 15.2's market-wide descriptive view is the one
# consumer that wants them (a complete "who traded today", not a predictor).
_INST_FOREIGN = frozenset({"Foreign_Investor", "Foreign_Dealer_Self"})
_INST_TRUST = "Investment_Trust"
_INST_DEALER = frozenset({"Dealer_self", "Dealer_Hedging"})
_CHIPS_COLUMNS = [
    "symbol",
    "date",
    "foreign_net_shares",
    "trust_net_shares",
    "dealer_net_shares",
    "foreign_hold_ratio",
    "margin_balance",
    "margin_short_balance",
    "currency",
    "provider",
    "fetched_at",
]

# --- sell-side chip data (roadmap 17.1 — the missing half of 11.3) ----------
# Securities-lending (借券賣出) short balance is share-denominated (verified 2026-07-11 by
# cross-checking against TaiwanStockPrice's Trading_Volume for the same symbol/dates — same
# order of magnitude), UNLIKE the board-lot-denominated (張) margin balances above. Keep the
# two on separate columns; never combine them without converting lots→shares (×1000) first.
_LENDING_COLUMNS = ["symbol", "date", "sbl_short_balance", "currency", "provider", "fetched_at"]


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

    def daily_chips(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Merged daily TW chip/flow panel — the signature籌碼 streams (roadmap 11.3).

        Outer-joins three FinMind datasets on trading day into one frame:
        institutional net-buy shares (外資 + 投信 + 自營商), foreign holding
        ratio, and margin buy/short balances (融資/融券). Columns ``[symbol,
        date, foreign_net_shares, trust_net_shares, dealer_net_shares,
        foreign_hold_ratio, margin_balance, margin_short_balance, currency,
        provider, fetched_at]``; feature construction (and the crucial **+1
        trading-day** point-in-time shift) is left to the caller
        (``research.dataset`` reads foreign/trust/margin only — dealer flows
        are hedging noise for signal purposes; ``research.flows_cache``,
        roadmap 15.2, is the one consumer of ``dealer_net_shares``).

        These values are published after trading day *d* closes (T+1 for the
        holding ratio), so a rebalance at *t* must read only through *t−1* — the
        panel enforces that shift. Fetched per symbol: FinMind's per-**date** bulk
        query (omit ``data_id``) requires a paid tier (probed 2026-07-08,
        reconfirmed live 2026-07-11 — the free ``register`` level gets a 400
        "please update your user level" refusal; see
        :meth:`bulk_institutional_by_date`), so whole-market builds loop symbols.
        """
        sym = self._require_market(symbol)
        inst = _normalize_institutional(
            self._get("TaiwanStockInstitutionalInvestorsBuySell", sym.ticker, start, end)
        )
        hold = _normalize_shareholding(self._get("TaiwanStockShareholding", sym.ticker, start, end))
        margin = _normalize_margin(
            self._get("TaiwanStockMarginPurchaseShortSale", sym.ticker, start, end)
        )
        return _merge_chips(inst, hold, margin, sym)

    def daily_lending(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Daily securities-lending (借券賣出) short balance — the informed sell-side
        counterpart to 11.3's buy-side flows, used mostly by foreign institutions
        (roadmap 17.1). Free-tier availability verified 2026-07-11 (live probe,
        registered token). Columns ``[symbol, date, sbl_short_balance, currency,
        provider, fetched_at]``; same **+1 trading-day** PIT rule as
        :meth:`daily_chips` — left to the caller.
        """
        sym = self._require_market(symbol)
        raw = self._get("TaiwanDailyShortSaleBalances", sym.ticker, start, end)
        return _normalize_lending(raw, sym)

    def bulk_institutional_by_date(self, d: date) -> pd.DataFrame | None:
        """Attempt FinMind's per-**date** bulk query (omit ``data_id``) for
        ``TaiwanStockInstitutionalInvestorsBuySell`` — the whole market in one
        request (roadmap 15.2). Returns ``None`` if this token's tier refuses
        it (a 400/error response — probed 2026-07-08, reconfirmed live
        2026-07-11: the free ``register`` level is refused, no free-tier
        example exists to golden-test the success path against real data) or
        if the market was closed that day (empty response) — either way the
        caller falls back to a per-symbol loop. Never raises for a refusal; a
        genuine network error still propagates. If a future paid tier unlocks
        bulk access, this starts returning real data with no caller-side
        change needed. Unnormalized — ``[stock_id, date, foreign_net_shares,
        trust_net_shares, dealer_net_shares]`` via
        :func:`_normalize_institutional_market_wide`.
        """
        try:
            raw = self._get("TaiwanStockInstitutionalInvestorsBuySell", None, d, d)
        except ProviderError:
            return None
        if not raw:
            return None
        return _normalize_institutional_market_wide(raw)

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

    def _get(
        self, dataset: str, data_id: str | None, start: date, end: date
    ) -> list[dict[str, Any]]:
        """``data_id=None`` omits the parameter entirely — FinMind's per-date bulk
        query shape (roadmap 15.2), as opposed to every other caller's per-symbol
        shape."""
        import requests

        self._throttle()
        params: dict[str, str] = {
            "dataset": dataset,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        if data_id is not None:
            params["data_id"] = data_id
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
    """FinMind ``TaiwanStockMonthRevenue`` rows → ``[symbol, month, filed_at, revenue, …]``.

    ``filed_at`` is the statutory availability date — §36 requires the prior
    month's revenue to be announced by the **10th of the following month** — so
    point-in-time features (roadmap 11.2) may only read a month's revenue on or
    after that date.
    """
    cols = ["symbol", "month", "filed_at", "revenue", "currency", "provider", "fetched_at"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    month = pd.to_datetime(dict(year=df["revenue_year"], month=df["revenue_month"], day=1))
    out = pd.DataFrame(
        {
            "symbol": sym.canonical,
            "month": month,
            "filed_at": month + pd.DateOffset(months=1, days=9),  # the 10th of the next month
            "revenue": df["revenue"].astype(float),
            "currency": sym.currency,
            "provider": "finmind",
            "fetched_at": datetime.now(UTC).replace(tzinfo=None),
        }
    )
    return out.sort_values("month").reset_index(drop=True)[cols]


def _normalize_institutional(raw: list[dict[str, Any]]) -> pd.DataFrame:
    """``TaiwanStockInstitutionalInvestorsBuySell`` rows → daily net-buy **shares**.

    Sums ``buy − sell`` per day for the foreign lines (外資 + 外資自營商), the
    trust line (投信), and the dealer lines (自營商自行買賣 + 避險) separately.
    Dealer flows are carried through (roadmap 15.2's market-wide descriptive
    view reads them) but stay excluded from every panel *feature* — callers in
    ``research/`` simply don't read ``dealer_net_shares``. Returns
    ``[date, foreign_net_shares, trust_net_shares, dealer_net_shares]``.
    """
    cols = ["date", "foreign_net_shares", "trust_net_shares", "dealer_net_shares"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    df["net"] = df["buy"].astype(float) - df["sell"].astype(float)
    foreign = df[df["name"].isin(_INST_FOREIGN)].groupby("date")["net"].sum()
    trust = df[df["name"] == _INST_TRUST].groupby("date")["net"].sum()
    dealer = df[df["name"].isin(_INST_DEALER)].groupby("date")["net"].sum()
    out = pd.DataFrame(
        {"foreign_net_shares": foreign, "trust_net_shares": trust, "dealer_net_shares": dealer}
    )
    return out.reset_index().sort_values("date").reset_index(drop=True)[cols]


def _normalize_institutional_market_wide(raw: list[dict[str, Any]]) -> pd.DataFrame:
    """Bulk per-date ``TaiwanStockInstitutionalInvestorsBuySell`` rows (every
    symbol, one date) → per-(stock_id, date) net shares for all three investor
    types (roadmap 15.2). The multi-symbol sibling of :func:`_normalize_institutional`
    — grouped by ``stock_id`` **and** ``date`` instead of just ``date``, since a
    bulk response covers the whole market in one call. Returns
    ``[stock_id, date, foreign_net_shares, trust_net_shares, dealer_net_shares]``.
    """
    cols = ["stock_id", "date", "foreign_net_shares", "trust_net_shares", "dealer_net_shares"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["date"])
    df["net"] = df["buy"].astype(float) - df["sell"].astype(float)
    pivot = df.pivot_table(
        index=["stock_id", "date"], columns="name", values="net", aggfunc="sum", fill_value=0.0
    )
    out = pd.DataFrame(index=pivot.index)
    out["foreign_net_shares"] = pivot.reindex(columns=list(_INST_FOREIGN), fill_value=0.0).sum(
        axis=1
    )
    out["trust_net_shares"] = pivot[_INST_TRUST] if _INST_TRUST in pivot.columns else 0.0
    out["dealer_net_shares"] = pivot.reindex(columns=list(_INST_DEALER), fill_value=0.0).sum(axis=1)
    return out.reset_index().sort_values(["stock_id", "date"]).reset_index(drop=True)[cols]


def _normalize_shareholding(raw: list[dict[str, Any]]) -> pd.DataFrame:
    """``TaiwanStockShareholding`` rows → daily foreign holding ratio (percent).

    ``ForeignInvestmentSharesRatio`` is the share of the company held by foreign
    investors (73.08 = 73.08%). Returns ``[date, foreign_hold_ratio]``.
    """
    cols = ["date", "foreign_hold_ratio"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "foreign_hold_ratio": df["ForeignInvestmentSharesRatio"].astype(float),
        }
    )
    return out.sort_values("date").reset_index(drop=True)[cols]


def _normalize_margin(raw: list[dict[str, Any]]) -> pd.DataFrame:
    """``TaiwanStockMarginPurchaseShortSale`` rows → daily margin buy + short balances.

    ``MarginPurchaseTodayBalance`` (融資餘額, buy side) and ``ShortSaleTodayBalance``
    (融券餘額, short side; roadmap 17.1) are both outstanding balances in **board
    lots (張)** — verified 2026-07-11 by cross-checking against daily share volume
    (46 vs ~25M shares traded is only plausible as lots). The unit is irrelevant
    downstream since every feature reading them is a %-change. Returns
    ``[date, margin_balance, margin_short_balance]``.
    """
    cols = ["date", "margin_balance", "margin_short_balance"]
    if not raw:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]),
            "margin_balance": df["MarginPurchaseTodayBalance"].astype(float),
            "margin_short_balance": df["ShortSaleTodayBalance"].astype(float),
        }
    )
    return out.sort_values("date").reset_index(drop=True)[cols]


def _normalize_lending(raw: list[dict[str, Any]], sym: Symbol) -> pd.DataFrame:
    """``TaiwanDailyShortSaleBalances`` rows → daily securities-lending short balance.

    ``SBLShortSalesCurrentDayBalance`` (借券賣出當日餘額) is **share**-denominated —
    confirmed 2026-07-11 against ``TaiwanStockPrice``'s ``Trading_Volume`` for the
    same symbol/dates (same order of magnitude: ~11M balance vs ~25M daily shares
    traded for 2330), unlike the lot-denominated margin balances in
    :func:`_normalize_margin`. Returns
    ``[symbol, date, sbl_short_balance, currency, provider, fetched_at]``.
    """
    if not raw:
        return pd.DataFrame(columns=_LENDING_COLUMNS)
    df = pd.DataFrame(raw)
    out = pd.DataFrame(
        {
            "symbol": sym.canonical,
            "date": pd.to_datetime(df["date"]),
            "sbl_short_balance": df["SBLShortSalesCurrentDayBalance"].astype(float),
            "currency": sym.currency,
            "provider": "finmind",
            "fetched_at": datetime.now(UTC).replace(tzinfo=None),
        }
    )
    return out.sort_values("date").reset_index(drop=True)[_LENDING_COLUMNS]


def _merge_chips(
    inst: pd.DataFrame, hold: pd.DataFrame, margin: pd.DataFrame, sym: Symbol
) -> pd.DataFrame:
    """Outer-join the three chip streams on trading day into one canonical frame."""
    if inst.empty and hold.empty and margin.empty:
        return pd.DataFrame(columns=_CHIPS_COLUMNS)
    merged = inst.merge(hold, on="date", how="outer").merge(margin, on="date", how="outer")
    merged = merged.sort_values("date").reset_index(drop=True)
    for col in (
        "foreign_net_shares",
        "trust_net_shares",
        "dealer_net_shares",
        "foreign_hold_ratio",
        "margin_balance",
        "margin_short_balance",
    ):
        if col not in merged.columns:
            merged[col] = float("nan")
    merged["symbol"] = sym.canonical
    merged["currency"] = sym.currency
    merged["provider"] = "finmind"
    merged["fetched_at"] = datetime.now(UTC).replace(tzinfo=None)
    return merged[_CHIPS_COLUMNS]


__all__ = ["FinMindProvider"]
