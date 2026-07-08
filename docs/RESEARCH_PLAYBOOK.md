# Research Playbook — how a signal becomes a standard

> Binding process for all signal research. Written so a session with **no quant background** can
> execute it mechanically: every threshold is a number, every judgment call is pre-made. If a
> situation is not covered here, **stop and ask the user** — do not improvise statistics.

## 1. Vocabulary

- **Feature** — one numeric column of the research panel (e.g. `roic`, `ret_12_1`). Features are
  point-in-time by construction (fundamentals keyed on `filed_at`).
- **Signal / spec** — a frozen recipe: a named set of features with fixed weights, ranked
  cross-sectionally within one market, taking the top `top_n`. Serialized as a `SignalSpec` JSON;
  identified by `name`, `version`, and its canonical SHA-256 hash.
- **Family** — a group of specs testing one idea (e.g. "US momentum"). The OOS budget (§4) is
  spent per family.
- **Panel** — the persisted research dataset: one row per (month-end, symbol) with features,
  eligibility, and forward labels. Built by `heimdall.research.build_dataset` (Phase 7.3).
- **Cohort** — the top-N picks of one rebalance date.
- **Certification** — a spec passing all gates (§5) on the OOS window, with a pre-registered log
  entry. Only certified specs may drive Today's Picks.

## 2. Labels (fixed)

For each (month-end `t`, symbol) row, using next-trading-day-adjusted closes:

- `fwd_1m` — return from `t` to the next rebalance date (used for IC/quantiles/backtest).
- `fwd_3m`, `fwd_6m` — 63- and 126-trading-day forward returns.
- `*_rel` variants — the same minus the market benchmark's return over the identical window
  (`SPY.US` for US, `0050.TW` for Taiwan). **All gates use `_rel` labels.**
- A row whose forward window is incomplete gets NaN labels (never a partial return).

## 3. Universe hygiene (applied before any scoring; constants live in `research/gates.py`)

| Filter | US | Taiwan |
| --- | --- | --- |
| Min price | $2 | NT$10 |
| Min liquidity (21-day median of close×volume) | $5M | NT$50M |
| Min history | 252 trading days | 252 trading days |
| Min cross-section per month | 100 eligible names, else the month is **dropped and reported** | same |

Ineligible rows stay in the panel with `eligible=False` and a reason — filtered, not deleted.

## 4. Data splits and the OOS discipline (frozen 2026-07-03)

| Window | Range | May be used for |
| --- | --- | --- |
| **Development** | 2010-01-01 → 2019-12-31 | Anything: explore, tune weights, iterate freely. |
| **Validation** | 2020-01-01 → 2022-12-31 | Selecting *which* dev-tuned spec to advance (covers crash, melt-up, bear). Iterate here sparingly. |
| **OOS vault** | 2023-01-01 → latest month with complete 6m labels | **Certification only.** |

Rules — these are the institution; breaking them silently destroys the project's meaning:

1. **Pre-register before touching the vault.** Append a `RESEARCH_LOG.md` entry (template §8) with
   the spec hash and a falsifiable hypothesis, **commit it**, then run certification. The certify
   CLI (Phase 8.2) refuses to run without a matching committed log entry.
2. **3 OOS attempts per family, ever.** v1/v2/v3. All spent and failed → the family is closed;
   reopening requires new *data* (not new weights) and a user sign-off recorded in the log.
3. **A failed certification is a successful experiment.** Log it, set status `rejected`, close the
   task as done. Tweaking weights and quietly re-running against the vault is the cardinal sin.
4. Gates never bend to fit a result. Changing `research/gates.py` is its own PR that must cite
   this file, update it in the same commit, and void (re-run) every existing certification.

## 5. Certification gates (v1 — mirror of `research/gates.py`; test-enforced to stay in sync)

All computed on the **OOS window only**, `_rel` labels, eligible rows only. Every gate must pass.

| # | Gate | Threshold |
| --- | --- | --- |
| G1 | Mean monthly Spearman IC (score vs `fwd_1m_rel`), plain t-stat, sample | IC ≥ **0.03**, t ≥ **2.0**, ≥ **24** months |
| G2 | Quintile spread: mean(Q5 − Q1 `fwd_1m_rel`); share of positive months | mean > **0**; positive in ≥ **55%** of months |
| G3 | **Selection skill** (the headline gate): per-cohort alpha = (EW top-N book 6m `fwd_6m_rel` mean − EW eligible-universe 6m mean); Newey–West t (lag 5) vs 0 | mean > **0**, NW-t ≥ **2.0** |
| G4 | Cost-aware top-N monthly backtest (20 bps per side all-in) vs benchmark | OOS CAGR **and** Sharpe both > benchmark |
| G5 | Stability: split OOS into halves; free-parameter count | mean IC > 0 in **both** halves; ≤ **4** parameters (each nonzero feature weight counts as one) |
| G6 | Mean one-way monthly turnover of the top-N set | ≤ **40%**; 40–60% → G4 must also pass at 40 bps per side; > 60% → reject |

**G3 rationale (redefined 2026-07-08, RESEARCH_LOG 008).** The old G3 (mean cohort *individual-pick*
beat rate ≥ 0.55) was biased below 50% by cap-weight-benchmark concentration (the median stock
underperforms a single-name-dominated index), and the naive portfolio fix is biased *high* by the
equal-weight/breadth premium (a no-skill EW book beat 0050 in 80.6% of validation cohorts). G3 now
gates the **selection alpha vs the equal-weight universe**, where both the benchmark and the EW
premium cancel — so it certifies stock-picking, not the tilt.

