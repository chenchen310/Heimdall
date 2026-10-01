"""Roadmap 17.11: FINRA short interest → canonical rows → days-to-cover features (no network).

The records mirror the real ``consolidatedShortInterest`` payload (probed 2026-10-01): field
names, ``marketClassCode`` values, ``stockSplitFlag`` and ``revisionFlag`` exactly as served.
"""

from __future__ import annotations

import gzip
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import NotSupported
from heimdall.data.providers import finra
from heimdall.factors.us_features import SHORT_INTEREST_KEYS, short_interest_features


def _rec(sym: str, settle: str, short: float, adv: float, cls: str = "NNM", **kw: Any) -> dict:
    return {
        "symbolCode": sym,
        "settlementDate": settle,
        "marketClassCode": cls,
        "currentShortPositionQuantity": short,
        "averageDailyVolumeQuantity": adv,
        "stockSplitFlag": kw.get("split"),
        "revisionFlag": kw.get("revision"),
    }


def test_normalize_cycle_golden() -> None:
    records = [
        _rec("AAPL", "2026-09-15", 110_000_000, 50_000_000),
        _rec("ZZOTC", "2026-09-15", 5_000, 1_000, cls="OTC"),  # OTC: not our universe
        _rec("BRK.B", "2026-09-15", 9_000_000, 4_000_000, cls="NYSE"),
        _rec("SPLT", "2026-09-15", 300, 100, cls="NYSE", split="S"),
        _rec("NOVOL", "2026-09-15", 300, 0, cls="ARCA", revision="R"),
        _rec("NEG", "2026-09-15", -5, 100, cls="NYSE"),  # impossible: dropped on ingest
        _rec("(N/A)", "2026-09-15", 5, 100, cls="NYSE"),  # junk symbol
        _rec("AAPL", "2026-09-15", 1, 1),  # duplicate: first published value wins
    ]
    stamp = datetime(2026, 10, 1)
    df = finra.normalize_cycle(records, stamp)
    assert list(df.columns) == finra.SHORT_INTEREST_COLUMNS
    assert df["symbol"].tolist() == ["AAPL.US", "BRK-B.US", "SPLT.US", "NOVOL.US"]
    aapl = df.iloc[0]
    assert aapl["settlement_date"] == pd.Timestamp("2026-09-15")
    # Never the settlement date: 10 weekdays later (FINRA's own schedule says 7 business days).
    assert aapl["available_at"] == pd.Timestamp("2026-09-29")
    assert aapl["short_shares"] == 110_000_000 and aapl["avg_daily_volume"] == 50_000_000
    assert not bool(aapl["split_flag"]) and aapl["provider"] == "finra"
    assert bool(df.set_index("symbol").loc["SPLT.US", "split_flag"])
    assert np.isnan(df.set_index("symbol").loc["NOVOL.US", "avg_daily_volume"])


def test_available_at_is_ten_weekdays_after_settlement() -> None:
    assert finra.available_at(pd.Timestamp("2017-12-29")) == pd.Timestamp("2018-01-12")
    assert finra.available_at(pd.Timestamp("2026-09-30")) == pd.Timestamp("2026-10-14")
    assert finra.clean_symbol("brk/b") == "BRK-B" and finra.clean_symbol("free text") == ""


