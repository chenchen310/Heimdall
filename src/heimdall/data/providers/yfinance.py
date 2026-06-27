"""yfinance price provider (US + Taiwan).

Prototyping-grade: yfinance is unofficial and rate-limited, so it is wrapped,
cached, and replaceable — never assumed reliable. See ``docs/DATA_SOURCES.md``.
Normalization (``_normalize``) is a pure function so it can be golden-tested
without touching the network.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pandas as pd
import yfinance as yf

from heimdall.data.base import DataProvider, NotSupported
from heimdall.data.schema import OHLCV_COLUMNS, validate_ohlcv
from heimdall.data.symbols import Symbol, parse_symbol

# yfinance ticker suffix per canonical market. US has no suffix.
_YF_SUFFIX: dict[str, str] = {"US": "", "TW": ".TW", "TWO": ".TWO"}

_RENAME: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


class YFinanceProvider(DataProvider):
    """Fetches split/dividend-aware EOD prices via yfinance."""

    markets = frozenset({"US", "TW", "TWO"})

    def __init__(self, min_interval_s: float = 0.3) -> None:
        # Minimal rate limiter: enforce a gap between outbound calls.
        self._min_interval_s = min_interval_s
        self._last_call = 0.0

    # -- public API ----------------------------------------------------------
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        sym = parse_symbol(symbol)
        if sym.market not in self.markets:
            raise NotSupported(f"{self.name} does not serve market {sym.market}")
        raw = self._download(sym, start, end)
        return _normalize(raw, sym)

    # -- internals -----------------------------------------------------------
    def _to_yf(self, sym: Symbol) -> str:
        return f"{sym.ticker}{_YF_SUFFIX[sym.market]}"

    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _download(self, sym: Symbol, start: date, end: date) -> pd.DataFrame:
        self._throttle()
        # yfinance `end` is exclusive; +1 day makes [start, end] inclusive.
        raw = yf.download(
            self._to_yf(sym),
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,  # keep raw OHLC + a separate Adj Close
            actions=False,
            progress=False,
        )
        return cast("pd.DataFrame", raw)


def _normalize(raw: pd.DataFrame, sym: Symbol) -> pd.DataFrame:
    """Convert a raw yfinance frame into the canonical OHLCV schema.

    Pure function (no network) — the unit of the golden test. Handles the
    single-ticker MultiIndex columns ``(Price, Ticker)`` that ``yf.download``
    returns, as well as flat columns.
    """
    empty = pd.DataFrame(columns=OHLCV_COLUMNS)
    if raw is None or raw.empty:
        return empty

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(-1)  # drop the per-ticker level

    df = df.reset_index().rename(columns={"Date": "date", "Datetime": "date"})
    df = df.rename(columns=_RENAME)

    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df["symbol"] = sym.canonical
    df["currency"] = sym.currency
    df["provider"] = "yfinance"
    df["fetched_at"] = datetime.now(UTC).replace(tzinfo=None)

    df = df[OHLCV_COLUMNS]
    return validate_ohlcv(df)