**Displayed probability** = the **portfolio-cohort beat rate** vs the benchmark — the fraction of
monthly cohorts whose EW top-N *book* beat 0050/SPY over the next 6 months — with its NW 95% CI
(`mean ± 1.96·SE_NW`) and the cohort count, shown next to the G3 selection-alpha. The UI must always
show the CI, `n`, and the skill-vs-EW-premium split, never a point estimate alone.

Reference implementations (copy verbatim; no new dependencies):

```python
import numpy as np
import numpy.typing as npt

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
```

## 6. Signal lifecycle

```
draft ──(pre-register: log entry + committed hash)──► registered
registered ──(certify CLI, all gates pass)──► certified ──► shown on Today's Picks
registered ──(any gate fails)──► rejected  (log the numbers honestly)
certified ──(drift alarm §9 or data break)──► under_review ──► retired | re-certified as new version
```

Registry statuses live in `signals/registry.json`; transitions happen **only** through
`heimdall.research` code paths, never by hand-editing (except `draft` creation).

## 7. Checklists

**Add a feature to the panel** (the only entry point for new predictive data):
1. Implement in `factors/metrics.py` (snapshot fields flow into the panel automatically) or in
   `research/dataset.py` for panel-only features. Fundamentals must key off `filed_at`.
2. Mandatory tests: a known-answer value test AND a point-in-time leak test (a value filed after
   date *d* must be absent from the row at *d*).
3. Document direction + rationale in one line in the feature table of `research/dataset.py`.
4. Run the 4 quality gates (ruff check / format, mypy, pytest). One PR.

**Propose a signal:** pick features already in the panel → tune weights on Development only →
frozen candidate → evaluate on Validation → if it looks alive, write the spec JSON under
`signals/specs/`, append a `RESEARCH_LOG` "registered" entry with the hash, commit.

**Certify:** `uv run python -m heimdall.research.certify signals/specs/<name>.json --log-entry <id>`
→ report JSON under `signals/certifications/` + registry update. Never run twice for one entry.

**Wire to Today's Picks:** nothing to do — the page reads every `certified` entry from the
registry. If it doesn't appear, the status isn't `certified`; fix the process, not the page.

**Monthly ops** (until Phase 12 automates): refresh snapshot (Build data page) → extend the panel
(`build_dataset` is resumable) → glance at the monitoring page for drift.

## 8. RESEARCH_LOG entry template

```markdown
## <id> — <family> / <spec name> v<N>   (<YYYY-MM-DD>, model: <who>)
- Hypothesis: <one falsifiable sentence, e.g. "12-1 momentum ranks 6m relative winners in US large caps">
- Spec: signals/specs/<file>.json   sha256: <hash>
- Dev result (2010–2019): IC <x>, Q5−Q1 <x>, notes
- Validation result (2020–2022): IC <x>, beat-rate <x>
- OOS attempt: <1|2|3> of 3
- OOS verdict: <pending | CERTIFIED | REJECTED (which gates failed, with numbers)>
- Registry status change: <registered → …>
```

## 9. Post-certification monitoring (Phase 12.2)

Each month, `heimdall.research.monitor` recomputes the realized OOS cohorts from the current panel
and appends the newest to the certification's monitoring series. The monitored quantity is **what was
certified — the G3 selection alpha** (per-cohort EW top-N book 6m minus EW eligible-universe 6m), not
the EW-premium-inflated beat rate (updated for the 12.5 decomposed metric; the alpha's null is 0, the
old beat rate's was 0.5). If the **trailing-12-cohort NW 95% CI upper bound falls below 0** — i.e. the
skill has gone significantly negative — the signal flips to `under_review` automatically and Today's
Picks shows a warning banner instead of its ranking. No silent decay. (The trailing beat rate is
still tracked and displayed, but the auto-flip guards the certified edge, not the tilt.)

## 10. Anti-patterns (named, so reviews can cite them)

- **Vault-peeking** — computing anything on 2023+ data during development. Includes "just to see".
- **Respin** — tweaking a rejected spec and re-certifying without a new log entry/attempt.
- **Gate-shopping** — proposing threshold changes alongside a result they would flip.
- **Label leakage** — a feature mechanically containing the label (e.g. any forward-window data);
  the oracle canary (Phase 8.3) exists to prove the harness *would* catch a leak's signature.
- **Uncertified display** — any ranking on Today's Picks not backed by a `certified` registry row.
- **Survivorship amnesia** — reporting certified numbers without the `current_universe` stamp.
- **Silent universe drift** — changing hygiene constants (§3) without re-certifying.

## 11. Working agreement for future (smaller-model) sessions

1. Read `docs/NORTH_STAR.md`, then pick the **single next unchecked card** in
   `docs/ROADMAP_V2.md` (or the card the user names). One card = one PR.
2. Never widen scope mid-card. Found a bug outside the card? Note it for the user; don't fix it inline.
3. Always finish with the quality gates: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest`.
4. Statistics beyond this playbook (new gate, new CI method, optimizer) → propose to the user
   first; never invent under time pressure.
5. When numbers disagree with expectations, report them as they are. The institution's only asset
   is that its numbers mean something.
