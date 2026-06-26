"""Two Sigma macro: indicators, signals, and regime read (no network/key)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from stockobserver.analytics.macro import macro_dashboard
from stockobserver.data.base import MacroProvider

# Inverted curve (-0.5) + restrictive policy (5.0) → late-cycle.
_VALUES = {
    "T10Y2Y": [0.5, 0.0, -0.5],
    "FEDFUNDS": [3.0, 4.5, 5.0],
    "CPIAUCSL": [290.0, 300.0, 315.0],
    "UNRATE": [3.5, 3.8, 4.2],
    "DGS10": [3.5, 4.0, 4.3],
    "GDPC1": [20000.0, 20500.0, 21000.0],
}


class _FakeMacro(MacroProvider):
    def get_series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        idx = pd.to_datetime(["2024-06-01", "2025-01-01", "2025-06-01"])
        return pd.DataFrame(
            {"series_id": series_id, "date": idx, "value": _VALUES.get(series_id, [1.0, 1.0, 1.0])}
        )


def test_signals_and_regime() -> None:
    rep = macro_dashboard(_FakeMacro())
    assert len(rep.indicators) == 6
    assert any("inverted" in s for s in rep.signals)  # T10Y2Y < 0
    assert any("Restrictive" in s for s in rep.signals)  # fed funds > 4
    assert rep.regime == "Late cycle / slowdown risk"
