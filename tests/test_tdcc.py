"""TDCC shareholding-dispersion provider: golden normalization (roadmap 13.9).

Fixture rows are a saved excerpt of the real bulk CSV (fetched live 2026-07-11
from opendata.tdcc.com.tw, dataset 1-5, stock 1101/台泥) — DictReader-shaped
(string values, the padded stock_id column exactly as TDCC serves it).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from heimdall.data.providers.tdcc import (
    AVAILABILITY_LAG,
    BIG_HOLDER_LEVELS,
    CANONICAL_COLUMNS,
    cache_path,
    fetch_and_cache_latest_week,
    load_cached_weeks,
    normalize,
)


def _row(
    data_date: str, stock_id: str, level: str, holders: str, shares: str, pct: str
) -> dict[str, str]:
    return {
        "資料日期": data_date,
        "證券代號": stock_id,
        "持股分級": level,
        "人數": holders,
        "股數": shares,
        "占集保庫存數比例%": pct,
    }


# Real excerpt: 1101 (台泥) 2026-07-03, a subset of levels spanning the
# interesting cases (a low tier, the big-holder range 12-15, the always-zero
# 16, and the level-17 total row). The trailing spaces on the stock_id are
# exactly how TDCC pads the column.
_1101_ROWS = [
    _row("20260703", "1101  ", "1", "146195", "20442442", "0.27"),
    _row("20260703", "1101  ", "12", "277", "134616392", "1.78"),
    _row("20260703", "1101  ", "13", "137", "94779841", "1.25"),
    _row("20260703", "1101  ", "14", "94", "85316889", "1.13"),
    _row("20260703", "1101  ", "15", "414", "3808433970", "50.62"),
    _row("20260703", "1101  ", "16", "0", "0", "0.00"),
    _row("20260703", "1101  ", "17", "516224", "7523181742", "100.00"),
]

_MARKET = {"1101": "TW", "6488": "TWO"}


def test_normalize_golden_known_answer() -> None:
    df = normalize(_1101_ROWS, _MARKET)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df["symbol"].unique().tolist() == ["1101.TW"]  # whitespace-padded id resolved + suffixed
    assert df["currency"].unique().tolist() == ["TWD"]
    assert df["provider"].unique().tolist() == ["tdcc"]

    level12 = df[df["level"] == 12].iloc[0]
    assert level12["holders"] == 277
    assert level12["shares"] == pytest.approx(134616392.0)
    assert level12["pct_of_custody"] == pytest.approx(1.78)
    assert level12["data_date"] == pd.Timestamp("2026-07-03")
    assert level12["available_at"] == pd.Timestamp("2026-07-03") + AVAILABILITY_LAG


def test_normalize_drops_the_level_17_total_row() -> None:
    df = normalize(_1101_ROWS, _MARKET)
    assert 17 not in set(df["level"])
    assert len(df) == 6  # 7 input rows minus the one level-17 total row


def test_normalize_drops_unmapped_stock_ids() -> None:
    rows = [*_1101_ROWS, _row("20260703", "0050  ", "1", "1", "100", "1.00")]
    df = normalize(rows, _MARKET)  # "0050" (an ETF) is absent from _MARKET
    assert "0050.TW" not in set(df["symbol"])
    assert "0050.TWO" not in set(df["symbol"])


def test_normalize_resolves_tw_vs_two_from_the_injected_map() -> None:
    rows = [
        _row("20260703", "1101", "1", "1", "1", "0.00"),
        _row("20260703", "6488", "1", "1", "1", "0.00"),
    ]
    df = normalize(rows, _MARKET).set_index("symbol")
    assert "1101.TW" in df.index
    assert "6488.TWO" in df.index


def test_normalize_empty() -> None:
    out = normalize([], _MARKET)
    assert out.empty
    assert list(out.columns) == CANONICAL_COLUMNS


def test_big_holder_levels_are_the_top_four_400_lot_brackets() -> None:
    # 400,000 shares = 400 lots; levels 12-15 cover 400,001 shares and above.
    assert {12, 13, 14, 15} == BIG_HOLDER_LEVELS


# --- weekly cache: fetch/skip/refresh, and concatenating accumulated weeks -----


def test_cache_path_is_keyed_by_data_date(tmp_path: Path) -> None:
    p = cache_path(date(2026, 7, 3), tmp_path)
    assert p == tmp_path / "tdcc" / "shareholding_2026-07-03.parquet"


def test_fetch_and_cache_writes_and_reuses_without_refetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def _fake_fetch() -> list[dict[str, object]]:
        calls["n"] += 1
        return _1101_ROWS

    monkeypatch.setattr("heimdall.data.providers.tdcc.fetch_raw", _fake_fetch)
    first = fetch_and_cache_latest_week(_MARKET, root=tmp_path)
    assert calls["n"] == 1
    assert len(first) == 6
    assert cache_path(date(2026, 7, 3), tmp_path).exists()

    second = fetch_and_cache_latest_week(_MARKET, root=tmp_path)
    assert calls["n"] == 2  # fetch_raw is still called (no date param exists)...
    assert len(second) == 6  # ...but the cached file is returned, not re-derived


def test_fetch_and_cache_refresh_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("heimdall.data.providers.tdcc.fetch_raw", lambda: _1101_ROWS)
    fetch_and_cache_latest_week(_MARKET, root=tmp_path)
    fetch_and_cache_latest_week(_MARKET, root=tmp_path, refresh=True)
    assert len(pd.read_parquet(cache_path(date(2026, 7, 3), tmp_path))) == 6


def test_fetch_and_cache_empty_normalized_result_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("heimdall.data.providers.tdcc.fetch_raw", lambda: [])
    out = fetch_and_cache_latest_week(_MARKET, root=tmp_path)
    assert out.empty
    assert not (tmp_path / "tdcc").exists()  # nothing written — no data_date to key on


def test_load_cached_weeks_concatenates_everything_on_disk(tmp_path: Path) -> None:
    from heimdall.data.providers.tdcc import _save_atomic

    week1 = normalize(_1101_ROWS, _MARKET)
    week2 = week1.copy()
    week2["data_date"] = pd.Timestamp("2026-07-10")
    week2["available_at"] = pd.Timestamp("2026-07-10") + AVAILABILITY_LAG

    _save_atomic(week1, cache_path(date(2026, 7, 3), tmp_path))
    _save_atomic(week2, cache_path(date(2026, 7, 10), tmp_path))

    out = load_cached_weeks(tmp_path)
    assert len(out) == 12  # 6 rows/week x 2 weeks
    dates = set(out["data_date"].unique())
    assert dates == {pd.Timestamp("2026-07-03"), pd.Timestamp("2026-07-10")}


def test_load_cached_weeks_empty_when_nothing_cached(tmp_path: Path) -> None:
    out = load_cached_weeks(tmp_path)
    assert out.empty
    assert list(out.columns) == CANONICAL_COLUMNS
