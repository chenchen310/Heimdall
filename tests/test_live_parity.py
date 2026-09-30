"""Live-snapshot parity (roadmap 18.16) — the research panel's US features, computed live.

The load-bearing test builds one month with the panel builder and one snapshot row with the
snapshot builder from the same providers, and asserts every shared feature is equal — the
guarantee that a strategy using these columns scores today exactly as it was backtested.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import DataProvider, NotSupported
from heimdall.data.providers.edgar import SecEdgarProvider
from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.factors.us_features import _INSIDER_KEYS, US_FEATURE_KEYS
from heimdall.research.dataset import build_dataset_iter, load_panel
from heimdall.screener.snapshot import build_row


def _ohlcv(symbol: str, n: int, daily: float, start: str = "2021-01-04") -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(symbol)) % 2**32)
    c = pd.Series(100 * np.cumprod(1 + daily + rng.normal(0, 0.01, n)), dtype=float)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.bdate_range(start, periods=n),
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "adj_close": c,
            "volume": 2_000_000.0,
            "currency": "USD",
            "provider": "t",
            "fetched_at": pd.Timestamp("2024-01-01"),
        }
    )[OHLCV_COLUMNS]


def _f(metric: str, fe: str, filed: str, v: float, period: str = "annual") -> dict[str, Any]:
    return {
        "symbol": "X.US",
        "metric": metric,
        "statement": "all",
        "period": period,
        "fiscal_end": pd.Timestamp(fe),
        "filed_at": pd.Timestamp(filed),
        "value": float(v),
        "currency": "USD",
        "provider": "t",
        "fetched_at": pd.Timestamp("2024-01-01"),
    }


def _annual() -> pd.DataFrame:
    rows = []
    for y, (ni, cfo, a, gp, rev, sh) in {
        2021: (8, 9, 100, 30, 90, 1000),
        2022: (9, 11, 110, 33, 100, 1010),
        2023: (11, 12, 120, 38, 115, 990),
    }.items():
        fe, filed = f"{y}-12-31", f"{y + 1}-02-15"
        rows += [
            _f("net_income", fe, filed, ni),
            _f("cfo", fe, filed, cfo),
            _f("assets", fe, filed, a),
            _f("gross_profit", fe, filed, gp),
            _f("revenue", fe, filed, rev),
            _f("shares_outstanding", fe, filed, sh),
            _f("eps_diluted", fe, filed, ni / 10),
        ]
    return pd.DataFrame(rows)[FUNDAMENTALS_COLUMNS]


def _quarterly() -> pd.DataFrame:
    rows = []
    for k, fe in enumerate(pd.date_range("2020-03-31", "2024-03-31", freq="QE")):
        if fe.month == 12:
            continue  # US files no discrete Q4
        filed = (fe + pd.Timedelta(days=40)).date().isoformat()
        e = fe.date().isoformat()
        rows += [
            _f("eps_diluted", e, filed, 0.2 + 0.01 * k + (0.05 if k % 3 else 0), "quarter"),
            _f("revenue", e, filed, 20 + k * (1 + 0.1 * k), "quarter"),
            _f("gross_profit", e, filed, 7 + 0.4 * k, "quarter"),
        ]
    return pd.DataFrame(rows)[FUNDAMENTALS_COLUMNS]


def _insider() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "filed_at": pd.to_datetime(["2024-04-10", "2024-05-02", "2024-05-20", "2024-06-03"]),
            "txn_date": pd.to_datetime(["2024-04-08", "2024-04-30", "2024-05-16", "2024-05-31"]),
            "owner_cik": ["1", "2", "3", "1"],
            "owner_name": ["a", "b", "c", "a"],
            "is_officer": [True, True, False, True],
            "is_director": [False, False, True, False],
            "is_ten_pct": False,
            "txn_code": ["P", "P", "P", "S"],
            "acquired_disposed": "A",
            "shares": [1000.0, 500.0, 300.0, 200.0],
            "price_per_share": [50.0, 51.0, 52.0, 55.0],
            "currency": "USD",
            "provider": "t",
            "fetched_at": pd.Timestamp("2024-07-01"),
        }
    )


class _Prices(DataProvider):
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        df = self._frames[symbol]
        return df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]


class _Funds(DataProvider):
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotSupported("no prices")

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        if symbol != "X.US":
            return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
        return _quarterly() if period == "quarter" else _annual()


def _drive(it: Any) -> None:
    for _ in it:
        pass


def test_snapshot_features_equal_the_panel_features(tmp_path: Path) -> None:
    frames = {"SPY.US": _ohlcv("SPY.US", 900, 0.0004), "X.US": _ohlcv("X.US", 900, 0.0006)}
    prices, funds = _Prices(frames), _Funds()
    quarterly = lambda s, a, b: funds.get_fundamentals(s, "income", "quarter")  # noqa: E731
    insider = lambda s, a, b: _insider() if s == "X.US" else pd.DataFrame()  # noqa: E731
    _drive(
        build_dataset_iter(
            ["X.US"],
            prices,
            funds,
            "US",
            date(2024, 6, 1),
            date(2024, 6, 30),
            root=tmp_path,
            min_cross_section=0,
            quarterly_fundamentals=quarterly,
            insider=insider,
        )
    )
    panel_row = load_panel("US", tmp_path).set_index("symbol").loc["X.US"]
    t = pd.Timestamp(panel_row["date"]).date()
    spy = frames["SPY.US"]
    bench = pd.Series(spy["adj_close"].to_numpy(), index=pd.DatetimeIndex(spy["date"]))
    live = build_row(
        "X.US",
        prices,
        funds,
        t,
        benchmarks={"US": bench},
        quarterly_fundamentals=quarterly,
        insider=insider,
    )
    assert live is not None
    keys = [*US_FEATURE_KEYS, *_INSIDER_KEYS, "beta_252d", "f_score", "max_ret_21d"]
    checked = 0
    for k in keys:
        a, b = float(panel_row[k]), float(live[k])  # type: ignore[arg-type]
        assert (np.isnan(a) and np.isnan(b)) or a == pytest.approx(b, rel=1e-12), k
        checked += int(not np.isnan(a))
    assert checked >= 8  # the fixture populates most features (not an all-NaN tautology)


def test_non_us_rows_get_nan_columns_and_no_streams_mean_no_columns() -> None:
    frames = {"2330.TW": _ohlcv("2330.TW", 300, 0.0)}
    q = lambda s, a, b: pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)  # noqa: E731
    tw = build_row(
        "2330.TW",
        _Prices(frames),
        _Funds(),
        date(2022, 2, 1),
        quarterly_fundamentals=q,
        insider=lambda s, a, b: pd.DataFrame(),
    )
    assert tw is not None
    assert all(np.isnan(tw[k]) for k in [*US_FEATURE_KEYS, *_INSIDER_KEYS])  # type: ignore[arg-type]
    plain = build_row("2330.TW", _Prices(frames), _Funds(), date(2022, 2, 1))
    assert plain is not None and "sue" not in plain and "insider_net_buy_90d" not in plain


def test_live_insider_is_nan_past_the_bulk_coverage() -> None:
    frames = {"X.US": _ohlcv("X.US", 900, 0.0006)}
    row = build_row(
        "X.US",
        _Prices(frames),
        _Funds(),
        date(2024, 6, 28),
        insider=lambda s, a, b: _insider(),
        insider_coverage_end=pd.Timestamp("2024-03-31"),
    )
    assert row is not None and all(np.isnan(row[k]) for k in _INSIDER_KEYS)  # type: ignore[arg-type]


# --- EDGAR freshness ------------------------------------------------------------------------


def _edgar(tmp_path: Path, max_age: float | None) -> tuple[SecEdgarProvider, Path]:
    (tmp_path / "edgar").mkdir(exist_ok=True)
    (tmp_path / "edgar" / "company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 7, "ticker": "X", "title": "X"}})
    )
    cache = tmp_path / "edgar" / "companyfacts_0000000007.json"
    cache.write_text(json.dumps({"cik": 7, "facts": {}, "v": "old"}))
    return SecEdgarProvider(root=tmp_path, max_age_days=max_age), cache


def _age(path: Path, days: float) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_edgar_refreshes_a_stale_cache_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heimdall.data.symbols import parse_symbol

    calls: list[str] = []

    def fake_get(self: SecEdgarProvider, url: str) -> dict[str, Any]:
        calls.append(url)
        return {"cik": 7, "facts": {}, "v": "new"}

    monkeypatch.setattr(SecEdgarProvider, "_get_json", fake_get)
    research, cache = _edgar(tmp_path, None)
    _age(cache, 90)
    assert research._companyfacts(parse_symbol("X.US"))["v"] == "old"  # research: never refresh
    live, cache = _edgar(tmp_path, 7)
    _age(cache, 3)
    assert live._companyfacts(parse_symbol("X.US"))["v"] == "old" and not calls  # fresh enough
    live, cache = _edgar(tmp_path, 7)
    _age(cache, 30)
    assert live._companyfacts(parse_symbol("X.US"))["v"] == "new" and len(calls) == 1
    assert json.loads(cache.read_text())["v"] == "new"  # atomically replaced


def test_edgar_falls_back_to_the_stale_cache_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    from heimdall.data.symbols import parse_symbol

    def offline(self: SecEdgarProvider, url: str) -> dict[str, Any]:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(SecEdgarProvider, "_get_json", offline)
    live, cache = _edgar(tmp_path, 7)
    _age(cache, 30)
    assert live._companyfacts(parse_symbol("X.US"))["v"] == "old"
