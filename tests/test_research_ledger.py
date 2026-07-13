"""Forward performance ledger (roadmap 16.1) — freeze immutability + known-answer curve.

The two institutions under test: a frozen cohort is **append-only** and refuses to
**backfill** before the certification month, and the realized track record recomputes
from the panel on the certify/monitor basis with G4 costs (hand-verifiable numbers).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.research.ledger import (
    BackfillRefused,
    cohort_path,
    freeze,
    load_cohorts,
    realized_track_record,
)
from heimdall.research.spec import SignalSpec

_SPEC = SignalSpec(name="t-mom", family="t-mom", market="US", features={"ret_6m": 1.0}, top_n=2)


def _snapshot(symbols: list[str], ret6: list[float], as_of: str = "2024-03-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbols,
            "as_of": pd.Timestamp(as_of),
            "price": 100.0,
            "dollar_vol_21d": 1e8,
            "ret_12_1": 0.1,
            "ret_6m": ret6,
        }
    )


def test_freeze_writes_picks_is_idempotent_and_refuses_backfill(tmp_path: Path) -> None:
    snap = _snapshot(["A.US", "B.US", "C.US"], [0.30, 0.20, 0.10])
    path = freeze(_SPEC, snap, "2024-01", root=tmp_path, today=date(2024, 3, 15))
    data = json.loads(path.read_text())
    assert data["month"] == "2024-03" and data["as_of"] == "2024-03-01"
    assert [p["symbol"] for p in data["picks"]] == ["A.US", "B.US"]  # top-2 by ret_6m

    # Second freeze of the same month refuses — a frozen cohort is immutable.
    with pytest.raises(FileExistsError):
        freeze(_SPEC, snap, "2024-01", root=tmp_path, today=date(2024, 3, 28))

    # A month before the certification month is a backfill — refused.
    with pytest.raises(BackfillRefused):
        freeze(_SPEC, snap, "2024-05", root=tmp_path, today=date(2024, 3, 15))


def _write_cohort(tmp_path: Path, month: str, picks: list[str]) -> None:
    path = cohort_path(_SPEC.name, _SPEC.version, month, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": _SPEC.name,
                "version": _SPEC.version,
                "market": "US",
                "month": month,
                "as_of": f"{month}-01",
                "picks": [{"symbol": s, "signal_score": 1.0} for s in picks],
            }
        )
    )


def _row(date_: str, sym: str, f1: float, f6: float, f6r: float) -> dict[str, object]:
    return {
        "date": pd.Timestamp(date_),
        "symbol": sym,
        "eligible": True,
        "fwd_1m": f1,
        "fwd_6m": f6,
        "fwd_6m_rel": f6r,
    }


def test_load_cohorts_is_month_sorted(tmp_path: Path) -> None:
    _write_cohort(tmp_path, "2024-02", ["B.US", "C.US"])
    _write_cohort(tmp_path, "2024-01", ["A.US", "B.US"])
    assert [c["month"] for c in load_cohorts(_SPEC.name, _SPEC.version, tmp_path)] == [
        "2024-01",
        "2024-02",
    ]


def test_realized_track_record_known_answer_alpha_and_costed_curve(tmp_path: Path) -> None:
    _write_cohort(tmp_path, "2024-01", ["A.US", "B.US"])
    _write_cohort(tmp_path, "2024-02", ["B.US", "C.US"])
    panel = pd.DataFrame(
        [
            # 2024-01 cross-section: 6m window complete.
            _row("2024-01-31", "A.US", 0.10, 0.36, 0.30),
            _row("2024-01-31", "B.US", 0.20, 0.12, 0.10),
            _row("2024-01-31", "C.US", 0.00, 0.00, 0.00),
            _row("2024-01-31", "D.US", -0.05, -0.12, -0.10),
            # 2024-02 cross-section: 1m realized, but 6m window still open (NaN).
            _row("2024-02-29", "A.US", 0.00, np.nan, np.nan),
            _row("2024-02-29", "B.US", 0.05, np.nan, np.nan),
            _row("2024-02-29", "C.US", 0.15, np.nan, np.nan),
            _row("2024-02-29", "D.US", 0.00, np.nan, np.nan),
        ]
    )
    tr = realized_track_record(_SPEC, panel, "2024-01", root=tmp_path)

    jan, feb = tr.cohorts
    # book = mean(A,B fwd_6m_rel) = 0.20; universe = mean(A,B,C,D) = 0.075; alpha = 0.125.
    assert jan.book_rel_6m == pytest.approx(0.20)
    assert jan.univ_rel_6m == pytest.approx(0.075)
    assert jan.alpha_6m == pytest.approx(0.125)
    assert jan.realized is True and jan.n_picks == 2
    assert feb.realized is False and np.isnan(feb.book_rel_6m)  # 6m window open

    # Curve: gross = [mean(0.10,0.20)=0.15, mean(0.05,0.15)=0.10]; turnover {A,B}->{B,C} = 0.5.
    # net month0 = 0.15 - 1.0*0.002 = 0.148 (full buy); net month1 = 0.10 - 2*0.5*0.002 = 0.098.
    assert [p.month for p in tr.curve] == ["2024-01", "2024-02"]
    assert tr.curve[0].gross == pytest.approx(0.15)
    assert tr.curve[0].net == pytest.approx(0.148)
    assert tr.curve[0].equity == pytest.approx(1.148)
    assert tr.curve[1].net == pytest.approx(0.098)
    assert tr.curve[1].equity == pytest.approx(1.148 * 1.098)


def test_realized_track_record_empty_when_nothing_frozen(tmp_path: Path) -> None:
    panel = pd.DataFrame([_row("2024-01-31", "A.US", 0.1, 0.1, 0.1)])
    tr = realized_track_record(_SPEC, panel, "2024-01", root=tmp_path)
    assert tr.cohorts == [] and tr.curve == []
