"""Drift monitoring (roadmap 12.2 / playbook §9).

Synthetic panels pin the auto-flip: a signal whose trailing-12-cohort selection
alpha goes significantly negative (CI upper < 0) flips certified → under_review;
a healthy one stays certified; a thin window never flips; the snapshot persists.
The metric is the same `cohort_alpha` certify uses (one home for the math).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from heimdall.research import registry
from heimdall.research.monitor import (
    TRAILING,
    load_monitoring,
    monitor_signal,
    realized_cohorts,
)
from heimdall.research.spec import SignalSpec


def _panel(n_months: int, sign: float, n_syms: int = 40, start: str = "2023-01-31") -> pd.DataFrame:
    """OOS panel where `sig` ranks names; sign=+1 → top-N book beats the universe (skill),
    sign=−1 → the book picks the worst names (drifted). Last 2 months' 6m windows are open."""
    months = pd.date_range(start, periods=n_months, freq="BME")
    rng = np.random.default_rng(1)
    rows: list[dict[str, object]] = []
    for m_idx, t in enumerate(months):
        done = m_idx < n_months - 2
        for i in range(n_syms):
            rel6 = sign * 0.01 * (n_syms / 2 - i) + float(rng.normal(0, 0.002))
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:02d}",
                    "eligible": True,
                    "sig": float(n_syms - i),  # higher sig for lower i (ranks with |rel6|)
                    "fwd_6m": (rel6 + 0.05) if done else float("nan"),
                    "fwd_6m_rel": rel6 if done else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _spec() -> SignalSpec:
    return SignalSpec.model_validate(
        {"name": "sig-x", "family": "fam-x", "market": "US", "features": {"sig": 1.0}, "top_n": 10}
    )


def _certify_in_registry(spec: SignalSpec, root: Path) -> None:
    registry.add(spec, "signals/specs/sig-x.json", root=root)
    registry.transition(spec.name, spec.version, "registered", root=root)
    registry.transition(
        spec.name, spec.version, "certified", cert_report="r.json", oos_attempt=1, root=root
    )


def test_healthy_signal_stays_certified(tmp_path: Path) -> None:
    spec = _spec()
    _certify_in_registry(spec, tmp_path)
    res = monitor_signal(spec, _panel(15, sign=+1.0), root=tmp_path, apply=True)
    assert res.trailing_n == TRAILING
    assert res.trailing_alpha_mean > 0.10  # book ≫ universe
    assert res.trailing_alpha_ci95[1] > 0  # CI upper above 0 ⇒ no drift
    assert res.drift is False and res.flipped is False
    assert res.status == "certified"
    assert registry.get(spec.name, 1, root=tmp_path)["status"] == "certified"


def test_drift_flips_to_under_review(tmp_path: Path) -> None:
    spec = _spec()
    _certify_in_registry(spec, tmp_path)
    res = monitor_signal(spec, _panel(15, sign=-1.0), root=tmp_path, apply=True)
    assert res.trailing_alpha_mean < -0.10  # the book now picks the worst names
    assert res.trailing_alpha_ci95[1] < 0  # CI upper below 0 ⇒ skill significantly negative
    assert res.drift is True and res.flipped is True
    assert res.status == "under_review"
    assert registry.get(spec.name, 1, root=tmp_path)["status"] == "under_review"


def test_drift_without_apply_reports_but_does_not_flip(tmp_path: Path) -> None:
    spec = _spec()
    _certify_in_registry(spec, tmp_path)
    res = monitor_signal(spec, _panel(15, sign=-1.0), root=tmp_path, apply=False)
    assert res.drift is True and res.flipped is False  # observed, not acted on
    assert registry.get(spec.name, 1, root=tmp_path)["status"] == "certified"


def test_thin_window_never_flips(tmp_path: Path) -> None:
    spec = _spec()
    _certify_in_registry(spec, tmp_path)
    # 10 months → 8 complete cohorts (< TRAILING): a drift verdict is not rendered.
    res = monitor_signal(spec, _panel(10, sign=-1.0), root=tmp_path, apply=True)
    assert res.trailing_n < TRAILING
    assert res.drift is False and res.flipped is False
    assert registry.get(spec.name, 1, root=tmp_path)["status"] == "certified"


def test_snapshot_persists_and_reloads(tmp_path: Path) -> None:
    spec = _spec()
    _certify_in_registry(spec, tmp_path)
    monitor_signal(spec, _panel(15, sign=+1.0), root=tmp_path, apply=True)
    mon = load_monitoring(spec.name, 1, tmp_path)
    assert mon is not None
    assert mon["status"] == "certified" and mon["drift"] is False
    assert mon["trailing_n"] == TRAILING
    assert len(mon["cohorts"]) == 13  # type: ignore[arg-type]  # 15 months − 2 open


def test_realized_cohorts_skip_open_windows() -> None:
    spec = _spec()
    cohorts = realized_cohorts(spec, _panel(15, sign=+1.0))
    assert len(cohorts) == 13  # the last 2 months' 6m windows are open ⇒ not realized
    assert all(c.alpha > 0 for c in cohorts)  # healthy signal: positive skill every cohort
    assert all(c.beat in (0.0, 1.0) for c in cohorts)
