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

---

## 002 — us-quality / equal-weight profitability (2026-07-08, model: Fable 5)

- Hypothesis: profitable, cash-generative names (`roic`, `fcf_margin`, `operating_margin`,
  equal weights) rank 6-month benchmark-relative winners in the eligible US universe (top-20,
  monthly). Same panel as entry 001.
- Coverage note (dev, eligible rows with all 3 features): 7% in 2010 → ~44% from 2013 → 52% in
  2019 — early-dev cross-sections are thin; `score()`'s missing-data-excludes rule shrinks the
  pool accordingly.
- **Development-only evaluations** (2010-01→2019-12; no row ≥ 2020 read):

  | candidate | IC (t) | 6m beat rate (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- |
  | `{roic, fcf_margin, operating_margin}` equal | +0.008 (0.88) | 51.3% (+0.59) | 12% |
  | `{roic}` pure | −0.004 (−0.43) | 51.6% (+0.71) | 10% |
  | `{roic, fcf_margin}` | +0.005 (0.52) | 50.9% (+0.40) | 11% |

- Contrast with 001 worth keeping: the quality book does **not** suffer the momentum family's
  cap-weighting headwind (beat ≈ 51% vs 43%; turnover ~10%, the book is stable profitable large
  caps that overlap SPY's leadership). The failure mode is different: **no cross-sectional edge**
  — IC is indistinguishable from zero in-sample, an order of magnitude under G1.
- Validation window (2020–2022): not evaluated — terminal dev verdict.
- **Verdict: FAMILY CLOSED AT DEVELOPMENT.** In-sample IC ≈ 0 and beat ≈ coin flip cannot clear
  G1 (≥ 0.03, t ≥ 2) or G3 (≥ 55%, NW-t ≥ 2) out-of-sample. The card's own caution ("quality
  alone is often weak standalone") is confirmed.
- OOS attempts spent: **0 of 3**. Registry status change: none (never pre-registered).
- Implication for 10.3: the value×quality composite (`fcf_yield`, `ev_ebitda`(−), `roic`) adds
  the valuation axis these ratios lack — it is the last free family on the board; same
  discipline: dev beat rate and IC first, close cheaply if dead.

---

## 003 — us-value-quality / us-fcf-yield v1 (2026-07-08, model: Fable 5)

- Hypothesis: high free-cash-flow yield (CFO − capex over market cap) ranks 6-month
  benchmark-relative winners in the eligible US universe (top-20, monthly rebalance).
- Spec: `signals/specs/us-fcf-yield.json`
  sha256: `ade91883d56d9b0b59a8837a9cc88dc027fe7c222f5e04152db5414bf6123871`
- **Development (2010-01→2019-12; full disclosure of the selection — 3 candidates looked at):**

  | candidate | IC (t) | 6m beat (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- |
  | card spec `{fcf_yield, −ev_ebitda, roic}` | −0.004 (−0.38) | 47.9% (−1.00) | 13% |
  | `{fcf_yield, roic}` | −0.002 (−0.18) | 49.8% (−0.07) | 11% |
  | **frozen: `{fcf_yield}` pure** | **+0.022 (+2.87, hit 60%)** | **54.9% (+2.46)** | 10% |

  `roic` and `ev_ebitda` subtract (consistent with entry 002); the single-feature,
  one-parameter spec is frozen. Marginally under the gate floors in-sample (IC 0.022 < 0.03;
  beat 54.9% < 55%) — advanced to validation on the strength of its significance.
- **Validation (2020-01→2022-12; the single look):** IC **+0.058** (t 2.71, hit 64%),
  6m beat **57.1%** (NW-t +1.35, 36 cohorts), turnover 11%. By year: 2020 −0.01, 2021 +0.14,
  2022 +0.05 — flat in the growth melt-up, strong in the value revival and the rate shock.
- OOS attempt: **1 of 3** for family `us-value-quality`.
- OOS verdict: **REJECTED** (2026-07-08; immutable report
  `signals/certifications/us-fcf-yield_v1.json`). OOS window 2023-01→2025-12, 36 cohorts:
  **G1_ic passed** (+0.031 ≥ 0.03) and **G5 stability passed** (IC positive in both halves) —
  the ranking information is real out-of-sample — but G1_t 1.59 < 2, G2 spread −0.24%/mo (47%
  positive), and above all **G3 beat rate 41.4%** (95% CI 35–48%, NW-t −2.77): the top-20 book
  *significantly underperformed* SPY over 6-month windows in the 2023–2025 mega-cap regime.
  G4: 11.3% CAGR / 0.61 Sharpe vs SPY's 21.0% / 1.70.
- Registry status change: draft → registered → **rejected** (attempt 1/3 spent; 2 remain for the
  family, to be used only on genuinely new evidence, not re-weightings).
- **Aggregate Phase-10 finding (001 + 002 + 003):** with free data, at the frozen definition
  (equal-weight top-20 vs SPY, 6-month horizon), **no family certifies** — momentum dev-dead
  (cap-weighting headwind), quality dev-dead (no cross-sectional edge), FCF yield vault-rejected
  (real IC, but SPY's 2023–25 run was unbeatable by a diversified value book). This arms the
  12.3 trigger: the paid-data decision memo and/or a user-level discussion of the program
  definition — **not** gate-softening. Today's Picks stays honestly empty, as designed.

---

## 004 — tw-price-momentum / ret_12_1 (2026-07-08, model: Opus 4.8)

- Hypothesis: skip-month momentum (`ret_12_1`), with an optional low-volatility tilt, ranks
  6-month benchmark-relative winners in the liquid Taiwan universe (top-20, monthly rebalance,
  benchmark `0050.TW`). First TW family of card 11.4.
- Panel: `panel_tw` (prices-only, no FinMind) built 2026-07-08. **Universe = the 800 most-liquid
  cached TW/TWO names** — a documented liquidity/survivorship selection *on top of*
  `current_universe (optimistic)` (see the 11.4 constraint note below); prices deep-backfilled
  2010→ via yfinance (626 deep, 0 fetch failures). 181 months 2011-06→2026-06; eligible/month
  min 125, median 263, max 745; 0 dropped (every month clears the 100-name floor).
- **Development-only evaluations** (2011-06→2019-12, 103 months; no row ≥ 2020 read — a hard
  assertion in the eval guards the OOS vault):

  | candidate | IC (t) | Q5−Q1 /mo | 6m beat rate (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- | --- |
  | v1 `{ret_12_1}` | +0.011 (0.65) | +1.03% (57% pos.) | **44.5% (−1.44)** | 30% |
  | v2 `{ret_12_1: 1, vol_63d: −0.5}` | **+0.042 (2.43)** | +1.00% (62% pos.) | **46.2% (−1.00)** | 35% |

- Validation window (2020–2022): **not evaluated** — the development verdict is terminal on the
  headline (playbook fewer-looks discipline, as in entry 001).
- **Verdict: FAMILY CLOSED AT DEVELOPMENT.** Both variants' cohort 6m beat rate is *below 50%* in
  development — an equal-weight top-20 book cannot beat the **TSMC-dominated, cap-weighted 0050**,
  the same equal-weight-vs-cap-weight headwind that sank US momentum vs SPY (entry 001). G3
  (≥ 55%) is unreachable. Worth recording: the low-vol tilt's **ranking IC is genuinely strong
  (t 2.43, clears G1 in-sample)** and its quintile spread is positive in 62% of months — the
  signal *has* cross-sectional information; it is the benchmark structure, not signal absence,
  that fails the book. Certifying would waste vault budget on a near-certain G3 failure.
- OOS attempts spent: **0 of 3** — the vault was never touched.
- Registry status change: none (never pre-registered).
- **Evidence for the eventual 12.3 / program-definition discussion:** the IC-vs-beat divergence in
  v2 is the cleanest case yet that "equal-weight top-20 beat rate vs a cap-weighted single-name-
  dominated benchmark" may under-credit real cross-sectional signal. Recorded, **not** acted on —
  the frozen definition stands until the user changes it.

### 11.4 free-data constraint (measured 2026-07-08, model: Opus 4.8)

FinMind's free tier serves ~**600 requests/hour**, enforced as a ~26-min IP ban (403 `ip banned`)
then 402 `quota reached`. A full TW panel needs per symbol: fundamentals (3) + monthly revenue (1)
+ daily chips (3) = 7 FinMind calls; for the 800-name universe that is ~5,600 calls ≈ **9
quota-hours** — not buildable in one session. Consequences for 11.4, agreed with the user:
- **Price momentum** needs no FinMind (cached prices) → evaluated above on the full 800-name universe.
- **Revenue momentum + flows** were built on a **reduced ~140-name top-liquidity universe** (fits
  one quota window). See entries 005–006. A full-universe TW build is deferred to a paced crawl
  (a FinMind stream disk-cache, resumable across quota windows) or a paid FinMind tier.

**Reduced-universe panel (entries 005–006):** 140 most-liquid non-ETF TW names (0050 excluded — it
is the benchmark), rev+chips fetched into a local stream cache (560 FinMind calls, 1 ban). The
`min_cross_section = 100` floor vs a 140-name universe drops every month with < 100 eligible, so the
panel is **2017-08→2026-06, 89 months**: DEV (2017-19) only **11 scattered months** (too thin to
decide on), VAL (2020-22) **36 months**, OOS (2023+) **35 complete-label months**. Because DEV is
uselessly thin, the decisive in-sample read below is the robust **validation window** (still
in-sample; the 2023+ vault was never touched — a hard assertion in the eval enforces it). This is a
liquidity/survivorship selection *on top of* `current_universe (optimistic)`.

## 005 — tw-revenue-momentum / monthly-revenue YoY + acceleration (2026-07-08, model: Opus 4.8)

- Hypothesis: Taiwan monthly-revenue momentum (`rev_mom_yoy`, `rev_mom_accel`; 11.2 features, PIT on
  the §36 10th-of-next-month availability) ranks 6-month 0050-relative winners (top-20, monthly).
- **Development (2017-08→2019-12, 11 months — thin, low-confidence):** `rev_accel` IC +0.025
  (t 0.84), Q5−Q1 +1.76% (73% pos.), 6m beat **40.5%**; `rev_yoy+accel` IC +0.023 (t 1.04), beat
  44.1%. All beat rates < 50% on the thin window.
- **Validation (2020-01→2022-12, 36 months — the decisive in-sample read):**

  | candidate | IC (t) | Q5−Q1 /mo (pos) | 6m beat (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- | --- |
  | `{rev_mom_yoy}` | +0.029 (1.23) | +2.18% (69%) | 47.1% (−0.81) | 36% |
  | **`{rev_mom_accel}`** | **+0.043 (1.81)** | +2.34% (75%) | **52.8% (+0.62)** | 41% |
  | `{rev_mom_yoy, rev_mom_accel}` | +0.041 (1.87) | +2.18% (69%) | 50.3% (+0.10) | 39% |

- **Verdict: FAMILY CLOSED AT DEVELOPMENT/VALIDATION.** The revenue-acceleration ranking is real
  (validation IC +0.043, t 1.81; quintile spread positive in 75% of months) — this is a genuine
  free TW signal. But the equal-weight top-20 **book** beats 0050 only **52.8%** of 6-month windows
  (NW-t +0.62, not distinguishable from a coin flip), short of the G3 headline (≥ 55%, NW-t ≥ 2).
  Advancing to the vault is −EV (US fcf-yield failed OOS from a stronger 57% validation, entry 003).
- OOS attempts spent: **0 of 3** — vault untouched; budget intact for the user to deploy later.
- Registry status change: none (never pre-registered).

## 006 — tw-flows / foreign & trust net-buy, holding, margin (2026-07-08, model: Opus 4.8)

- Hypothesis: Taiwan institutional-flow features (11.3: `foreign_net_buy_21d/63d`, `trust_net_buy_21d`,
  `foreign_hold_delta_63d`, `margin_delta_21d`; +1-trading-day PIT shift) rank 6-month 0050-relative
  winners (top-20, monthly). Priors registered in the 11.3 card: foreign-flow momentum is the
  best-documented but most-crowded TW chip signal; margin direction expected negative.
- **Development (11 months — thin):** `foreign_63d` IC +0.036 (t 1.01), beat **41.8%**; `foreign_21d`
  IC **−0.031** (short-horizon foreign flow reverses), beat 40.0%. All < 50% on the thin window.
- **Validation (36 months — the decisive in-sample read):**

  | candidate | IC (t) | Q5−Q1 /mo (pos) | 6m beat (NW-t vs 0.5) | turnover |
  | --- | --- | --- | --- | --- |
  | `{foreign_net_buy_63d}` | +0.033 (1.33) | +1.22% (56%) | 50.8% (+0.18) | 39% |
  | `{foreign_net_buy_21d}` | +0.043 (1.95) | +1.39% (61%) | 52.2% (+0.61) | **68%** |
  | `{foreign_63d, trust_21d×0.5}` | +0.024 (0.96) | +0.94% (56%) | **52.9% (+0.63)** | 48% |
  | `{foreign_63d, margin_21d×−0.5}` | +0.038 (1.84) | +0.74% (64%) | 52.4% (+0.48) | 49% |

- **Verdict: FAMILY CLOSED AT DEVELOPMENT/VALIDATION.** Foreign-flow momentum shows the strongest
  single-feature IC of any TW family (`foreign_21d` validation IC +0.043, t 1.95 — nearly G1's t 2),
  confirming the literature's prior that it is the best-documented TW chip signal. But again the
  top-20 book beats 0050 only ~51–53% over 6-month windows (all NW-t < 1, none ≥ G3's 55%); the
  best book-beat (`foreign+trust`, 52.9%) also isn't significant. `foreign_21d`'s 68% turnover would
  additionally face the G6 stress band. Short-horizon foreign flow (`foreign_21d`) even had negative
  dev IC — consistent with the "most-crowded, fastest-decaying" prior. Not worth a vault attempt.
- OOS attempts spent: **0 of 3** — vault untouched; budget intact.
- Registry status change: none.

## 007 — 11.4 aggregate TW finding (2026-07-08, model: Opus 4.8)

- Across all three TW families (price momentum on the broad 800-name panel; revenue + flows on the
  reduced 140-name panel), the story is identical and now spans two markets: **the factors carry
  real positive cross-sectional IC** (TW validation: revenue t 1.81, flows t 1.95; quintile spreads
  positive in 56–75% of months) **yet the equal-weight top-20 book's 6-month beat rate vs the
  TSMC-dominated, cap-weighted 0050 caps at ~53%** — never the G3 headline (55%), never significant.
  The same equal-weight-vs-cap-weight structure sank every US family vs SPY (entries 001–003).
- This is the clearest evidence yet that the **frozen success definition** (equal-weight top-20 6m
  beat rate vs a cap-weighted, single-name-dominated benchmark) may be structurally unable to
  certify signals that demonstrably *do* rank the cross-section. Strong input for the **12.3
  program-definition discussion** — candidate remedies to raise with the user (each a definition
  change requiring sign-off, never a silent gate edit): a benchmark-/cap-weighted book instead of
  equal-weight; an equal-weight benchmark (e.g. an EW index) as the beat target; or crediting
  IC/quantile-spread alongside the book beat rate. **Not** grounds to lower G3.
- The three TW families are **closed, not rejected**: 0 OOS attempts spent, full 3/3 budget intact
  per family. The user may authorize a vault shot on the single best candidate (`tw-revenue-momentum`
  `{rev_mom_accel}` or `tw-flows` `{foreign_63d, trust_21d}`) at any time; the disciplined default is
  to hold until either the success definition is revisited or a fuller-universe TW panel exists.
- Today's Picks stays honestly empty. No TW signal is certified.

## 008 — success-metric redefinition: decomposed portfolio + skill (2026-07-08, model: Opus 4.8)

The "program-definition discussion" that entries 001–003 and 007 kept pointing to, held with the
user this session. **Decision recorded; implementation is its own card (ROADMAP 12.5) — gates.py is
NOT changed by this entry, and no result below is certified (all in-sample).**

- **The finding.** The frozen headline metric (G3 = mean cohort **individual-pick** hit rate: the
  fraction of the top-N picks whose 6m return beats the benchmark) is **structurally biased in both
  directions**, which is why every US and TW family "failed":
  - *Biased low.* When the benchmark is cap-weighted and single-name-dominated (0050 ≈ 50% TSMC;
    SPY ≈ mega-caps), the *median* stock underperforms the index by construction, so the fraction
    of picks beating it sits < 50% regardless of skill. This one artifact sank Phases 10 + 11.4.
  - *A naive fix is biased high.* Switching to the **portfolio** beat rate (does the EW top-20 book
    beat the benchmark?) inverts the bias: measured on validation (TW, 2020–22, 36 months), a
    **no-skill equal-weight universe book beats 0050 in 80.6% of 6m windows (+5.9%)** and a random
    top-20 in 70.6% — the pure equal-weight/breadth premium, not selection.
  - *The honest skill metric* is the book vs the **equal-weight eligible universe** (both are
    benchmark-relative, so 0050 *and* the EW premium cancel, leaving pure selection). On TW
    validation: `tw-revenue-momentum {rev_mom_accel}` **+6.35% (NW-t 2.07, 72% of cohorts)**,
    `{rev_mom_yoy,rev_mom_accel}` +5.10% (t 1.92); every `tw-flows` candidate ≈ 0 (foreign+trust
    +0.84% t 0.69, foreign_63d +1.03% t 0.44, foreign-margin −0.29%). So among TW's free signals,
    **monthly-revenue momentum has genuine stock-picking skill; institutional flows are almost
    entirely the EW premium.** (Rank IC — G1/G2 — is already benchmark-weighting-immune: subtracting
    a per-cohort constant benchmark does not change within-cohort ranks. Only G3 was broken.)
- **Decision (user sign-off 2026-07-08): the DECOMPOSED metric.**
  - **Displayed probability** (Today's Picks + `NORTH_STAR` §"displayed probability"): the
    **portfolio-cohort beat rate vs the benchmark** — fraction of monthly cohorts whose EW top-N
    book's 6m return beats 0050/SPY — with its NW 95% CI and cohort count. This is what the investor
    actually experiences (they hold the book, not isolated names).
  - **Certification skill gate (the new G3):** the per-cohort **selection alpha** = (EW top-N book
    6m return − EW eligible-universe 6m return), requiring **mean > 0 and NW-t (lag 5) ≥ 2.0**. This
    is the real hurdle; it certifies stock-picking above the equal-weight premium, so a no-skill EW
    book cannot pass. G1, G2, G4, G5, G6 unchanged (G1/G2 are already skill; G4 stays the
    cost-aware vs-benchmark check, honestly inflated by the EW premium and reported as such).
- **Unavoidable caveat.** All of the above is in-sample (validation). The 2023+ vault is untouched
  and decisive, and the 2023–25 regime (TSMC AI dominance, like the US mega-caps) most likely
  *reverses* the EW premium and pressures momentum — so even revenue-momentum's in-sample skill may
  not survive OOS. The redefinition gives the families a **fair test on the right metric**; it does
  not promise a pass. `tw-revenue-momentum {rev_mom_accel}` is the natural first candidate for a
  pre-registered OOS attempt *after* ROADMAP 12.5 lands (never before — the vault stays sealed).
- **This is a §4-rule-4 gate change**: ROADMAP 12.5 must alter `research/gates.py` + this playbook
  §5 in one commit and void/re-run every certification (there are none → trivial), with tests
  proving a no-skill EW book fails the new G3 and a skilled book passes.

## 009 — tw-revenue-momentum / rev_mom_accel v1 (2026-07-09, model: Opus 4.8)

- Hypothesis: Taiwan monthly-revenue **acceleration** (`rev_mom_accel`, PIT on the §36
  10th-of-next-month availability) ranks 6-month 0050-relative winners in the liquid TW universe
  **with selection skill above equal-weighting** — top-20, monthly rebalance. Falsifiable under the
  decomposed metric (ROADMAP 12.5): G3 = mean per-cohort selection alpha (EW top-20 book 6m − EW
  eligible-universe 6m) **> 0 with NW-t (lag 5) ≥ 2.0** on the 2023+ vault; if not, REJECTED.
- Spec: `signals/specs/tw-revenue-momentum.json`
  sha256: `146f08a6e5df9d2ecb1b5a80c781b9ea029302ca9a10ef736a3ddb85234c0c2b`
- Substrate: `panel_tw` — 140 most-liquid non-ETF TW names (RESEARCH_LOG 005/008; a
  liquidity/survivorship selection on top of `current_universe (optimistic)`). OOS 2023-01→2025-11,
  **35 complete-6m months** (≥ G1's 24). Benchmark `0050.TW`.
- Dev (2017-08→2019-12, 11 months — thin): rank IC +0.025 (t 0.84); old individual-beat 40.5%.
- Validation (2020-01→2022-12, 36 months): rank IC +0.043 (t 1.81), Q5−Q1 +2.34% (75% pos.);
  **selection skill vs the EW-universe +6.35% (NW-t 2.07)**; displayed portfolio-vs-0050 beat 77.8%.
- OOS attempt: **1 of 3** (family `tw-revenue-momentum`).
- OOS verdict: **pending** (this entry is the committed pre-registration; the certify CLI refuses to
  run without the matching sha256 above).
- Registry status change: draft → registered (on certify).
- Honest prior recorded before the vault is touched: the 2023–25 TW regime (TSMC AI dominance) most
  likely **reverses** the equal-weight/breadth premium and pressures momentum, so a fair test is
  **not** a promised pass. Whatever the number, it is logged and the family closes on this attempt
  unless genuinely new data (not a re-weighting) appears.

**OOS RESULT (2026-07-09): CERTIFIED.** Immutable report
`signals/certifications/tw-revenue-momentum_v1.json`. OOS 2023-01→2025-11, 35 cohorts, all 13 gate
checks pass:
- G1 IC **+0.049 (t 3.16)**, 35 months; G2 spread +1.48% (positive in 65.7% of months).
- **G3 selection skill +8.13% (NW-t 2.02)** — the alpha vs the equal-weight universe *strengthened*
  out-of-sample (validation was +6.35%). The pre-registered "the regime reverses the EW premium"
  prior was **wrong**: revenue-acceleration kept selecting the 2023–25 AI-supply-chain winners.
- G4 cost-aware book **75.2% CAGR / 2.44 Sharpe vs 0050's 34.3% / 1.75**; G5 IC positive in both
  halves (+0.042, +0.056), 1 parameter; G6 turnover 34.6% (≤ 40%, no stress band).
- **Displayed probability: portfolio-cohort beat rate 68.6%, 95% CI 41.1%–96.1%** — the CI is *wide*
  because 35 overlapping 6-month windows carry heavy autocorrelation. Strong point estimate, honestly
  imprecise interval.
- Registry: draft → registered → **certified** (attempt **1/3** spent; 2 remain, for genuinely new
  data only, never a re-weighting). **Today's Picks now renders — the first certified signal.**
- **Caveats that ride with every display** (signal-certification rule): `current_universe
  (optimistic)` × the 140-name most-liquid selection (a sharper survivorship/liquidity tilt than the
  US panels); G3_alpha_t cleared the bar by a hair (2.02 ≥ 2.0); and 2023–25 was an AI-boom regime
  unusually kind to revenue-acceleration names. Post-cert drift monitoring (12.2) is the honest next
  guard — if the trailing-12-cohort skill decays, it flips to `under_review`.

## 010 — tw-price-factors / harder universe, skill-metric search (2026-07-09, model: Opus 4.8)

- Goal: on a **harder, less-biased TW universe** and under the 12.5 decomposed metric (selection
  alpha vs the equal-weight universe — the certified G3, via the shared `certify.cohort_alpha`),
  search for a price-based strategy other than revenue momentum.
- **Harder universe (the point of this entry).** Prices-only `panel_tw` over the **full 2,130-name**
  TW universe, not a liquidity-cherry-picked subset: every cached symbol is fed in and the panel's
  monthly point-in-time hygiene (NT$10 / NT$50M 21-day dollar-vol / 252 bars) decides each month's
  eligible set, so a name liquid in 2013 but illiquid now is correctly eligible in 2013 and not now.
  All names deep-warmed to 2010 via yfinance (**1,432 with pre-2013 history**, up from 625; 168
  legitimately absent — delisted/never-listed, the accepted free-data survivorship gap). Result:
  **181 months, eligible/month 141–744 (0 dropped), DEV 103 months / VAL 36 / OOS 42** — a *full*
  development window, vs the 11 scattered months the 140-name cert panel could muster (entry 005).
- **Development (2011-06→2019-12, 103 months; OOS vault never read — a hard assert guards it):**
  a coherent story — **trend/relative-strength has 6-month alpha, skip-month momentum is dead:**

  | candidate | IC (t) [G1] | selection alpha (NW-t) [G3] | turnover |
  | --- | --- | --- | --- |
  | `{ret_12_1}` (US-classic momentum) | +0.010 (0.61) | −1.54% (−1.04) | 34% |
  | `{ret_6m}` | −0.003 (−0.17) | +3.27% (+2.10) | 44% |
  | `{pct_above_sma_200}` | −0.003 (−0.15) | +4.16% (+2.77) | 48% |
  | `{vol_63d:−1}` (low-vol) | +0.067 (3.08) | +0.87% (+0.68) | 27% |
  | **`{vol_63d:−1, ret_6m:1}`** | **+0.069 (3.53)** | **+3.90% (+4.36)** | 51% |
  | **`{vol_63d:−1, pct_above_sma_200:1}`** | **+0.067 (3.27)** | **+3.82% (+3.75)** | 52% |

  Trend factors carry the alpha but ~0 one-month IC (fail G1); low-vol carries the IC but ~0 alpha
  (fail G3); the **low-vol × trend combination clears BOTH gates in-sample** (the low-vol anomaly ×
  relative strength — 2 parameters). Reversal/RSI-oversold were strongly *negative* (−3.5%/−2.6%),
  confirming the trend direction, not mean-reversion.
- **Validation (2020-01→2022-12, 36 months — the decisive single look): every candidate collapses.**
  `{vol_63d:−1, ret_6m:1}` +3.90% (t 4.36) → **−2.61% (NW-t −0.87)**; `{vol_63d:−1, sma200:1}`
  +3.82% → **+0.08% (t 0.03)**; `above_sma200` +4.16% → +1.41% (0.28); nothing has significant
  positive alpha in *both* windows. The strong dev signal is **regime-dependent / dev-overfit** —
  it does not survive the COVID-crash / melt-up / 2022-rate-shock window.
- **Verdict: FAMILY CLOSED AT VALIDATION.** No new certifiable price strategy. Validation did its
  job — caught a candidate that cleared both gates in development and saved a vault attempt.
- OOS attempts spent: **0 of 3** (family `tw-price-momentum` / low-vol-trend). Registry: no change.
- Honesty caveats: (1) ~15 candidates were compared in development, so the strong dev numbers carry
  multiple-comparison selection — the validation collapse is consistent with that. (2) The harder
  universe still can't include *fully* delisted names (no free source), so it lowers but does not
  eliminate survivorship bias. (3) This says nothing about revenue momentum (entry 009), which is
  certified on the reduced 140-name panel and unaffected; re-certifying it on this harder universe
  is a worthwhile future step but needs FinMind (monthly revenue) across ~700 names (quota-bound).

## 011 — US re-evaluation under the decomposed metric (2026-07-11, model: Opus 4.8)

- Card: ROADMAP 13.1. Goal: the US families 001–003 were closed under the **old, structurally
  biased G3** (mean individual-pick beat rate, shown in entry 008 to sit < 50% by cap-weight-
  benchmark concentration); nobody ever measured their **selection alpha** (the 12.5 G3 = EW
  top-20 book 6m `fwd_6m_rel` − EW eligible-universe 6m, NW-t vs 0). Re-score the closed families
  **plus the entry-010 low-vol×trend combos** on Dev/Validation only, under the new metric.
- Tool: `heimdall.research.evaluate` (new this card) — a windowed lens that **imports** the certify
  gate helpers (`information_coefficient`, `certify._monthly_spread`, `certify._book_minus_universe`
  + `gates.nw_tstat`, `cohort_turnover`) so the in-sample read is the identical math the vault
  referee uses; it **refuses any window ≥ `OOS_START`** (a hard assert + test). No vault row touched.
- Panel: `panel_us` (built 2026-07-07; 3,436-name VTI universe; 199 months 2010-01→2026-07;
  `current_universe (optimistic)`). All eight candidate feature columns present.
- **Consistency check (not a result, a correctness proof):** the new tool's DEV rank-IC reproduces
  the prior sessions' independently-computed numbers to 3 dp — `ret_12_1` +0.013 (t 0.92) = entry
  001; quality-equal +0.008 (t 0.88) = entry 002; `fcf_yield` +0.022 (t 2.87) = entry 003. Rank IC
  is weighting-immune (008), so it *should* match; it does.

- **Development (2010-01→2019-12, 120 months; no row ≥ 2023 read — evaluate() asserts it).** All
  eight pre-stated candidates (no additions mid-session); "beat" = the new portfolio-cohort beat
  rate vs SPY, "alpha (t)" = the G3 selection alpha and its NW-t:

  | candidate | IC (t) [G1] | spread/mo [G2] | selection alpha (NW-t) [G3] | beat | turn | advances |
  | --- | --- | --- | --- | --- | --- | --- |
  | `{ret_12_1}` momentum | +0.013 (0.92) | +0.37% | +1.12% (+0.54) | 53.3% | 38% | no |
  | `{roic,fcf_margin,operating_margin}` eq | +0.008 (0.88) | +0.24% | +1.15% (+1.26) | 62.5% | 12% | no |
  | **`{fcf_yield}`** | **+0.022 (+2.87)** | +0.53% | **+2.99% (+3.92)** | 78.3% | 10% | **YES** |
  | `{ret_6m}` | −0.009 (−0.61) | −0.12% | +1.16% (+0.60) | 50.8% | 48% | no |
  | `{pct_above_sma_200}` | −0.009 (−0.58) | −0.19% | +1.20% (+0.63) | 50.8% | 50% | no |
  | `{vol_63d:−1}` low-vol | +0.011 (0.54) | −0.08% | −1.26% (−0.93) | 49.2% | 39% | no |
  | `{vol_63d:−1, ret_6m:1}` | +0.006 (0.31) | −0.01% | −0.78% (−0.92) | 48.3% | 63% | no |
  | `{vol_63d:−1, pct_above_sma_200:1}` | +0.005 (0.23) | −0.02% | **−1.81% (−2.57)** | 36.7% | 62% | no |

  Advance bar (entry-010 precedent): dev IC-t ≥ 2 **and** dev alpha-t ≥ 2. Only `{fcf_yield}` clears
  both. **The entry-010 TW low-vol×trend winners do not transfer to US** — both combos have
  *negative* US selection alpha (one significantly so), and low-vol alone is negative too. So the
  US market's only free selection-skill signal on this board is valuation (`fcf_yield`), not trend.

- **Validation (2020-01→2022-12, 36 months — the single look, `{fcf_yield}` only):** IC **+0.058
  (t 2.71)**, spread +0.81%/mo, **selection alpha +7.89% (NW-t +2.98)**, portfolio beat 72.2%
  (95% CI 46%–99%, 36 cohorts), turnover 11%. Selection skill is significant in **both** in-sample
  windows under the new metric.

- **Looks disclosed:** 8 development evaluations + 1 validation = 9 in-sample reads; 0 OOS.
- **Verdict:** 7 candidates **closed at development** (no selection skill under the honest metric).
  **`{fcf_yield}` advances to card 13.2** (conditional one-shot OOS). This is the anticipated
  outcome: the family's prior vault rejection (entry 003) was scored on the biased old G3, so its
  *selection alpha* out-of-sample is genuinely new information, not a respin of a re-weighting.
- **OOS attempts spent: 0 of 3.** Registry status change: none (nothing pre-registered here).
- **⚠️ Governance flag carried to 13.2 (for the user, not decided here).** The 13.2 candidate
  `{fcf_yield}` is the *same recipe* as the already-rejected `us-fcf-yield v1`
  (sha256 `ade91883…`), which spent `us-value-quality` attempt 1/3. The 12.5 gate change (§4 rule 4)
  voids/re-runs *certifications*; entry 003 was a **rejection**, not a certification, so it is unclear
  whether re-running the identical spec under the new G3 is a free 12.5 void-and-rerun or a fresh
  attempt 2/3. 13.2 must get the user's ruling **before** touching the vault (the card says so).
  Also open for 13.2: whether to submit `{fcf_yield}` as `us-fcf-yield v2` (new spec version, clean
  registry lineage) rather than colliding with the immutable v1 report.

## 012 — us-value-quality / us-fcf-yield v2 (2026-07-11, model: Opus 4.8)

- Card: ROADMAP 13.2. Hypothesis: pure free-cash-flow yield (`fcf_yield`) ranks 6-month
  SPY-relative winners in the eligible US universe (top-20, monthly) **with selection skill above
  equal-weighting** — the 12.5 decomposed G3: mean per-cohort selection alpha (EW top-20 book 6m
  `fwd_6m_rel` − EW eligible-universe 6m) **> 0 with NW-t (lag 5) ≥ 2.0** on the 2023+ vault. If not,
  REJECTED.
- Spec: `signals/specs/us-fcf-yield-v2.json`
  sha256: `74268903697af89e6715c94147e6ca9e4da047ab6b3e144288e753ca213a4add`
- **This is a §4-rule-4 void-and-rerun, not a new attempt (user sign-off, verbatim).** The v2 recipe
  is identical to `us-fcf-yield v1`, which spent `us-value-quality` attempt 1/3 and was vault-REJECTED
  (entry 003) — but that rejection was scored on the **old individual-pick G3** that ROADMAP 12.5
  disowned as structurally biased. Asked to rule how to proceed (13.2 step 2), the user chose:
  *"當 void-and-rerun，送 v2（推薦）"* — treat it as the gate-change re-run (family budget stays
  1/3, not a fresh attempt 2/3) and submit as a new version `v2` so v1's immutable report is
  untouched. Run via `certify --void-and-rerun` (the sanctioned no-new-attempt path; a prior attempt
  must exist to re-run, and every other guard — immutable report, committed pre-registration,
  transition-through-code — is intact).
- Substrate: `panel_us` (built 2026-07-07; 3,436-name VTI universe; `current_universe (optimistic)`).
  Benchmark `SPY.US`. OOS 2023-01 → last month with complete 6m labels.
- Dev (2010-19, entry 011): selection alpha +2.99% (NW-t +3.92), rank IC +0.022 (t 2.87).
- Validation (2020-22, entry 011): selection alpha +7.89% (NW-t +2.98), rank IC +0.058 (t 2.71),
  displayed portfolio-vs-SPY beat 72.2%.
- OOS attempt: **re-run of attempt 1 of 3** (family `us-value-quality`; the counter stays at 1).
- OOS verdict: **pending** (this entry is the committed pre-registration; the certify CLI refuses to
  run without the matching sha256 above).
- Registry status change: draft → registered (on certify).
- Honest prior recorded before the vault is re-touched: the 2023-25 US regime (mega-cap AI dominance,
  like the TSMC-led 0050) most likely **pressures a diversified value book** — the same structure that
  first sank v1's old-metric beat rate. The corrected metric gives fcf-yield a **fair** test of its
  *selection* skill (which is real and significant in both in-sample windows); it does **not** promise
  a pass. Whatever the number, it is logged and the family closes on this re-run unless genuinely new
  data (not a re-weighting) appears.

**OOS RESULT (2026-07-11): REJECTED.** Immutable report
`signals/certifications/us-fcf-yield_v2.json`. OOS 2023-01-31 → 2025-12-31, 36 cohorts. The honest
prior held — the in-sample selection skill did **not** survive the 2023-25 mega-cap regime:
- **G3 selection alpha −0.80% (NW-t −0.52)** — FAIL, the decisive gate. The dev +2.99% (t +3.92) /
  val +7.89% (t +2.98) skill vs the equal-weight universe **reversed to slightly negative** OOS: a
  diversified value book did not out-select the equal-weight universe while mega-caps led.
- G1 IC **+0.0307 passes** the level but **G1_t 1.59 fails** (< 2). Worth recording: this OOS IC is
  ~identical to entry 003's old-metric run (+0.031) — rank IC is weighting-immune, so the *ranking
  information* is the same real-but-marginal signal both times; what the corrected G3 newly shows is
  that this ranking does **not** translate into selection skill above equal-weighting in this regime.
- G2 spread −0.24%/mo (positive 47.2%) FAIL; G4 11.3% CAGR / 0.61 Sharpe vs SPY 21.0% / 1.70 FAIL.
- G5 stability PASS (IC +0.049 / +0.013 across halves, 1 parameter); G6 turnover 12.6% PASS.
- Displayed portfolio-cohort beat rate **30.6% (95% CI 12.5%–48.6%)**.
- Registry: draft → registered → **rejected**. **Void-and-rerun honored: family `us-value-quality`
  attempts stays 1/3** (2 genuine attempts remain, for new data only — never a re-weighting). v1's
  immutable report is untouched.
- **Aggregate finding, now on the corrected metric:** with free data, no US family certifies. The
  strongest free US signal (`fcf_yield`) has real cross-sectional ranking information (OOS IC +0.031)
  and genuine *in-sample* selection skill, but that skill does not survive the 2023-25 regime OOS.
  Today's Picks stays US-empty (the certified TW `tw-revenue-momentum v1` is unaffected). This
  sharpens the 12.3 paid-data trigger (estimate revisions) — armed but, per the user, unscheduled.

## 013 — MOPS monthly-revenue announcement-date probe (2026-07-11, model: Sonnet 5)

Card ROADMAP 17.9. NORTH_STAR accepted limitation 5 promised per-filing validation of the TW
`filed_at` heuristic (fiscal/revenue-period end + statutory lag) "if a TW family reaches
pre-registration" — `tw-revenue-momentum v1` is certified, so the debt is due. Not an OOS-vault
experiment (no signal spec, no family budget touched) — an infrastructure/data-discipline
validation, logged per the card's own DoD ("log note committed").

**Step 1 — probe in order, live, 2026-07-11 (verbatim findings):**

- **(a) FinMind.** No dedicated announcement-date dataset (reconfirms 11.1, 2026-07-08). But a
  field *inside* `TaiwanStockMonthRevenue` itself — `create_time` — was checked at the raw-row
  level for the first time. Findings, decisive:
  - Recent months (2026-04, 2026-05) show plausible per-symbol variation across 8 sampled names
    (large-to-mid cap): April revenue `create_time` ranged 05-06→05-15, May ranged 06-06→06-12 —
    *shaped* like real disclosure staggering.
  - But 2026-02 and 2026-03 revenue show an **identical** `create_time = 2026-04-21` across all 8
    symbols and both months — a batch-reprocessing timestamp, not a per-filing date (no company
    plausibly disclosed Feb *and* March revenue simultaneously on April 21).
  - 2019 revenue (12 symbols sampled, spanning cement/electronics/finance/steel/food) has
    `create_time = ""` (empty) for every single row — the field isn't populated for deep history
    at all.
  - **Verdict: disqualified.** `create_time` is a "last touched" marker, corrupted by at least one
    known reprocessing event, and absent entirely before some retention horizon. Not a usable
    historical per-filing source for the 2020–2025 OOS window the certification was built on.
- **(b) MOPS** (`mopsov.twse.com.tw/nas/t21/sii/t21sc03_{ROC_year}_{month}.html`, the compiled
  monthly-revenue archive; fetched ROC 113/4 = 2024-04 as a sample, Big5-decoded). Table columns:
  公司代號, 公司名稱, 當月營收, 上月營收, 去年當月營收, 增減%, 累計營收… — **no per-company date
  or timestamp column of any kind.** This is a compiled summary, not a per-filing record.
  (MOPS's separate 重大訊息/individual-announcement query system might carry real per-filing
  timestamps, but it is a session/POST-driven search form — probing it further would exceed
  "polite page requests" per the card's own guardrail; flagged as a possible future avenue,
  **not attempted**, pending explicit user authorization for deeper MOPS integration.)
- **(c) TWSE OpenAPI** (`openapi.twse.com.tw/v1/opendata/t187ap05_L`). Has a `出表日期`
  (report-generation date) field — but the live probe (1,082 rows) showed exactly **one** distinct
  `資料年月` (2026-05 only — the latest period, not a history) and exactly **one** distinct
  `出表日期` (2026-06-17) across every company. A single current-snapshot report-generation date,
  not historical, not per-company.

**All three candidate sources are disqualified.** The card's step-3 fallback applies.

**Step 3 — live-observation mechanism (built, not yet run).** New
`src/heimdall/research/mops_probe.py`: `tracked_symbols()` samples ~30 names evenly across the
sorted TW universe (index-spread as a free, hallucination-free proxy for cap-size spread — no
market-cap fetch needed); `update_observations()` is a pure, idempotent first-appearance recorder
(a re-run never rewrites an already-observed date); `summarize()` reports each first-seen date's
offset from the §36 10th-of-next-month deadline, with the mandatory **"late filings > 2% ⇒ stop
and ask" guard** wired into the CLI's `--summarize` output. 10 unit tests (idempotency, the
December year-roll, atomic store round-trip), no network. **Not yet executable to completion**:
the card's window is "days 1–12 of the next calendar month" — today is 2026-07-11, so the next
valid window is **2026-08-01 → 2026-08-12** (observing July 2026 revenue disclosures). Whoever
picks this up then runs `uv run python -m heimdall.research.mops_probe --record` once daily
across that window, then `--summarize 2026-07` once it closes.

**Card status: infrastructure + probe complete; empirical measurement pending the Aug 2026
window** (docs/ROADMAP_V2.md 17.9 stays unchecked — DoD requires "numbers", which don't exist
yet). `docs/NORTH_STAR.md` limitation 5 updated with these dated findings.
