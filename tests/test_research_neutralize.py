"""Roadmap 18.18: ``neutralize="sector_size"`` — sector and size removed from every feature.

The known answer: a feature built as a·log(cap) + a sector effect + ε, with ε exactly
orthogonal to the sector dummies and log(cap), must rank exactly as ε after neutralization.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.factors.scoring import _zscore
from heimdall.research.spec import SignalSpec, feature_z, score
from heimdall.research.today import _construction_columns


def _spec(**kw: object) -> SignalSpec:
    base: dict[str, object] = {"name": "t", "family": "f", "market": "US", "features": {"x": 1.0}}
    return SignalSpec.model_validate({**base, **kw})


def _cross(seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    """60 names in 3 sectors; returns the cross-section and the orthogonal ε it hides."""
    rng = np.random.default_rng(seed)
    n = 60
    sector = np.array(["A", "B", "C"] * (n // 3))
    logcap = rng.uniform(20.0, 26.0, n)
    design = np.column_stack([(sector == s).astype(float) for s in ("A", "B", "C")] + [logcap])
    raw = rng.normal(0.0, 1.0, n)
    beta, *_ = np.linalg.lstsq(design, raw, rcond=None)
    eps = raw - design @ beta  # exactly orthogonal to the dummies and log(cap)
    effect = pd.Series(sector).map({"A": 1.0, "B": -1.0, "C": 3.0}).to_numpy()
    x = 2.0 * logcap + effect + eps
    cross = pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(n)],
            "sector": sector,
            "market_cap": np.exp(logcap),
            "x": x,
            "eligible": True,
        }
    )
    return cross, eps


def test_sector_size_ranks_exactly_as_the_hidden_residual() -> None:
    cross, eps = _cross()
    assert float(_zscore(cross["x"]).abs().max()) < 3.0  # no winsorizing: the map stays linear
    neutral = score(_spec(neutralize="sector_size"), cross)
    order = np.argsort(-eps, kind="stable")
    assert list(np.argsort(-neutral.to_numpy(), kind="stable")) == list(order)
    raw = score(_spec(), cross)
    assert list(np.argsort(-raw.to_numpy(), kind="stable")) != list(order)  # size dominates raw
    # Residual properties: no size left, every sector centred.
    logcap = np.log(cross["market_cap"])
    assert abs(np.corrcoef(neutral, logcap)[0, 1]) < 1e-9
    assert neutral.groupby(cross["sector"]).mean().abs().max() < 1e-9


def test_small_sectors_and_unusable_caps_score_nan() -> None:
    cross, _ = _cross()
    cross.loc[:3, "sector"] = "Tiny"  # 4 names: fewer than 5 ⇒ a dummy would fit them exactly
    cross.loc[10, "market_cap"] = np.nan
    cross.loc[11, "market_cap"] = 0.0
    cross.loc[12, "sector"] = None  # a missing sector is its own "Unknown" level (1 name ⇒ NaN)
    z = feature_z(cross["x"], cross, "sector_size")
    assert z.loc[:3].isna().all() and z.loc[10:12].isna().all()
    assert z.drop(index=[0, 1, 2, 3, 10, 11, 12]).notna().all()


def test_missing_columns_raise_and_the_validator_knows_the_option() -> None:
    cross, _ = _cross()
    with pytest.raises(KeyError, match="market_cap"):
        score(_spec(neutralize="sector_size"), cross.drop(columns="market_cap"))
    with pytest.raises(KeyError, match="sector"):
        score(_spec(neutralize="sector_size"), cross.drop(columns="sector"))
    assert _spec(neutralize="sector_size").neutralize == "sector_size"
    with pytest.raises(ValidationError, match="neutralize"):
        _spec(neutralize="size")
    # The live path asks the snapshot for both columns.
    assert {"sector", "market_cap"} <= _construction_columns(_spec(neutralize="sector_size"))
    assert "market_cap" not in _construction_columns(_spec(neutralize="sector"))


def test_feature_z_is_the_one_home_for_every_neutralization() -> None:
    cross, _ = _cross()
    for nz in ("", "sector", "sector_size"):
        via_score = score(_spec(neutralize=nz), cross)
        assert via_score.equals(feature_z(cross["x"], cross, nz))
