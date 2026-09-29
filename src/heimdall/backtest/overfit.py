"""Over-fitting statistics for selection among many backtests (roadmap 18.4).

When thousands of candidates are tried, the best in-sample result looks good by luck alone.
These are the standard corrections the Strategy Factory gates on (playbook §12.1):

- :func:`psr` — Probabilistic Sharpe Ratio: P(true SR > a benchmark SR) given the sample
  length, skew and kurtosis (Bailey & López de Prado, 2012, *The Sharpe Ratio Efficient
  Frontier*).
- :func:`expected_max_sharpe` / :func:`dsr` — the Deflated Sharpe Ratio: the PSR against the
  Sharpe the best of ``n_trials`` *unskilled* candidates would show by chance (Bailey & López
  de Prado, 2014, *The Deflated Sharpe Ratio*). F1.
- :func:`pbo_cscv` — Probability of Backtest Overfitting by combinatorially-symmetric
  cross-validation: how often the in-sample winner ranks below the median out-of-sample
  (Bailey, Borwein, López de Prado & Zhu, 2017, *The Probability of Backtest Overfitting*). F2.
- :func:`hlz_threshold` — the Bonferroni multiple-testing t hurdle of Harvey, Liu & Zhu (2016),
  *…and the Cross-Section of Expected Returns*, for display.

All Sharpe ratios here are **per period** (not annualized) unless a function says otherwise; a
variance of Sharpe ratios must be on the same scale. Pure numpy + stdlib ``NormalDist`` — no new
dependency. Lives in ``backtest/`` so both ``research.factory`` and the technical-rule factory
(18.8) can use it (``backtest`` may not import ``research``).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def moments(returns: npt.ArrayLike) -> tuple[float, int, float, float]:
    """(per-period Sharpe, n, skew, kurtosis) of a return series, NaNs dropped.

    Sharpe = mean / sample std (ddof 1); skew and kurtosis are the population moment ratios
    (kurtosis is *not* excess: a normal distribution has 3).
    """
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return float("nan"), n, float("nan"), float("nan")
    sd = float(x.std(ddof=1))
    e = x - x.mean()
    m2 = float((e**2).mean())
    skew = float((e**3).mean() / m2**1.5) if m2 > 0 else float("nan")
    kurt = float((e**4).mean() / m2**2) if m2 > 0 else float("nan")
    return (float(x.mean()) / sd if sd > 0 else float("nan")), n, skew, kurt


def psr_from_moments(
    sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0
) -> float:
    """PSR = Φ[(SR − SR*)·√(n−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²)] (Bailey & López de Prado 2012)."""
    if not all(math.isfinite(v) for v in (sr, skew, kurt, sr_benchmark)) or n < 2:
        return float("nan")
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return float("nan")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom))


def psr(returns: npt.ArrayLike, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio of a return series against ``sr_benchmark`` (per period)."""
    sr, n, skew, kurt = moments(returns)
    return psr_from_moments(sr, n, skew, kurt, sr_benchmark)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max SR] of ``n_trials`` unskilled candidates with Sharpe variance ``sr_variance``:
    √V · [(1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))] (γ = Euler–Mascheroni). 0 for N ≤ 1."""
    if n_trials <= 1 or not (math.isfinite(sr_variance) and sr_variance >= 0):
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b)


def dsr_from_moments(
    sr: float, n: int, skew: float, kurt: float, n_trials: int, sr_variance: float
) -> float:
    """Deflated Sharpe Ratio: the PSR against :func:`expected_max_sharpe`."""
    return psr_from_moments(sr, n, skew, kurt, expected_max_sharpe(n_trials, sr_variance))


def dsr(returns: npt.ArrayLike, n_trials: int, sr_variance: float) -> float:
    """Deflated Sharpe Ratio of a return series selected as the best of ``n_trials``.

    ``sr_variance`` = variance of the per-period Sharpe ratios across all the run's trials.
    """
    sr, n, skew, kurt = moments(returns)
    return dsr_from_moments(sr, n, skew, kurt, n_trials, sr_variance)


def hlz_threshold(n_trials: int, alpha: float = 0.05) -> float:
    """Bonferroni t hurdle for ``n_trials`` two-sided tests at family-wise level ``alpha``
    (Harvey, Liu & Zhu 2016): Φ⁻¹(1 − α / (2N)). 1.96 for a single test."""
    return _N.inv_cdf(1.0 - alpha / (2.0 * max(n_trials, 1)))


@dataclass
class PBOResult:
    pbo: float  # share of splits whose in-sample winner ranks at/below the OOS median
    logits: npt.NDArray[np.float64]  # λ per split (≤ 0 ⇒ overfit in that split)
    n_splits: int
    degradation_slope: float  # OLS slope of the winner's OOS Sharpe on its IS Sharpe
    prob_oos_loss: float  # share of splits whose winner has a negative OOS Sharpe


def _block_sums(
    m: npt.NDArray[np.float64], s: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Per-block (S × N) sums, sums of squares and counts, NaN-aware."""
    blocks = np.array_split(np.arange(m.shape[0]), s)
    finite = np.isfinite(m)
    z = np.where(finite, m, 0.0)
    s1 = np.stack([z[b].sum(axis=0) for b in blocks])
    s2 = np.stack([(z[b] ** 2).sum(axis=0) for b in blocks])
    cnt = np.stack([finite[b].sum(axis=0) for b in blocks]).astype(float)
    return s1, s2, cnt


