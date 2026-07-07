# Research Log — append-only

> Every experiment that touches the OOS vault is registered **here, before it runs** (see
> `docs/RESEARCH_PLAYBOOK.md` §4 and §8 for the rules and the entry template). Entries are
> append-only: never edit or delete a past entry; corrections are new entries that reference the
> old id. The certify CLI refuses to run without a committed entry whose spec hash matches.

---

## 000 — institution established (2026-07-03, model: Fable 5)

- Decisions frozen with the user: success = 6-month benchmark-relative (3m secondary); monthly
  top-10–20 rebalance; US first, Taiwan second; free data first.
- Splits frozen: Development 2010–2019 · Validation 2020–2022 · OOS vault 2023→(complete-label
  frontier). OOS budget: 3 attempts per family.
- Gates v1 frozen as `docs/RESEARCH_PLAYBOOK.md` §5 (to be mirrored in `research/gates.py`,
  Phase 8.2, with a sync test).
- Known accepted limitations recorded in `docs/NORTH_STAR.md` (survivorship: current universe;
  TW synthetic filed_at until Phase 11.1; free-data ceiling).
- No signals exist yet. Next research entries begin at 001 with Phase 10 pre-registrations.

---

## 001 — us-momentum / us-mom-12-1 (2026-07-08, model: Fable 5)

- Hypothesis: skip-month momentum (`ret_12_1`) ranks 6-month benchmark-relative winners in the
  eligible US universe (top-20, monthly rebalance).
- Panel: `panel_us` built 2026-07-07 (universe 3,436; 199 months 2010-01→2026-07; eligible
  807→2,283/month; 0 dropped; survivorship: current_universe (optimistic)). Data note: an
  adjustment-basis seam scan across all 3,452 cached US price files found **0** split-sized and
  **0** mild breaks at fetch-segment joins — the stitched price cache is clean for this work.
- **Development-only evaluations** (2010-01→2019-12, 120 months; no row ≥ 2020 was read):

  | candidate | IC (t) | Q5−Q1 /mo | 6m beat rate (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- | --- |
  | v1 `{ret_12_1: 1.0}` | +0.013 (0.92) | +0.37% (53% pos.) | **43.5% (−2.37)** | 38% |
  | v2a `{ret_12_1: 1, vol_63d: −0.5}` (pre-authorized tilt) | +0.017 (1.03) | — | **43.7% (−2.79)** | 47% |
  | v2b `{ret_12_1: 1, vol_63d: −1.0}` | +0.018 (1.00) | — | **42.9% (−3.44)** | 54% |
  | reference `{vol_63d: −1.0}` | +0.011 (0.54) | — | 46.3% (−1.05) | 39% |

- Validation window (2020–2022): **not evaluated** — the development verdict was terminal;
  fewer looks, less dredging.
- **Verdict: FAMILY CLOSED AT DEVELOPMENT.** The headline-gate analogue (cohort 6m beat rate) is
  significantly *below* 50% in development for every variant: an equal-weight top-20 book drawn
  from this ~2,000-name universe carries a structural cap-weighting headwind against SPY that
  price momentum does not overcome (mega-cap-led decade), with or without a low-vol tilt.
  G3 (≥ 55%) is unreachable; certifying would have wasted vault budget.
- OOS attempts spent: **0 of 3** — the vault was never touched; development failures are free.
- Registry status change: none (the spec was never pre-registered).
- Implication for 10.2/10.3: the same equal-weight-vs-SPY headwind applies to any top-N family;
  check the dev beat rate before anything else. If every free family dies here, that aggregate
  finding triggers the 12.3 data-decision memo / a user-level discussion of the program — it is
  **not** grounds for softening gates.
