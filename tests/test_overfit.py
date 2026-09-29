"""Over-fitting statistics (roadmap 18.4) — published worked example + hand answers + properties."""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from heimdall.backtest import overfit

_N = NormalDist()


def test_dsr_reproduces_the_published_worked_example() -> None:
    """Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, numerical example: an
    annualized SR of 2.5 over 5 years of daily returns (T = 1250), skew −3, kurtosis 10,
    selected as the best of N = 100 trials whose annualized Sharpe variance is 0.5
    → DSR ≈ 0.9004. Per-period scale uses 250 trading days/year, as the paper does."""
    days = 250.0
    sr = 2.5 / math.sqrt(days)
    var = 0.5 / days  # a variance scales with 1/days when the SR scales with 1/√days
    e_max_ann = overfit.expected_max_sharpe(100, 0.5)
    assert e_max_ann == pytest.approx(1.7894, abs=1e-4)
    assert overfit.dsr_from_moments(sr, 1250, -3.0, 10.0, 100, var) == pytest.approx(
        0.9004, abs=1e-4
    )


def test_psr_hand_answer_on_a_two_point_series() -> None:
    # x ∈ {+2%, −1%} alternating: mean .5%, sample sd 1.5·√(n/(n−1))%, skew 0, kurtosis 1.
    x = np.tile([0.02, -0.01], 50)
    sr, n, skew, kurt = overfit.moments(x)
    assert n == 100 and skew == pytest.approx(0.0, abs=1e-12) and kurt == pytest.approx(1.0)
    expected_sr = 0.005 / (0.015 * math.sqrt(100 / 99))
    assert sr == pytest.approx(expected_sr)
    hand = _N.cdf(expected_sr * math.sqrt(99) / math.sqrt(1.0))  # (γ₄−1)/4 = 0, γ₃ = 0
    assert overfit.psr(x) == pytest.approx(hand)
    assert overfit.psr(x, sr_benchmark=expected_sr) == pytest.approx(0.5)


def test_expected_max_sharpe_and_dsr_monotone_in_trials() -> None:
    assert overfit.expected_max_sharpe(1, 1.0) == 0.0
    maxes = [overfit.expected_max_sharpe(n, 0.01) for n in (2, 10, 100, 1000, 5000)]
    assert maxes == sorted(maxes)
    rng = np.random.default_rng(0)
    x = rng.normal(0.02, 0.1, 240)
    dsrs = [overfit.dsr(x, n, 0.01) for n in (1, 10, 100, 1000, 5000)]
    assert all(a > b for a, b in zip(dsrs, dsrs[1:], strict=False))
    assert dsrs[0] == pytest.approx(overfit.psr(x))  # one trial: nothing to deflate


def test_hlz_threshold() -> None:
    assert overfit.hlz_threshold(1) == pytest.approx(1.959964, abs=1e-6)
    assert overfit.hlz_threshold(100) == pytest.approx(_N.inv_cdf(1 - 0.05 / 200))
    assert overfit.hlz_threshold(5000) > overfit.hlz_threshold(100) > 3.0


def test_moments_guards() -> None:
    sr, n, _, _ = overfit.moments([0.01, np.nan])
    assert n == 1 and math.isnan(sr)
    assert math.isnan(overfit.psr([0.01, 0.01, 0.01, 0.01]))  # zero variance


def test_pbo_is_about_half_on_pure_noise() -> None:
    rng = np.random.default_rng(42)
    noise = rng.normal(0.0, 0.05, size=(192, 60))
    res = overfit.pbo_cscv(noise, s=16, max_splits=1000, seed=1)
    assert res.n_splits == 1000
    assert 0.35 <= res.pbo <= 0.65
    assert res.degradation_slope < 0.5  # the IS edge does not carry over


def test_pbo_is_near_zero_with_one_dominant_signal() -> None:
    rng = np.random.default_rng(7)
    m = rng.normal(0.0, 0.05, size=(192, 60))
    m[:, 13] += 0.04  # one genuinely skilled trial
    res = overfit.pbo_cscv(m, s=16, max_splits=1000, seed=1)
    assert res.pbo < 0.05
    assert res.prob_oos_loss < 0.05


def test_pbo_uses_all_splits_by_default_and_tolerates_nans() -> None:
    rng = np.random.default_rng(3)
    m = rng.normal(0.0, 0.05, size=(40, 6))
    m[:5, 2] = np.nan  # a trial with a late start
    res = overfit.pbo_cscv(m, s=4)
    assert res.n_splits == math.comb(4, 2)
    assert np.isfinite(res.logits).all()


def test_pbo_input_validation() -> None:
    with pytest.raises(ValueError, match="N ≥ 2"):
        overfit.pbo_cscv(np.zeros((20, 1)))
    with pytest.raises(ValueError, match="s must be even"):
        overfit.pbo_cscv(np.zeros((20, 3)), s=5)
