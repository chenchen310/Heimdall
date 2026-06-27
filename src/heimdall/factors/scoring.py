"""Multi-factor scoring (RenTech lens).

Each factor blends a few canonical metrics, **cross-sectionally** z-scored within
the universe (so factors are comparable), then mapped to a 0–100 percentile. The
composite is a weighted blend. Direction ``-1`` means "smaller is better" (e.g.
a low P/E is good value). See ``docs/ARCHITECTURE.md`` §6.

Validate a factor with ``factors.validate`` (IC / quantile spread) *before*
trusting it in a backtest — see ``.claude/rules/backtest-honesty.md``.
"""

from __future__ import annotations

import pandas as pd

# factor name -> list of (snapshot column, direction). +1: higher is better.
FACTORS: dict[str, list[tuple[str, int]]] = {
    "value": [("pe", -1), ("ps", -1), ("fcf_yield", +1)],
    "quality": [("roe", +1), ("net_margin", +1), ("gross_margin", +1), ("debt_to_equity", -1)],
    "momentum": [("ret_3m", +1), ("ret_6m", +1), ("ret_12m", +1)],
    "growth": [("revenue_growth_yoy", +1)],
}
FACTOR_NAMES: list[str] = list(FACTORS)
DEFAULT_WEIGHTS: dict[str, float] = {"value": 1.0, "quality": 1.0, "momentum": 1.0, "growth": 1.0}


def _zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score, winsorized to ±3 to tame outliers."""
    std = s.std()
    if not std or pd.isna(std):
        return pd.Series(float("nan"), index=s.index)
    return ((s - s.mean()) / std).clip(-3, 3)


def _percentile_0_100(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100.0


def _factor_z(cross: pd.DataFrame, inputs: list[tuple[str, int]]) -> pd.Series:
    """Mean of directional z-scores over a factor's input columns (skips missing)."""
    parts = [direction * _zscore(cross[col]) for col, direction in inputs if col in cross.columns]
    if not parts:
        return pd.Series(float("nan"), index=cross.index)
    return pd.concat(parts, axis=1).mean(axis=1, skipna=True)


def factor_scores(
    cross_section: pd.DataFrame, weights: dict[str, float] | None = None
) -> pd.DataFrame:
    """Add ``{factor}_score`` (0–100) and ``composite_score`` to one cross-section.

    Normalization is *within this cross-section* (one date's universe), so call it
    per rebalance date for a panel. Returns a copy.
    """
    w = weights or DEFAULT_WEIGHTS
    out = cross_section.copy()

    factor_z: dict[str, pd.Series] = {}
    for name, inputs in FACTORS.items():
        z = _factor_z(out, inputs)
        factor_z[name] = z
        out[f"{name}_score"] = _percentile_0_100(z)

    weighted = [w.get(name, 0.0) * z for name, z in factor_z.items()]
    composite_z = pd.concat(weighted, axis=1).mean(axis=1, skipna=True)
    out["composite_score"] = _percentile_0_100(composite_z)
    return out
