"""Canonical data schema — the contract every provider normalizes into.

Nothing downstream of a provider may use vendor-specific column names or symbol
formats. See ``docs/ARCHITECTURE.md`` §1 and ``.claude/rules/canonical-schema.md``.
"""

from __future__ import annotations

import pandas as pd

# --- Canonical OHLCV (one row per symbol per bar) ---------------------------
# Raw prices are stored as traded; ``adj_close`` is split/dividend adjusted.
OHLCV_COLUMNS: list[str] = [
    "symbol",  # canonical TICKER.MARKET
    "date",  # bar timestamp (tz-naive UTC date for EOD)
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "currency",  # ISO 4217, always carried
    "provider",  # source tag (provenance)
    "fetched_at",  # retrieval time (provenance / point-in-time)
]

PRICE_COLUMNS: list[str] = ["open", "high", "low", "close", "adj_close"]

# --- Canonical fundamentals (tidy long: one metric value per row) -----------
# Point-in-time: every row carries ``filed_at`` (when the value became knowable);
# downstream code keys off it, never ``fiscal_end``. See data-discipline.md.
FUNDAMENTALS_COLUMNS: list[str] = [
    "symbol",  # canonical TICKER.MARKET
    "metric",  # canonical metric name (e.g. "revenue", "net_income")
    "statement",  # income / balance / cashflow
    "period",  # annual / quarter
    "fiscal_end",  # end of the fiscal period
    "filed_at",  # SEC filing/availability date — the point-in-time key
    "value",  # numeric value in `currency` (or shares for share counts)
    "currency",  # reporting currency
    "provider",  # source tag (provenance)
    "fetched_at",  # retrieval time (provenance)
]


# --- Canonical macro series (FRED etc.) -------------------------------------
MACRO_COLUMNS: list[str] = ["series_id", "date", "value"]


class SchemaError(ValueError):
    """Raised when a DataFrame does not conform to a canonical schema."""


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and lightly normalize a canonical OHLCV frame.

    Enforces the data-discipline invariants that are cheap to check on ingest:
    required columns present, no negative prices/volume, sorted unique dates.
    Returns the frame (sorted) so callers can use it inline.
    """
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"OHLCV frame missing columns: {missing}")

    if df.empty:
        return df

    prices = df[PRICE_COLUMNS]
    if (prices < 0).to_numpy().any():
        raise SchemaError("OHLCV contains negative prices")
    if (df["volume"] < 0).to_numpy().any():
        raise SchemaError("OHLCV contains negative volume")

    out = df.sort_values("date").reset_index(drop=True)
    if out["date"].duplicated().any():
        raise SchemaError("OHLCV contains duplicate dates for one symbol")
    return out


def validate_fundamentals(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a canonical tidy-long fundamentals frame.

    The load-bearing check is that every row carries ``filed_at`` — without it
    a value has no knowable-as-of date and cannot be used point-in-time.
    """
    missing = [c for c in FUNDAMENTALS_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"fundamentals frame missing columns: {missing}")
    if df.empty:
        return df
    if df["filed_at"].isna().any():
        raise SchemaError("fundamentals rows must all carry filed_at (point-in-time)")
    return df.sort_values(["metric", "filed_at"]).reset_index(drop=True)
