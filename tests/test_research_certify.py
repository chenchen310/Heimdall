"""Certify harness (roadmap 8.2) — gate math by hand, and the guarded flow.

Hand answers pin the statistics (NW t exactly 6.0 on an alternating series,
turnover 0.4 on a 2-of-5 swap); an engineered good signal must CERTIFY and a
noise signal must REJECT; the record flow refuses cheaply (immutable report,
missing/wrong pre-registration, spent budget) and spends the family's OOS
attempt only when it actually evaluates the vault.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.research import gates, registry
from heimdall.research.certify import (
    apply_costs,
    certify,
    certify_and_record,
    check_preregistration,
    cohort_turnover,
    report_path,
)
from heimdall.research.spec import SignalSpec

# --- gates mirror the playbook (the tripwire) ----------------------------------


def test_gates_mirror_playbook() -> None:
    # docs/RESEARCH_PLAYBOOK.md §5 — change either side alone and this fails.
    assert gates.OOS_START == "2023-01-01"
    assert gates.G1_MIN_IC == 0.03 and gates.G1_MIN_T == 2.0 and gates.G1_MIN_MONTHS == 24
    assert gates.G2_MIN_POSITIVE_SHARE == 0.55
    assert gates.G3_MIN_BEAT_RATE == 0.55 and gates.G3_MIN_NW_T == 2.0 and gates.NW_LAG == 5
    assert gates.G4_COST_BPS == 20.0
    assert gates.G5_MAX_PARAMS == 4
    assert gates.G6_MAX_TURNOVER == 0.40
    assert gates.G6_STRESS_TURNOVER == 0.60 and gates.G6_STRESS_COST_BPS == 40.0


# --- Newey–West, by hand --------------------------------------------------------


def test_nw_tstat_hand_answer() -> None:
    # x = [1,0,1,0,1,0], lag 1: mean .5, s = .25 − 1.25/6 = 1/24 → t = .5/√(1/144) = 6.
    x = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
    assert gates.nw_tstat(x, null=0.0, lag=1) == pytest.approx(6.0)
    assert gates.nw_tstat(x, null=0.5, lag=1) == pytest.approx(0.0)  # null shift
    with_nan = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 0.0, np.nan])
    assert gates.nw_tstat(with_nan, null=0.0, lag=1) == pytest.approx(6.0)  # NaNs dropped


def test_nw_ci95_hand_answer() -> None:
    x = np.array([1.0, 0.0, 1.0, 0.0, 1.0, 0.0])
    lo, hi = gates.nw_ci95(x, lag=1)  # .5 ± 1.96·(1/12)
    assert lo == pytest.approx(0.5 - 1.96 / 12)
    assert hi == pytest.approx(0.5 + 1.96 / 12)


# --- turnover & costs, by hand ---------------------------------------------------


def test_cohort_turnover_hand_answer() -> None:
    a, b = {"A", "B", "C", "D", "E"}, {"A", "B", "C", "F", "G"}
    assert cohort_turnover([a, b]) == [pytest.approx(0.4)]  # 2 of 5 replaced
    assert cohort_turnover([a, a]) == [0.0]
    assert cohort_turnover([a, {"V", "W", "X", "Y", "Z"}]) == [1.0]


def test_apply_costs_hand_answer() -> None:
    # 20 bps per side: month 0 buys the book (1 side); later months trade 2×turnover.
    net = apply_costs([0.02, 0.02, 0.02], [0.5, 0.5], cost_bps=20.0)
    assert net == pytest.approx([0.02 - 0.002, 0.02 - 0.002, 0.02 - 0.002])


# --- synthetic panels ------------------------------------------------------------


def _bench_series(start: str = "2022-12-01", n: int = 900) -> pd.Series:
    """Benchmark adj-close with *varying* daily drift (a flat line has no Sharpe)."""
    k = np.arange(n)
    daily = 0.0003 + 0.0002 * np.sin(k / 7.0)
    return pd.Series(100.0 * np.cumprod(1.0 + daily), index=pd.bdate_range(start, periods=n))


def _bench_month(bench: pd.Series, t: pd.Timestamp, nxt: pd.Timestamp) -> float:
    i, j = int(bench.index.searchsorted(t)), int(bench.index.searchsorted(nxt))
    return float(bench.iloc[j] / bench.iloc[i] - 1.0)


def _good_panel(bench: pd.Series, n_months: int = 31, n_syms: int = 40) -> pd.DataFrame:
    """A signal that honestly ranks forward relative returns, with mild noise."""
    rng = np.random.default_rng(7)
    months = list(pd.date_range("2023-01-31", periods=n_months, freq="BME"))
    rows: list[dict[str, object]] = []
    for m_idx, t in enumerate(months):
        nxt = months[m_idx + 1] if m_idx + 1 < len(months) else None
        bench_m = _bench_month(bench, t, nxt) if nxt is not None else 0.0
        complete6 = m_idx < n_months - 2  # the last 2 months' 6m windows are open
        for i in range(n_syms):
            base = float(n_syms - i)  # lower i = better name
            rel1 = 0.002 * (base - n_syms / 2) + float(rng.normal(0, 0.004))
            rel6 = 6 * rel1 + float(rng.normal(0, 0.01))
            if i == 4 and m_idx % 4 == 0:  # an occasional top-5 miss → beat rate varies
                rel6 = -0.02
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:02d}",
                    "eligible": True,
                    "sig": base + float(rng.normal(0, 0.05)),
                    "fwd_1m": rel1 + bench_m,
                    "fwd_1m_rel": rel1,
                    "fwd_6m": (rel6 + 0.05) if complete6 else float("nan"),
                    "fwd_6m_rel": rel6 if complete6 else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _spec(**overrides: object) -> SignalSpec:
    base: dict[str, object] = {
        "name": "good-sig",
        "family": "test-good",
        "market": "US",
        "version": 1,
        "features": {"sig": 1.0},
        "top_n": 5,
    }
    base.update(overrides)
    return SignalSpec.model_validate(base)


# --- the referee on engineered panels --------------------------------------------


def test_good_signal_certifies_and_window_excludes_open_months() -> None:
    bench = _bench_series()
    report = certify(_spec(), _good_panel(bench), bench)
    assert report.verdict == "CERTIFIED"
    assert all(g.passed for g in report.gates)
    assert report.n_months == 29  # 31 months − 2 with open 6m windows
    assert report.window_start == "2023-01-31"
    lo, hi = report.beat_rate_ci95
    assert lo > 0.5 and hi <= 1.0 + 1e-9
    assert report.mean_turnover <= gates.G6_MAX_TURNOVER
    assert report.survivorship == "current_universe (optimistic)"


def test_noise_signal_is_rejected() -> None:
    bench = _bench_series()
    panel = _good_panel(bench)
    rng = np.random.default_rng(11)
    panel["sig"] = rng.normal(0, 1, len(panel))  # score is pure noise
    report = certify(_spec(), panel, bench)
    assert report.verdict == "REJECTED"
    g1 = [g for g in report.gates if g.gate.startswith("G1")]
    assert any(not g.passed for g in g1)  # no information ⇒ G1 falls


def _turnover_panel(bench: pd.Series, n_fixed: int, rot_size: int) -> pd.DataFrame:
    """Top-5 book: ``n_fixed`` permanent names + two alternating groups of ``rot_size``."""
    months = list(pd.date_range("2023-01-31", periods=30, freq="BME"))
    rows: list[dict[str, object]] = []
    for m_idx, t in enumerate(months):
        nxt = months[m_idx + 1] if m_idx + 1 < len(months) else None
        bench_m = _bench_month(bench, t, nxt) if nxt is not None else 0.0
        for i in range(10):
            fixed = i < n_fixed
            in_a = n_fixed <= i < n_fixed + rot_size
            in_b = n_fixed + rot_size <= i < n_fixed + 2 * rot_size
            boosted = fixed or (in_a and m_idx % 2 == 0) or (in_b and m_idx % 2 == 1)
            sig = (100.0 - i) if fixed else (50.0 - i if boosted else 1.0 - i)
            rel = 0.05 if i < n_fixed + 2 * rot_size else -0.05
            rel6 = 6 * rel
            if i == 0 and m_idx % 3 == 0:  # vary the beat rates → finite NW t, no 0/0
                rel6 = -0.01
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i}",
                    "eligible": True,
                    "sig": sig,
                    "fwd_1m": rel + bench_m,
                    "fwd_1m_rel": rel,
                    "fwd_6m": rel6,
                    "fwd_6m_rel": rel6,
                }
            )
    return pd.DataFrame(rows)


def test_turnover_stress_band_reruns_g4_at_double_cost() -> None:
    bench = _bench_series()
    report = certify(_spec(), _turnover_panel(bench, n_fixed=2, rot_size=3), bench)
    g6 = {g.gate: g for g in report.gates}
    assert g6["G6_turnover"].value == pytest.approx(0.6)  # 3 of 5 swap every month
    assert g6["G6_turnover"].passed  # strong economics survive 40 bps
    assert g6["G6_stress_cagr"].passed and g6["G6_stress_sharpe"].passed


def test_turnover_above_stress_band_rejects() -> None:
    bench = _bench_series()
    report = certify(_spec(), _turnover_panel(bench, n_fixed=1, rot_size=4), bench)
    g6 = {g.gate: g for g in report.gates}
    assert g6["G6_turnover"].value == pytest.approx(0.8)
    assert not g6["G6_turnover"].passed
    assert "G6_stress_cagr" not in g6  # no stress escape hatch above the band
    assert report.verdict == "REJECTED"


# --- pre-registration + the guarded record flow ----------------------------------


def _write_log(path: Path, entry_id: str, spec_hash: str) -> None:
    path.write_text(
        "# Research Log — append-only\n\n"
        f"## {entry_id} — test-good / good-sig v1 (2026-07-07, model: test)\n"
        f"- Spec: signals/specs/good-sig.json   sha256: {spec_hash}\n"
        "- OOS attempt: 1 of 3\n"
    )


def test_preregistration_missing_or_wrong_hash_refuses(tmp_path: Path) -> None:
    spec = _spec()
    log = tmp_path / "LOG.md"
    _write_log(log, "001", spec.canonical_hash())
    check_preregistration(spec, "001", log)  # exact entry → no raise
    with pytest.raises(ValueError, match="pre-register first"):
        check_preregistration(spec, "002", log)  # absent id
    _write_log(log, "001", "0" * 64)
    with pytest.raises(ValueError, match="does not contain this spec's sha256"):
        check_preregistration(spec, "001", log)  # wrong hash


def test_record_flow_writes_immutable_report_and_transitions(tmp_path: Path) -> None:
    bench = _bench_series()
    spec = _spec()
    log = tmp_path / "LOG.md"
    _write_log(log, "001", spec.canonical_hash())
    registry.add(spec, "signals/specs/good-sig.json", root=tmp_path)

    report = certify_and_record(
        spec, _good_panel(bench), bench, log_entry="001", log_path=log, root=tmp_path
    )
    assert report.verdict == "CERTIFIED"
    assert report_path(spec, tmp_path).exists()  # committed evidence
    entry = registry.get("good-sig", 1, root=tmp_path)
    assert entry["status"] == "certified"
    assert entry["oos_attempts_family"] == 1
    assert registry.family_attempts("test-good", root=tmp_path) == 1

    with pytest.raises(FileExistsError, match="immutable"):  # second run refuses
        certify_and_record(
            spec, _good_panel(bench), bench, log_entry="001", log_path=log, root=tmp_path
        )


def test_record_flow_refusals_cost_no_attempt(tmp_path: Path) -> None:
    bench = _bench_series()
    spec = _spec(name="guarded", family="guarded-family")
    log = tmp_path / "LOG.md"
    _write_log(log, "001", "f" * 64)  # wrong hash on purpose
    registry.add(spec, "p.json", root=tmp_path)
    with pytest.raises(ValueError, match="does not contain"):
        certify_and_record(
            spec, _good_panel(bench), bench, log_entry="001", log_path=log, root=tmp_path
        )
    assert registry.family_attempts("guarded-family", root=tmp_path) == 0  # refusal is free
    assert not report_path(spec, tmp_path).exists()


def test_record_flow_refuses_once_budget_is_spent(tmp_path: Path) -> None:
    bench = _bench_series()
    spec = _spec(name="late-idea", family="spent-family")
    log = tmp_path / "LOG.md"
    _write_log(log, "009", spec.canonical_hash())
    registry.add(spec, "p.json", root=tmp_path)
    for _ in range(3):
        registry.spend_attempt("spent-family", root=tmp_path)
    with pytest.raises(ValueError, match="exhausted"):
        certify_and_record(
            spec, _good_panel(bench), bench, log_entry="009", log_path=log, root=tmp_path
        )
    assert not report_path(spec, tmp_path).exists()  # the vault was never evaluated
    assert registry.get("late-idea", 1, root=tmp_path)["status"] == "registered"
