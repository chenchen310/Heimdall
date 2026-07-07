"""SignalSpec + registry (roadmap 8.1) — signals as data with an enforced lifecycle.

The hash-stability tests pin what pre-registration commits to; the transition
tests pin the lifecycle graph (terminal states stay terminal — resurrection is
a new version); the attempts tests pin the 3-per-family OOS budget.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.research import registry
from heimdall.research.spec import SignalSpec, load_spec, score


def _spec(**overrides: object) -> SignalSpec:
    base: dict[str, object] = {
        "name": "us-mom-v1",
        "family": "us-momentum",
        "market": "US",
        "version": 1,
        "features": {"ret_12_1": 1.0, "vol_63d": -0.5},
    }
    base.update(overrides)
    return SignalSpec.model_validate(base)


# --- spec: canonical hash -----------------------------------------------------


def test_hash_ignores_feature_order_and_description() -> None:
    a = _spec(features={"ret_12_1": 1.0, "vol_63d": -0.5}, description="momentum")
    b = _spec(features={"vol_63d": -0.5, "ret_12_1": 1.0}, description="totally different prose")
    assert a.canonical_hash() == b.canonical_hash()


def test_hash_changes_with_meaning() -> None:
    a = _spec()
    assert a.canonical_hash() != _spec(features={"ret_12_1": 1.0, "vol_63d": -0.4}).canonical_hash()
    assert a.canonical_hash() != _spec(top_n=10).canonical_hash()
    assert a.canonical_hash() != _spec(version=2).canonical_hash()


def test_spec_roundtrips_through_json(tmp_path: Path) -> None:
    a = _spec()
    path = tmp_path / "spec.json"
    path.write_text(a.model_dump_json())
    assert load_spec(path) == a
    assert load_spec(path).canonical_hash() == a.canonical_hash()


# --- spec: validation guards --------------------------------------------------


def test_forward_label_features_are_rejected() -> None:
    with pytest.raises(ValidationError, match="label leakage"):
        _spec(features={"fwd_6m_rel": 1.0})


def test_zero_or_nonfinite_weights_and_empty_features_rejected() -> None:
    with pytest.raises(ValidationError, match="finite and nonzero"):
        _spec(features={"ret_12_1": 0.0})
    with pytest.raises(ValidationError, match="finite and nonzero"):
        _spec(features={"ret_12_1": float("nan")})
    with pytest.raises(ValidationError, match="at least one feature"):
        _spec(features={})


def test_unknown_market_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown market"):
        _spec(market="JP")


# --- spec: scoring ------------------------------------------------------------


def _cross() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "a": [1.0, 2.0, 3.0, 4.0, 100.0],
            "b": [4.0, 3.0, 2.0, 1.0, 0.0],
            "eligible": [True, True, True, True, False],
        }
    )


def test_score_known_answer_and_ineligible_nan() -> None:
    spec = _spec(features={"a": 1.0, "b": -1.0})
    got = score(spec, _cross())
    # Expected: z-scores over the *eligible* pool only, computed independently here.
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([4.0, 3.0, 2.0, 1.0])
    za = (a - a.mean()) / a.std(ddof=1)
    zb = (b - b.mean()) / b.std(ddof=1)
    expected = za - zb
    assert got.iloc[:4].to_numpy() == pytest.approx(expected)
    assert pd.isna(got.iloc[4])  # ineligible rows never rank


def test_score_nan_feature_excludes_row() -> None:
    cross = _cross()
    cross.loc[1, "a"] = float("nan")  # B is missing one feature
    got = score(_spec(features={"a": 1.0, "b": -1.0}), cross)
    assert pd.isna(got.iloc[1])  # missing data excludes, never re-weights
    assert pd.notna(got.iloc[0]) and pd.notna(got.iloc[2])


def test_score_missing_feature_column_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        score(_spec(features={"nope": 1.0}), _cross())


# --- registry: add / get ------------------------------------------------------


def test_add_get_and_duplicate_rejected(tmp_path: Path) -> None:
    spec = _spec()
    entry = registry.add(spec, "signals/specs/us-mom-v1.json", root=tmp_path)
    assert entry["status"] == "draft"
    assert entry["spec_hash"] == spec.canonical_hash()
    with pytest.raises(ValueError, match="already exists"):
        registry.add(spec, "signals/specs/us-mom-v1.json", root=tmp_path)
    registry.add(_spec(version=2), "signals/specs/us-mom-v2.json", root=tmp_path)
    assert registry.get("us-mom-v1", root=tmp_path)["version"] == 2  # latest by default
    assert registry.get("us-mom-v1", version=1, root=tmp_path)["version"] == 1


# --- registry: lifecycle ------------------------------------------------------


def test_legal_path_draft_registered_certified(tmp_path: Path) -> None:
    registry.add(_spec(), "p.json", root=tmp_path)
    registry.transition("us-mom-v1", 1, "registered", root=tmp_path)
    entry = registry.transition(
        "us-mom-v1",
        1,
        "certified",
        cert_report="signals/certifications/x.json",
        oos_attempt=1,
        root=tmp_path,
    )
    assert entry["status"] == "certified"
    assert entry["cert_report"] == "signals/certifications/x.json"
    assert entry["oos_attempts_family"] == 1
    registry.transition("us-mom-v1", 1, "under_review", root=tmp_path)
    registry.transition("us-mom-v1", 1, "retired", root=tmp_path)


@pytest.mark.parametrize(
    ("path", "to"),
    [
        ([], "certified"),  # draft cannot skip pre-registration
        ([], "retired"),
        (["registered"], "under_review"),
        (["registered", "rejected"], "registered"),  # rejected is terminal
        (["registered", "certified", "under_review", "retired"], "certified"),  # retired too
    ],
)
def test_illegal_transitions_raise(tmp_path: Path, path: list[str], to: str) -> None:
    registry.add(_spec(), "p.json", root=tmp_path)
    for step in path:
        kw = {"cert_report": "r.json"} if step in {"certified", "rejected"} else {}
        registry.transition("us-mom-v1", 1, step, root=tmp_path, **kw)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="illegal transition"):
        registry.transition("us-mom-v1", 1, to, cert_report="r.json", root=tmp_path)


def test_certification_outcomes_require_report(tmp_path: Path) -> None:
    registry.add(_spec(), "p.json", root=tmp_path)
    registry.transition("us-mom-v1", 1, "registered", root=tmp_path)
    with pytest.raises(ValueError, match="requires the certification report"):
        registry.transition("us-mom-v1", 1, "certified", root=tmp_path)
    with pytest.raises(ValueError, match="requires the certification report"):
        registry.transition("us-mom-v1", 1, "rejected", root=tmp_path)


def test_failed_transition_does_not_save(tmp_path: Path) -> None:
    registry.add(_spec(), "p.json", root=tmp_path)
    with pytest.raises(ValueError, match="illegal transition"):
        registry.transition("us-mom-v1", 1, "certified", cert_report="r.json", root=tmp_path)
    assert registry.get("us-mom-v1", root=tmp_path)["status"] == "draft"  # unchanged on disk


# --- registry: the OOS budget -------------------------------------------------


def test_family_attempts_increment_persist_and_cap(tmp_path: Path) -> None:
    assert registry.family_attempts("us-momentum", root=tmp_path) == 0
    assert registry.spend_attempt("us-momentum", root=tmp_path) == 1
    assert registry.spend_attempt("us-momentum", root=tmp_path) == 2
    assert registry.family_attempts("us-momentum", root=tmp_path) == 2  # persisted
    assert registry.spend_attempt("us-momentum", root=tmp_path) == 3
    with pytest.raises(ValueError, match="exhausted"):
        registry.spend_attempt("us-momentum", root=tmp_path)
    assert registry.family_attempts("other-family", root=tmp_path) == 0  # budgets are per family
