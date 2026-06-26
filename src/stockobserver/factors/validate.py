"""Factor validation — information coefficient and quantile spread.

The IC is the per-period Spearman rank correlation between the factor and the
forward return (averaged across periods); the quantile spread is the
top-minus-bottom bucket forward return. Computed directly so it's robust on small
universes; ``alphalens_ic`` offers the alphalens-reloaded path for richer tear
sheets. Validate *before* backtesting — see ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FactorIC:
    mean_ic: float
    ic_std: float
    t_stat: float
    hit_rate: float  # share of periods with IC > 0
    n_periods: int


def information_coefficient(
    panel: pd.DataFrame, factor_col: str = "composite_score", fwd_col: str = "fwd_return"
) -> FactorIC:
    """Per-period rank IC summarized across rebalance dates."""
    clean = panel.dropna(subset=[factor_col, fwd_col])
    ics: list[float] = []
    for _, grp in clean.groupby("date"):
        if grp[factor_col].nunique() < 3:
            continue
        ic = grp[factor_col].corr(grp[fwd_col], method="spearman")
        if pd.notna(ic):
            ics.append(float(ic))

    if not ics:
        return FactorIC(float("nan"), float("nan"), float("nan"), float("nan"), 0)
    arr = np.array(ics)
    std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    t = float(arr.mean() / (std / np.sqrt(len(arr)))) if std > 0 else float("nan")
    return FactorIC(float(arr.mean()), std, t, float((arr > 0).mean()), len(arr))


def quantile_spread(
    panel: pd.DataFrame,
    factor_col: str = "composite_score",
    fwd_col: str = "fwd_return",
    q: int = 3,
) -> pd.Series:
    """Mean forward return per factor quantile (averaged across periods).

    Index runs low→high factor; a monotone, positive-sloping series with a
    positive top-minus-bottom gap is the encouraging shape.
    """
    clean = panel.dropna(subset=[factor_col, fwd_col])
    per_period: list[pd.Series] = []
    for _, grp in clean.groupby("date"):
        if len(grp) < q:
            continue
        buckets = pd.qcut(grp[factor_col].rank(method="first"), q, labels=False)
        per_period.append(grp.groupby(buckets)[fwd_col].mean())

    if not per_period:
        return pd.Series(dtype="float64")
    out = pd.concat(per_period, axis=1).mean(axis=1)
    out.index = [f"Q{i + 1}" for i in range(len(out))]
    return out


def alphalens_ic(
    panel: pd.DataFrame, prices: pd.DataFrame, periods: tuple[int, ...] = (21,), quantiles: int = 3
) -> pd.DataFrame | None:
    """Optional: IC via alphalens-reloaded. Returns None if the data is too sparse."""
    import alphalens as al

    factor = (
        panel.rename(columns={"symbol": "asset"})
        .set_index(["date", "asset"])["composite_score"]
        .dropna()
    )
    try:
        fd = al.utils.get_clean_factor_and_forward_returns(
            factor, prices, periods=periods, quantiles=quantiles, max_loss=1.0
        )
        return cast("pd.DataFrame", al.performance.factor_information_coefficient(fd))
    except (ValueError, KeyError):
        return None
