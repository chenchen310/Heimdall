"""US free feature batch (roadmap 18.12) — known answers and point-in-time guards.

``max_ret_21d`` (lottery demand, −), ``beta_252d`` (betting-against-beta, −),
``ind_mom_6m`` (industry momentum, +), ``f_score`` (Piotroski, +) with ``f_score_n``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from heimdall.data.base import DataProvider
from heimdall.data.providers.edgar import _normalize_companyfacts
from heimdall.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from heimdall.data.symbols import Symbol
from heimdall.factors.metrics import (
    add_industry_momentum,
    beta_252d,
    piotroski_f_score,
    snapshot_row,
)
from heimdall.screener.snapshot import build_snapshot, fetch_benchmarks


def _ohlcv(close: np.ndarray, start: str = "2023-01-02") -> pd.DataFrame:
    c = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "date": pd.bdate_range(start, periods=len(c)),
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "adj_close": c,
            "volume": 1_000_000.0,
            "currency": "USD",
            "provider": "t",
            "fetched_at": pd.Timestamp("2024-01-01"),
        }
    )[OHLCV_COLUMNS]


# --- max_ret_21d -------------------------------------------------------------------


def test_max_ret_21d_is_the_largest_recent_up_day() -> None:
    close = np.full(60, 100.0)
    close[50] = 110.0  # +10% on day 50 (within the last 21 returns), back down next day
    close[51:] = 110.0
    close[20] = 150.0  # an older, bigger spike outside the window
    row = snapshot_row(
        "X.US", _ohlcv(close), pd.DataFrame(columns=FUNDAMENTALS_COLUMNS), date(2024, 6, 1)
    )
    assert row["max_ret_21d"] == pytest.approx(0.10)
    short = snapshot_row(
        "X.US",
        _ohlcv(np.full(15, 1.0)),
        pd.DataFrame(columns=FUNDAMENTALS_COLUMNS),
        date(2024, 6, 1),
    )
    assert np.isnan(short["max_ret_21d"])  # type: ignore[arg-type]


# --- beta_252d -------------------------------------------------------------------------


def _bench_and_stock(n: int = 300, k: float = 2.0) -> tuple[pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(1)
    b_ret = rng.normal(0.0005, 0.01, n)
    days = pd.bdate_range("2023-01-02", periods=n)
    bench = pd.Series(100 * np.cumprod(1 + b_ret), index=days)
    stock = 50 * np.cumprod(1 + k * b_ret)
    return bench, _ohlcv(stock)


def test_beta_known_answer() -> None:
    bench, stock = _bench_and_stock()
    as_of = stock["date"].iloc[-1].date()
    assert beta_252d(stock, bench, as_of) == pytest.approx(2.0)


def test_beta_ignores_benchmark_bars_after_as_of() -> None:
    bench, stock = _bench_and_stock(n=320)
    as_of = stock["date"].iloc[299].date()
    before = beta_252d(stock, bench, as_of)
    shocked = bench.copy()
    shocked.iloc[300:] *= 3.0  # a benchmark jump after the decision date
    assert beta_252d(stock, shocked, as_of) == pytest.approx(before)
    assert np.isnan(beta_252d(stock, bench, stock["date"].iloc[200].date()))  # < 252 returns


def test_snapshot_row_beta_is_opt_in() -> None:
    bench, stock = _bench_and_stock()
    empty = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)
    as_of = stock["date"].iloc[-1].date()
    assert "beta_252d" not in snapshot_row("X.US", stock, empty, as_of)
    assert snapshot_row("X.US", stock, empty, as_of, benchmark=bench)["beta_252d"] == pytest.approx(
        2.0
    )


# --- Piotroski F-score ---------------------------------------------------------------------


def _fund(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": "X.US",
            "metric": [r[0] for r in rows],
            "statement": "all",
            "period": "annual",
            "fiscal_end": pd.to_datetime([r[1] for r in rows]),
            "filed_at": pd.to_datetime([r[2] for r in rows]),
            "value": [r[3] for r in rows],
            "currency": "USD",
            "provider": "edgar",
            "fetched_at": pd.Timestamp("2025-01-01"),
        }
    )[FUNDAMENTALS_COLUMNS]


def _two_years() -> list[tuple[str, str, str, float]]:
    y0, y1 = "2022-12-31", "2023-12-31"
    f0, f1 = "2023-02-15", "2024-02-15"
    prior = {
        "net_income": 5,
        "cfo": 6,
        "assets": 100,
        "long_term_debt": 30,
        "current_assets": 40,
        "current_liabilities": 20,
        "shares_outstanding": 10,
        "gross_profit": 30,
        "revenue": 100,
    }
    # Every check improves in the latest year …
    latest = {
        "net_income": 10,
        "cfo": 12,
        "assets": 100,
        "long_term_debt": 20,
        "current_assets": 50,
        "current_liabilities": 20,
        "shares_outstanding": 10,
        "gross_profit": 40,
        "revenue": 110,
    }
    return [(m, y0, f0, float(v)) for m, v in prior.items()] + [
        (m, y1, f1, float(v)) for m, v in latest.items()
    ]


def test_f_score_known_answer() -> None:
    out = piotroski_f_score(_fund(_two_years()), date(2024, 6, 1))
    assert out == {"f_score": 9.0, "f_score_n": 9.0}


def test_f_score_partial_and_point_in_time() -> None:
    rows = [r for r in _two_years() if r[0] not in ("current_assets", "current_liabilities")]
    out = piotroski_f_score(_fund(rows), date(2024, 6, 1))
    assert out == {"f_score": 8.0, "f_score_n": 8.0}  # the current-ratio check is not evaluable
    # Before the FY2023 10-K is filed, only FY2022 is known: no prior year ⇒ only the
    # three level checks (ROA > 0, CFO > 0, CFO > NI) are evaluable.
    early = piotroski_f_score(_fund(_two_years()), date(2024, 1, 31))
    assert early == {"f_score": 3.0, "f_score_n": 3.0}
    none = piotroski_f_score(_fund([]), date(2024, 6, 1))
    assert np.isnan(none["f_score"]) and none["f_score_n"] == 0.0


def test_f_score_missing_debt_tag_means_no_debt() -> None:
    rows = [r for r in _two_years() if r[0] != "long_term_debt"]
    out = piotroski_f_score(_fund(rows), date(2024, 6, 1))
    assert out["f_score_n"] == 9.0  # 0/100 vs 0/100: evaluable, and not a decrease
    assert out["f_score"] == 8.0


# --- industry momentum --------------------------------------------------------------------


def test_industry_momentum_known_answer_and_guards() -> None:
    frame = pd.DataFrame(
        {
            "symbol": [f"T{i}.US" for i in range(6)]
            + [f"F{i}.US" for i in range(3)]
            + ["U0.US", "2330.TW"]
            + [f"{i}.TW" for i in range(1101, 1105)],
            "sector": ["Tech"] * 6 + ["Finance"] * 3 + ["Unknown", "Tech"] + ["Tech"] * 4,
            "ret_6m": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6] + [0.0] * 3 + [9.0, 1.0] + [1.0] * 4,
        }
    )
    out = add_industry_momentum(frame).set_index("symbol")["ind_mom_6m"]
    assert out["T0.US"] == pytest.approx(0.35)  # US Tech: mean of the 6 US names only
    assert np.isnan(out["F0.US"])  # a 3-name group is too small
    assert np.isnan(out["U0.US"])  # Unknown sector
    assert out["2330.TW"] == pytest.approx(1.0)  # TW "Tech" is its own group (5 names)
    assert "ind_mom_6m" not in add_industry_momentum(frame.drop(columns="sector")).columns


# --- EDGAR tags + snapshot wiring ---------------------------------------------------------


def test_edgar_normalizes_current_assets_and_liabilities() -> None:
    fact: dict[str, Any] = {
        "end": "2023-12-31",
        "val": 50,
        "fp": "FY",
        "form": "10-K",
        "filed": "2024-02-01",
    }
    facts = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "AssetsCurrent": {"units": {"USD": [fact]}},
                "LiabilitiesCurrent": {"units": {"USD": [{**fact, "val": 20}]}},
            }
        },
    }
    df = _normalize_companyfacts(facts, Symbol("X", "US"))
    got = dict(zip(df["metric"], df["value"], strict=True))
    assert got == {"current_assets": 50.0, "current_liabilities": 20.0}


class _Prices(DataProvider):
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return self._frames[symbol]


class _NoFund(DataProvider):
    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        return pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)


def test_build_snapshot_carries_beta_and_industry_momentum() -> None:
    bench, stock = _bench_and_stock()
    frames = {f"S{i}.US": stock.assign(symbol=f"S{i}.US") for i in range(5)}
    frames["SPY.US"] = _ohlcv(bench.to_numpy()).assign(symbol="SPY.US")
    as_of = stock["date"].iloc[-1].date()
    prices = _Prices(frames)
    benches = fetch_benchmarks(prices, list(frames)[:5], as_of)
    assert set(benches) == {"US"}
    snap = build_snapshot(
        list(frames)[:5],
        prices,
        _NoFund(),
        as_of,
        sector_map={s: "Tech" for s in frames},
        benchmarks=benches,
    )
    assert snap["beta_252d"].to_numpy() == pytest.approx([2.0] * 5)
    assert snap["ind_mom_6m"].notna().all()