def _sharpe(
    s1: npt.NDArray[np.float64], s2: npt.NDArray[np.float64], cnt: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s1 / cnt
        var = (s2 - cnt * mean**2) / (cnt - 1.0)
        out = mean / np.sqrt(var)
    out[~np.isfinite(out)] = np.nan
    return np.asarray(out, dtype=float)


def pbo_cscv(
    trial_matrix: npt.ArrayLike,
    s: int = 16,
    max_splits: int | None = None,
    seed: int = 0,
    chunk: int = 256,
) -> PBOResult:
    """Probability of Backtest Overfitting by CSCV (Bailey, Borwein, López de Prado & Zhu 2017).

    ``trial_matrix`` is T periods × N trials of returns (NaN allowed — a trial with no return in
    a period simply has fewer observations). Rows are cut into ``s`` contiguous blocks; every
    choice of ``s/2`` blocks is an in-sample set and its complement the out-of-sample set. The
    in-sample Sharpe winner's OOS relative rank ω gives λ = ln(ω / (1 − ω)); PBO = P(λ ≤ 0).
    ``max_splits`` draws a seeded random subset of the C(s, s/2) splits for speed.
    """
    m = np.asarray(trial_matrix, dtype=float)
    if m.ndim != 2 or m.shape[1] < 2:
        raise ValueError("trial_matrix must be T periods × N ≥ 2 trials")
    if s < 2 or s % 2 or m.shape[0] < s:
        raise ValueError(f"s must be even, ≥ 2 and ≤ the number of periods; got s={s}")
    n_trials = m.shape[1]
    s1, s2, cnt = _block_sums(m, s)
    splits = list(itertools.combinations(range(s), s // 2))
    if max_splits is not None and len(splits) > max_splits:
        rng = np.random.default_rng(seed)
        pick = rng.choice(len(splits), size=max_splits, replace=False)
        splits = [splits[i] for i in sorted(pick)]
    mask = np.zeros((len(splits), s))
    for k, combo in enumerate(splits):
        mask[k, list(combo)] = 1.0

    logits: list[float] = []
    is_best: list[float] = []
    oos_best: list[float] = []
    for lo in range(0, len(splits), chunk):
        mk = mask[lo : lo + chunk]
        is_sr = _sharpe(mk @ s1, mk @ s2, mk @ cnt)
        oos_sr = _sharpe((1 - mk) @ s1, (1 - mk) @ s2, (1 - mk) @ cnt)
        winner = np.nanargmax(np.where(np.isnan(is_sr), -np.inf, is_sr), axis=1)
        rows = np.arange(len(mk))
        w_oos = oos_sr[rows, winner]
        oos_filled = np.where(np.isnan(oos_sr), -np.inf, oos_sr)
        w_filled = oos_filled[rows, winner][:, None]
        below = (oos_filled < w_filled).sum(axis=1)
        ties = (oos_filled == w_filled).sum(axis=1)
        rank = below + (ties + 1) / 2.0  # average rank, 1 = worst
        omega = rank / (n_trials + 1.0)
        logits.extend(np.log(omega / (1.0 - omega)).tolist())
        is_best.extend(is_sr[rows, winner].tolist())
        oos_best.extend(w_oos.tolist())

    lam = np.asarray(logits, dtype=float)
    x, y = np.asarray(is_best), np.asarray(oos_best)
    ok = np.isfinite(x) & np.isfinite(y)
    slope = float("nan")
    if ok.sum() >= 2 and float(np.var(x[ok])) > 0:
        slope = float(np.cov(x[ok], y[ok], ddof=1)[0, 1] / np.var(x[ok], ddof=1))
    return PBOResult(
        pbo=float((lam <= 0).mean()),
        logits=lam,
        n_splits=len(lam),
        degradation_slope=slope,
        prob_oos_loss=float((y[np.isfinite(y)] < 0).mean()) if np.isfinite(y).any() else 0.0,
    )
