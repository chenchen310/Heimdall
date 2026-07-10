"""Windowed evaluation (roadmap 13.1).

Two load-bearing guarantees: evaluate() **refuses** any window that reaches the OOS vault
(so a dev/val lens can never peek), and its numbers are **identical** to the certify gate
helpers applied by hand to the same in-sample rows (so it cannot silently fork the math the
referee uses). Plus the dev/val window boundaries mirror the playbook, and the advance flag
follows the entry-010 both-gates rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from heimdall.factors.validate import information_coefficient
from heimdall.research import gates
from heimdall.research.certify import (
    _SCORE,
    _book_minus_universe,
    _monthly_spread,
    cohort_turnover,
)
from heimdall.research.evaluate import WINDOWS, evaluate
from heimdall.research.spec import SignalSpec, score


def _spec(**overrides: object) -> SignalSpec:
    base: dict[str, object] = {
        "name": "eval-sig",
        "family": "test-eval",
        "market": "US",
        "features": {"sig": 1.0},
        "top_n": 5,
    }
    base.update(overrides)
    return SignalSpec.model_validate(base)


def _insample_panel(
    start: str = "2015-01-31", n_months: int = 24, n_syms: int = 40
) -> pd.DataFrame:
    """A signal that genuinely ranks forward relative returns, dated inside development.

    6m labels are complete for every month (historical rows always are), so there is no
    open-window bookkeeping — the whole point of an in-sample lens.
    """
    rng = np.random.default_rng(13)
    months = list(pd.date_range(start, periods=n_months, freq="BME"))
    rows: list[dict[str, object]] = []
    for t in months:
        for i in range(n_syms):
            base = float(n_syms - i)  # lower i = better name
            rel1 = 0.002 * (base - n_syms / 2) + float(rng.normal(0, 0.004))
            rel6 = 6 * rel1 + float(rng.normal(0, 0.01))
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:02d}",
                    "eligible": True,
                    "sig": base + float(rng.normal(0, 0.05)),
                    "fwd_1m_rel": rel1,
                    "fwd_6m_rel": rel6,
                }
            )
    return pd.DataFrame(rows)


# --- the guard: no window may reach the vault -----------------------------------


def test_evaluate_refuses_a_window_reaching_the_oos_vault() -> None:
    panel = _insample_panel()
    with pytest.raises(ValueError, match="OOS vault"):
        evaluate(_spec(), panel, ("2022-01-01", "2023-06-30"))
    with pytest.raises(ValueError, match="OOS vault"):  # exactly OOS_START is already the vault
        evaluate(_spec(), panel, ("2020-01-01", gates.OOS_START))
    # a validation window ending the day before the vault is allowed
    rep = evaluate(_spec(), panel, ("2015-01-01", "2019-12-31"))
    assert rep.n_months > 0


# --- parity: evaluate ≡ the certify gate helpers on the same rows ----------------


def test_evaluate_matches_certify_gate_math() -> None:
    spec, panel = _spec(), _insample_panel()
    window = ("2015-01-01", "2016-12-31")
    rep = evaluate(spec, panel, window)

    # Reproduce with the *same* imported helpers the referee uses — no forked formula.
    start, end = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    dates = pd.to_datetime(panel["date"])
    win = panel.loc[(dates >= start) & (dates <= end)].copy()
    win["date"] = pd.to_datetime(win["date"])
    frames: list[pd.DataFrame] = []
    cohort_sets: list[set[str]] = []
    alphas: list[float] = []
    beats: list[float] = []
    for t in sorted(pd.Timestamp(x) for x in win["date"].unique()):
        cross = win[win["date"] == t].copy()
        cross[_SCORE] = score(spec, cross)
        frames.append(cross)
        ranked = cross.dropna(subset=[_SCORE]).sort_values(_SCORE, ascending=False)
        cohort_sets.append(set(ranked.head(spec.top_n)["symbol"]))
        bu = _book_minus_universe(cross, spec.top_n)
        assert bu is not None
        beats.append(float(bu[0] > 0))
        alphas.append(bu[0] - bu[1])
    scored = pd.concat(frames, ignore_index=True)
    ic = information_coefficient(scored, factor_col=_SCORE, fwd_col="fwd_1m_rel")
    spreads = _monthly_spread(scored)

    assert rep.ic_mean == pytest.approx(ic.mean_ic)
    assert rep.ic_t == pytest.approx(ic.t_stat)
    assert rep.ic_months == ic.n_periods
    assert rep.spread_mean == pytest.approx(float(np.mean(spreads)))
    assert rep.spread_positive_share == pytest.approx(float(np.mean([s > 0 for s in spreads])))
    assert rep.selection_alpha_mean == pytest.approx(float(np.mean(alphas)))
    assert rep.selection_alpha_t == pytest.approx(
        gates.nw_tstat(np.asarray(alphas), null=0.0, lag=gates.NW_LAG)
    )
    assert rep.portfolio_beat_rate == pytest.approx(float(np.mean(beats)))
    assert rep.mean_turnover == pytest.approx(float(np.mean(cohort_turnover(cohort_sets))))
    assert rep.n_cohorts == len(alphas)


def test_evaluate_windows_the_panel() -> None:
    # Only rows inside [start, end] feed the read: a strict sub-window of a 24-month panel.
    panel = _insample_panel(start="2015-01-31", n_months=24)
    d = pd.to_datetime(panel["date"])
    expected = panel.loc[(d >= "2015-01-01") & (d <= "2015-12-31"), "date"].nunique()
    rep = evaluate(_spec(), panel, ("2015-01-01", "2015-12-31"))
    assert rep.n_months == expected
    assert 0 < expected < panel["date"].nunique()  # a real sub-window, not the whole panel
    assert "2015-01-01" <= rep.window_start <= rep.window_end <= "2015-12-31"


# --- the windows mirror the playbook, and the advance rule is both-gates ---------


def test_windows_mirror_playbook_and_stay_out_of_the_vault() -> None:
    # docs/RESEARCH_PLAYBOOK.md §4 splits — dev 2010–2019, val 2020–2022.
    assert WINDOWS["dev"] == ("2010-01-01", "2019-12-31")
    assert WINDOWS["val"] == ("2020-01-01", "2022-12-31")
    # both windows must end strictly before the vault — the guard depends on it.
    for _name, (_start, end) in WINDOWS.items():
        assert pd.Timestamp(end) < pd.Timestamp(gates.OOS_START)


def test_advances_requires_both_gate_floors() -> None:
    # A strong, clean signal clears both G1-t and G3-t ⇒ advances.
    strong = evaluate(_spec(), _insample_panel(), ("2015-01-01", "2016-12-31"))
    assert strong.ic_t >= gates.G1_MIN_T and strong.selection_alpha_t >= gates.G3_MIN_SKILL_T
    assert strong.advances is True

    # Pure noise clears neither ⇒ does not advance (and never crashes on NaN t-stats).
    noisy = _insample_panel()
    noisy["sig"] = np.random.default_rng(0).normal(0, 1, len(noisy))
    weak = evaluate(_spec(), noisy, ("2015-01-01", "2016-12-31"))
    assert weak.advances is False
