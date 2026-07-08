"""The referee's numbers — universe hygiene (§3) and certification gates (§5).

Every constant mirrors ``docs/RESEARCH_PLAYBOOK.md`` and is pinned by a test
(the duplication is the tripwire: changing either place alone fails CI). A
change here is a process event (playbook §4 rule 4: its own PR, playbook
updated in the same commit, every existing certification voided and re-run).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

# Min raw close, in the market's local currency (US$2 / NT$10).
MIN_PRICE: dict[str, float] = {"US": 2.0, "Taiwan": 10.0}

# Min liquidity: 21-day median of close×volume (US$5M / NT$50M).
MIN_DOLLAR_VOL_21D: dict[str, float] = {"US": 5_000_000.0, "Taiwan": 50_000_000.0}

# One trading year of history before a name is rankable.
MIN_HISTORY_BARS: int = 252

# Months with fewer eligible names are dropped and reported, never silently kept.
MIN_CROSS_SECTION: int = 100

# --- Certification gates G1–G6 (playbook §5) — all evaluated on the OOS vault only ---

# The vault: certification evaluates months on/after this date; development never reads past it.
OOS_START: str = "2023-01-01"

G1_MIN_IC: float = 0.03  # mean monthly Spearman IC (score vs fwd_1m_rel)
G1_MIN_T: float = 2.0  # plain t-stat of the monthly IC series
G1_MIN_MONTHS: int = 24  # minimum OOS months

G2_MIN_POSITIVE_SHARE: float = 0.55  # Q5−Q1 spread positive in ≥ this share of months (mean > 0)

# G3 (selection skill) — per-cohort alpha = (equal-weight top-N book 6m fwd_6m_rel mean − equal-
# weight eligible-universe 6m fwd_6m_rel mean). Both legs are benchmark-relative, so the benchmark
# AND the equal-weight/breadth premium cancel, leaving pure stock-picking. Requires mean > 0 and
# NW-t (lag 5) vs 0 ≥ the floor. The certified probability *displayed* is the portfolio-cohort beat
# rate vs the benchmark; the *gate* is skill above equal-weighting, so the EW premium alone can't
# certify. Redefined 2026-07-08 (RESEARCH_LOG 008) — replaced the old individual-pick beat rate,
# which was biased below 50% by cap-weight-benchmark concentration.
G3_MIN_SKILL_T: float = 2.0  # Newey–West t (lag 5) of the per-cohort selection alpha, vs 0
NW_LAG: int = 5  # Bartlett lag for overlapping 6m windows on a monthly cadence

G4_COST_BPS: float = 20.0  # all-in per-side trading cost for the top-N backtest

G5_MAX_PARAMS: int = 4  # free parameters: each nonzero feature weight counts as one

G6_MAX_TURNOVER: float = 0.40  # mean one-way monthly turnover of the top-N set
G6_STRESS_TURNOVER: float = 0.60  # 40–60%: G4 must also pass at the stress cost; above: reject
G6_STRESS_COST_BPS: float = 40.0


def nw_tstat(series: npt.ArrayLike, null: float = 0.0, lag: int = 5) -> float:
    """t-stat of mean(series) vs `null`, Newey-West (Bartlett) HAC standard error.

    Use for overlapping-window series (e.g. monthly cohorts of 6m beat rates, lag=5).
    """
    x = np.asarray(series, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    mu = x.mean() - null
    e = x - x.mean()
    s = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * float(e[:-k] @ e[k:]) / n
    return float(mu / np.sqrt(s / n))


def nw_ci95(series: npt.ArrayLike, lag: int = 5) -> tuple[float, float]:
    x = np.asarray(series, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    e = x - x.mean()
    s = float(e @ e) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * float(e[:-k] @ e[k:]) / n
    half = 1.96 * float(np.sqrt(s / n))
    return float(x.mean() - half), float(x.mean() + half)
