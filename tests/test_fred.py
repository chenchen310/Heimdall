"""FRED macro provider — normalization and key handling (no network/key)."""

from __future__ import annotations

import pandas as pd
import pytest

from stockobserver.data.base import NotSupported
from stockobserver.data.providers.fred import FredProvider, _normalize_series
from stockobserver.data.schema import MACRO_COLUMNS


class _FakeFred:
    def get_series(self, series_id: str, observation_start=None, observation_end=None) -> pd.Series:
        idx = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"])
        return pd.Series([1.0, 2.0, float("nan")], index=idx)


def test_normalize_series() -> None:
    df = _normalize_series(_FakeFred().get_series("CPIAUCSL"), "CPIAUCSL")
    assert list(df.columns) == MACRO_COLUMNS
    assert len(df) == 2  # the NaN observation is dropped
    assert df["series_id"].unique().tolist() == ["CPIAUCSL"]
    assert df["date"].dtype.kind == "M"


def test_provider_with_injected_client() -> None:
    df = FredProvider(client=_FakeFred()).get_series("UNRATE")
    assert df["series_id"].unique().tolist() == ["UNRATE"]


def test_missing_key_raises_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(NotSupported, match="FRED_API_KEY"):
        FredProvider(api_key=None).get_series("GDP")
