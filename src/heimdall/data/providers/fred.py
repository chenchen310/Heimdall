"""FRED macro provider (Federal Reserve Economic Data).

Feeds the macro/rate-sensitivity lenses (Two Sigma, Citadel). Needs a free
``FRED_API_KEY``. The client is injectable so ``_normalize_series`` and the
provider can be tested without a key or network.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd

from heimdall.data.base import MacroProvider, NotSupported
from heimdall.data.schema import MACRO_COLUMNS

# A few commonly used series, for discoverability (Two Sigma / Citadel personas).
COMMON_SERIES: dict[str, str] = {
    "GDP": "Gross Domestic Product",
    "CPIAUCSL": "CPI (all urban consumers)",
    "UNRATE": "Unemployment rate",
    "FEDFUNDS": "Effective federal funds rate",
    "T10Y2Y": "10Y–2Y Treasury spread",
    "DGS10": "10-Year Treasury yield",
}


class FredProvider(MacroProvider):
    """Macro series via ``fredapi``."""

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        self._client = client  # inject a fake/real Fred for tests
        self._api_key = api_key or os.environ.get("FRED_API_KEY")

    def _fred(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise NotSupported("FRED requires FRED_API_KEY (set it in .env)")
        from fredapi import Fred  # imported lazily so the dep is optional

        self._client = Fred(api_key=self._api_key)
        return self._client

    def get_series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        raw = self._fred().get_series(
            series_id,
            observation_start=start.isoformat() if start else None,
            observation_end=end.isoformat() if end else None,
        )
        return _normalize_series(raw, series_id)


def _normalize_series(raw: pd.Series, series_id: str) -> pd.DataFrame:
    """Convert a date-indexed FRED Series into canonical ``[series_id, date, value]``."""
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=MACRO_COLUMNS)
    out = raw.rename("value").reset_index()
    out.columns = ["date", "value"]
    out["date"] = pd.to_datetime(out["date"])
    out["series_id"] = series_id
    return out[MACRO_COLUMNS].dropna(subset=["value"]).reset_index(drop=True)
