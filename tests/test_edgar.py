"""Golden test: EDGAR companyfacts JSON → canonical tidy-long fundamentals (no network)."""

from __future__ import annotations

from typing import Any

from heimdall.data.providers.edgar import _normalize_companyfacts
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.symbols import Symbol


def _fact(end: str, val: object, fp: str, filed: str, form: str = "10-K") -> dict[str, Any]:
    return {"end": end, "val": val, "fp": fp, "form": form, "filed": filed}


_FACTS: dict[str, Any] = {
    "cik": 320193,
    "entityName": "Test Co",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        _fact("2022-12-31", 100, "FY", "2023-02-01"),
                        _fact("2023-12-31", 120, "FY", "2024-02-01"),
                        _fact("2023-03-31", 30, "Q1", "2023-04-15", form="10-Q"),
                        _fact("2023-12-31", None, "FY", "2024-02-01"),  # dropped (no val)
                    ]
                }
            },
            "NetIncomeLoss": {"units": {"USD": [_fact("2023-12-31", 20, "FY", "2024-02-01")]}},
            "CommonStockSharesOutstanding": {
                "units": {"shares": [_fact("2023-12-31", 1000, "FY", "2024-02-01")]}
            },
        }
    },
}


def test_normalize_companyfacts() -> None:
    df = _normalize_companyfacts(_FACTS, Symbol("AAPL", "US"))

    assert list(df.columns) == FUNDAMENTALS_COLUMNS
    assert df["symbol"].unique().tolist() == ["AAPL.US"]
    assert df["provider"].unique().tolist() == ["edgar"]
    # the None-valued fact is dropped; 3 revenue rows remain (2 annual, 1 quarter)
    rev = df[df["metric"] == "revenue"]
    assert len(rev) == 3
    assert set(rev["period"]) == {"annual", "quarter"}
    # share counts mapped from the 'shares' unit; statement classified
    assert "shares_outstanding" in set(df["metric"])
    assert df.loc[df["metric"] == "net_income", "statement"].iloc[0] == "income"


def test_every_row_is_point_in_time() -> None:
    df = _normalize_companyfacts(_FACTS, Symbol("AAPL", "US"))
    assert df["filed_at"].notna().all()  # the load-bearing invariant
    assert df["filed_at"].dtype.kind == "M"  # datetime
