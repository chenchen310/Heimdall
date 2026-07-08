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
