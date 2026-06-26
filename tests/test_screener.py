"""Declarative screener: predicate evaluation, NaN exclusion, ranking, persistence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockobserver.screener import store
from stockobserver.screener.engine import evaluate
from stockobserver.screener.model import Predicate, Screen


def _snap() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["A.US", "B.US", "C.US", "D.US"],
            "pe": [10.0, 20.0, np.nan, 12.0],
            "rsi_14": [25.0, 80.0, 50.0, 35.0],
            "roe": [0.20, 0.10, 0.30, 0.25],
        }
    )


def test_comparison_and_nan_excludes() -> None:
    res = evaluate(Screen(name="x", predicates=[Predicate(field="pe", op="<", value=15)]), _snap())
    # B (pe=20) fails; C (pe=NaN) is excluded, not included
    assert res["symbol"].tolist() == ["A.US", "D.US"]


def test_multiple_predicates_are_anded() -> None:
    screen = Screen(
        name="x",
        predicates=[
            Predicate(field="pe", op="<", value=15),
            Predicate(field="roe", op=">", value=0.22),
        ],
    )
    assert evaluate(screen, _snap())["symbol"].tolist() == ["D.US"]


def test_between_in_notna() -> None:
    snap = _snap()
    assert evaluate(
        Screen(name="x", predicates=[Predicate(field="rsi_14", op="between", value=[30, 60])]), snap
    )["symbol"].tolist() == ["C.US", "D.US"]
    in_screen = Screen(
        name="x", predicates=[Predicate(field="symbol", op="in", value=["A.US", "C.US"])]
    )
    assert evaluate(in_screen, snap)["symbol"].tolist() == ["A.US", "C.US"]
    assert evaluate(
        Screen(name="x", predicates=[Predicate(field="pe", op="notna", value=None)]), snap
    )["symbol"].tolist() == ["A.US", "B.US", "D.US"]


def test_sort_and_limit() -> None:
    screen = Screen(name="x", predicates=[], sort_by="roe", ascending=False, limit=2)
    assert evaluate(screen, _snap())["symbol"].tolist() == ["C.US", "D.US"]


def test_unknown_field_raises() -> None:
    with pytest.raises(KeyError, match="nope"):
        evaluate(Screen(name="x", predicates=[Predicate(field="nope", op="<", value=1)]), _snap())


def test_bad_operator_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown operator"):
        Predicate(field="pe", op="≈", value=1)


def test_save_load_roundtrip(tmp_path: Path) -> None:
    screen = Screen(
        name="cheap", predicates=[Predicate(field="pe", op="<", value=15)], sort_by="pe"
    )
    store.save_screen(screen, root=tmp_path)
    assert "cheap" in store.list_screens(root=tmp_path)
    assert store.load_screen("cheap", root=tmp_path) == screen
    store.delete_screen("cheap", root=tmp_path)
    assert store.list_screens(root=tmp_path) == []
