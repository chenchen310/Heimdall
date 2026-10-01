"""Roadmap 18.22: declared composites in scoring (playbook §12.6, RESEARCH_LOG 024).

Pins the declaration (members, directions, hashes), checks a hand-computed known answer, the
NaN and neutralization rules, the one-parameter counting, hash embedding, the validators, the
fast-path equivalence, and that the panel path and the live Today path score identically.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.research import composites, construct, factory
from heimdall.research.evaluate import evaluate
from heimdall.research.spec import (
    SignalSpec,
    _sector_zscore,
    count_free_params,
    score,
    term_z,
)
from heimdall.research.today import eligibility, todays_picks

MOM = "cmp:momentum"
MEMBERS = ["ret_12_1", "pct_of_52w_high", "ind_mom_6m"]


def _spec(**kw: object) -> SignalSpec:
    base: dict[str, object] = {"name": "c", "family": "f", "market": "US", "features": {MOM: 1.0}}
    return SignalSpec.model_validate({**base, **kw})


# --- the declaration ------------------------------------------------------------------------


def test_the_declaration_is_exactly_entry_024() -> None:
    got = {name: dict(c.members) for name, c in composites.COMPOSITES.items()}
    assert got == {
        "value": {"pe": -1, "ps": -1, "fcf_yield": 1},
        "profitability": {"roe": 1, "operating_margin": 1, "fcf_margin": 1},
        "investment": {"asset_growth": -1, "share_dilution_yoy": -1},
        "momentum": {"ret_12_1": 1, "pct_of_52w_high": 1, "ind_mom_6m": 1},
        "low_risk": {"beta_252d": -1, "vol_63d": -1, "max_ret_21d": -1},
    }
    assert len(composites.COMPOSITES) <= composites.MAX_PER_DECLARATION
    assert {c.log_entry for c in composites.COMPOSITES.values()} == {"024"}


def test_declarations_are_hash_pinned() -> None:
    # Editing a member or a direction changes these: that is a new name and a new declaration
    # (playbook §12.6 rule 4), never an edit.
    pins = {
        "value": "9cfb62f36894260e0f27876045514427558b9c9e7306fc8be3375781146df7b4",
        "profitability": "d43bfe0dc5058b0400709d954cc8b984074fd1e05c5f474bdd1f0b93f7facb8b",
        "investment": "be209e89fca09f68e1b1850a184ecda5c1ca261e4008f7bc40e00b0960ccbef3",
        "momentum": "44317651b7cba685ece080e7f79f54fba9979c149962b6b66297620bb3a4e112",
        "low_risk": "0ab1bd24b9bcbd32d56158744c04fd82ce8593302eda5dcda828ca5639d18f06",
    }
    assert {n: c.canonical_hash() for n, c in composites.COMPOSITES.items()} == pins


def test_members_carry_their_documented_directions() -> None:
    # Every member is a documented, live-available feature of the us-f1 pool (entry 021), with
    # the same a-priori direction — composites never re-sign a feature.
    root = Path(__file__).resolve().parents[1]
    pool = json.loads((root / "signals/search/us-f1/config.json").read_text())["feature_pool"]
    for comp in composites.COMPOSITES.values():
        for feat, sign in comp.members:
            assert pool[feat] == sign, (comp.name, feat)


# --- scoring --------------------------------------------------------------------------------


def _cross() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [f"S{i}" for i in range(6)],
            "ret_12_1": [0.30, 0.10, -0.05, 0.20, 0.00, -0.20],
            "pct_of_52w_high": [0.95, 0.80, 0.70, 0.90, 0.85, 0.60],
            "ind_mom_6m": [0.05, 0.02, 0.01, -0.01, 0.03, 0.00],
            "sector": ["A", "A", "A", "B", "B", "B"],
            "market_cap": [1e9, 2e9, 3e9, 4e9, 5e9, 6e9],
            "eligible": True,
        }
    )


def _z(x: np.ndarray) -> np.ndarray:
    return np.clip((x - x.mean()) / x.std(ddof=1), -3, 3)


def test_known_answer_three_member_composite() -> None:
    cross = _cross()
    members = [_z(cross[c].to_numpy(dtype=float)) for c in MEMBERS]  # all directions +1
    expected = _z(np.mean(members, axis=0))
    assert score(_spec(), cross).to_numpy() == pytest.approx(expected, abs=1e-12)


def test_a_missing_member_scores_nan() -> None:
    cross = _cross()
    cross.loc[2, "ind_mom_6m"] = np.nan
    out = score(_spec(), cross)
    assert np.isnan(out.loc[2]) and out.drop(index=2).notna().all()
    with pytest.raises(KeyError, match="pct_of_52w_high"):
        score(_spec(), cross.drop(columns="pct_of_52w_high"))


def test_neutralized_composite_is_the_composite_of_neutralized_members() -> None:
    cross = pd.concat([_cross(), _cross().assign(symbol=lambda d: d["symbol"] + "b")])
    cross = cross.reset_index(drop=True)
    parts = [_sector_zscore(cross[c], cross["sector"]) for c in MEMBERS]
    manual = pd.concat(parts, axis=1).mean(axis=1)
    want = (manual - manual.mean()) / manual.std()
    got = score(_spec(neutralize="sector"), cross)
    assert got.to_numpy() == pytest.approx(want.clip(-3, 3).to_numpy(), abs=1e-12)
    assert term_z(MOM, cross, "sector").equals(got)


def test_one_parameter_per_composite_with_members_disclosed() -> None:
    spec = _spec(features={MOM: 1.0, "cmp:value": 1.0, "vol_63d": -1.0})
    n, structural = count_free_params(spec)
    assert n == 3
    assert structural["composites"] == {
        MOM: {"ret_12_1": 1, "pct_of_52w_high": 1, "ind_mom_6m": 1},
        "cmp:value": {"pe": -1, "ps": -1, "fcf_yield": 1},
    }


def test_spec_hash_embeds_the_composite_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec()
    before, recipe = spec.canonical_hash(), spec.recipe_hash()
    changed = composites.Composite(
        "momentum", (("ret_12_1", 1), ("pct_of_52w_high", 1)), "x", "2099-01-01", "999"
    )
    monkeypatch.setitem(composites.COMPOSITES, "momentum", changed)
    assert spec.canonical_hash() != before and spec.recipe_hash() != recipe


def test_validators_accept_only_declared_composites_with_positive_weight() -> None:
    with pytest.raises(ValidationError, match="not declared"):
        _spec(features={"cmp:quality_junk": 1.0})
    with pytest.raises(ValidationError, match="positive"):
        _spec(features={MOM: -1.0})
    base = {"run_id": "c1", "universes": [""]}
    with pytest.raises(ValidationError, match=r"\+1"):
        factory.SearchConfig.model_validate({**base, "feature_pool": {MOM: -1}})
    with pytest.raises(ValidationError, match="not declared"):
        factory.SearchConfig.model_validate({**base, "feature_pool": {"cmp:nope": 1}})
    assert factory.SearchConfig.model_validate({**base, "feature_pool": {MOM: 1}})


# --- the factory fast path and the live path ------------------------------------------------


def _panel(n_syms: int = 90, end: str = "2014-12-31", seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.date_range("2010-01-31", end, freq="BME")
    state = rng.normal(size=(4, n_syms))
    rows: list[dict[str, object]] = []
    for t in months:
        state = 0.9 * state + np.sqrt(1 - 0.81) * rng.normal(size=state.shape)
        edge = 0.004 * state[:3].mean(axis=0)
        rel1 = edge + rng.normal(0, 0.02, n_syms)
        rel6 = 6 * edge + rng.normal(0, 0.05, n_syms)
        for i in range(n_syms):
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:03d}.US",
                    "eligible": bool(i % 17 != 0),
                    "ret_12_1": state[0, i],
                    "pct_of_52w_high": state[1, i],
                    "ind_mom_6m": state[2, i] if i % 11 else np.nan,  # sparse member
                    "vol_63d": 0.1 + 0.3 * abs(state[3, i]),
                    "market_cap": float(np.exp(22 + state[3, i])),
                    "sector": ["E", "F", "H", "T", "R"][i % 5],
                    "fwd_1m_rel": rel1[i],
                    "fwd_1m": rel1[i] + 0.008,
                    "fwd_6m_rel": rel6[i],
                    "fwd_6m": rel6[i] + 0.05,
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    "construction",
    [
        {},
        {"neutralize": "sector"},
        {"neutralize": "sector_size", "weighting": "rank_linear", "exit_rank": 20},
        {"features": {MOM: 1.0, "vol_63d": -1.0}, "weighting": "inverse_vol"},
    ],
)
def test_fast_path_reproduces_evaluate_on_composite_specs(construction: dict[str, object]) -> None:
    panel = _panel()
    cfg = factory.SearchConfig.model_validate(
        {
            "run_id": "c1",
            "feature_pool": {MOM: 1, "vol_63d": -1},
            "universes": [""],
            "neutralize_menu": ["", "sector", "sector_size"],
        }
    )
    spec = _spec(top_n=10, **construction)
    fast = factory.evaluate_fast(spec, factory.prepare(panel, cfg))
    ref = evaluate(spec, panel, ("2010-01-01", "2019-12-31"))
    for got, want in [
        (fast.ic_mean, ref.ic_mean),
        (fast.ic_t, ref.ic_t),
        (fast.spread_mean, ref.spread_mean),
        (fast.alpha_mean, ref.selection_alpha_mean),
        (fast.alpha_t, ref.selection_alpha_t),
        (fast.turnover, ref.mean_turnover),
    ]:
        assert got == pytest.approx(want, abs=1e-10, nan_ok=True)
    assert fast.n_cohorts == ref.n_cohorts


def test_panel_scoring_equals_live_today_scoring() -> None:
    # The same cross-section, scored the way certify/evaluate do (construct.pool_scores on rows
    # with an eligible flag) and the way the live Today page does (todays_picks on a snapshot).
    panel = _panel(end="2010-03-31")
    month = panel[panel["date"] == panel["date"].max()].reset_index(drop=True)
    snap = month.drop(columns=["eligible"]).assign(
        as_of=date(2010, 3, 31), price=50.0, dollar_vol_21d=1e8
    )
    snap.loc[snap.index % 13 == 0, "dollar_vol_21d"] = 1.0  # some names fail liquidity
    spec = _spec(neutralize="sector_size", top_n=15)
    live = todays_picks(spec, snap)
    panel_cross = snap.assign(eligible=eligibility(snap, "US")["eligible"].to_numpy())
    panel_scores = construct.pool_scores(spec, panel_cross)
    by_symbol = pd.Series(panel_scores.to_numpy(), index=panel_cross["symbol"])
    assert len(live) == 15
    assert live["signal_score"].to_numpy() == pytest.approx(
        by_symbol.loc[live["symbol"]].to_numpy(), abs=1e-12
    )
    assert list(live["symbol"]) == construct.ranked_symbols(panel_cross, panel_scores)[:15]
    # The live table explains a composite by its z and its members' raw values.
    assert {f"z_{MOM}", *MEMBERS} <= set(live.columns)
    assert live[f"z_{MOM}"].to_numpy() == pytest.approx(live["signal_score"].to_numpy())
