"""Construction as data (roadmap 18.1) — known answers for every construction option.

The load-bearing one is legacy equivalence: a default spec must yield exactly the book
``certify`` always built (``dropna → sort_values → head(top_n)`` at equal weight), so no
certified or rejected number can move when 18.2 routes the referee through this module.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.research import construct, gates
from heimdall.research.certify import cohort_turnover
from heimdall.research.spec import SignalSpec, count_free_params, score
from heimdall.screener.model import Predicate


def _spec(**kw: object) -> SignalSpec:
    base: dict[str, object] = {
        "name": "t",
        "family": "f",
        "market": "US",
        "features": {"x": 1.0},
        "top_n": 2,
    }
    base.update(kw)
    return SignalSpec.model_validate(base)


def _cross(n: int = 6, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "symbol": [f"S{i}.US" for i in range(n)],
            "x": rng.normal(size=n),
            "vol_63d": np.linspace(0.1, 0.6, n),
            "market_cap": np.arange(n, 0, -1) * 1e9,  # S0 largest
            "sector": ["A", "A", "A", "B", "B", "C"][:n] + ["C"] * max(n - 6, 0),
            "pe": np.linspace(-5, 20, n),
            "eligible": [True] * n,
        }
    )


# --- legacy equivalence -------------------------------------------------------


def test_default_spec_reproduces_the_legacy_book() -> None:
    cross = _cross(20, seed=3)
    cross.loc[[4, 9], "eligible"] = False
    spec = _spec(top_n=5)
    legacy = cross.assign(s=score(spec, cross)).dropna(subset=["s"])
    legacy_top = list(legacy.sort_values("s", ascending=False).head(5)["symbol"])

    book = construct.construct_book(spec, cross)
    assert list(book.index) == legacy_top
    assert np.allclose(book.to_numpy(), 0.2)
    assert construct.is_equal_weight(spec)
    # pool scores are the legacy scores exactly (same pool, same z-scores)
    pd.testing.assert_series_equal(construct.pool_scores(spec, cross), score(spec, cross))


def test_ranking_ignores_ineligible_and_missing() -> None:
    cross = _cross()
    cross.loc[0, "x"] = 99.0
    cross.loc[0, "eligible"] = False
    cross.loc[1, "x"] = np.nan
    ranked = construct.ranked_symbols(cross, construct.pool_scores(_spec(), cross))
    assert "S0.US" not in ranked and "S1.US" not in ranked


# --- universe tier -------------------------------------------------------------


def test_us_large_tier_is_point_in_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "US_LARGE_N", 3)
    spec = _spec(universe="us_large")
    month1 = _cross()  # caps 6,5,4,3,2,1 (×1e9): tier = S0,S1,S2
    tier1 = month1[construct.universe_mask(spec, month1)]
    assert set(tier1["symbol"]) == {"S0.US", "S1.US", "S2.US"}
    month2 = month1.copy()
    month2.loc[5, "market_cap"] = 10e9  # S5 grows into the tier, S2 drops out
    tier2 = month2[construct.universe_mask(spec, month2)]
    assert set(tier2["symbol"]) == {"S5.US", "S0.US", "S1.US"}


def test_us_large_excludes_ineligible_and_missing_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "US_LARGE_N", 3)
    cross = _cross()
    cross.loc[0, "eligible"] = False  # the largest name fails hygiene → the tier moves down
    cross.loc[1, "market_cap"] = np.nan  # no cap → never in the tier
    tier = cross[construct.universe_mask(_spec(universe="us_large"), cross)]
    assert set(tier["symbol"]) == {"S2.US", "S3.US", "S4.US"}


def test_us_large_needs_market_cap() -> None:
    with pytest.raises(KeyError, match="market_cap"):
        construct.universe_mask(_spec(universe="us_large"), _cross().drop(columns="market_cap"))


def test_scores_are_z_scored_inside_the_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "US_LARGE_N", 3)
    cross = _cross()
    s = construct.pool_scores(_spec(universe="us_large"), cross)
    assert s.notna().sum() == 3
    assert abs(float(s.dropna().mean())) < 1e-12  # standardized within the 3-name pool


# --- filters -------------------------------------------------------------------


def test_filters_restrict_the_pool_and_missing_fails() -> None:
    cross = _cross()
    cross.loc[5, "pe"] = np.nan
    spec = _spec(filters=[Predicate(field="pe", op=">", value=0)])
    pool = cross[construct.pool_mask(spec, cross)]
    # pe = -5, 0, 5, 10, 15, NaN → only 5, 10, 15 pass (0 is not > 0; NaN fails)
    assert set(pool["symbol"]) == {"S2.US", "S3.US", "S4.US"}


# --- weighting -----------------------------------------------------------------


def test_inverse_vol_known_answer_and_fallback() -> None:
    cross = pd.DataFrame(
        {"symbol": ["A", "B", "C"], "vol_63d": [0.1, 0.2, np.nan], "x": [3.0, 2.0, 1.0]}
    )
    spec = _spec(top_n=2, weighting="inverse_vol")
    w = construct.weights_for(spec, cross, ["A", "B"])
    assert w["A"] == pytest.approx(2 / 3) and w["B"] == pytest.approx(1 / 3)
    # C's missing vol takes the mean raw weight of A and B (10 and 5 → 7.5)
    w3 = construct.weights_for(spec, cross, ["A", "B", "C"])
    assert w3.to_dict() == pytest.approx({"A": 10 / 22.5, "B": 5 / 22.5, "C": 7.5 / 22.5})
    assert not construct.is_equal_weight(spec)


# --- sector cap ----------------------------------------------------------------


def test_sector_cap_redistributes_pro_rata() -> None:
    w = pd.Series(0.25, index=["a1", "a2", "a3", "b1"])
    sec = pd.Series({"a1": "A", "a2": "A", "a3": "A", "b1": "B"})
    out = construct.cap_sectors(w, sec, 0.5)
    assert out[["a1", "a2", "a3"]].sum() == pytest.approx(0.5)
    assert out["b1"] == pytest.approx(0.5)
    assert out.sum() == pytest.approx(1.0)


def test_sector_cap_cascades_until_every_sector_fits() -> None:
    # A holds 0.6 → capped to 0.4; its excess pushes B over the cap too; C absorbs the rest.
    w = pd.Series({"a1": 0.3, "a2": 0.3, "b1": 0.35, "c1": 0.05})
    sec = pd.Series({"a1": "A", "a2": "A", "b1": "B", "c1": "C"})
    out = construct.cap_sectors(w, sec, 0.4)
    totals = out.groupby(sec).sum()
    assert (totals <= 0.4 + 1e-9).all()
    assert out.sum() == pytest.approx(1.0)


def test_infeasible_sector_cap_leaves_cash() -> None:
    w = pd.Series(0.5, index=["a1", "a2"])
    out = construct.cap_sectors(w, pd.Series({"a1": "A", "a2": "A"}), 0.3)
    assert out.sum() == pytest.approx(0.3)  # the other 70% is cash, never re-inflated


def test_missing_sector_counts_as_unknown() -> None:
    w = pd.Series(0.25, index=["u1", "u2", "u3", "a1"])
    sec = pd.Series({"u1": None, "u2": np.nan, "u3": None, "a1": "A"})
    out = construct.cap_sectors(w, sec, 0.5)
    assert out[["u1", "u2", "u3"]].sum() == pytest.approx(0.5)


# --- rank buffer ---------------------------------------------------------------


def test_buffered_members_known_answer() -> None:
    ranked = ["a", "b", "c", "d", "e"]
    # d (rank 4 ≤ exit 4) is kept; x no longer ranks → dropped; a fills the free seat.
    assert construct.buffered_members(ranked, {"d", "x"}, top_n=2, exit_rank=4) == ["a", "d"]
    # e (rank 5 > exit 4) falls out.
    assert construct.buffered_members(ranked, {"e", "a"}, top_n=2, exit_rank=4) == ["a", "b"]
    # fewer ranked names than top_n: take them all
    assert construct.buffered_members(["a"], {"a"}, top_n=3, exit_rank=5) == ["a"]


def test_members_without_prev_is_plain_top_n() -> None:
    spec = _spec(top_n=2, exit_rank=4)
    assert construct.members(spec, ["a", "b", "c"], None) == ["a", "b"]
    assert construct.members(spec, ["a", "b", "c"], set()) == ["a", "b"]


def test_buffer_cuts_turnover_on_a_churny_panel() -> None:
    rng = np.random.default_rng(7)
    n, months = 60, 36
    base = rng.normal(size=n)
    plain, buffered = _spec(top_n=10), _spec(top_n=10, exit_rank=20)
    sets_plain: list[set[str]] = []
    sets_buf: list[set[str]] = []
    prev: set[str] | None = None
    for _ in range(months):
        cross = pd.DataFrame(
            {
                "symbol": [f"S{i}" for i in range(n)],
                "x": base + rng.normal(scale=0.8, size=n),  # persistent signal + monthly noise
                "eligible": True,
            }
        )
        sets_plain.append(set(construct.construct_book(plain, cross).index))
        book = construct.construct_book(buffered, cross, prev)
        prev = set(book.index)
        sets_buf.append(prev)
    assert np.mean(cohort_turnover(sets_buf)) < np.mean(cohort_turnover(sets_plain))
    assert all(len(s) == 10 for s in sets_buf)


# --- overlay -------------------------------------------------------------------


def test_overlay_cash_known_answer() -> None:
    idx = pd.bdate_range("2020-01-01", periods=250)
    rising = pd.Series(np.linspace(100, 200, 250), index=idx)
    falling = pd.Series(np.linspace(200, 100, 250), index=idx)
    spec = _spec(overlay="spy_sma200_cash")
    assert construct.overlay_cash(spec, rising, idx[-1]) is False  # above its SMA
    assert construct.overlay_cash(spec, falling, idx[-1]) is True  # below its SMA
    assert construct.overlay_cash(spec, falling, idx[150]) is False  # < 200 bars: invested
    assert construct.overlay_cash(_spec(), falling, idx[-1]) is False  # no overlay
    # only bars ≤ t count: a crash after t must not move the decision at t
    crash = rising.copy()
    crash.iloc[-10:] = 1.0
    assert construct.overlay_cash(spec, crash, idx[-11]) is False


# --- spec validation + hashing -------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "match"),
    [
        ({"universe": "us_small"}, "universe must be"),
        ({"weighting": "cap"}, "weighting must be"),
        ({"overlay": "vix"}, "overlay must be"),
        ({"max_sector_weight": 0.0}, "max_sector_weight"),
        ({"max_sector_weight": 1.5}, "max_sector_weight"),
        ({"exit_rank": 2}, "must exceed top_n"),
        ({"universe": "us_large", "market": "Taiwan"}, "US tier"),
        ({"filters": [Predicate(field="fwd_6m_rel", op=">", value=0)]}, "label leakage"),
        ({"filters": [Predicate(field="pe", op=">", value=0, enabled=False)]}, "disabled"),
    ],
)
def test_construction_validators(kw: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _spec(**kw)


def test_default_construction_does_not_change_the_hash() -> None:
    explicit = _spec(
        universe="",
        filters=[],
        weighting="",
        max_sector_weight=None,
        exit_rank=None,
        overlay="",
    )
    assert explicit.canonical_hash() == _spec().canonical_hash()


@pytest.mark.parametrize(
    "kw",
    [
        {"universe": "us_large"},
        {"filters": [Predicate(field="pe", op=">", value=0)]},
        {"weighting": "inverse_vol"},
        {"max_sector_weight": 0.3},
        {"exit_rank": 4},
        {"overlay": "spy_sma200_cash"},
    ],
)
def test_each_construction_choice_changes_the_hash(kw: dict[str, object]) -> None:
    assert _spec(**kw).canonical_hash() != _spec().canonical_hash()


def test_count_free_params_counts_features_and_discloses_structure() -> None:
    n, structural = count_free_params(_spec(features={"x": 1.0, "y": -1.0}))
    assert (n, structural) == (2, {})
    n, structural = count_free_params(_spec(weighting="inverse_vol", exit_rank=4))
    assert n == 1
    assert structural == {"weighting": "inverse_vol", "exit_rank": 4}
