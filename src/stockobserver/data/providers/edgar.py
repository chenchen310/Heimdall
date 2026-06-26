"""SEC EDGAR provider — point-in-time US fundamentals from XBRL company facts.

EDGAR is the gold standard for look-ahead-safe fundamentals: every fact carries
its ``filed`` date, so we know what was knowable when. Normalization
(``_normalize_companyfacts``) is pure and golden-tested without the network.
See ``.claude/rules/data-discipline.md`` and ``docs/DATA_SOURCES.md``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from stockobserver.data.base import DataProvider, NotSupported, ProviderError
from stockobserver.data.schema import FUNDAMENTALS_COLUMNS, validate_fundamentals
from stockobserver.data.store import data_root
from stockobserver.data.symbols import Symbol, parse_symbol

# Canonical metric → (statement, [candidate us-gaap tags], XBRL unit).
# Multiple tags per metric cover vendors/years that switch XBRL concepts.
MetricSpec = tuple[str, str, list[str], str]
METRIC_SPECS: list[MetricSpec] = [
    (
        "revenue",
        "income",
        ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
        "USD",
    ),
    ("gross_profit", "income", ["GrossProfit"], "USD"),
    ("operating_income", "income", ["OperatingIncomeLoss"], "USD"),
    ("net_income", "income", ["NetIncomeLoss"], "USD"),
    ("eps_diluted", "income", ["EarningsPerShareDiluted"], "USD/shares"),
    ("assets", "balance", ["Assets"], "USD"),
    ("liabilities", "balance", ["Liabilities"], "USD"),
    ("equity", "balance", ["StockholdersEquity"], "USD"),
    ("cash", "balance", ["CashAndCashEquivalentsAtCarryingValue"], "USD"),
    ("long_term_debt", "balance", ["LongTermDebtNoncurrent", "LongTermDebt"], "USD"),
    (
        "shares_outstanding",
        "balance",
        ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
        "shares",
    ),
    ("cfo", "cashflow", ["NetCashProvidedByUsedInOperatingActivities"], "USD"),
    ("capex", "cashflow", ["PaymentsToAcquirePropertyPlantAndEquipment"], "USD"),
]

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _user_agent() -> str:
    # SEC fair-access policy requires a descriptive UA with contact info.
    return os.environ.get("SEC_EDGAR_USER_AGENT", "stock-observer (set SEC_EDGAR_USER_AGENT)")


class SecEdgarProvider(DataProvider):
    """US fundamentals via the EDGAR XBRL ``companyfacts`` API (free, no key)."""

    markets = frozenset({"US"})

    def __init__(self, root: Path | None = None, min_interval_s: float = 0.12) -> None:
        self._root = root if root is not None else data_root()
        self._min_interval_s = min_interval_s  # SEC allows ~10 req/s
        self._last_call = 0.0
        self._cik: dict[str, int] | None = None

    # -- ABC: prices not served here -----------------------------------------
    def get_ohlcv(self, symbol: str, start: object, end: object) -> pd.DataFrame:
        raise NotSupported("edgar serves fundamentals, not prices")

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        """Canonical tidy-long fundamentals for ``symbol``.

        ``statement`` is one of ``all`` / ``income`` / ``balance`` / ``cashflow``;
        ``period`` is ``all`` / ``annual`` / ``quarter``.
        """
        sym = parse_symbol(symbol)
        if sym.market not in self.markets:
            raise NotSupported(f"edgar does not serve market {sym.market}")
        facts = self._companyfacts(sym)
        df = _normalize_companyfacts(facts, sym)
        if statement != "all":
            df = df[df["statement"] == statement]
        if period != "all":
            df = df[df["period"] == period]
        return df.reset_index(drop=True)

    # -- network / cache -----------------------------------------------------
    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get_json(self, url: str) -> Any:
        self._throttle()
        resp = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=60)
        if resp.status_code != 200:
            raise ProviderError(f"EDGAR {resp.status_code} for {url}")
        return resp.json()

    def _cik_for(self, ticker: str) -> int:
        if self._cik is None:
            cache = self._root / "edgar" / "company_tickers.json"
            if cache.exists():
                raw = json.loads(cache.read_text())
            else:
                raw = self._get_json(_TICKERS_URL)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(raw))
            self._cik = {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}
        try:
            return self._cik[ticker.upper()]
        except KeyError:
            raise ProviderError(f"no SEC CIK for ticker {ticker!r}") from None

    def _companyfacts(self, sym: Symbol) -> dict[str, Any]:
        cik = self._cik_for(sym.ticker)
        cache = self._root / "edgar" / f"companyfacts_{cik:010d}.json"
        if cache.exists():
            return json.loads(cache.read_text())  # type: ignore[no-any-return]
        facts = self._get_json(_FACTS_URL.format(cik=cik))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(facts))
        return facts  # type: ignore[no-any-return]


def _normalize_companyfacts(facts: dict[str, Any], sym: Symbol) -> pd.DataFrame:
    """Convert an EDGAR ``companyfacts`` JSON into canonical tidy-long rows.

    Pure (no network) — the unit of the golden test. Period is ``annual`` when
    the fiscal period is ``FY`` else ``quarter``; every row carries ``filed_at``.
    """
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    usgaap: dict[str, Any] = facts.get("facts", {}).get("us-gaap", {})
    rows: list[dict[str, Any]] = []

    for metric, statement, tags, unit in METRIC_SPECS:
        for tag in tags:
            node = usgaap.get(tag)
            if node is None:
                continue
            for fact in node.get("units", {}).get(unit, []):
                filed, end, val = fact.get("filed"), fact.get("end"), fact.get("val")
                if filed is None or end is None or val is None:
                    continue
                rows.append(
                    {
                        "symbol": sym.canonical,
                        "metric": metric,
                        "statement": statement,
                        "period": "annual" if fact.get("fp") == "FY" else "quarter",
                        "fiscal_end": end,
                        "filed_at": filed,
                        "value": float(val),
                        "currency": sym.currency,
                        "provider": "edgar",
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
