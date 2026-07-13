"""FinMind paced crawler (roadmap 13.7) — ledger idempotency + quota backoff, no network.

Every test drives :func:`crawl` with a fake provider that counts calls and can be
scripted to raise canned 402/403 quota errors, and injects ``sleep``/``monotonic``
so there are no real waits. The load-bearing DoD guarantees: an interrupt-then-rerun
makes **zero** duplicate calls, and a quota/ban backs off and retries rather than
crashing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pandas as pd

from heimdall.data.base import NotSupported, ProviderError
from heimdall.research.finmind_crawl import (
    CrawlProgress,
    crawl,
    ledger_path,
    load_cached_stream,
    stream_cache_path,
)


class _FakeFinMind:
    """Counts calls per (method, symbol); optionally scripts failures per symbol."""

    def __init__(self, *, fail: dict[str, list[Exception]] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail or {}  # symbol -> queue of exceptions to raise before succeeding

    def _serve(self, method: str, symbol: str) -> pd.DataFrame:
        self.calls.append((method, symbol))
        queue = self._fail.get(symbol)
        if queue:
            raise queue.pop(0)
        return pd.DataFrame({"symbol": [symbol], "value": [1.0]})

    def monthly_revenue(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._serve("revenue", symbol)

    def daily_chips(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._serve("chips", symbol)

    def daily_lending(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._serve("lending", symbol)

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        return self._serve("fundamentals", symbol)


def _drive(it: Iterator[CrawlProgress]) -> CrawlProgress:
    prog = CrawlProgress(total=0)
    for prog in it:  # noqa: B007 — the same instance is mutated and re-yielded
        pass
    return prog


def _no_sleep(_seconds: float) -> None:
    return None


def test_crawl_caches_each_item_and_writes_the_ledger(tmp_path: Path) -> None:
    fake = _FakeFinMind()
    prog = _drive(
        crawl(
            ["1101.TW", "2330.TW"],
            fake,  # type: ignore[arg-type]
            datasets=("revenue", "chips"),
            root=tmp_path,
            sleep=_no_sleep,
        )
    )
    assert prog.finished and prog.done == 4 and prog.ok == 4
    assert len(fake.calls) == 4  # one call per (symbol, dataset)
    # A Parquet per (dataset, symbol), plus a populated ledger.
    assert stream_cache_path("revenue", "1101.TW", tmp_path).exists()
    assert stream_cache_path("chips", "2330.TW", tmp_path).exists()
    assert ledger_path(tmp_path).exists()
    got = load_cached_stream("revenue", "1101.TW", root=tmp_path)
    assert got["symbol"].tolist() == ["1101.TW"]


def test_rerun_makes_zero_duplicate_calls(tmp_path: Path) -> None:
    fake = _FakeFinMind()
    args = (["1101.TW", "2330.TW", "2317.TW"],)
    kwargs = {"datasets": ("revenue",), "root": tmp_path, "sleep": _no_sleep}
    _drive(crawl(*args, fake, **kwargs))  # type: ignore[arg-type]
    assert len(fake.calls) == 3

    # A second full run is a complete no-op: every item is already in the ledger.
    fake2 = _FakeFinMind()
    prog = _drive(crawl(*args, fake2, **kwargs))  # type: ignore[arg-type]
    assert fake2.calls == []  # ZERO duplicate calls
    assert prog.cached == 3 and prog.done == 0


def test_interrupt_midway_then_rerun_completes_without_duplicates(tmp_path: Path) -> None:
    # Consume only the first two yields (simulating a Ctrl-C after ~2 items), then
    # start a brand-new crawl: already-completed items are skipped, the rest fetched.
    fake = _FakeFinMind()
    it = crawl(
        ["A.TW", "B.TW", "C.TW", "D.TW"],
        fake,  # type: ignore[arg-type]
        datasets=("revenue",),
        root=tmp_path,
        sleep=_no_sleep,
    )
    next(it)
    next(it)
    done_first = len(fake.calls)
    it.close()  # interrupt

    fake2 = _FakeFinMind()
    prog = _drive(
        crawl(
            ["A.TW", "B.TW", "C.TW", "D.TW"],
            fake2,  # type: ignore[arg-type]
            datasets=("revenue",),
            root=tmp_path,
            sleep=_no_sleep,
        )
    )
    # No symbol is fetched twice across the two runs; all four end up cached.
    assert done_first + len(fake2.calls) == 4
    assert prog.finished
    for sym in ("A.TW", "B.TW", "C.TW", "D.TW"):
        assert stream_cache_path("revenue", sym, tmp_path).exists()


def test_quota_ban_backs_off_and_retries_the_same_item(tmp_path: Path) -> None:
    waited: list[float] = []
    # 2330.TW's first attempt hits a 402 quota error, then a 403 ip-ban, then succeeds.
    fake = _FakeFinMind(
        fail={
            "2330.TW": [
                ProviderError("FinMind quota reached — set FINMIND_TOKEN"),
                ProviderError("FinMind 403 for TaiwanStockMonthRevenue"),
            ]
        }
    )
    prog = _drive(
        crawl(
            ["2330.TW"],
            fake,  # type: ignore[arg-type]
            datasets=("revenue",),
            root=tmp_path,
            ban_seconds=1600.0,
            sleep=waited.append,
        )
    )
    assert waited == [1600.0, 1600.0]  # two bans, each a full window wait
    assert prog.bans == 2 and prog.ok == 1 and prog.failed == 0
    assert stream_cache_path("revenue", "2330.TW", tmp_path).exists()  # eventually cached


def test_non_quota_error_is_recorded_not_retried(tmp_path: Path) -> None:
    waited: list[float] = []
    fake = _FakeFinMind(fail={"BAD.TW": [NotSupported("no data for BAD.TW")] * 5})
    prog = _drive(
        crawl(
            ["BAD.TW", "OK.TW"],
            fake,  # type: ignore[arg-type]
            datasets=("revenue",),
            root=tmp_path,
            sleep=waited.append,
        )
    )
    assert waited == []  # a genuine failure never triggers a quota backoff
    assert prog.failed == 1 and prog.ok == 1
    # BAD.TW attempted exactly once (not retried); it is recorded so a rerun skips it.
    assert [c for c in fake.calls if c[1] == "BAD.TW"] == [("revenue", "BAD.TW")]
    assert not stream_cache_path("revenue", "BAD.TW", tmp_path).exists()


def test_hourly_budget_pauses_until_the_window_resets(tmp_path: Path) -> None:
    waited: list[float] = []
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    # budget 2/hr, 3 revenue items (cost 1 each): the 3rd must wait out the hour.
    fake = _FakeFinMind()
    _drive(
        crawl(
            ["A.TW", "B.TW", "C.TW"],
            fake,  # type: ignore[arg-type]
            datasets=("revenue",),
            root=tmp_path,
            budget_per_hour=2,
            sleep=waited.append,
            monotonic=fake_monotonic,
        )
    )
    assert waited == [3600.0]  # exactly one window wait before the 3rd call
    assert len(fake.calls) == 3


def test_load_cached_stream_missing_is_empty(tmp_path: Path) -> None:
    assert load_cached_stream("revenue", "NONE.TW", root=tmp_path).empty
