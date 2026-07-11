"""TW market-wide chip cache (roadmap 15.2) — build orchestration, no network.

Covers the load-bearing properties: bulk is tried first and used when available,
refusal (None) falls back to the per-symbol loop, a quota/hard-error mid-loop stops
the loop rather than burning through every remaining symbol, an existing cache file
is reused (never re-fetched) unless ``refresh=True``, and ``load_window`` only ever
concatenates days that actually have a cache file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from heimdall.data.base import DataProvider, ProviderError
from heimdall.data.schema import OHLCV_COLUMNS
from heimdall.research.flows_cache import (
    DAILY_COLUMNS,
    BuildResult,
    build_day,
    flows_cache_path,
    load_window,
)

_D = date(2024, 1, 10)


class _FakeFinMind:
    """Duck-typed FinMindProvider fake — build_day only calls these two methods."""

    def __init__(
        self,
        chips_by_symbol: dict[str, pd.DataFrame] | None = None,
        bulk: pd.DataFrame | None = None,
        raise_on: dict[str, Exception] | None = None,
    ) -> None:
        self._chips = chips_by_symbol or {}
        self._bulk = bulk
        self._raise_on = raise_on or {}
        self.chips_calls: list[str] = []

    def bulk_institutional_by_date(self, d: date) -> pd.DataFrame | None:
        return self._bulk

    def daily_chips(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.chips_calls.append(symbol)
        if symbol in self._raise_on:
            raise self._raise_on[symbol]
        return self._chips.get(symbol, pd.DataFrame())


class _FakePrices(DataProvider):
    def __init__(self, close_by_symbol: dict[str, float]) -> None:
        self._close = close_by_symbol

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if symbol not in self._close:
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        return pd.DataFrame({"date": [pd.Timestamp(end)], "close": [self._close[symbol]]})


def _chips_row(
    symbol: str, d: date, foreign: float, trust: float, dealer: float, hold: float
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "date": pd.Timestamp(d),
                "foreign_net_shares": foreign,
                "trust_net_shares": trust,
                "dealer_net_shares": dealer,
                "foreign_hold_ratio": hold,
            }
        ]
    )


def _bulk_frame(rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stock_id": sid,
                "date": pd.Timestamp(_D),
                "foreign_net_shares": f,
                "trust_net_shares": t,
                "dealer_net_shares": d,
            }
            for sid, f, t, d in rows
        ]
    )


# --- build_day: bulk vs loop ------------------------------------------------------


def test_build_day_uses_bulk_when_available(tmp_path: Path) -> None:
    bulk = _bulk_frame([("2330", 100.0, 10.0, -5.0)])
    finmind = _FakeFinMind(bulk=bulk)
    sectors = {"2330.TW": "半導體業"}
    result = build_day(_D, ["9999.TW"], finmind, _FakePrices({}), sectors, root=tmp_path)
    assert result.source == "bulk"
    assert finmind.chips_calls == []  # loop never ran
    df = pd.read_parquet(flows_cache_path(_D, tmp_path))
    row = df.set_index("symbol").loc["2330.TW"]
    assert row["sector"] == "半導體業"
    assert row["foreign_net_shares"] == 100.0
    assert pd.isna(row["close"])  # bulk mode doesn't reach price/holding data yet


def test_build_day_falls_back_to_loop_when_bulk_refused(tmp_path: Path) -> None:
    finmind = _FakeFinMind(
        chips_by_symbol={"2330.TW": _chips_row("2330.TW", _D, 100.0, 10.0, -5.0, 73.0)},
        bulk=None,  # refused, matching the real free-tier behavior
    )
    result = build_day(
        _D,
        ["2330.TW"],
        finmind,
        _FakePrices({"2330.TW": 600.0}),
        {"2330.TW": "半導體業"},
        root=tmp_path,
    )
    assert result.source == "loop"
    assert finmind.chips_calls == ["2330.TW"]
    df = pd.read_parquet(flows_cache_path(_D, tmp_path))
    row = df.set_index("symbol").loc["2330.TW"]
    assert row["close"] == 600.0
    assert row["foreign_hold_ratio"] == 73.0


def test_from_loop_skips_symbol_with_no_row_for_the_day(tmp_path: Path) -> None:
    finmind = _FakeFinMind(chips_by_symbol={"A.TW": pd.DataFrame(columns=["symbol", "date"])})
    result = build_day(_D, ["A.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    assert result.rows == 0  # no data for A on this date -> not a crash, just absent


def test_from_loop_stops_on_provider_error_but_reaches_earlier_symbols(tmp_path: Path) -> None:
    finmind = _FakeFinMind(
        chips_by_symbol={
            "A.TW": _chips_row("A.TW", _D, 1.0, 1.0, 1.0, 50.0),
            "C.TW": _chips_row("C.TW", _D, 9.0, 9.0, 9.0, 50.0),  # never reached
        },
        raise_on={"B.TW": ProviderError("quota reached")},
    )
    result = build_day(_D, ["A.TW", "B.TW", "C.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    # stopped before C — quota is gone, don't burn through the rest of the universe.
    assert finmind.chips_calls == ["A.TW", "B.TW"]
    assert result.rows == 1  # only A made it in


def test_from_loop_skips_one_bad_symbol_but_continues(tmp_path: Path) -> None:
    finmind = _FakeFinMind(
        chips_by_symbol={"C.TW": _chips_row("C.TW", _D, 9.0, 9.0, 9.0, 50.0)},
        raise_on={"B.TW": ValueError("malformed response")},  # not a ProviderError
    )
    result = build_day(_D, ["B.TW", "C.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    assert finmind.chips_calls == ["B.TW", "C.TW"]  # kept going past the bad symbol
    assert result.rows == 1


# --- build_day: cache reuse ---------------------------------------------------------


def test_build_day_reuses_existing_cache_without_fetching(tmp_path: Path) -> None:
    pre = pd.DataFrame([{"symbol": "X.TW", **{c: float("nan") for c in DAILY_COLUMNS[1:]}}])
    pre["date"] = pd.Timestamp(_D)
    pre["sector"] = "Unknown"
    flows_cache_path(_D, tmp_path).parent.mkdir(parents=True)
    pre[DAILY_COLUMNS].to_parquet(flows_cache_path(_D, tmp_path))

    finmind = _FakeFinMind()  # would raise/crash if actually called
    result = build_day(_D, ["Y.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    assert result.source == "cached"
    assert finmind.chips_calls == []
    assert result.rows == 1  # the pre-existing file's row count, untouched


def test_build_day_refresh_forces_a_rebuild(tmp_path: Path) -> None:
    stale = pd.DataFrame([{"symbol": "OLD.TW", **{c: float("nan") for c in DAILY_COLUMNS[1:]}}])
    stale["date"], stale["sector"] = pd.Timestamp(_D), "Unknown"
    flows_cache_path(_D, tmp_path).parent.mkdir(parents=True)
    stale[DAILY_COLUMNS].to_parquet(flows_cache_path(_D, tmp_path))

    finmind = _FakeFinMind(
        chips_by_symbol={"NEW.TW": _chips_row("NEW.TW", _D, 1.0, 1.0, 1.0, 50.0)}
    )
    result = build_day(
        _D, ["NEW.TW"], finmind, _FakePrices({"NEW.TW": 10.0}), {}, root=tmp_path, refresh=True
    )
    assert result.source == "loop"
    assert finmind.chips_calls == ["NEW.TW"]
    df = pd.read_parquet(flows_cache_path(_D, tmp_path))
    assert df["symbol"].tolist() == ["NEW.TW"]  # the stale file was overwritten, not merged


# --- load_window -------------------------------------------------------------------


def test_load_window_concatenates_only_days_that_exist(tmp_path: Path) -> None:
    finmind = _FakeFinMind(chips_by_symbol={"A.TW": _chips_row("A.TW", _D, 1.0, 1.0, 1.0, 50.0)})
    build_day(_D, ["A.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    two_days_later = date(2024, 1, 12)
    finmind2 = _FakeFinMind(
        chips_by_symbol={"A.TW": _chips_row("A.TW", two_days_later, 2.0, 2.0, 2.0, 51.0)}
    )
    build_day(two_days_later, ["A.TW"], finmind2, _FakePrices({}), {}, root=tmp_path)
    # 2024-01-11 (a Thursday, in between) was never built — load_window must skip it,
    # not error, and still find both real days within its calendar-day search slack.
    out = load_window(two_days_later, n_sessions=2, root=tmp_path)
    assert sorted(out["date"].dt.date.unique()) == [_D, two_days_later]


def test_load_window_gives_up_gracefully_when_too_few_days_exist(tmp_path: Path) -> None:
    finmind = _FakeFinMind(chips_by_symbol={"A.TW": _chips_row("A.TW", _D, 1.0, 1.0, 1.0, 50.0)})
    build_day(_D, ["A.TW"], finmind, _FakePrices({}), {}, root=tmp_path)
    out = load_window(_D, n_sessions=21, root=tmp_path)  # only 1 day was ever built
    assert set(out["date"].dt.date.unique()) == {_D}  # returns what exists, doesn't hang/crash


def test_load_window_no_cache_at_all_is_empty(tmp_path: Path) -> None:
    out = load_window(_D, n_sessions=5, root=tmp_path)
    assert out.empty
    assert list(out.columns) == DAILY_COLUMNS


def test_build_result_is_a_plain_dataclass() -> None:
    r = BuildResult(_D, "loop", 10, 8)
    assert r.date == _D and r.source == "loop" and r.universe_size == 10 and r.rows == 8


def test_flows_cache_path_matches_the_14_2_contract(tmp_path: Path) -> None:
    # This exact name/path is what ui/sector_page.py's _flows_cache_path already expects.
    assert flows_cache_path(date(2026, 7, 10), tmp_path) == (
        tmp_path / "research" / "flows" / "institutional_2026-07-10.parquet"
    )