class _FakeApi:
    """Two anchors list three cycles of 2–4 records, served 2 per page."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cycles = {
            "2018-01-12": [_rec("AAPL", "2018-01-12", 10, 5), _rec("MSFT", "2018-01-12", 4, 2)],
            "2018-01-31": [_rec("AAPL", "2018-01-31", 12, 5), _rec("MSFT", "2018-01-31", 4, 4)],
            "2017-12-29": [
                _rec("AAPL", "2017-12-29", 8, 4),
                _rec("MSFT", "2017-12-29", 2, 2),
                _rec("X", "2017-12-29", 1, 1),
                _rec("BRKB", "2017-12-29", 7, 3, cls="NYSE"),
            ],
        }

    def __call__(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(body)
        flt = body["compareFilters"][0]
        if flt["fieldName"] == "symbolCode":
            return [{"settlementDate": d} for d in self.cycles if flt["fieldValue"] == "AAPL"]
        recs = self.cycles.get(flt["fieldValue"], [])
        off = int(body.get("offset", 0))
        return recs[off : off + int(body["limit"])]


def test_ingest_pages_stores_raw_and_is_delta_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(finra, "_PAGE", 2)  # force paging: the 3-record cycle needs two pages
    api = _FakeApi()
    rep = finra.ingest(tmp_path, query=api)
    assert (rep.cycles, rep.new_cycles, rep.first, rep.last) == (3, 3, "2017-12-29", "2018-01-31")
    assert rep.rows == 8
    raw = finra.finra_dir(tmp_path) / "raw" / "2017-12-29.json.gz"
    assert len(json.loads(gzip.decompress(raw.read_bytes()))["records"]) == 4
    assert json.loads(finra.marker_path(tmp_path).read_text())["cycles"] == 3

    api.calls.clear()
    again = finra.ingest(tmp_path, query=api)
    assert again.new_cycles == 0 and again.rows == 8
    assert all(c["compareFilters"][0]["fieldName"] == "symbolCode" for c in api.calls)

    prov = finra.FinraProvider(root=tmp_path)
    got = prov.short_interest("AAPL.US", date(2018, 1, 1), date(2018, 12, 31))
    assert got["settlement_date"].dt.strftime("%m-%d").tolist() == ["01-12", "01-31"]
    assert prov.short_interest("NOPE.US", date(2018, 1, 1), date(2018, 12, 31)).empty
    # FINRA writes share classes without a separator: BRK-B is served from its ``BRKB`` code.
    assert prov.short_interest("X-Y.US", date(2018, 1, 1), date(2018, 12, 31)).empty
    brk = prov.short_interest("BRK-B.US", date(2017, 1, 1), date(2018, 12, 31))
    assert brk["symbol"].tolist() == ["BRK-B.US"] and brk["short_shares"].tolist() == [7.0]
    with pytest.raises(NotSupported):
        prov.short_interest("2330.TW", date(2018, 1, 1), date(2018, 12, 31))
    with pytest.raises(NotSupported):
        prov.get_ohlcv("AAPL.US", date(2018, 1, 1), date(2018, 12, 31))


def _si(cycles: list[tuple[str, float, float]], split: str | None = None) -> pd.DataFrame:
    rows = [_rec("X", d, s, v, split="S" if d == split else None) for d, s, v in cycles]
    return finra.normalize_cycle(rows, datetime(2026, 1, 1))


def _price(end: str, n: int = 200) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.bdate_range(end=end, periods=n)})


def test_days_to_cover_is_point_in_time_on_availability() -> None:
    si = _si(
        [
            ("2024-05-15", 600, 200),  # available 2024-05-29
            ("2024-05-31", 900, 300),  # available 2024-06-14
            ("2024-06-14", 5000, 100),  # settled before 06-20 but available only 06-28
        ]
    )
    out = short_interest_features(si, _price("2024-06-20"), pd.Timestamp("2024-06-20"))
    assert out["short_ratio"] == pytest.approx(3.0)  # 900 / 300: the newest *available* cycle
    later = short_interest_features(si, _price("2024-06-28"), pd.Timestamp("2024-06-28"))
    assert later["short_ratio"] == pytest.approx(50.0)  # now the June 14 cycle is known
    # A cycle published after the date must not move any feature (the PIT leak test).
    early = si[si["available_at"] <= pd.Timestamp("2024-06-20")]
    again = short_interest_features(early, _price("2024-06-20"), pd.Timestamp("2024-06-20"))
    assert pd.Series(again).equals(pd.Series(out))  # NaN-safe equality


def test_delta_staleness_split_and_empty() -> None:
    si = _si([("2024-02-29", 400, 200), ("2024-05-31", 900, 300)])
    price = _price("2024-06-20")
    out = short_interest_features(si, price, pd.Timestamp("2024-06-20"))
    # 63 bars before 2024-06-20 is 2024-03-25: the Feb 29 cycle (available 03-14) applies, 2.0.
    assert pd.Timestamp(price["date"].iloc[-64]) == pd.Timestamp("2024-03-25")
    assert out["short_ratio_delta_63d"] == pytest.approx(3.0 - 2.0)
    # Only the Feb cycle known in mid-May: settled > 35 days earlier ⇒ a feed gap ⇒ NaN.
    gap = short_interest_features(si, _price("2024-05-20"), pd.Timestamp("2024-05-20"))
    assert np.isnan(gap["short_ratio"])
    split = _si([("2024-05-31", 900, 300)], split="2024-05-31")
    assert np.isnan(
        short_interest_features(split, price, pd.Timestamp("2024-06-20"))["short_ratio"]
    )
    empty = short_interest_features(pd.DataFrame(), price, pd.Timestamp("2024-06-20"))
    assert list(empty) == SHORT_INTEREST_KEYS and all(np.isnan(v) for v in empty.values())
