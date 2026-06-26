"""Factor panel construction (no network): structure, point-in-time, momentum."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stockobserver.data.base import DataProvider
from stockobserver.data.schema import FUNDAMENTALS_COLUMNS, OHLCV_COLUMNS
from stockobserver.factors.panel import build_panel

_DATES = pd.bdate_range("2022-01-03", periods=300)
_TRENDS = {"A.US": 0.002, "B.US": 0.0, "C.US": -0.001}  # up / flat / down


class FakePrices(DataProvider):
    markets = frozenset({"US"})

    def __init__(self) -> None:
        self._data: dict[str, pd.DataFrame] = {}
        for sym, drift in _TRENDS.items():
            px = 100 * np.exp(drift * np.arange(len(_DATES)))
            self._data[sym] = pd.DataFrame(
                {
                    "symbol": sym,
                    "date": _DATES,
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "adj_close": px,
                    "volume": 1000,
                    "currency": "USD",
                    "provider": "fake",
                    "fetched_at": pd.Timestamp("2022-01-01"),
                },
                columns=OHLCV_COLUMNS,
            )

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        df = self._data[symbol]
        m = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
        return df[m].reset_index(drop=True)


class FakeFund(DataProvider):
    markets = frozenset({"US"})

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError  # fundamentals-only fake

    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame:
        vals = {
            "revenue": 1000.0,
            "net_income": 100.0,
            "equity": 500.0,
            "shares_outstanding": 10.0,
            "cfo": 150.0,
            "capex": 20.0,
            "liabilities": 300.0,
        }
        rows = [
            {
                "symbol": symbol,
                "metric": k,
                "statement": "income",
                "period": "annual",
                "fiscal_end": pd.Timestamp("2021-12-31"),
                "filed_at": pd.Timestamp("2022-02-15"),
                "value": v,
                "currency": "USD",
                "provider": "fake",
                "fetched_at": pd.Timestamp("2022-03-01"),
            }
            for k, v in vals.items()
        ]
        return pd.DataFrame(rows, columns=FUNDAMENTALS_COLUMNS)


def test_panel_structure_and_forward_returns() -> None:
    data = build_panel(
        list(_TRENDS),
        FakePrices(),
        FakeFund(),
        start=date(2022, 10, 1),
        end=date(2022, 12, 31),
        freq="ME",
        min_bars=60,
    )
    assert not data.panel.empty
    for col in ["date", "symbol", "composite_score", "momentum_score", "fwd_return"]:
        assert col in data.panel.columns
    assert len(data.rebalance_dates) >= 2
    # forward return is undefined at the final rebalance date
    last = data.panel[data.panel["date"] == data.rebalance_dates[-1]]
    assert last["fwd_return"].isna().all()


def test_momentum_ranks_uptrend_above_downtrend() -> None:
    data = build_panel(
        list(_TRENDS),
        FakePrices(),
        FakeFund(),
        start=date(2022, 10, 1),
        end=date(2022, 12, 31),
        freq="ME",
        min_bars=60,
    )
    cross = data.panel[data.panel["date"] == data.rebalance_dates[0]].set_index("symbol")
    assert cross.loc["A.US", "momentum_score"] > cross.loc["C.US", "momentum_score"]
