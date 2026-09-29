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

Strategy Factory path (§12):
draft ──(factory promote: F1–F5 pass)──► incubating ──► shown on the Strategy Lab only
incubating ──(user go/no-go + committed log entry, certify CLI)──► registered ──► certified | rejected
incubating ──(§9 drift rule, once ≥ 12 forward cohorts are realized)──► incubation_retired
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
- **Config-shopping** — declaring a factory search run (§12) whose feature pool or menus were chosen
  after looking at a prior run's VAL numbers, any 2023+ data, or the technical-rule factory's
  results. A new run's pool is justified from DEV evidence or the literature only.
- **Trial amnesia** — showing any factory leaderboard row or number without its run's trial count
  N, DSR and PBO.
- **Tier leakage** — an `incubating` strategy's holdings rendered anywhere a certified list is
  expected (Today's Picks, rebalance defaults, a notification's picks section).

## 11. Working agreement for future (smaller-model) sessions

1. Read `docs/NORTH_STAR.md`, then pick the **single next unchecked card** in
   `docs/ROADMAP_V2.md` (or the card the user names). One card = one PR.
2. Never widen scope mid-card. Found a bug outside the card? Note it for the user; don't fix it inline.
3. Always finish with the quality gates: `uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest`.
4. Statistics beyond this playbook (new gate, new CI method, optimizer) → propose to the user
   first; never invent under time pressure.
5. When numbers disagree with expectations, report them as they are. The institution's only asset
   is that its numbers mean something.

## 12. Automated search — the Strategy Factory (added 2026-09-30, RESEARCH_LOG 019)

The factory (ROADMAP_V2 Phase 18) lets the platform generate candidates itself instead of a session
hand-writing 1–8 per card. Searching thousands of candidates makes the best in-sample result look
good by luck alone, so every factory number is **deflated by how many were tried**. The rules below
bind the factory code and every session that runs it; §4–§6 still hold unchanged — the factory adds
a tier *below* certification, it never replaces the vault.

### 12.1 Factory gates (mirror of `research/gates.py` `FACTORY_*`; test-enforced to stay in sync)

A candidate enters the `incubating` tier only if its run passes F2, it passes F1, F3 and F5 on DEV,
and it then passes F4 on its single VAL look. User-confirmed 2026-09-30.

| # | Factory gate (DEV unless stated) | Threshold |
| --- | --- | --- |
| F1 | Deflated Sharpe Ratio of the candidate's monthly **net selection-alpha** series (EW book net of costs − EW tier universe, `fwd_1m_rel` basis), deflated by the run's trial count N and the cross-trial Sharpe variance | DSR ≥ **0.95** |
| F2 | Run-level Probability of Backtest Overfitting (CSCV, S = **16** blocks of DEV months) | PBO ≤ **0.30**, else **no** candidate of the run is promoted |
| F3 | G3 selection alpha (6m, certify math) NW-t — the Harvey–Liu–Zhu hurdle for mined signals — plus G1 IC t | alpha NW-t ≥ **3.0** and IC t ≥ **2.0** |
| F4 | VAL single look (≤ **5** finalists per run) | selection alpha > 0 **and** mean IC > 0; turnover ≤ **60%** |
| F5 | Free parameters (G5 counting; structural menu picks don't count but are disclosed) | ≤ **4** |
| F6 | Trials per run | N ≤ **5,000** |

Why these numbers: F1 and F2 are the standard corrections for selection among many backtests
(Bailey & López de Prado 2014; Bailey, Borwein, López de Prado & Zhu 2017); F3 raises the hand-made
t ≥ 2 bar to t ≥ 3 because a mined candidate has already been selected for a high t (Harvey, Liu &
Zhu 2016); F6 bounds the run so its N stays interpretable. Changing any of them follows §4 rule 4
(its own PR, playbook + `gates.py` in one commit, every incubating strategy re-evaluated).

### 12.2 Declaring and running a search

1. A **search run** is declared by `signals/search/<run_id>/config.json`. Its canonical hash goes into
   a committed RESEARCH_LOG "search declared" entry **before** the run; the factory refuses to run
   otherwise.
2. The config fixes the whole space: the feature pool with **a-priori directions** (from the
   `research/dataset.py` feature table, the `_technicals` comments, or cited literature — never
   inferred from data; directions are never searched), the weight menu, the construction menus,
   the universes, the stages, and the seed. Nothing is added mid-run; a changed config is a new run.
3. **Every** evaluated candidate is a **trial**, appended to `signals/search/<run_id>/trials.parquet`
   (append-only: trial id, spec hash, DEV metrics, and the monthly series F1/F2 need). N = its row
   count. N, DSR and PBO travel with every number the run shows (see *trial amnesia*, §10).
4. Search reads **DEV rows only**. VAL is one look per finalist (≤ 5 per run, F4). The OOS vault
   stays `certify`'s alone (§4).

### 12.3 Families, the vault, and the incubating tier

- Each run is its own family `us-factory-<run_id>` with the standard 3-attempt budget, and **at most
  one finalist per run may be pre-registered** — after a recorded user go/no-go, exactly as §4.
- A finalist whose **recipe hash** equals that of any spec already in the registry is ineligible
  (no respins through the factory). The recipe hash (`SignalSpec.recipe_hash`) is the canonical
  payload without `name`/`family`/`version` — the canonical hash would change on a mere rename, so
  it cannot catch a respin (clarified 2026-09-30 by card 18.7).
- Every certification report of a factory spec states the run's N, DSR and PBO and the market's
  **cumulative vault-touch count** (US: 2 as of 2026-09-30 — `us-fcf-yield` v1 and v2).
- **Incubating tier.** F1–F5 pass → registry `draft → incubating` via `research.factory` → monthly
  ledger freezes (the 16.1 machinery, append-only, no backfill) → rendered **only** on the Strategy
  Lab, labeled 「未認證・孵化中」, with its run's N/DSR/PBO. It never feeds Today's Picks, rebalance
  defaults, or a notification's picks section (*tier leakage*, §10).
- **Demotion.** Once ≥ **12** forward cohorts are realized, the §9 drift rule applies: trailing-12
  NW 95% CI upper bound of the selection alpha < 0 → `incubation_retired` (terminal).
- **Promotion to certified** only through the unchanged path: user go/no-go → committed log entry →
  `certify` (G1–G6 on the vault) → `certified` | `rejected`.

### 12.4 Overlay (market-timing) strategies

A regime overlay (e.g. cash when the benchmark is below its 200-day SMA) is a book-level switch.
The **selection** gates — G1–G3, G5, G6 and F1–F4 — score the **un-overlaid** book, so timing
cannot masquerade as stock-picking; G4 and every displayed equity curve use the **overlaid** book.

### 12.5 Single-stock technical rules

Daily entry/exit rules (the technical-rule factory, ROADMAP 18.8) are **research-only**: their
horizon is under the NORTH_STAR one-month floor, so they are never tiered, never registered, and
never read the research panel. They still report their trial count and DSR, and their results may
not inform any factory config (*config-shopping*, §10).
