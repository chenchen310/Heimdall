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
