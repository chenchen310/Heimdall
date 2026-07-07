"""Canary tests (roadmap 8.3) — the referee itself must have power.

Two canaries guard the certification harness:

- a **noise** spec must be REJECTED — at 200 names × 36 months the gates
  cannot be fooled by luck;
- an **oracle** spec — the forward label smuggled in under a non-``fwd_``
  name, i.e. the statistical signature of label leakage — must light up
  G1–G3 overwhelmingly. If the oracle ever stops passing those gates, the
  harness has lost its power and every other verdict is meaningless.

The oracle is TEST-ONLY. ``SignalSpec`` refuses ``fwd_*`` features outright
(asserted below), which is exactly why a real leak would have to arrive
renamed — and why the canary smuggles it the same way. Instructively, the
oracle's overall verdict is still REJECTED: an iid one-month-ahead oracle
replaces the whole book every month, so G6 (turnover) refuses it — the gates
measure implementability, not just information.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.research.certify import CertReport, GateResult, certify
from heimdall.research.spec import SignalSpec

N_MONTHS, N_SYMS = 36, 200


def _bench_series(start: str = "2022-12-01", n: int = 1000) -> pd.Series:
    """Benchmark with *varying* drift (a flat line has no Sharpe to compare)."""
    k = np.arange(n)
    daily = 0.0003 + 0.0002 * np.sin(k / 7.0)
    return pd.Series(100.0 * np.cumprod(1.0 + daily), index=pd.bdate_range(start, periods=n))


@pytest.fixture(scope="module")
def canary() -> tuple[pd.DataFrame, pd.Series]:
    """36 months × 200 symbols with an oracle column and a noise column.

    ``oracle`` is ``fwd_1m_rel`` plus microscopic jitter (σ=2e-4 vs the label's
    σ=0.05): a *perfect* copy has IC exactly 1.0 every month — zero variance,
    so the IC t-stat is undefined — while the jitter keeps ranks essentially
    identical and the t finite. ``fwd_6m_rel`` tracks ``fwd_1m_rel`` with real
    noise so cohort beat rates vary (a constant series has no NW error term).
    """
    rng = np.random.default_rng(2023)
    bench = _bench_series()
    months = list(pd.date_range("2023-01-31", periods=N_MONTHS, freq="BME"))
    symbols = [f"S{i:03d}" for i in range(N_SYMS)]

    frames: list[pd.DataFrame] = []
    for m_idx, t in enumerate(months):
        if m_idx + 1 < len(months):
            i, j = bench.index.searchsorted(t), bench.index.searchsorted(months[m_idx + 1])
            bench_m = float(bench.iloc[int(j)] / bench.iloc[int(i)] - 1.0)
        else:
            bench_m = 0.0
        rel1 = rng.normal(0.0, 0.05, N_SYMS)
        rel6 = 3.0 * rel1 + rng.normal(0.0, 0.15, N_SYMS)
        frames.append(
            pd.DataFrame(
                {
                    "date": t,
                    "symbol": symbols,
                    "eligible": True,
                    "oracle": rel1 + rng.normal(0.0, 2e-4, N_SYMS),
                    "noise": rng.normal(0.0, 1.0, N_SYMS),
                    "fwd_1m": rel1 + bench_m,
                    "fwd_1m_rel": rel1,
                    "fwd_6m": rel6 + 0.03,
                    "fwd_6m_rel": rel6,
                }
            )
        )
    return pd.concat(frames, ignore_index=True), bench


def _spec(name: str, family: str, feature: str) -> SignalSpec:
    return SignalSpec.model_validate(
        {
            "name": name,
            "family": family,
            "market": "US",
            "version": 1,
            "features": {feature: 1.0},
            "top_n": 20,
            "description": "TEST-ONLY canary",
        }
    )


def _gates(report: CertReport) -> dict[str, GateResult]:
    return {g.gate: g for g in report.gates}


def test_spec_refuses_forward_labels_outright() -> None:
    # The belt-and-braces guard: a leak cannot even be *named*; it must arrive
    # renamed — which is precisely the disguise the oracle canary wears.
    with pytest.raises(ValidationError, match="label leakage"):
        _spec("leak", "canary", "fwd_1m_rel")


def test_noise_canary_is_rejected(canary: tuple[pd.DataFrame, pd.Series]) -> None:
    panel, bench = canary
    report = certify(_spec("noise-canary", "canary-noise", "noise"), panel, bench)
    assert report.verdict == "REJECTED"
    failed = {g.gate for g in report.gates if not g.passed}
    assert failed & {"G1_ic", "G1_t"}  # no information ⇒ the information gates fall


def test_oracle_canary_proves_the_harness_has_power(
    canary: tuple[pd.DataFrame, pd.Series],
) -> None:
    panel, bench = canary
    report = certify(_spec("oracle-canary", "canary-oracle", "oracle"), panel, bench)
    g = _gates(report)

    # G1–G3 must be overwhelming — this is what label leakage looks like, and
    # what a real (weaker) signal is measured against.
    assert g["G1_ic"].value > 0.9 and g["G1_ic"].passed
    assert g["G1_t"].value > 10 and g["G1_t"].passed
    assert g["G1_months"].passed
    assert g["G2_mean"].value > 0.05 and g["G2_mean"].passed
    assert g["G2_share"].value == 1.0
    assert g["G3_rate"].value > 0.9 and g["G3_rate"].passed
    assert g["G3_t"].value > 10 and g["G3_t"].passed

    # …and yet the verdict is REJECTED: an iid oracle replaces essentially the
    # whole top-20 every month, so G6 turnover refuses it. Information alone
    # is not a standard — it also has to be tradeable.
    assert g["G6_turnover"].value > 0.8
    assert not g["G6_turnover"].passed
    assert report.verdict == "REJECTED"
