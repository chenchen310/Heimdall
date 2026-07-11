"""Golden test: EDGAR companyfacts JSON → canonical tidy-long fundamentals (no network)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from heimdall.data.providers.edgar import _normalize_companyfacts
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.symbols import Symbol


def _fact(
    end: str, val: object, fp: str, filed: str, form: str = "10-K", start: str | None = None
) -> dict[str, Any]:
    fact: dict[str, Any] = {"end": end, "val": val, "fp": fp, "form": form, "filed": filed}
    if start is not None:
        fact["start"] = start
    return fact


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
            # 17.3: GrossProfit exercises the duration-span filter in isolation from the
            # `Revenues` assertions above.
            "GrossProfit": {
                "units": {
                    "USD": [
                        # A Q2 10-Q files BOTH the discrete 3-month fact (91d) and the
                        # year-to-date 6-month fact (181d) under the same end/fp/filed —
                        # only the discrete one may survive.
                        _fact(
                            "2023-06-30", 35, "Q2", "2023-08-01", form="10-Q", start="2023-04-01"
                        ),
                        _fact(
                            "2023-06-30", 65, "Q2", "2023-08-01", form="10-Q", start="2023-01-01"
                        ),
                        # A properly year-length (364d) FY fact — survives the annual bound.
                        _fact("2023-12-31", 140, "FY", "2024-02-01", start="2023-01-01"),
                        # The mirror trap: FY-tagged but quarter-length (92d) span — dropped
                        # entirely, never reclassified as a quarter row.
                        _fact("2021-12-31", 999, "FY", "2022-02-01", start="2021-10-01"),
                    ]
                }
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


def test_normalize_companyfacts_drops_ytd_and_mistagged_duration_facts() -> None:
    """roadmap 17.3: the YTD trap (a Q2 fact pair) and the FY-mirror trap."""
    df = _normalize_companyfacts(_FACTS, Symbol("AAPL", "US"))
    gp = df[df["metric"] == "gross_profit"]

    # Only the discrete 3-month Q2 fact survives — the 181-day YTD twin is dropped, not
    # arbitrarily deduped against it.
    q2 = gp[(gp["period"] == "quarter") & (gp["fiscal_end"] == "2023-06-30")]
    assert len(q2) == 1
    assert q2["value"].iloc[0] == 35

    # The genuine year-length FY fact survives the annual bound.
    fy = gp[(gp["period"] == "annual") & (gp["fiscal_end"] == "2023-12-31")]
    assert len(fy) == 1
    assert fy["value"].iloc[0] == 140

    # The FY-tagged but quarter-length "mirror trap" fact is dropped entirely — not kept as
    # an annual row (wrong span) and not reclassified as a quarter row (wrong bucket).
    assert not (gp["fiscal_end"] == pd.Timestamp("2021-12-31")).any()
