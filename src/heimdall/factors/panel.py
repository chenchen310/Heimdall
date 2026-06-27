"""Historical factor panel — point-in-time cross-sections over rebalance dates.

At each rebalance date, metrics are computed from only the data knowable then
(prices up to the date; fundamentals filed on/before it — reusing
``snapshot_row``), then scored cross-sectionally. Forward returns to the next
rebalance feed factor validation and the portfolio backtest.

NOTE: over a *current* universe this still carries **survivorship bias** — treat
results as an optimistic upper bound. See ``.claude/rules/data-discipline.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import cast

import pandas as pd

from heimdall.data.base import DataProvider
from heimdall.factors.metrics import snapshot_row
from heimdall.factors.scoring import factor_scores


@dataclass(frozen=True)
class PanelData:
    panel: pd.DataFrame  # long: date, symbol, metrics, *_score, composite_score, fwd_return
    prices: pd.DataFrame  # wide daily adj_close (date x symbol)
    rebalance_dates: list[pd.Timestamp]


def _prices_wide(price_hist: dict[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {sym: df.set_index("date")["adj_close"] for sym, df in price_hist.items()}
    return pd.DataFrame(cols).sort_index().ffill()


def _rebalance_dates(
    index: pd.DatetimeIndex, start: date, end: date, freq: str
) -> list[pd.Timestamp]:
    """Last trading day of each period in ``[start, end]``."""
    labels = pd.Series(1, index=index).resample(freq).last().index
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    out: list[pd.Timestamp] = []
    for label in labels:
        prior = index[index <= label]
        if len(prior):
            out.append(prior[-1])
    return sorted({d for d in out if s <= d <= e})


def build_panel(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    start: date,
    end: date,
    freq: str = "ME",
    min_bars: int = 200,
    weights: dict[str, float] | None = None,
) -> PanelData:
    """Build the point-in-time factor panel and the wide price frame."""
    price_start = start - timedelta(days=500)
    price_hist: dict[str, pd.DataFrame] = {}
    fund_data: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        ohlcv = prices.get_ohlcv(sym, price_start, end)
        if ohlcv.empty:
            continue
        price_hist[sym] = ohlcv
        fund_data[sym] = fundamentals.get_fundamentals(sym, "all", "annual")

    if not price_hist:
        return PanelData(pd.DataFrame(), pd.DataFrame(), [])

    wide = _prices_wide(price_hist)
    rebal = _rebalance_dates(cast("pd.DatetimeIndex", wide.index), start, end, freq)
    fwd = wide.reindex(rebal).shift(-1) / wide.reindex(rebal) - 1.0  # to next rebalance

    frames: list[pd.DataFrame] = []
    for d in rebal:
        rows = [
            snapshot_row(sym, ohlcv[ohlcv["date"] <= d], fund_data[sym], d.date())
            for sym, ohlcv in price_hist.items()
            if (ohlcv["date"] <= d).sum() >= min_bars
        ]
        if not rows:
            continue
        cross = factor_scores(pd.DataFrame(rows), weights)
        cross["date"] = d
        cross["fwd_return"] = [
            fwd.loc[d, s] if s in fwd.columns else float("nan") for s in cross["symbol"]
        ]
        frames.append(cross)

    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return PanelData(panel, wide, list(rebal))
