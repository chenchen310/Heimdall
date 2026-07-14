# Roadmap v2 — from calculator to referee

> Phases 0–6 (`docs/ROADMAP.md`) built the honest calculator. This roadmap builds the **referee**:
> persisted labels → certification harness → a Today's Picks page that only ever shows certified
> signals. Goal and definitions: `docs/NORTH_STAR.md`. Process and gates: `docs/RESEARCH_PLAYBOOK.md`.

**How to work this roadmap (binding for every session):**

- Execute **one card per session/PR**, top to bottom unless the user picks a card. Mark it `[x]`
  in the same PR.
- A card lists its Definition of Done. Done = steps complete + named tests passing + the four
  quality gates green (`uv run ruff check . && uv run ruff format . && uv run mypy && uv run pytest`).
- Don't widen scope. Don't refactor neighbours. Don't invent statistics — the playbook has the
  numbers; if something is genuinely unspecified, stop and ask the user.
- New runtime code lives in `src/heimdall/research/` (imports from `data`/`factors`/`screener`/
  `backtest`; imported by `ui` only). Tests mirror as `tests/test_research_*.py`, no network.

---

## Phase 7 — Research data layer (labels, liquidity, benchmarks)

### 7.1 Liquidity + missing return features in the snapshot row  `[x]`

**Goal:** the snapshot (and therefore the panel) gains the fields hygiene filters and momentum
signals need. **Files:** `src/heimdall/factors/metrics.py`, `tests/test_snapshot.py`.

Steps — extend `_technicals` (all from the `ohlcv` frame already passed in):
1. `dollar_vol_21d` — median over the last 21 bars of `close × volume` (raw close, not adjusted).
2. `ret_12_1` — skip-month momentum: `adj_close[-21] / adj_close[-252] − 1` (NaN if < 252 bars).
   Note in a comment why: the most recent month reverses; classic momentum skips it.
3. `vol_63d` — std of daily `adj_close` pct-changes over the last 63 bars, annualized (×√252).

DoD: known-answer tests for each on synthetic series (e.g. constant close×volume ⇒ exact
`dollar_vol_21d`); NaN behavior tested for short history; existing tests untouched and green.
**Don't:** change existing column semantics (`ret_12m` stays as-is); don't touch providers.

### 7.2 Benchmark map + relative-return helper  `[x]`

**Goal:** one sanctioned place answering "which benchmark, and what did it return over my window".
**Files:** new `src/heimdall/research/__init__.py`, `src/heimdall/research/benchmark.py`,
`tests/test_research_benchmark.py`.

Steps:
1. `BENCHMARK: dict[str, str] = {"US": "SPY.US", "Taiwan": "0050.TW"}` (keys = `Symbol.region`).
2. `def forward_return(adj: pd.Series, start: pd.Timestamp, bars: int) -> float` — return over
   `bars` trading bars from the first bar ≥ `start`; NaN if the window is incomplete. Pure
   function on a date-indexed adj-close series; both symbol and benchmark labels use it, which
   guarantees identical windows for the `_rel` subtraction.

DoD: known-answer tests incl. the incomplete-window NaN and the "first bar ≥ start" alignment.
**Don't:** fetch anything here; callers pass series in.

### 7.3 Persisted research panel with forward labels (the dataset)  `[x]`

**Goal:** the reusable, resumable dataset every experiment reads — one row per (month-end, symbol):
all `snapshot_row` fields + `eligible`/`inelig_reason` + `fwd_1m/3m/6m` and `*_rel` labels.
**Files:** new `src/heimdall/research/dataset.py`, `tests/test_research_dataset.py`.

Steps:
1. Reuse `factors.panel` machinery (`_rebalance_dates`, `snapshot_row`) — do **not** duplicate the
   PIT logic. Labels via 7.2 (`fwd_1m` = to next rebalance date; `fwd_3m`=63, `fwd_6m`=126 bars).
2. Eligibility per playbook §3; constants imported from `research/gates.py` — create that module
   now containing **only** the hygiene constants (gates arrive in 8.2), each with a comment
   mirroring the playbook table.
3. Persist to `data/research/panel_{us|tw}.parquet` (atomic write — copy `save_snapshot`'s
   temp+`os.replace` pattern) + sidecar `panel_{market}.meta.json`: `built_at`, month range,
   eligible counts per month, dropped months, and the literal stamp
   `"survivorship": "current_universe (optimistic)"`.
4. CLI `uv run python -m heimdall.research.build_dataset --market us --start 2010-01 [--end …]`,
   resumable by month (skip months already in the parquet), progress prints like `screener.build`.

DoD tests (synthetic providers, no network): **PIT leak test** — a fundamental with
`filed_at` after month-end *t* must not affect row *t* (this is the most important test of the
phase); label known-answer on a hand-built price path incl. benchmark-relative sign; incomplete
forward window ⇒ NaN label; eligibility flags with reasons; resume skips existing months.
**Don't:** hit the network in tests; don't compute scores here (specs do that later); don't drop
ineligible rows.

## Phase 8 — Certification harness + registry

### 8.1 SignalSpec + registry  `[x]`

**Goal:** signals become data with enforced lifecycle. **Files:** new
`src/heimdall/research/spec.py`, `src/heimdall/research/registry.py`, `signals/specs/.gitkeep`,
`signals/registry.json` (init `{"signals": []}`), `tests/test_research_registry.py`.

Steps:
1. `class SignalSpec(BaseModel)`: `name`, `family`, `market` ("US"/"Taiwan"), `version: int`,
   `features: dict[str, float]` (panel column → weight; direction via sign), `top_n: int = 20`,
   `description: str = ""`. `canonical_hash()` = sha256 of `model_dump_json()` with sorted keys,
   excluding `description`.
2. `score(spec, cross_section) -> pd.Series` — winsorized (±3σ) z-score each feature within the
   eligible cross-section, weighted sum. Reuse `factors.scoring._zscore`; do not fork the math.
3. Registry entries: `{name, family, version, spec_path, spec_hash, status, oos_attempts_family,
   cert_report, updated_at}`; statuses `draft|registered|certified|rejected|under_review|retired`;
   `register()/transition()` enforce the lifecycle graph in playbook §6 and raise on illegal moves.

DoD: hash stability test (key order / description don't change it); illegal-transition tests;
attempts counter increments per family. **Don't:** allow status writes except via `transition()`.

### 8.2 Certify harness + gates  `[x]`

**Goal:** the referee. **Files:** `src/heimdall/research/gates.py` (extend),
`src/heimdall/research/certify.py`, `tests/test_research_certify.py`.

Steps:
1. `gates.py`: G1–G6 thresholds exactly as playbook §5, plus `nw_tstat`/`nw_ci95` copied verbatim
   from the playbook. Add `test_gates_mirror_playbook` asserting the literal numbers (duplication
   is the tripwire: changing either place alone fails CI).
2. `certify(spec, panel, benchmark_adj) -> CertReport` — filter to OOS window (start `2023-01-01`,
   end = last month with non-NaN `fwd_6m`), compute G1–G6, verdict = all-pass. G4 is a monthly
   top-N backtest derived **directly from the panel's own `fwd_1m` labels** (gross = mean pick
   return per rebalance, minus 20 bps per side on traded value; G6's 40–60% branch re-runs at 40)
   — implemented this way instead of via `backtest.portfolio` so every gate sits on the *same*
   calendar windows as the labels, with no second pricing path to disagree with them. Report
   dataclass: every gate's value, threshold, pass flag; cohort series; window; the survivorship
   stamp; spec hash.
3. CLI `uv run python -m heimdall.research.certify signals/specs/<f>.json --log-entry <id>`:
   parse `docs/RESEARCH_LOG.md` for `## <id> —` containing the spec's sha256 → refuse if absent
   (message: "pre-register first, see playbook §4"); refuse if family attempts ≥ 3; write report
   JSON to `signals/certifications/{name}_v{version}.json`; registry → certified/rejected.

DoD: gate math known-answer on tiny hand-computed panels (esp. NW t and turnover); log-entry
enforcement (absent id / wrong hash / attempts=3 all refuse); report file written and immutable
(second run for same entry refuses). **Don't:** let any code path evaluate OOS without an entry.

### 8.3 Canary tests (the harness must have power)  `[x]`

**Goal:** prove certification rejects noise and would catch leakage-strength signals.
**Files:** `tests/test_research_canary.py` (+ a small synthetic-panel builder in the test).

Steps: build a synthetic 36-month panel (~200 symbols) where `oracle = fwd_1m_rel` rank exactly
and `noise` is seeded random. Assert: noise spec **fails** certification; oracle spec **passes**
G1–G3 overwhelmingly (skip G4 if the synthetic panel lacks price series — document that). Mark the
oracle clearly as test-only; registry code must refuse any spec whose feature list contains a
column starting with `fwd_` (add that guard in 8.1's `score` if not present — belt and braces).

DoD: both canaries in the normal suite, < 5 s runtime, no network.

## Phase 9 — Today's Picks

### 9.1 Picks engine  `[x]`

**Goal:** certified spec + fresh snapshot → today's ranked cohort. **Files:**
`src/heimdall/research/today.py`, `tests/test_research_today.py`.

Steps: `todays_picks(spec, snapshot) -> pd.DataFrame` — eligibility filter (same gates constants),
spec score, top-N, with per-feature z-scores as columns (so the UI can show *why* each name
ranks); `freshness(snapshot) -> int` returning business-day staleness of `as_of`.

DoD: known-answer ranking on a crafted snapshot; ineligible names excluded with reasons; staleness
math tested. **Don't:** read the registry here (pure function); the page composes.

### 9.2 Today's Picks page  `[x]`

**Goal:** the north-star surface. **Files:** `src/heimdall/ui/today_page.py`, `app.py` (nav group
"Stock picking", first position), `i18n.py` (zh strings), `tests/test_ui_smoke.py`.

Steps:
1. Read registry → certified specs for the chosen market (reuse `market_radio`). None ⇒ honest
   empty state: "No certified signal yet" + pointer to the roadmap — and **nothing else**.
2. For each certified spec: evidence box first — G3 beat rate with CI + cohort count, IC, spread,
   certification date, `survivorship: current_universe (optimistic)`, benchmark name; then the
   picks table (pinned `symbol`, currency-labelled money columns) via 9.1.
3. Staleness > 5 business days ⇒ warning banner linking to Build data.

DoD: AppTest smokes for the empty state and for a fake-certified registry fixture rendering
evidence + picks; zh translations present. **Don't:** any path that renders a ranking without a
`certified` registry row (this is the rule; the test asserts the empty state).

## Phase 10 — First certified signals (US, free data)

> Research cards. Follow playbook §7 "propose a signal" exactly: tune on Development only, select
> on Validation, pre-register (log entry with hash), then certify once. **A REJECTED verdict,
> honestly logged, completes the card.** Each card: spec JSON under `signals/specs/`, a log
> entry, a certification run, roadmap checkbox.

### 10.1 US momentum family (`ret_12_1`, optionally `vol_63d` tilt)  `[x]`
Hypothesis to register: skip-month momentum ranks 6-month relative winners in the eligible US
universe. Start pure single-feature (1 parameter); a low-vol tilt is v2 *only if* v1 fails on a
pre-stated reason.

> **Outcome (2026-07-08): family closed at development** — dev 6m beat rate 43–44%
> (significantly < 50%, NW-t −2.4…−3.4) for v1 and both pre-authorized vol tilts: a structural
> equal-weight-vs-SPY cap-weighting headwind that momentum doesn't overcome. **0/3 OOS attempts
> spent**; vault untouched. Full numbers: `docs/RESEARCH_LOG.md` entry 001.

### 10.2 US quality/profitability family (`roic`, `fcf_margin`, `operating_margin`)  `[x]`
Equal weights first (3 parameters). Watch G1 — quality alone is often weak standalone; expect a
possible honest rejection.

> **Outcome (2026-07-08): family closed at development** — dev IC ≈ 0 (t < 1) across all three
> variants; beat rate ≈ coin flip (51%). No benchmark headwind this time (stable large-cap book,
> 10–12% turnover) — simply no cross-sectional edge. **0/3 OOS attempts spent.** See
> `docs/RESEARCH_LOG.md` entry 002.

### 10.3 US value×quality family (`fcf_yield`, `ev_ebitda`(−), `roic`)  `[x]`
The composite most literature supports at 6m horizons. Negative weight = lower-is-better.

> **Outcome (2026-07-08): pre-registered and vault-REJECTED** — the full pipeline ran end to end
> for the first time. Dev selected pure `{fcf_yield}` (IC t 2.87); validation confirmed
> (IC +0.058, beat 57.1%); the one-shot OOS run **passed G1_ic and G5** (the ranking information
> is real) but failed G3 decisively (beat 41.4%, NW-t −2.77) — the top-20 book lost to SPY's
> 2023–25 mega-cap run. Attempt 1/3 spent; immutable report committed. **Phase-10 aggregate:**
> no free family certifies at the frozen definition → the 12.3 trigger is armed. See
> `docs/RESEARCH_LOG.md` entry 003.

## Phase 11 — Taiwan enablement

### 11.1 Real TW filing dates  `[x]`
Probe FinMind for a financial-statement announcement-date dataset (check API docs live; e.g. a
`*FinancialStatementsDate`-like dataset). If found: wire into `filed_at` (golden-test with saved
JSON). If not: keep +90d but validate against ≥ 10 known filings (document the error bound in
`docs/NORTH_STAR.md` accepted limitations). Monthly revenue: set `filed_at = month_end + 10 days`
(statutory deadline) — implement regardless.

> **Outcome (2026-07-08):** FinMind has **no announcement-date dataset** (probed the API's
> datalist + candidate names + the official docs). Fallback taken, upgraded from "~90d heuristic"
> to **statutory grounding**: Securities and Exchange Act §36 fetched and cited — annual within
> 3 months (⇒ `+90d` = 3/31 exactly), monthly revenue by the 10th of the following month (now a
> `filed_at` column on `monthly_revenue`, golden-tested incl. the December year-roll). Error
> bound documented as NORTH_STAR accepted limitation 5 (deadline = latest legal availability ⇒
> no look-ahead for on-time filers; per-filing validation would need MOPS — deferred unless a TW
> family reaches pre-registration).

### 11.2 TW monthly-revenue momentum feature  `[x]`
Panel-only feature (TW rows): `rev_mom_yoy` (latest month YoY) and `rev_mom_accel` (3m mean YoY −
prior 3m mean YoY), point-in-time per 11.1's rule. PIT leak test mandatory. This is Taiwan's
signature free signal — treat carefully.

### 11.3 TW chip/flow features (法人買賣超・外資持股・融資融券)  `[x]`

**Reality check (probed live 2026-07-07, free tier with registered token):**
`TaiwanStockInstitutionalInvestorsBuySell` (daily buy/sell per investor type — `Foreign_Investor`,
`Investment_Trust`, `Dealer_self`, `Dealer_Hedging`), `TaiwanStockShareholding` (daily foreign
holding ratio), `TaiwanStockMarginPurchaseShortSale` (daily margin/short balances) — all fresh to
T+1. `TaiwanStockHoldingSharesPer` (TDCC big-holder brackets) needs a paid FinMind tier — skip;
if ever wanted, TDCC's own open-data portal serves the weekly file free (separate provider card).

Steps:
1. `FinMindProvider` methods for the three datasets (golden-test from saved JSON; rate limiter).
   Probe whether per-**date** bulk queries (omit `data_id`) work — if yes, prefer 1 request/day
   over per-symbol loops for whole-market builds.
2. Panel features (TW rows; each shifted **+1 trading day** so row *t* uses only data through
   *t−1* — test the shift): `foreign_net_buy_21d` / `foreign_net_buy_63d` (Σ net-buy shares ×
   close ÷ 21d median dollar volume), `trust_net_buy_21d`, `foreign_hold_delta_63d` (pp change in
   holding ratio), `margin_delta_21d` (margin-balance %-change; expected direction **negative** —
   rising retail leverage is crowding).
3. Priors to register honestly (from the literature, not to be presented as results): foreign-flow
   momentum is the best-documented TW chip signal at weeks–months horizons, but is partly global
   risk-appetite beta (our `_rel` labels strip that) and is the most crowded signal type in Taiwan
   (expect decay); trust flows are shorter-lived with quarter-end distortions; dealer flows are
   hedging noise — excluded on purpose.

### 11.4 Certify TW families  `[x]`
Build `panel_tw` (7.3 CLI), then run 10.x-style cards for: monthly-revenue momentum, price
momentum, flows. Benchmark `0050.TW`. Note in the log that TW history via FinMind may start later
than 2010 — splits shrink accordingly (validation/OOS boundaries stay fixed).

**Done 2026-07-08 (RESEARCH_LOG 004–007).** All three families **closed at development/validation,
0 OOS attempts** — factors carry real cross-sectional IC (TW validation: revenue t 1.81, flows
t 1.95) but the equal-weight top-20 book's 6m beat rate vs the TSMC-dominated 0050 caps at ~53%,
never clearing G3's 55% — the same equal-weight-vs-cap-weight structure that sank every US family.
Constraint met: FinMind free tier ≈ 600 req/hr (≈ 26-min IP bans) makes a full 800-name multi-stream
build ≈ 9 quota-hours, so price momentum ran on the broad 800-name (prices-only) panel and
revenue/flows on a reduced 140-name top-liquidity panel (dev 2017-19 shrank to 11 months; val/OOS
robust). Budget intact; a full-universe TW build (paced FinMind stream cache or paid tier) is the
open follow-on. Aggregate finding strengthens the 12.3 program-definition case.

### 11.5 TW Chips (籌碼) dashboard — descriptive lens, NOT a signal  `[x]`
**Goal:** the daily "who is buying" view, kept firmly outside certification. **Files:**
`src/heimdall/ui/chips_page.py` (nav group "Analyst lenses"), `i18n.py`, AppTest smoke.
Per symbol: cumulative 外資/投信 net-buy vs price, foreign holding %, margin balance; market-wide
top-10 net buy/sell lists (bulk per-date query). Requires only 11.3 step 1, so it may be built
right after it. The page must carry a fixed caption — *descriptive chip data, not a certified
signal; Today's Picks ignores this page* — in both languages. **Don't:** render anything that
looks like a recommendation ranking.

> Scheduled (2026-07-11) as card **15.1** — Phase 15 wave 1. Execute this card's text verbatim;
> mark both checkboxes in the same PR.

## Phase 12 — Operations & evolution

### 12.1 Scheduled refresh  `[x]`
A `launchd` plist template + `docs/OPERATIONS.md` (weekly: snapshot refresh + panel extension via
the existing resumable CLIs), or extend the Build-data page with a one-click "refresh all
certified inputs". Staleness banners already exist (9.2).

> **Done via card 16.2 (2026-07-13)** — the plist + `docs/OPERATIONS.md` + the weekly chain shipped
> there; see 16.2's outcome.

### 12.2 Drift monitoring  `[x]`
`research/monitor.py` + a monitoring section on Today's Picks: each month append the newest
realized cohort beat rate to the cert's monitoring series; trailing-12 NW CI upper < 0.5 ⇒ auto
`under_review` + banner. Tests with synthetic drift.

**Done 2026-07-09.** `research/monitor.py` recomputes each certified signal's realized OOS cohorts
from the current panel and watches **the certified edge — the G3 selection alpha** (not the
EW-premium-inflated beat rate; playbook §9 updated for the 12.5 metric): trailing-12 NW 95% CI
**upper < 0** ⇒ auto `certified → under_review`. Snapshots persist to `signals/monitoring/`; Today's
Picks shows a drift banner (ranking withheld) for under-review signals and a trailing-skill line for
healthy ones. CLI `python -m heimdall.research.monitor [--apply]`. Synthetic-drift tests + a UI
banner test. First real run: `tw-revenue-momentum v1` healthy — trailing-12 skill +16.4% (CI +2.0%
to +30.9%), no drift.

### 12.3 Paid-data decision memo  `[ ]`
Only after ≥ 2 Phase-10 families are certified-or-rejected: write `docs/DATA_DECISION.md` — what
free signals achieved, what FMP estimates/revisions would add, cost vs measured gap. A memo, not
an integration; the user decides.

> User decision 2026-07-11: the trigger is armed but this card stays **unscheduled** — write the
> memo only when the user asks. Not part of the Phase 13–16 waves.

### 12.4 US insider-transactions feature (Form 4) — the honest US "smart money"  `[x]`

> **Outcome (2026-07-12):** executed via card **13.3** (both checkboxes ticked in one PR).
> See 13.3's outcome for the provider + feature + tests.

**Reality note (binding):** the US has **no public daily institutional flow**. Retail-app "money
flow" for US stocks is a price/volume proxy (tick-rule buy/sell imbalance) — it may be added as a
*technical* feature but must never be labelled institutional flow. 13F is quarterly with a 45-day
lag (cloning evidence weak). The credible free option is SEC **Form 4** insider transactions
(EDGAR, ~2-business-day lag): provider + panel feature `insider_net_buy_90d` (officer/director
open-market buys − sells ÷ market cap) with a cluster-buy flag; golden-tested from saved filings;
keyed on the filing timestamp (point-in-time). Prior: moderate, event-like, works at long
horizons. Pre-register before any OOS touch, as always.

> Scheduled (2026-07-11) as card **13.3** — Phase 13 wave 3. Execute this card's text verbatim;
> mark both checkboxes in the same PR.

### 12.5 Redefine the success metric — decomposed portfolio + skill  `[x]`
**Foundational; decided with the user 2026-07-08 (RESEARCH_LOG 008). Do this BEFORE any further
OOS attempt** — the current G3 is structurally broken (biased low by cap-weight-benchmark
concentration; the naive portfolio fix is biased high by the equal-weight premium — a no-skill EW
book beats 0050 in 80.6% of validation cohorts). A §4-rule-4 gate change: one PR, playbook updated
in the same commit, every certification voided/re-run (there are none → trivial).

Steps:
1. `research/gates.py`: replace the G3 constants. New **G3 = selection-skill gate**: per-cohort
   alpha = (EW top-N book 6m `fwd_6m_rel` mean − EW eligible-universe 6m `fwd_6m_rel` mean);
   require `mean > 0` and `nw_tstat(alpha, null=0, lag=5) >= G3_MIN_SKILL_T = 2.0`. Keep G1, G2,
   G4, G5, G6 exactly as they are. Mirror the change in playbook §5 (the sync test enforces it).
2. `research/certify.py`: in the OOS loop, also compute the EW eligible-universe book's `fwd_6m_rel`
   mean per cohort (mean over all `eligible` rows), the per-cohort selection alpha, and the
   **portfolio-cohort beat rate** (fraction of cohorts with book `fwd_6m_rel` mean > 0) + its NW CI.
   New `CertReport` fields: `portfolio_beat_rate`, `portfolio_beat_ci95`, `selection_alpha_mean`,
   `selection_alpha_t`. G3 now reads the alpha; the displayed probability is `portfolio_beat_rate`.
3. `docs/NORTH_STAR.md` "displayed probability" + `docs/RESEARCH_PLAYBOOK.md` §5 headline row and the
   "Displayed probability" paragraph: portfolio-cohort beat rate (vs benchmark) for display; skill
   alpha (vs EW-universe) for the gate.
4. `ui/today_page.py`: show the portfolio beat rate + CI as the probability, and the selection-alpha
   (skill vs equal-weight) as a second evidence line so the EW-premium vs skill split is visible.
5. Tests (`tests/test_certify.py`): a **no-skill equal-weight book fails the new G3** (alpha ≈ 0),
   a **skilled book passes**, and the report carries the new fields; update the gate-mirror test.
6. After it lands: re-evaluate the closed families on the new metric; `tw-revenue-momentum`
   `{rev_mom_accel}` (validation skill +6.35%, NW-t 2.07) is the first pre-registration candidate —
   but the 2023+ regime (TSMC AI dominance) may reverse the EW premium and pressure momentum, so a
   fair test is not a promised pass. Vault stays sealed until pre-registration.

## Phase 13 — Signal expansion (US re-evaluation + free features; TW full universe)

> Program decided with the user 2026-07-11 (the four-need expansion; needs 2–3 are Phases 14–15).
> Binding choices: **US** = (a) re-evaluate the closed families under the 12.5 decomposed metric,
> (b) new *free* feature families — the 12.3 paid-data memo stays armed but **unscheduled** (write
> it only when the user asks). **TW** = free paced FinMind crawl, no paid tier. Execution order:
> the wave plan at the bottom of this file (it overrides top-to-bottom across Phases 11.5–16).
> Vault discipline is unchanged and explicit: every card that could touch OOS (**13.2, 13.6,
> 13.8**) must stop and get a **recorded user go/no-go before pre-registering**. A REJECTED
> verdict, honestly logged, completes a card.

### 13.1 US re-evaluation under the decomposed metric  `[x]`

> **Outcome (2026-07-11, RESEARCH_LOG 011): `{fcf_yield}` is the sole survivor** — dev selection
> alpha +2.99% (NW-t +3.92), val +7.89% (NW-t +2.98); its skill was real all along, masked by the
> old biased G3. The other 7 (incl. the entry-010 TW low-vol×trend combos, which are *negative* on
> US) closed at development. 0 OOS touched. `evaluate()` + tests landed; `{fcf_yield}` → card 13.2,
> which must first get the user's void-vs-attempt ruling (see the log's governance flag).

**Goal:** the 001–003 US families died under the *old, structurally biased* G3; nobody has ever
measured their selection alpha. Re-score them (plus the entry-010 combos) on Dev/Validation only.
**Files:** new `src/heimdall/research/evaluate.py`, `tests/test_research_evaluate.py`, a
RESEARCH_LOG entry.

Steps:
1. `evaluate(spec, panel, window) -> EvalReport` — the same math as certification (import
   `certify.cohort_alpha` and the existing IC/spread/turnover paths; do **not** fork formulas),
   but windowed. **Hard guard, tested: raise if the window end ≥ `gates.OOS_START`** — dev/val
   evaluation becomes a sanctioned reusable path instead of per-session ad-hoc scripts.
2. Verify the candidate columns exist in `panel_us` (`ret_12_1`, `roic`, `fcf_margin`,
   `operating_margin`, `fcf_yield`, `ret_6m`, `pct_above_sma_200`, `vol_63d`); any missing ⇒
   extend the panel first (7.3 CLI, resumable).
3. Pre-stated candidates — no additions mid-session (tempted ⇒ stop and ask): `{ret_12_1}`,
   `{roic, fcf_margin, operating_margin}` equal, `{fcf_yield}`, `{ret_6m}`, `{pct_above_sma_200}`,
   `{vol_63d: −1}`, `{vol_63d: −1, ret_6m: 1}`, `{vol_63d: −1, pct_above_sma_200: 1}`.
4. DEV (2010–2019) on all eight; advance to the **single** VAL look only candidates with dev
   selection-alpha NW-t ≥ 2 **and** dev IC t ≥ 2 (the entry-010 precedent).
5. RESEARCH_LOG entry: dev + val tables, count of looks (full disclosure), per-candidate verdict
   (advance to 13.2 / closed).

DoD: OOS-window-refused test; parity test (evaluate ≡ certify gate math on the same synthetic
rows); log entry committed; quality gates green.
**Don't:** read any row ≥ 2023-01-01 (hard assert in the run); no weight tuning after the VAL
look; no pre-registration here — that is 13.2's decision.

### 13.2 US survivor: pre-register + one OOS attempt (conditional)  `[x]`

> **Outcome (2026-07-11, RESEARCH_LOG 012): `us-fcf-yield v2` vault-REJECTED.** User ruled the
> re-run a §4-rule-4 void-and-rerun (family stays 1/3, submitted as v2); a `--void-and-rerun` path
> was added to the certify flow (guard-preserving, tested). OOS G3 selection alpha −0.80% (NW-t
> −0.52) — the in-sample skill (dev +2.99%/t3.92, val +7.89%/t2.98) did not survive the 2023-25
> mega-cap regime, exactly the pre-registered prior. G1_ic +0.031 reproduces the old run (rank IC
> is weighting-immune) but G1_t 1.59 < 2. Family `us-value-quality` has 2 genuine attempts left
> (new data only). Today's Picks stays US-empty; the 12.3 paid-data trigger is sharpened (unscheduled).

**Goal:** one disciplined vault shot for the best 13.1 survivor — only if one exists.
**Files:** `signals/specs/<name>.json`, RESEARCH_LOG entry, `signals/certifications/…`.

Steps:
1. Precondition: a 13.1 candidate with VAL selection-alpha NW-t ≥ 2 and VAL IC alive. None ⇒
   record "closed — no candidate" on this card; done.
2. **Stop and ask the user (mandatory; the ruling is copied verbatim into the log entry):**
   (a) authorize spending the family's OOS attempt; (b) *if* the candidate is `{fcf_yield}` with
   the identical spec hash `ade91883…`, ask whether the run counts as a **12.5 void-and-rerun**
   (§4 rule 4 voids old-gate certifications; a free re-run of the same frozen spec) or as
   **attempt 2/3** of `us-value-quality` (the conservative reading).
3. Pre-register (playbook §8), commit, run the certify CLI; registry transitions through code only.

DoD: verdict logged either way; immutable report committed if run.
**Don't:** touch the vault before the recorded go; never adjust weights after seeing an OOS number.

### 13.3 US insider-transactions feature — execute card 12.4  `[x]`

> **Outcome (2026-07-12):** new layer-pure `data/providers/form4.py` — `normalize_ownership_doc`
> (Form 4 `ownershipDocument` XML → canonical per-transaction rows, golden-tested from a hand-built
> namespace-free fixture) + a `Form4Provider` whose `get_insider_transactions` crawls the issuer's
> EDGAR submissions index and caches per symbol. Keyed on **`filed_at`** (the filing date, supplied
> alongside the XML since it lives in submission metadata, not the document) — never `txn_date`, so
> the two-business-day reporting lag can't leak the future. Panel feature `insider_net_buy_90d`
> (officer/director open-market **P** buys − **S** sells, each `shares × price`, ÷ market cap, 90-day
> trailing window) + a boolean `insider_cluster_buy` (≥3 distinct insiders buying) in
> `research.dataset._insider_features`, wired as an optional per-symbol `insider` stream in
> `build_dataset_iter` and the US branch of the build CLI. Tests: golden + no-symbol guard
> (`test_form4.py`), plus known-answer / PIT-leak / role-filter / market-cap-guard / panel-wiring
> (`test_research_dataset.py`). An empty stream ⇒ NaN (column genuinely absent for a symbol with no
> Form 4s); a populated stream with no in-window trade ⇒ a real 0. **No real crawl was run** — the
> data acquisition + `panel_us` column population is card 17.7's one rebuild (this card is "insider
> if merged" there). Quality gates green; full suite 372 passed.

**Card 12.4 verbatim** (Form 4 provider + `insider_net_buy_90d` + cluster-buy flag, point-in-time
on the filing timestamp), sequenced into this phase's feature wave. Mark both checkboxes in the
same PR. The feature then enters the `us-insider` family in 13.6.

### 13.4 US earnings-surprise (PEAD) features — estimate-free  `[x]`

> **Outcome (2026-07-12):** `research.dataset._pead_features` adds `sue` and `earn_gap` (US rows).
> **Key correction, verified against the real cached EDGAR data:** US 10-Ks file **no discrete Q4**,
> so EDGAR carries only **3** quarterly `eps_diluted` rows/year — a *positional* "q−4" would pair
> mismatched quarters. `sue` therefore aligns each quarter to the same fiscal quarter a year earlier
> (fiscal-end span in [300, 430] days, nearest 365 — robust to the day-drift, e.g. Apple's
> Dec-30→Dec-28), then standardizes the latest seasonal surprise by the std of the last 8 (`np.std`;
> the ddof is ranking-immaterial at a fixed 8-obs window). `earn_gap` is the (stock − benchmark)
> one-bar return on the first bar ≥ the latest EPS filing (annual **or** quarterly, so 10-K/Q4
> earnings count), gated to a 65-trading-day recency window. Quarterly rows reach the panel via a new
> optional `quarterly_fundamentals` stream (re-normalized from the same cached companyfacts JSON — no
> extra network) whose presence is the US-fundamentals-feature switch. Tests: seasonal-alignment
> known-answer + PIT-leak + <8-obs guard for `sue`; known-answer + recency guard for `earn_gap`;
> panel-wiring. **Panel extension is consolidated into card 17.7** (the one `panel_us` rebuild), per
> the Wave-3 design — not run here. Gates green.

**Goal:** the post-earnings-drift axis without paid analyst estimates.
**Files:** `src/heimdall/research/dataset.py` (panel-only features),
`tests/test_research_dataset.py`.

Steps (US rows; every input is already normalized by the EDGAR provider — `eps_diluted` quarterly
rows carry `filed_at`; **don't touch providers**):
1. `sue` — standardized unexpected earnings: latest (EPS_q − EPS_{q−4}) ÷ std of the last 8 such
   YoY changes, using only quarterly rows with `filed_at` ≤ the row's month-end; NaN if < 8
   observations. Direction **+**.
2. `earn_gap` — announcement reaction: (stock − benchmark) return over the first trading bar ≥
   the latest `filed_at` within the past 65 trading days; NaN when no filing in the window.
   Direction **+** (drift continues the initial reaction).
3. Feature-table doc lines (direction + one-line rationale), per playbook §7.
4. Extend `panel_us` (resumable CLI; EDGAR is cached — no rate concerns).

DoD: the mandatory **PIT leak test** (a quarterly filed after month-end *t* must not move row *t*)
plus known-answer tests covering the q−4 alignment, the 8-obs std window, and `earn_gap`'s
first-bar-≥-`filed_at` rule; suite green.
**Don't:** key anything off fiscal period end; don't synthesize EPS from net income when the tag
is missing (report coverage instead).

### 13.5 US issuance / asset-growth / gross-profitability features  `[x]`

> **Outcome (2026-07-12):** `research.dataset._issuance_quality_features` adds `net_issuance_12m`
> (YoY % Δ shares_outstanding, dir −), `asset_growth` (YoY % Δ assets, dir −), and
> `gross_profitability` (`gross_profit ÷ assets`, Novy-Marx, dir +; NaN when the `GrossProfit` tag is
> absent — never derived from revenue − COGS). All annual, `filed_at`-keyed via a local
> `_annual_yoy_pct` mirroring `factors.metrics._growth_yoy`. **Noted overlap:** `net_issuance_12m` is
> numerically identical to the snapshot's existing `share_dilution_yoy` — it is kept as an explicitly
> named member of the `us-issuance-quality` family (13.6) rather than aliased; the panel will carry
> both columns with equal values (flagged to the user). Gated on the same `quarterly_fundamentals`
> US switch as 13.4. Tests: known-answer + PIT-leak + missing-GrossProfit for the three features,
> plus the shared panel-wiring test. **Panel extension consolidated into card 17.7** (not run here).
> Gates green.

**Goal:** three documented free axes orthogonal to the already-tested roic/margin set.
**Files:** `src/heimdall/research/dataset.py`, `tests/test_research_dataset.py`.

Steps (annual EDGAR rows, `filed_at`-keyed, already normalized — `shares_outstanding`, `assets`,
`gross_profit` all exist in `METRIC_SPECS`):
1. `net_issuance_12m` — YoY % change in `shares_outstanding` between consecutive annual rows.
   Direction **−** (issuance is bad news; buybacks good).
2. `asset_growth` — YoY % change in `assets`. Direction **−** (the asset-growth anomaly).
3. `gross_profitability` — `gross_profit ÷ assets` (Novy-Marx). Direction **+**. NaN when the
   `GrossProfit` tag is absent — report dev-window coverage in the 13.6 log entry.
4. PIT leak + known-answer tests per feature; feature-table doc lines; extend `panel_us`.

DoD: tests as above; gates green.
**Don't:** derive gross profit from revenue − COGS (COGS isn't normalized; coverage honesty over
completeness); don't touch providers.

### 13.6 US new-feature families — research card  `[ ]`

> **Deferred (2026-07-12, user decision): blocked on 17.7.** The 13.3–13.5 features are merged
> (code + tests), but this card's DEV/VAL `evaluate()` needs them as **columns in `panel_us`**, and
> `panel_us` is only rebuilt with the new columns by card **17.7** (Wave 3, sequenced before this
> Wave-4 card). 17.7's governance precondition is already satisfied (no US signal is `certified` —
> only `us-fcf-yield` rejected). Two notes for whoever runs this next: (a) the `us-insider` family
> additionally needs a real Form 4 crawl — `Form4Provider` exists but no filings are cached, and a
> US rebuild will trigger that ~3,400-issuer network crawl unless the insider stream is disabled, so
> 17.7 may run fundamentals-only first (PEAD + issuance), with `us-insider` waiting on a later
> crawl+rebuild; (b) every vault touch here still stops for a recorded user go/no-go (§4).

**Goal:** playbook §7 end-to-end over the 13.3–13.5 features. Family boundaries (binding for the
3-attempt budget): `us-insider` = the insider features; `us-pead` = {sue, earn_gap};
`us-issuance-quality` = {net_issuance_12m, asset_growth, gross_profitability}. A composite that
crosses these boundaries is a **new family** (`us-composite-…`), never billed to an existing one.

Steps:
1. Pre-stated candidates per family: each single feature + one equal-weight composite per family;
   ≤ 4 parameters each. Evaluate with 13.1's `evaluate` on DEV; single VAL look for dev survivors
   (same advance bars as 13.1 step 4).
2. One RESEARCH_LOG entry per family evaluated (tables + look counts). Honest closures complete
   the card — never force a vault attempt.
3. Any VAL survivor: **stop and ask the user** before pre-registering (13.2's protocol).

DoD: log entries committed; zero OOS reads outside a user-authorized, pre-registered certify run.
**Don't:** mix family budgets; don't add candidates mid-session.

### 13.7 FinMind paced crawler (full-TW streams, free tier)  `[x]`

> **Outcome (2026-07-13):** `research/finmind_crawl.py` — a paced pre-warmer over `tw_symbols()` ×
> {revenue, chips, fundamentals, lending} that persists each `(symbol, dataset)` to a disk stream
> cache and yields progress per item. **Placed in `research/`, not the card's suggested `data/`:**
> the card's own Step 2 iterates `screener.tw_symbols()`, and `data/` may never import `screener`
> (the one-way layer rule — no `data/` module does); universe-iterating provider-orchestrators
> already live in `research/` (`build_dataset.py`, `tdcc_cache.py`). Since **no committed stream
> cache existed** (the 005/006 one was scratch, 560 calls, long gone), this defines the *one*
> canonical format: `data/research/streams/{dataset}/{TICKER_MARKET}.parquet` + `streams/_ledger.json`,
> with `load_cached_stream()` reading it back with a provider-method-shaped signature for 13.8's
> offline substrate. Ledger-keyed skip ⇒ interrupt-then-rerun makes **zero** duplicate calls;
> hourly-budget pacing (`--budget-per-hour`, default 550); 402/403 quota-ban backoff sleeps a
> window (~26 min) and **retries the same item** (never marked done until it truly completes), while
> a genuine failure is recorded-not-retried. Tests (`test_finmind_crawl.py`, 7): a fake provider,
> injected `sleep`/`monotonic`, **no network** — ledger idempotency, interrupt-then-rerun zero-dup,
> canned-402/403 backoff, non-quota handling, budget pause. **The multi-day crawl itself was not
> run** (it is the operator chore this tool enables — ~9+ quota-hours over days). Gates green;
> suite 379.

**Goal:** the full ~2,130-name TW streams on disk without a paid tier. The 11.4 constraint
measured ~5,600 calls ≈ 9 quota-hours — make that a background chore, not a blocked session.
**Files:** new `src/heimdall/data/finmind_crawl.py`, `tests/test_finmind_crawl.py`.

Steps:
1. Locate the stream cache the 005/006 build used (RESEARCH_LOG 004 note) and **reuse that
   format/path** — one cache, never a second format. If the streams are cached inside the
   provider path, the crawler is simply a paced pre-warmer calling the same
   `FinMindProvider.monthly_revenue` / `.daily_chips` / fundamentals methods.
2. CLI `uv run python -m heimdall.data.finmind_crawl --market tw
   [--datasets revenue,chips,fundamentals,lending] [--budget-per-hour 550]`: iterate
   `tw_symbols()`; a per-(symbol, dataset) progress-ledger JSON makes re-runs skip completed
   work; pace under the hourly budget; on 402/403 sleep until the window resets (~26-min bans —
   log and wait, never crash). **TODO (17.1 landed first):** include `FinMindProvider.daily_lending`
   under the `lending` dataset choice, alongside `monthly_revenue`/`daily_chips`.
3. Progress + ETA prints in the `screener.build` mould; safe to interrupt at any point.

DoD: interrupt-then-rerun makes **zero** duplicate calls (ledger test with a fake provider);
backoff unit-tested from canned 402/403 responses; no network in tests. Operator note: run
detached/overnight or across days.
**Don't:** bypass the provider's rate limiter; don't invent a second cache format.

### 13.8 Full-universe `panel_tw` + revenue-momentum v2 (user-gated)  `[ ]`

> **Blocked (2026-07-13): needs 13.7's crawl to have actually _run_, + a mandatory user gate.**
> 13.7 shipped the crawler tool, but Step 1's precondition is the full-universe streams **on disk**,
> which requires running that crawl — ~9+ FinMind quota-hours across days, with 26-min IP bans —
> and that **cannot happen in-session** (live network + quota). Every step here (build to
> `data/research/full/`, DEV/VAL re-eval, then the Step-4 vault decision) sits on that substrate.
> Correction for whoever picks this up: the shipped `panel_tw` is **price/fundamentals-only** — it
> carries *none* of the `rev_mom_*` / flow columns (verified 2026-07-13), so v1's certification used
> a separate reduced-universe substrate, not this file. Path once the crawl has run: wire
> `finmind_crawl.load_cached_stream` as the stream callables into a `root=data/research/full/`
> build, run the free re-eval, then **stop and ask the user** (Step 4) before any vault touch.

**Goal:** rebuild the TW panel on the full universe (entry 010's hard substrate), re-evaluate the
closed TW candidates fairly, and — with sign-off — take revenue momentum's v2 shot, removing the
140-name-selection caveat from the program's only certified signal.
**Files:** panel via the 7.3 CLI (separate root), RESEARCH_LOG entries, spec v2 JSON if authorized.

Steps:
1. Precondition: 13.7 complete for revenue + chips (+ fundamentals if feasible).
2. Build the full panel to a **separate root** (`data/research/full/`; `dataset.py` already takes
   `root`) — the shipped `panel_tw` is `tw-revenue-momentum v1`'s certified **and monitoring**
   substrate and must stay untouched until the v2 decision.
3. Free re-eval (13.1's `evaluate`; DEV + single VAL look), pre-stated: `{rev_mom_accel}`,
   `{rev_mom_yoy, rev_mom_accel}`, `{foreign_net_buy_63d}`,
   `{foreign_net_buy_63d, trust_net_buy_21d: 0.5}`.
4. **Stop and ask the user:** (a) spend `tw-revenue-momentum` attempt **2/3** on v2 (same recipe,
   genuinely new substrate — §4 rule 2 compliant)? (b) confirm the panel-promotion rule: v2
   certifies ⇒ promote the full panel to the standard path and retire v1 via the sanctioned
   lifecycle ("re-certified as new version"); v2 fails ⇒ the 140-name panel stays shipped (v1 and
   its monitoring stand) and the full panel remains a research artifact. `tw-flows` gets **no**
   vault touch without its own separate authorization.
5. If authorized: pre-register, certify, registry through code.

DoD: log entry with dev/val tables; if run, immutable report + the promotion rule executed
exactly; gates green.
**Don't:** overwrite the certified panel before the decision; don't let a v2 failure silently
discredit v1 — record the divergence honestly instead.

### 13.9 TDCC big-holder provider + concentration feature  `[x]`

> **Outcome (2026-07-12):** live-derived the bracket table (no official code table was
> fetchable) via direct arithmetic on the real full file — Σ(levels 1–16) == level 17 exactly
> for every stock checked, proving level 17 is a summary row; levels 1–15 cross-checked against
> a public label listing. **Level 16 correction mid-investigation:** an initial 6-stock spot
> check wrongly suggested "always zero" — the full 4,001-security file showed 78 nonzero cases
> (57 plain common stocks), each with exactly one holder and a small/round share count,
> inconsistent with an ownership-size tier; documented honestly as unresolved and excluded from
> `BIG_HOLDER_LEVELS` (its magnitudes never approach 400 lots regardless). **PIT lag was
> genuinely ambiguous — stopped and asked per the card's own instruction**: a secondary source
> claimed ~1-day lag, but a live probe found the bulk file still 9+ days stale with no delay
> notice; user chose the conservative `data_date + 14 days`. `data/providers/tdcc.py` stays
> layer-pure (`normalize()` takes an injected `market_by_id`, since TDCC's file carries no
> market-type field); `research/tdcc_cache.py` does the cross-layer wiring. **No historical
> backfill exists** on this endpoint — `big_holder_ratio_delta_4w` (in `research/dataset.py`,
> PIT-leak tested) will read NaN until 4 real weeks accumulate via
> `python -m heimdall.research.tdcc_cache`, run weekly. Full writeup: `docs/RESEARCH_LOG.md`
> entry 014. Quality gates green; full suite 350 passed.

**Goal:** the weekly 集保 (TDCC) shareholding-dispersion file as a canonical provider + a
point-in-time concentration feature. Double-serves need 3 (card 15.3). FinMind's equivalent
dataset is paid-tier; the TDCC open-data portal serves the weekly whole-market file free.
**Files:** new `src/heimdall/data/providers/tdcc.py`, `tests/test_tdcc.py` (golden from a saved
CSV excerpt), `src/heimdall/research/dataset.py` feature + tests.

Steps:
1. Provider: fetch + normalize the weekly file (canonical `TICKER.TW`, `data_date`, bracket
   level, holder count, shares, %). Keep the raw file per data-discipline; delta-only (skip weeks
   already stored). Verify the bracket→lot mapping against the portal's definition table inside
   the golden test (the ≥ 400-lot brackets are the "大戶" set).
2. Availability rule (PIT): the weekly file is published *after* its data date — verify the
   observed lag on the portal, encode `available_at = data_date + observed lag` in the provider,
   document it in the docstring. Ambiguous ⇒ stop and ask.
3. Feature `big_holder_ratio_delta_4w` (TW rows): pp change over 4 weekly files of the ≥ 400-lot
   share-%; a row may only read files with `available_at` ≤ its month-end (**PIT leak test
   mandatory**). Direction prior **+** (rising concentration = large-holder accumulation).

DoD: golden + PIT + known-answer tests; gates green. Researching this feature later = its own
`tw-bigholder` family card, not part of this one.
**Don't:** FinMind's paid `TaiwanStockHoldingSharesPer`; no scraping beyond the official
open-data endpoint.

## Phase 14 — Sector focus (quant core + optional AI brief)

> Need 2, decided 2026-07-11: the page itself is **computed** (rotation/breadth/flows); news and
> named-authority views live only in an **optional, clearly-labelled AI commentary** (personas
> pattern — the app is fully functional without it, and nothing here feeds any certified
> computation). Every page in Phases 14–15 carries the 11.5 fixed caption in both languages:
> *descriptive data, not a certified signal; Today's Picks ignores this page.*

### 14.1 Sector classification on the snapshot  `[x]`

> **Outcome (2026-07-11):** TW reuses `_parse_tw_info`'s already-fetched `industry_category`
> (refactored into a shared `_parse_tw_rows` core, zero behavior change to `_parse_tw_info`) via
> new `tw_sector_map()`, cached beside `tw_all.json`. US: option (a) confirmed dead (nothing
> cached carries sector); option (b) implemented — EDGAR `submissions` JSON's numeric `sic`,
> bucketed into one of the 10 standard **SIC Divisions** (not raw `sicDescription`, which is
> 1000+ distinct strings — too granular to aggregate a sector page over) via new
> `us_sector_map()`, incrementally cached, ~10 req/s. `build_row`/`build_snapshot`/
> `build_snapshot_iter` gained an opt-in `sector_map` param mirroring `monthly_revenue`'s exact
> precedent (present → every row gets `sector`, "Unknown" if missing from the map; omitted →
> column entirely absent, so old callers/tests are untouched). Wired into `build.py`'s CLI. zh
> glosses added for all 10 Division names + "Unknown" + "Sector" (TW's industry strings are
> already zh). `DATA_SOURCES.md` documents the choice. Tests: TW/US/Unknown known-answers +
> SIC-division boundary-contiguity + the sector_map threading suite; existing snapshot tests
> untouched. Quality gates green.

**Goal:** one `sector` string per snapshot row, both markets.
**Files:** `src/heimdall/screener/universe.py`, `src/heimdall/screener/build.py` (carry the
field), `docs/DATA_SOURCES.md` (one line on the chosen US source), tests.

Steps:
1. TW: `_parse_tw_info` already reads `industry_category` — persist a symbol→industry map beside
   the cached universe file instead of discarding it.
2. US: probe in order, take the first workable, document the choice: (a) a sector field already
   present in cached universe/snapshot artifacts; (b) EDGAR `submissions` JSON `sicDescription`
   (one cached request per symbol under the EDGAR rate limit); (c) a committed static CSV
   fallback.
3. Snapshot rows gain `sector` ("Unknown" when missing — never drop a row). i18n: TW categories
   are already zh; add zh glosses for the ~dozen US sector groups in `i18n.py`.

DoD: mapping known-answer tests (one TW, one US, one Unknown); existing snapshot tests untouched.
**Don't:** per-symbol yfinance `.info` loops (rate-fragile, unofficial).

### 14.2 Sector-focus page  `[x]`

> **Outcome (2026-07-11):** new `analytics/sector_focus.py` (pure — `trailing_return`,
> `sector_table`, `member_table`, known-answer tested) keeps `ui/sector_page.py` thin, matching
> the `rotation_page.py`/`analytics.rotation` precedent. One price fetch per member covers the
> largest (21-bar) window so the 日/週/月 toggle needs no re-fetch, cached via `st.cache_data`.
> Sector table sorted by return-vs-benchmark descending ("who leads"); per-sector drill-down
> expanders show members ranked by return with RS vs the sector mean. TW-only 法人分產業 block
> checks for 15.2's (not-yet-built) cache and shows a graceful pending hint instead of crashing —
> the exact expected path is now documented as a contract on 15.2's own card. Old snapshots
> without a `sector` column (pre-14.1) get an actionable hint rather than crashing — confirmed
> live against the real (pre-14.1) snapshot in-browser, alongside the TW empty-market path; no
> console/server errors. AppTest smokes cover both empty states + the full flow (table, TW hint,
> per-sector expanders) with faked prices (no network). Fixed non-certified caption, both
> languages. Quality gates green; full suite 262 passed.

**Goal:** the daily/weekly/monthly answer to "which industries lead, and who inside them".
**Files:** new `src/heimdall/ui/sector_page.py`, `app.py` (nav group "Analyst lenses"),
`i18n.py`, `tests/test_ui_smoke.py`.

Steps:
1. Window toggle 日/週/月 = 1/5/21 trading days over cached adjusted closes.
2. Per sector (equal-weight over members with data): window return vs the market benchmark,
   member count, breadth (% of members with `pct_above_sma_200 > 0` from the snapshot); ranked
   table.
3. TW-only block: 法人分產業 net buy over the window, reading 15.2's daily bulk cache; cache
   absent ⇒ an info hint pointing at 15.2 — no crash, no fetch storm.
4. Drill-down expander per sector: members ranked by window return, RS vs the sector mean.
5. The phase's fixed caption, both languages.

DoD: AppTest smokes — renders from a snapshot fixture, caption present, missing-chips hint path;
zh strings; gates green.
**Don't:** anything that reads as a buy list; no LLM on this page.

### 14.3 Optional AI sector brief (personas layer)  `[ ]`

**Goal:** on-demand news/authority context for a chosen sector — bull *and* bear cases with
cited sources — as personas-pattern commentary.
**Files:** `src/heimdall/personas/templates.py` (+ reuse `client.py`/`render.py`), the
`src/heimdall/ui/_personas.py` hook used from `sector_page.py`, disk cache under
`data/reports/sector_briefs/` (gitignored), template-render test (no API call).

Steps:
1. Payload = 14.2's computed stats for the sector + its quant-ranked top/bottom members. The
   brief may **only** discuss tickers from that payload — the LLM never picks or re-ranks names.
2. Template requirements: web-search the window's sector news + named-authority views; every
   claim cited with a link; an explicit bull case and bear case; fixed header — *AI commentary,
   not a certified signal, not investment advice* — in both languages.
3. Claude API with the web-search tool enabled (read the `claude-api` skill for current model ids
   and search pricing; default to a current model). Cache by (sector, window, as-of date);
   regenerate only on explicit click; surface the ~$0.05–0.15 per-brief cost in the button help.
4. The page stays fully functional without the `personas` extra (existing `_personas.py` gating).

DoD: template golden test; UI degrades gracefully without the extra; caption present.
**Don't:** auto-generate on page load; nothing from a brief feeds any computation or ranking.

## Phase 15 — TW money-flow lenses (法人・大戶・投信代理)

> Need 3, decided 2026-07-11: institutional flows (daily) + TDCC big holders (weekly), with 投信
> net buy/sell as the **active-money proxy** — the user explicitly chose **not** to scrape
> per-ETF PCF holdings; do not add such scrapers. Everything here is descriptive; the 11.5
> caption rule binds every view.

### 15.1 Per-stock chips dashboard — execute card 11.5  `[x]`

**Card 11.5 verbatim** (per-symbol 外資/投信 cumulative net buy vs price, foreign holding %,
margin balance; market top-10 lists). Wave 1: its data layer (11.3) is already wired. Mark both
checkboxes in the same PR.

> **Outcome (2026-07-11): the per-symbol lens shipped; market-wide top-10 deferred to 15.2.**
> `ui/chips_page.py` (nav "Analyst lenses" → "TW Chips") renders, for one TW symbol, cumulative
> 外資/投信 net-buy vs price + foreign holding % + margin balance, with the fixed non-certified
> caption both languages. Aggregation is `analytics.cumulative_flows` (pure, known-answer tested);
> the page is thin. **The market-wide top-10 clause of 11.5 was NOT built here:** 11.3 established
> FinMind's per-date bulk query is paid-tier, so a free-tier market-wide list would loop ~2,000
> names/day (quota-prohibitive). That aggregation belongs to 15.2, which builds the cached per-date
> store; 15.1 shows an on-page pointer to it. AppTest smoke asserts the render is network-free until
> "Load chip data" is clicked.

### 15.2 Market-wide money-flow page  `[x]`

> **Outcome (2026-07-11):** live-reconfirmed the bulk-per-date refusal (400 "please update your
> user level", same as 11.3's 2026-07-08 probe) before building anything. Three-layer split:
> `data/providers/finmind.py` gained `bulk_institutional_by_date()` (tries bulk, returns `None`
> on refusal — forward-compatible with a future paid tier, golden-tested via
> `_normalize_institutional_market_wide` on saved-JSON-shaped fixtures) and `_get`'s `data_id`
> became optional (bulk omits it); `_normalize_institutional` now also carries
> `dealer_net_shares` (自營商, same already-fetched call — zero extra quota; excluded from every
> panel *feature* as before, only this descriptive view reads it). New `research/flows_cache.py`
> orchestrates: bulk first, else loop the **current TW snapshot's** symbols (the sanctioned
> "cached-universe loop" — not the full ~2,130-name market, which stays 13.7's job) via the
> existing `daily_chips`; a `ProviderError` (quota exhaustion) stops the loop early rather than
> burning through the rest, other per-symbol errors are skipped. Writes exactly the path 14.2
> already contracted for. New `analytics/flows.py` (pure): market totals, by-sector rollup,
> top-N buy/sell, 投信 streak ("主動資金代理", the card's fixed label), foreign holding-ratio Δ.
> New `ui/flows_page.py` (日/週/月 toggle, an in-app "Build today's flows" button alongside the
> CLI). **Closed the 14.2 loop**: `sector_page.py`'s TW block upgraded from a raw passthrough to
> a real `sector_rollup()` aggregation, with a new test proving real cache data now renders
> genuine rows instead of the pending hint. Tests: bulk golden + refusal/empty-market/data_id-
> omission, `_from_loop`'s quota-stop-vs-skip distinction, cache reuse/refresh, `load_window`'s
> calendar-gap tolerance, all `analytics/flows` functions, and AppTest smokes for both the
> no-cache empty state and a full multi-day render. Browser live-check was blocked by a
> persistent tool-side "policy check" hang (not a code issue — same infra hiccup hit earlier in
> the session); relied on the AppTest suite instead. Quality gates green; full suite 328 passed.

**Goal:** where TW money went — day/week/month, market-wide.
**Files:** `src/heimdall/data/providers/finmind.py` (bulk per-date methods + golden tests), a
per-(dataset, date) disk cache, new `src/heimdall/ui/flows_page.py`, `i18n.py`,
`tests/test_ui_smoke.py`.

Steps:
1. Bulk per-date fetch (the 11.3 step-1 probe, now load-bearing): query each chip dataset with
   `start_date == end_date` and **no** `data_id` → whole market in ~1 request/day/dataset. If the
   free tier refuses bulk, fall back to a cached-universe loop and label the coverage on-page.
2. Cache per (dataset, date) parquet, delta-only — a month of history ≈ 60–90 requests, well
   inside quota. **Contract owed to 14.2 (already shipped and blocked on this):**
   `ui/sector_page.py`'s `_flows_cache_path(as_of, root)` already expects a by-sector
   institutional-flow parquet at `data/research/flows/institutional_{YYYY-MM-DD}.parquet`
   (minimum shape: a `sector` column) and renders it as-is once present — either write to
   exactly that path/name as part of this card's per-(dataset, date) cache, or update
   `sector_page.py`'s contract function in the same PR if a different layout turns out better.
3. Page, with 日/週/月 = 1/5/21-session aggregation: market net buy by investor type
   (外資/投信/自營); by-sector rollup (needs 14.1 — hide the block gracefully if `sector` is
   absent); top-N net buy/sell names by NT$ value (net shares × close); **投信 streak ranking**
   (consecutive net-buy/-sell days) labelled 「主動資金代理 — 含全體投信基金（主動+被動+非ETF）」;
   foreign holding-ratio Δ ranking.
4. Fixed caption; zh strings.

DoD: aggregation known-answer tests on synthetic frames; bulk-path golden test from saved JSON;
AppTest smoke incl. the no-cache empty state; gates green. Also re-run 14.2's
`test_sector_page_full_flow_and_missing_flows_hint` (or its successor) once real data exists to
confirm the flows block now renders real rows instead of the pending hint.
**Don't:** per-ETF holdings scrapers (user decision 2026-07-11); nothing presented as a
recommendation ranking.

### 15.3 Big-holder (大戶) weekly view  `[x]`

> **Outcome (2026-07-12):** `analytics/big_holder.py` (pure, no I/O) provides
> `big_holder_pct` (sums 13.9's `BIG_HOLDER_LEVELS` per symbol/week),
> `weekly_delta_ranking` (last-minus-oldest of the latest 4 available weeks, PIT-safe on
> `available_at`), `monthly_delta_ranking` (last-4-mean vs prior-4-mean, needs 8 weeks), and
> `symbol_history` (ascending per-symbol series for the chart overlay). `flows_page.py`'s
> `render()` now splits into `st.tabs(["Institutional Flows", "Big Holders (大戶)"])` — verified
> empirically (existing AppTest assertions re-run unchanged) that Streamlit/AppTest renders every
> tab body regardless of which tab is visually active, so no existing widget-index test broke.
> The big-holder tab applies the §3 liquidity floor (`gates.MIN_DOLLAR_VOL_21D["Taiwan"]`) before
> ranking, with an honest empty state if that leaves nothing. `chips_page.py` gained a
> `_big_holder_block` dual-axis overlay (大戶 % vs price) beneath the existing chip charts, same
> weekly-cadence caption citing 13.9's `AVAILABILITY_LAG`. Both surfaces state on-page that this
> is a **weekly** series, never interpolated to daily. New tests:
> `tests/test_analytics_big_holder.py` (11, known-answer Δ math + PIT-leak + empty guards) and 4
> new AppTest smoke tests in `test_ui_smoke.py` (flows-page tab empty/populated states,
> chips-page overlay empty/populated states). Full suite 363 passed; ruff/ruff-format/mypy clean.

**Goal:** the "大戶動向" lens on its honest weekly cadence. Needs 13.9.
**Files:** extend `flows_page.py` (weekly tab) + the per-symbol view in `chips_page.py`,
`i18n.py`, tests.

Steps:
1. Weekly tab on the flows page: top risers/fallers in the ≥ 400-lot holders' share-% (4-week Δ),
   filtered by the §3 liquidity floor so micro-caps don't dominate; 月 view = trailing 4 files vs
   the prior 4.
2. Per-symbol overlay in the chips dashboard: big-holder % vs price (dual axis), weekly points.
3. Same fixed caption; state the weekly publication lag on-page (from 13.9's `available_at`).

DoD: known-answer Δ math tests; AppTest smoke; zh strings; gates green.
**Don't:** interpolate the weekly series to daily; no ranking framed as picks.

## Phase 16 — Trust & usability layer

> Need 4, decided 2026-07-11: three scheduled cards + a backlog. Recorded **non-goals**
> (unchanged institutions): no paid 分點/broker-branch data, no sub-month signals, no
> social-sentiment scraping, no black-box weight optimizers. 12.3 stays armed-but-unscheduled.

### 16.1 Forward performance ledger (live track record)  `[x]`

> **Outcome (2026-07-13):** new `research/ledger.py`. `freeze(spec, snapshot, cert_month)` writes
> `signals/ledger/{name}_v{v}/{YYYY-MM}.json` from `today.todays_picks` — **append-only** (a second
> freeze of a month raises `FileExistsError`) and **no-backfill** (a month before `cert_month` raises
> `BackfillRefused`). `realized_track_record` recomputes each frozen cohort from the panel on the
> exact monitor/certify basis (EW book 6m rel, EW eligible-universe 6m rel, their alpha = the G3
> selection skill) and a "followed every month" equity curve chaining realized 1-month book returns
> **through `certify.apply_costs`/`cohort_turnover` at `gates.G4_COST_BPS`** — one home for the cost
> math. `freeze_all` (the monthly step 16.2 schedules) reads the registry (the one certified-only
> gate), each cert report's month + survivorship, and freezes the live snapshot; already-frozen and
> pre-cert months are silent no-ops. Today's Picks gained a **Live track record** section (cohort
> table + net equity curve + cert-date/survivorship caption) with an honest empty state before the
> first freeze. Tests: freeze-idempotency + no-backfill, known-answer alpha + costed curve, load
> ordering (`test_research_ledger.py`); 2 AppTest smokes (empty + populated). Gates green; suite 400.
>
> **Follow-up (2026-07-13):** the first real freeze (`tw-revenue-momentum` v1, month 2026-07)
> surfaced a UX gap — a cohort frozen mid-month, before the panel has *any* cross-section for that
> month yet, showed every column as a literal "None" and a candidate count of 0, indistinguishable
> from "nothing was frozen." Root cause: `RealizedCohort.n_picks` conflated "frozen" with "realized
> with a complete 6m label." Fixed without touching the certified month-anchored math (that stays
> exactly aligned with `certify`/`monitor` on purpose): split into `n_frozen` (always known) and
> `n_realized`; added a new, deliberately **separate** `unrealized_mark()` — a benchmark-relative,
> gross (nothing sold yet) live mark computed from today's cached prices via `ui._data.get_ohlcv`,
> shown only for not-yet-realized cohorts so it never competes with the official 6-month figure.
> Table columns reformatted to percentage strings with "—" for missing, eliminating the raw "None"
> text. Tests: 4 known-answer `unrealized_mark` cases + 1 AppTest smoke reproducing the exact
> mid-month scenario. Gates green; suite 405.
>
> **Follow-up 2 (2026-07-14, user-requested):** `unrealized_mark` now carries a per-symbol
> `positions: list[PositionMark]` breakdown (each pick's entry/latest/return + benchmark-relative
> alpha); the track-record UI keys the table by the freeze **date** (`as_of`) instead of the month
> and, for each still-live cohort, shows a per-symbol P&L expander (best performers first, pinned
> symbol column). Also clarified the caption so the intentionally-blank certified columns (book /
> universe / selection skill — they only fill after the 6-month window closes) read as expected, not
> broken. Verified against the real 19-name 2026-07 cohort. Suite 405.

**Goal:** freeze each month's certified picks and show the realized, costed track record — the
strongest honest trust feature the app can have.
**Files:** new `src/heimdall/research/ledger.py`, `signals/ledger/` (committed), a Today's Picks
section, `tests/test_research_ledger.py`.

Steps:
1. `freeze(signal, snapshot)` → `signals/ledger/{name}_v{v}/{YYYY-MM}.json` (as_of, spec hash,
   picks + scores). Append-only: a second freeze of the same month refuses, mirroring
   certification immutability. Only months ≥ the certification date — **no backfill** (pre-cert
   history is the OOS report's job; backfilled rows would masquerade as live).
2. Realized view: each frozen cohort's forward returns vs the benchmark and vs the EW eligible
   universe, recomputed from the panel — the same sanctioned post-2023 monitoring basis as 12.2
   (cite it in the module docstring); cumulative "followed every month" equity curve at G4's
   20 bps per side.
3. UI: track-record table + curve + the survivorship stamp and certification date, beside the
   existing evidence box.

DoD: freeze-idempotency test; known-answer curve math incl. costs; AppTest smoke; gates green.
**Don't:** backfill; don't track non-certified signals; don't drop the stamp.

### 16.2 Scheduled refresh + notifications (completes 12.1)  `[x]`

> **Outcome (2026-07-13):** new `src/heimdall/ops/` package (CLI-altitude — imports research/data,
> imported by nothing). `notify.run_weekly` chains the resumable CLIs (snapshot build → panel extend
> US+TW → `monitor --apply`) via an **injectable runner** (subprocess by default), then freezes the
> month's cohorts **in-process** through `ledger.freeze_all` (idempotent — one freeze/month on a
> weekly cadence, so no first-weekday date logic needed). It emits **one digest per run**: job-step
> failures (non-zero exit, never aborts the chain), drift flips (certified→under_review, detected by
> before/after registry status), cohorts frozen, and snapshot staleness (best-effort via
> `today.freshness`). Channels from `.env` — SMTP and/or Telegram (**not** LINE Notify, discontinued);
> unconfigured ⇒ **print-only dry run**. `com.heimdall.weekly.plist` (Mon 08:00; passes `plutil
> -lint`, a placeholder repo path the operator fills) + `docs/OPERATIONS.md` (install/verify/uninstall
> + what each notification means). Tests (`test_ops_notify.py`, 8): formatting worst-first,
> channel-selection, dry-run print, chained-run order + failure reporting + frozen-cohort events, plist
> lint — **no network, fake runner**. **12.1 marked `[x]` in the same PR.** Gates green; suite 400.

**Goal:** the weekly chore runs itself and pings the user only when something needs them.
**Files:** `docs/OPERATIONS.md`, a launchd plist template (checked in), new
`src/heimdall/ops/notify.py` (CLI-altitude module: may import research/data; imported by no core
module), tests.

Steps:
1. Weekly launchd job chaining the existing resumable CLIs: snapshot refresh → panel extension →
   `research.monitor` → (first weekday of the month) `ledger.freeze`.
2. Notifier with pluggable channels from `.env`: SMTP email and/or a Telegram bot token (LINE
   Notify is discontinued — do not use). Unset ⇒ print-only dry run. Events: cohort frozen;
   certified → under_review flip; snapshot staleness > 5 business days; job failure.
3. `docs/OPERATIONS.md`: install/verify/uninstall steps + what each notification means.

DoD: message-formatting + dry-run tests (no network); plist passes `plutil -lint`; mark **12.1
`[x]`** in the same PR with a "completed by 16.2" note.
**Don't:** schedulers that require the Streamlit app to be running; no notification spam (one
digest per run).

### 16.3 Monthly rebalance helper  `[x]`

> **Outcome (2026-07-13):** new pure `research/rebalance.py`. `diff_picks` classifies
> current-vs-last-frozen-cohort into added/dropped/kept; `target_shares` floors to TW 1,000-share
> board lots (odd-lot toggle relaxes it) / US whole shares (floor, never overspend); `trade_cost`
> encodes the **asymmetry** — TW 0.1425% fee/side + 0.3% tax on **sells only**, US flat bps
> (editable constants). `rebalance_plan` buys the **added** names to the equal-weight target and
> sells the **dropped** names (sized at the prior EW book — a documented assumption), holding kept
> names (no churn, no scheme beyond equal weight); `orders_to_csv` exports symbol/side/shares/ref-
> close/est-cost. Today's Picks gained a **Rebalance helper** section (added/dropped/kept metrics,
> budget input, TW odd-lot toggle, order table, CSV download) under the fixed bilingual "execution
> aid, not an order system, not advice" caption. Tests: known-answer lot rounding + odd-lot + the
> sell-tax asymmetry + the plan + CSV (`test_research_rebalance.py`, 6) and 1 AppTest smoke; zh
> strings added. Gates green; suite 400.

**Goal:** from "here are the picks" to "here is exactly what to change", with costs — an
execution aid, never an order system.
**Files:** new `src/heimdall/research/rebalance.py` (pure math), a Today's Picks section, tests.

Steps:
1. Diff current picks vs the latest frozen cohort (16.1): added / dropped / kept.
2. Allocation calculator: budget input → equal-weight targets → share counts. TW: 1,000-share
   board lots with an odd-lot toggle; US: whole shares. Costs: TW 0.1425% fee per side + 0.3%
   sell tax (editable constants); US flat-or-bps setting.
3. CSV export (symbol, side, shares, reference close, est. cost). Fixed caption: *an execution
   aid, not an order system, not advice; orders are placed at your broker* — both languages.

DoD: known-answer lot/cost tests (incl. odd-lot rounding and the sell-tax asymmetry); AppTest
smoke; zh strings.
**Don't:** broker-API integration; no sizing schemes beyond equal weight (that would be a spec
change requiring certification).

### 16.4 TDCC weekly cache joins the scheduled chain (closes 13.9's operational loop)  `[x]`

> **Outcome (2026-07-14):** `heimdall.research.tdcc_cache` appended **last** to `ops.notify`'s
> `WEEKLY_CHAIN` (after `monitor --apply`) — the 16.2 order stays a prefix, so existing order
> assertions hold, and the plist is untouched (the job reads the chain). A broken fetch (incl. the
> CLI's own exit-1 on an empty week) already surfaces via the shared non-zero-exit → `error` digest
> path, which never aborts the chain. New best-effort, read-only `_tdcc_staleness_event(today)` beside
> `_staleness_event`: via `tdcc.load_cached_weeks()`, empty/missing history ⇒ `None` (step-1's failure
> event already covers a broken fetch — no double-report), newest cached `data_date` **≥ 9 calendar
> days** old ⇒ a `warn` naming the date (fresh Monday age ~3 days; the 13.9 probe caught a 9-day-old
> re-served file). Wired into `run_weekly` next to the snapshot staleness check, so a stale TDCC cache
> suppresses the "completed cleanly" line. `docs/OPERATIONS.md` documents the step + both event
> meanings, the **missed-weeks-are-unrecoverable** caveat, that `--rebuild` only re-fetches the current
> week, and a "run it once now, don't wait for Monday" seed step. Tests (`test_ops_notify.py`, +5):
> chain-appends-tdcc-last (prior order intact), tdcc-failure-reported-but-freeze-still-runs, and three
> staleness known-answers (fresh ⇒ none / 9-day ⇒ warn / no-history ⇒ none) with a faked
> `load_cached_weeks`, no network. The fetch itself was **not** run in-session (it's the operator's
> weekly chore — live network). Gates green; suite 410. **Don't**s honored: fetch stays a subprocess
> (no in-process move), one digest per run, `data/providers/tdcc.py` + the `data_date + 14 days` PIT
> rule untouched.

**Goal:** 13.9's big-holder history accrues only in real calendar time — the TDCC endpoint serves
**only the current week; no backfill exists** — but `research.tdcc_cache` is not in 16.2's chain
(verified 2026-07-14: `WEEKLY_CHAIN` = snapshot → panel ×2 → monitor only). Every week it doesn't
run is `tw-bigholder`/15.3 history lost forever, and `big_holder_ratio_delta_4w` stays NaN until
4 real weeks sit on disk. Schedule it, and alarm on silent staleness — the 13.9 probe caught the
endpoint serving a 9-day-old file with no delay notice.
**Files:** `src/heimdall/ops/notify.py`, `tests/test_ops_notify.py`, `docs/OPERATIONS.md`.

Steps:
1. Append `["heimdall.research.tdcc_cache"]` to `WEEKLY_CHAIN` (append **last**, after
   `monitor --apply`, so existing order assertions stay prefix-stable). Failure handling is
   already built: a non-zero exit (incl. the CLI's own exit-1 on an empty fetch) becomes an
   `error` digest event and never aborts the chain. No plist change — the job reads the chain.
2. New `_tdcc_staleness_event(today)` beside `_staleness_event`, best-effort and read-only via
   `tdcc.load_cached_weeks()`: empty/missing history ⇒ `None` (step 1's failure event already
   covers a broken fetch); latest cached `data_date` **≥ 9 calendar days** old ⇒ `warn` naming
   the date (fresh Monday-run age is ~3 days; the observed 13.9 incident was exactly 9 — this
   catches both a missed week and the endpoint silently re-serving an old file). Wire into
   `run_weekly` next to the snapshot staleness check.
3. `docs/OPERATIONS.md`: document the new step and both event meanings; state the caveat in
   bold — **missed weeks are unrecoverable** — and that `--rebuild` re-fetches a same-week file.
4. Operator note (record it in OPERATIONS.md too): run
   `uv run python -m heimdall.research.tdcc_cache` once immediately after merging — don't wait
   for Monday's scheduled run.

DoD: chain test updated (new step present, prior order intact); tdcc-failure-reported-but-chain-
continues asserted; staleness known-answers (fresh ⇒ no event; 9-day-old ⇒ warn; no history ⇒
`None`) with a faked `load_cached_weeks`, no network; plist untouched; quality gates green.
**Don't:** move the fetch in-process (subprocess isolation, like every other data step); no extra
notification sends (one digest per run stands); don't touch `data/providers/tdcc.py` semantics or
the 13.9 `available_at = data_date + 14 days` PIT rule.

### 16.B Backlog — promote to a full card with the user before executing

- **Regime dashboard** — benchmark concentration (top-name weight), EW−CW return spread,
  certified signals' trailing skill; descriptive only, never a gate.
- **Real-holdings risk view** — the user's actual portfolio through the Bridgewater risk module,
  side by side with the picks book.
- **Data-integrity sentinel** — yfinance-vs-TWSE close spot-checks, scheduled seam scans, a
  staleness rollup across datasets.
- **TW event calendar** — 月營收 dates, ex-div, 股東會 short-recall windows, 處置股 list;
  display-only (a 處置股 hygiene filter would be a §3 change → its own card + re-certification).
- **Multi-signal combiner** — unlocks at ≥ 2 certified signals; an equal-weight blend is its own
  spec + family through the full pipeline.

## Phase 17 — Orthogonal alpha axes & mechanism upgrades (expert review 2026-07-11)

> Program decided with the user 2026-07-11 (expert-review session). Motivation: the fastest honest
> route to a higher displayed win rate is **more mutually-orthogonal certified families** (which
> also unlocks the 16.B combiner), plus mechanism upgrades that make any book cheaper to hold and
> any measurement more trustworthy. Cards appear in the user's priority order; the wave plan at
> the bottom of this file resolves dependencies and overrides top-to-bottom. All Phase-13 rules
> bind unchanged: one card per PR; research cards follow playbook §7; **every vault touch (17.2,
> 17.8, 17.13) stops for a recorded user go/no-go before pre-registering**; a REJECTED verdict,
> honestly logged, completes a research card.
>
> **Family boundaries (binding for the 3-attempt budgets), with pre-registered direction priors:**
> `tw-short-pressure` = {sbl_short_delta_21d −, sbl_short_delta_63d −, margin_short_delta_21d −};
> `us-fundamental-accel` = {rev_accel_q +, gross_margin_delta_q +};
> `us-earnings-quality` = {accruals −};
> `us-value-neutral` = sector-neutralized value specs — lineage: the `us-value-quality` *idea*
> under a different **construction** (within-sector ranking), ruled a NEW family with a fresh
> budget because neutralization is not a re-weighting; this ruling is recorded here with the
> user's roadmap sign-off and must be restated verbatim in any pre-registration entry;
> `us-short-interest` = {short_ratio −, short_ratio_delta_63d −};
> `tw-crowding` = {max_ret_21d −, day_trade_ratio_21d −};
> `us-52wh` / `tw-52wh` = {pct_of_52w_high +} (17.14 — 52-week-high **anchoring**; ruled NEW
> families distinct from the closed return-continuation momentum families (entries 001/004/010)
> because the predictor is price vs a salient reference level, not past return; ruling recorded
> 2026-07-14 with the user's roadmap sign-off and must be restated in any pre-registration entry).
> A composite crossing any boundary is a new `…-composite-…` family (13.6 rule). `margin_delta_21d`
> stays in `tw-flows` (entry 006) and is deliberately **outside** these boundaries.

### 17.1 TW sell-side chip data + features (借券/融券 — the missing half of 11.3)  `[x]`

> **Outcome (2026-07-11):** both datasets confirmed live with the registered token — no need for
> the `TaiwanStockSecuritiesLending` fallback. **Unit trap found and documented:** margin
> short-sale balance (`ShortSaleTodayBalance`, from the already-fetched
> `TaiwanStockMarginPurchaseShortSale`) is **board-lot (張)** denominated, while SBL securities-
> lending balance (`SBLShortSalesCurrentDayBalance`, from the new `TaiwanDailyShortSaleBalances`)
> is **share**-denominated — confirmed by cross-checking both against `TaiwanStockPrice`'s daily
> `Trading_Volume` for 2330 (46 vs ~25M shares only makes sense as lots; ~11M vs ~25M is
> plausible as shares). `_normalize_margin` now also returns `margin_short_balance`;
> new `daily_lending()` + `_normalize_lending()` return `sbl_short_balance`. `_flow_features`
> gained `margin_short_delta_21d` (from step 1's already-fetched column, zero extra quota);
> new `_lending_features()` computes `sbl_short_delta_21d`/`_63d` (Δ-over-window × close ÷ median
> dollar volume — the `_net_buy` pattern applied to a level-delta, mirroring
> `foreign_hold_delta_63d`'s window semantics). Wired into `build_dataset_iter` (new
> `daily_lending=` callable) and `build_dataset.py`'s TW CLI branch. `panel_tw` (the certified
> substrate) untouched — new columns only reach research via 13.8's full-universe root. TODO left
> on 13.7 to add a `lending` dataset choice once that card lands. Tests: goldens (margin extended +
> new lending normalizer), known-answer + PIT-shift for both feature builders, a full-panel PIT
> test via the injected callable, and the "no stream ⇒ no columns" guard extended. Quality gates
> green; full suite 200 passed.

**Goal:** 11.3 wired the buy side (foreign/trust net buys); the informed **sell side** —
securities-lending short balances (借券賣出, used mostly by foreign institutions) and margin short
sales (融券) — was never fetched. Free-tier availability verified 2026-07-11 against the FinMind
docs (`TaiwanDailyShortSaleBalances`, `TaiwanStockSecuritiesLending` both listed free).
**Files:** `src/heimdall/data/providers/finmind.py`, `tests/test_finmind.py` (goldens),
`src/heimdall/research/dataset.py`, `tests/test_research_dataset.py`.

Steps:
1. Extend `_normalize_margin` to **also carry the margin short-sale balance** (融券餘額) from the
   already-fetched `TaiwanStockMarginPurchaseShortSale` — zero extra quota. Probe the raw field
   name live (candidates like `ShortSaleTodayBalance`); pin it with a golden test. Only **add** a
   column to `daily_chips` output — never rename/change existing golden-pinned columns.
2. New provider method `daily_lending(symbol, start, end)` fetching `TaiwanDailyShortSaleBalances`
   (free), normalized to `[date, sbl_short_balance]`. Probe the raw column names live and pin by
   golden test. If the dataset proves paid/empty in practice, probe `TaiwanStockSecuritiesLending`
   as fallback and **stop and ask** before proceeding.
3. `build_dataset_iter` gains an optional injected callable `daily_lending=` (the
   `monthly_revenue`/`daily_chips` precedent) and a `_lending_features()` builder (TW rows, **+1
   trading-day PIT shift exactly like `_flow_features` — test the shift**):
   - `sbl_short_delta_21d`, `sbl_short_delta_63d` — Δ(sbl_short_balance over the window) × close ÷
     21d median dollar volume (the `_net_buy` scaling pattern). Direction **−**.
   - `margin_short_delta_21d` — %-change of the margin short balance over 21 bars, computed in
     `_flow_features` from step 1's column. Direction **−** (weaker prior: retail shorting is
     partly squeeze fuel — record the ambiguity in the 17.2 log entry).
4. Feature-table doc lines; PIT leak + known-answer tests on hand-built frames (no network).

DoD: goldens + PIT-shift + known-answer tests; quality gates green. If 13.7 is already merged, add
`lending` to its `--datasets` choices in this PR; otherwise leave a one-line TODO on 13.7's card.
**Don't:** touch the certified `panel_tw` (panel features are frozen at first write — new columns
enter research only via the 13.8 full-universe root); don't research the family here (that's 17.2).

### 17.2 `tw-short-pressure` family — research card (user-gated)  `[ ]`

**Goal:** playbook §7 end-to-end for the sell side — the first TW family with a negative-
information prior, orthogonal by construction to revenue momentum (fundamental, certified) and to
006's buy-side flows (shown to be mostly EW premium).
**Files:** RESEARCH_LOG entry; spec JSON under `signals/specs/` only if a candidate advances.

Steps:
1. Preconditions: 17.1 merged; 13.7 crawled chips+lending for the full universe; 13.8 built the
   full-universe TW panel (`data/research/full/`) **including the 17.1 columns**. Research runs on
   that root, never the certified 140-name `panel_tw`.
2. Pre-stated candidates (no additions mid-session): `{sbl_short_delta_21d: −1}`,
   `{sbl_short_delta_63d: −1}`, `{margin_short_delta_21d: −1}`,
   `{sbl_short_delta_63d: −1, margin_short_delta_21d: −1}` equal-weight. ≤ 2 parameters each.
3. `evaluate` on DEV; advance to the **single** VAL look only candidates with dev IC-t ≥ 2 **and**
   dev selection-alpha NW-t ≥ 2 (the 13.1 bars). The lending stream may start later than prices —
   report the actual feature-coverage window; if dev has < 36 covered months, say so and treat VAL
   as the decisive in-sample read (the entry-005 precedent).
4. One RESEARCH_LOG entry (dev/val tables + look counts). Any VAL survivor: **stop and ask the
   user** before pre-registering (13.2 protocol).

DoD: log entry committed; zero OOS reads outside a user-authorized, pre-registered certify run.
**Don't:** mix this budget with `tw-flows`/`tw-revenue-momentum`; don't flip a pre-stated direction
after seeing dev numbers (that would be a new, unlisted candidate — stop).

### 17.3 EDGAR quarterly rows must be discrete 3-month durations (the YTD trap)  `[x]`

> **Outcome (2026-07-11):** `_normalize_companyfacts` now reads each fact's `start`; a new
> `_is_discrete_duration(period, start, end)` keeps duration facts only when their span matches
> the bucket (quarter 60–120d, annual 330–430d) and passes instant (no-`start`) facts through
> unchanged. Golden fixture extended with a `GrossProfit` tag isolated from the existing
> `Revenues` assertions: a Q2 3-month/6-month pair (only the 91d fact survives), a genuine
> 364d FY fact (survives), and an FY-tagged 92d "mirror trap" fact (dropped entirely — neither
> annual nor quarter). Existing tests untouched; full suite green (188 passed).

**Goal:** `_normalize_companyfacts` labels every non-FY fact `period="quarter"`, but 10-Q duration
facts (revenue, EPS, CFO…) include **year-to-date** values under the same tag and end date (a Q2
10-Q files both Apr–Jun and Jan–Jun revenue as `fp="Q2"` with the same `filed_at`); the dedup on
(metric, period, fiscal_end, filed_at) then keeps an arbitrary one. Every quarterly feature —
13.4's `sue` and 17.4 — is garbage until "quarter" means *one discrete quarter*. **This card
blocks 13.4 and 17.4.**
**Files:** `src/heimdall/data/providers/edgar.py`, `tests/test_edgar.py` (golden extension).

Steps:
1. In `_normalize_companyfacts`, read each fact's `start` (duration facts carry it; instant
   balance-sheet facts don't and pass through unchanged). Keep a `quarter` row only when
   `end − start` is 60–120 days; keep an `annual` duration row only when it is 330–430 days
   (guards the mirror trap of a Q4-discrete fact tagged FY). This is normalization — exactly the
   provider's job (the FinMind cumulative-cash-flow precedent) — so **no schema change**.
2. Extend the golden fixture with a real Q2-style pair (3-month + 6-month fact, same end/filed)
   asserting only the 3-month row survives, plus the FY-duration assertion.
3. Note for consumers, in the provider docstring: 10-Q cash-flow facts are often YTD-only, so
   discrete-quarter `cfo` will be sparse — no planned feature uses it; income-statement items
   (revenue, EPS, gross profit) do carry discrete quarters.

DoD: goldens green; existing annual-based tests untouched; gates green.
**Don't:** derive missing Q4-discrete values here (feature-builder decision, 17.4 step 4); don't
change `FUNDAMENTALS_COLUMNS`.

### 17.4 US fundamental-acceleration features (the certified idea, ported)  `[x]`

> **Outcome (2026-07-14):** `research.dataset._accel_features` adds `rev_accel_q` and
> `gross_margin_delta_q` (US rows), both keyed on `filed_at`. A shared `_discrete_quarters` helper
> returns PIT (filed ≤ *t*), deduped-per-fiscal-end discrete-quarter rows and **derives a missing
> fiscal Q4** as `FY − (Q1+Q2+Q3)` (only when the FY row and exactly the three prior discrete
> quarters exist, never over a real reported Q4), stamping the derived row's `filed_at` with the FY
> 10-K's date — so the residual is knowable only once the 10-K is filed. Seasonal alignment
> (`_seasonal_prior`, span in [320, 410] days nearest 365) matches each quarter to the same quarter a
> year earlier, robust to the US 3-discrete-quarters-a-year cadence (17.3) and to fiscal-end day
> drift. `rev_accel_q` = latest quarterly YoY revenue growth − mean of the prior 4 (NaN under 9 usable
> quarterly revenue obs or under 5 computable YoY growths); `gross_margin_delta_q` = (gross_profit ÷
> revenue) latest-quarter minus seasonal-prior, in **pp** (NaN when `GrossProfit` absent — never
> revenue − COGS). Gated on the same `quarterly_fundamentals` US switch as 13.4/13.5. Tests:
> seasonal-alignment known-answer + PIT + <9-obs guard for `rev_accel_q`; Q4-derivation arithmetic +
> derived-`filed_at` + real-Q4-not-overwritten + PIT for `_discrete_quarters`; gross-margin-delta
> known-answer + missing-GrossProfit; panel-wiring. **Panel extension is consolidated into card 17.7**
> (the one `panel_us` rebuild). Gates green.

**Goal:** the program's only certified signal is TW monthly-revenue **acceleration** (entry 009).
Port the economics to the US on free data: quarterly revenue acceleration + gross-margin trend
from EDGAR 10-Qs — coarser cadence, same idea (fundamentals improving faster than before).
**Files:** `src/heimdall/research/dataset.py`, `tests/test_research_dataset.py`.

Steps (US rows; **needs 17.3**; the quarterly-rows fetch is 13.4's machinery — if 13.4 hasn't
landed yet, add the `get_fundamentals(sym, "all", "quarter")` stream here in the same style):
1. Builder-internal `rev_yoy_q` series: for each quarterly `revenue` row usable at month-end *t*
   (`filed_at ≤ t`), `rev_q / rev_{q−4} − 1`, where the q−4 row is the one whose `fiscal_end` is
   ~365 days earlier (tolerate ±45d for fiscal-year shifts); NaN when no match.
2. Feature `rev_accel_q` = latest `rev_yoy_q` − mean of the prior **4** `rev_yoy_q` values; NaN if
   fewer than 9 usable quarterly revenue observations. Direction **+**.
3. Feature `gross_margin_delta_q` = (gross_profit ÷ revenue, latest quarter) − (same, q−4), in
   percentage points, both legs discrete-quarter rows with `filed_at ≤ t`. NaN when `GrossProfit`
   is absent — **report dev-window coverage in the 17.8 log entry**; never synthesize from
   revenue − COGS (13.5 precedent). Direction **+**.
4. Q4 gaps: when a fiscal Q4 discrete revenue row is missing but FY and Q1–Q3 of the same fiscal
   year all exist, derive Q4 = FY − (Q1+Q2+Q3) with `filed_at` = the FY row's (PIT: knowable only
   once the 10-K is filed). Unit-test the arithmetic and the derived `filed_at`. Derivation lives
   in the feature builder — providers stay as-reported.
5. Feature-table doc lines; the mandatory **PIT leak test** (a quarter filed after month-end *t*
   must not move row *t*) + known-answer tests for the q−4 alignment and the accel window.

DoD: tests as above; gates green. Panel extension happens in 17.7, not here.
**Don't:** key anything off `fiscal_end`; don't mix annual rows into these features; don't touch
providers beyond what 17.3 landed.

### 17.5 Sector-neutral scoring option (needs 14.1)  `[x]`

> **Outcome (2026-07-14):** `SignalSpec` gains `neutralize: str = ""` (validator: `""` or
> `"sector"`). **Hash stability held:** `canonical_hash()` pops the field when it equals the default,
> so every pre-17.5 hash is byte-identical — a new registry-wide regression test
> (`test_registry_spec_hashes_match_on_disk`) reloads all three committed specs (certified
> `tw-revenue-momentum` + both `us-fcf-yield`) and confirms each still hashes to its recorded
> `spec_hash`, pinning them without a second hardcode. `score()` grows a `neutralize=="sector"` branch:
> each feature is winsorized-z-scored *within* its `sector` group via a new `_sector_zscore` helper;
> groups with < 5 members score NaN (excluded, never a degenerate 1–2-name z), and a missing `sector`
> column raises `KeyError` (same posture as a missing feature). The default path is byte-for-byte
> unchanged (an explicit `assert_series_equal` equivalence test guards it). Panel wiring:
> `build_dataset_iter` gains a `sector_map` param that stamps a **static current-map** `sector` on
> every row ("Unknown" when absent) — flagged in the docstring as an accepted, *not* point-in-time
> approximation (sector is a grouping label, not a return-bearing feature); the build CLI passes
> `us_sector_map(symbols)` / `tw_sector_map()`. `today.py` requires `sector` only when the spec
> neutralizes, and its displayed per-feature z respects neutralization so the breakdown still
> reconciles with the score. Tests: validator, hash-stability, registry-wide regression, neutralized
> known-answer (raw ranks a sector wholesale, neutral picks each sector's leaders), small-group +
> missing-column, equivalence, panel-wiring. Gates green; research deferred to 17.8. **panel_us gains
> the `sector` column via 17.7's rebuild.**

**Goal:** the recorded US failure mode (entries 011/012) is that a raw value book is a structural
short on whatever mega-cap theme leads the index. Within-sector ranking removes the sector bet and
keeps the within-sector selection — the standard practitioner fix, as one clean mechanism.
**Files:** `src/heimdall/research/spec.py`, `src/heimdall/research/dataset.py`,
`src/heimdall/research/today.py`, `tests/test_research_spec.py`, `tests/test_research_dataset.py`.

Steps:
1. `SignalSpec` gains `neutralize: str = ""` (validator: `""` or `"sector"`). **Hash stability is
   load-bearing:** in `canonical_hash()`, pop the field from the payload when it equals the
   default, so every existing spec hash is unchanged. Add a registry-wide regression test: for
   every entry in `signals/registry.json`, `load_spec(spec_path).canonical_hash() == spec_hash`
   (this pins the certified `tw-revenue-momentum` hash without hardcoding it twice).
2. `score()`: when `neutralize == "sector"`, compute each feature's winsorized z within
   (eligible pool × `sector` group); groups with < 5 members score NaN (excluded, never a
   degenerate z-score). Missing `sector` column ⇒ `KeyError` (same posture as a missing feature).
   Known-answer test: two sectors with opposite feature levels — raw scoring ranks one sector
   wholesale; neutralized scoring picks each sector's internal leaders.
3. Panel wiring: `build_dataset_iter` merges 14.1's persisted symbol→sector map onto every row
   (static column; `"Unknown"` when missing). **Accepted approximation — state it in the builder
   docstring and in every log entry that uses `neutralize`:** the *current* sector map is applied
   to history; sector is a grouping label, not a return-bearing feature, and reclassifications
   are rare — but it is not point-in-time.
4. `today.py`: require `sector` in the snapshot columns only when the spec neutralizes.
5. Equivalence test: with `neutralize=""` the new `score()` reproduces the old scores bit-for-bit.

DoD: hash-regression + neutralized known-answer + Unknown/small-group + equivalence tests; gates
green.
**Don't:** neutralize by default; don't invent a sector taxonomy (14.1 owns it); don't research
here (17.8 owns `us-value-neutral`).

### 17.6 US earnings-quality feature (accruals)  `[ ]`

**Goal:** the Sloan (1996) accruals anomaly — earnings not backed by cash flow revert. The one
documented free US axis untouched by Phases 10/13 (13.5 covers issuance/asset-growth/
profitability; this is earnings *quality*).
**Files:** `src/heimdall/research/dataset.py`, `tests/test_research_dataset.py`.

Steps (annual EDGAR rows, `filed_at`-keyed, all three metrics already normalized):
1. `accruals` = (net_income − cfo) ÷ assets, all from the latest annual row set with
   `filed_at ≤ t`; the three metrics must share one `fiscal_end` (mismatched years ⇒ NaN).
   Direction **−**.
2. Feature-table doc line; PIT leak test; known-answer test incl. the mismatched-year NaN.

DoD: tests green; gates green. Panel extension happens in 17.7.
**Don't:** decompose working-capital line items — the NI−CFO form is the parameter-free version;
finer decompositions need tags with thin coverage.

### 17.7 `panel_us` v2 — one rebuild carrying every new US column  `[ ]`

**Goal:** panel feature values are frozen at first write (the dataset.py resume invariant), so new
columns require a **rebuild**, not a resume. Do it once for all US features (13.3 insider if
merged, 13.4 sue/earn_gap, 13.5 issuance set, 17.4 acceleration, 17.6 accruals, 17.11
short-interest, 17.5/14.1 sector, 17.12's `max_ret_21d`, 17.14's `pct_of_52w_high`), with a
mechanical reproduction gate.
**Files:** none new (7.3 CLI; add a `--rebuild` flag if it lacks one — archive the old parquet as
`panel_us.v1.parquet` rather than deleting, per data-discipline); a RESEARCH_LOG "panel_us v2"
note; tick the deferred extend-panel steps of 13.4/13.5 in the same PR with a "consolidated into
17.7" note.

Steps:
1. Preconditions: 17.3, 17.4, 17.6 merged; 13.4/13.5 merged; 14.1+17.5 merged if sector rides
   this rebuild (preferred — one rebuild, not two). 13.3 rides it if already merged; otherwise a
   later second rebuild must re-run this card's reproduction gate (cite this card).
2. Governance check, printed and logged: **no US signal is `certified` in the registry** (rejected
   reports are immutable JSON, unaffected) — rebuilding `panel_us` in place is sanctioned only
   under that condition; otherwise stop and ask.
3. Rebuild 2010-01→present. EDGAR + prices are local caches — hours of compute, zero quota; run
   detached (the 13.7 operational mould).
4. **Reproduction gate (mandatory):** `evaluate` `{fcf_yield}` dev+val on the new panel must
   reproduce entry 011 to ~2 dp (dev IC +0.022 t +2.87, alpha +2.99% t +3.92; val IC +0.058
   t +2.71, alpha +7.89% t +2.98). Material drift ⇒ stop, diagnose (17.3's duration filter must
   not have touched annual rows), report before any research proceeds.
5. Log note: columns added; dev-window coverage per new feature (% of eligible rows non-NaN); the
   reproduction table.

DoD: rebuilt panel + meta; reproduction table committed in the log note; gates green.
**Don't:** touch `panel_tw` or `data/research/full/`; don't start 17.8 in the same PR.

### 17.8 US new-family research: acceleration · earnings-quality · neutral-value (user-gated)  `[ ]`

**Goal:** playbook §7 over the 17.x US features on the 17.7 panel — plus the sector-neutral
re-read of the one US signal with proven OOS ranking information.
**Files:** RESEARCH_LOG entries (one per family); spec JSONs only for advancers.

Steps:
1. Pre-stated candidates (nothing added mid-session):
   - `us-fundamental-accel`: `{rev_accel_q}`, `{gross_margin_delta_q}`, equal composite.
   - `us-earnings-quality`: `{accruals: −1}`.
   - `us-value-neutral`: `{fcf_yield}` with `neutralize="sector"` — restate the phase-intro
     family ruling and the sector-map approximation caveat in the log entry.
   - (13.6's families run under their own card, not here.)
2. DEV for all; the **single** VAL look only for dev IC-t ≥ 2 **and** dev alpha-t ≥ 2; full
   look-count disclosure per family.
3. Honest prior for any value-flavored candidate must name the 2023–25 mega-cap regime explicitly.
   Any VAL survivor: **stop and ask the user** (13.2 protocol) before pre-registering.

DoD: one committed log entry per family; zero unauthorized OOS reads. Honest closures complete
the card.
**Don't:** cross family budgets; don't re-run raw `{fcf_yield}` (the `us-value-quality` remaining
attempts are reserved for genuinely new data — and neutral-value is a different family by the
recorded ruling).

### 17.9 MOPS monthly-revenue announcement-date validation (limitation-5 debt)  `[~]` in progress

> **Status (2026-07-11):** step 1 (probe) done — (a)/(b)/(c) all live-probed and disqualified,
> verbatim findings in RESEARCH_LOG 013 and NORTH_STAR limitation 5. Step 3's mechanism is built
> and unit-tested (`heimdall.research.mops_probe`), but **not yet run**: it needs a real 12-day
> calendar window, the next being 2026-08-01 → 2026-08-12. Checkbox stays open — the DoD requires
> measured numbers, which don't exist until that window closes. **Next action (Aug 2026): run
> `uv run python -m heimdall.research.mops_probe --record` once daily on days 1–12, then
> `--summarize 2026-07`; update this card + NORTH_STAR limitation 5 + a RESEARCH_LOG follow-up
> with the result. The ≤2%-late-filer stop-and-ask guard is already wired into `--summarize`.**

**Goal:** NORTH_STAR accepted limitation 5 promised per-filing validation "if a TW family reaches
pre-registration" — `tw-revenue-momentum` is **certified**, so the debt is due. Validate the
`month_end + 10d` statutory `filed_at` empirically; the certified signal's PIT base either gains
evidence or an honest correction.
**Files:** `docs/NORTH_STAR.md` (limitation 5 update), a RESEARCH_LOG note; provider wiring only
if a real historical dataset exists.

Steps:
1. Probe in order, recording findings verbatim: (a) FinMind datalist for any revenue
   announcement-date field; (b) MOPS (mops.twse.com.tw) monthly-revenue pages for a queryable
   per-company announcement date; (c) TWSE OpenAPI equivalents.
2. If a historical per-filing source exists: sample ≥ 30 (symbol, month) pairs across market-cap
   sizes; report the actual-date distribution vs the statutory 10th + the late-filer share.
3. If none exists: live-observation fallback — during days 1–12 of the next calendar month,
   record daily when each of ~30 tracked names' latest revenue first appears (one FinMind/MOPS
   check per day; trivial quota); report first-appearance vs the 10th.
4. Update limitation 5 with the measured bound. **If late filings exceed 2% of the sample, stop
   and ask the user** — a conservative `filed_at` bump would be a §4-rule-4-grade change
   (re-certification of the TW signal).

DoD: docs updated with numbers + method; log note committed.
**Don't:** scrape MOPS beyond polite page requests; never adjust `filed_at` silently.

### 17.10 Rank-buffer membership (turnover hysteresis)  `[ ]`

**Goal:** enter at rank ≤ top_n, hold until rank > exit_rank — the standard churn reducer. At
G4's 20 bps/side, cutting one-way turnover ~30–50% adds material net CAGR to any future signal
and widens G6 headroom. A per-spec mechanism (certified through the normal pipeline), not a gate
change.
**Files:** `src/heimdall/research/spec.py`, `certify.py`, `evaluate.py`, `monitor.py`,
`today.py`, test mirrors.

Steps:
1. `SignalSpec.exit_rank: int | None = None` (validator: `> top_n` when set). Canonical-hash rule
   exactly as 17.5 step 1 (pop when default; the registry-wide hash-regression test covers it).
2. Pure helper in spec.py —
   `buffered_members(ranked: list[str], prev: set[str], top_n: int, exit_rank: int) -> set[str]`:
   keep = prev members whose current rank ≤ exit_rank; fill to top_n with the best-ranked
   non-kept names. Known-answer tests incl. the fewer-than-top_n cross-section edge.
3. Thread stateful membership through the monthly loops of `certify()` and `evaluate()` (both
   currently `ranked.head(spec.top_n)`): with `exit_rank` set, month 1 = plain top-N, later
   months = `buffered_members`. `_book_minus_universe` gains an optional
   `members: set[str] | None` (book = member rows) so G3/G4/G6 all price the *held* book;
   `monitor.cohort_alpha` replays the same stateful sequence from the OOS start (deterministic).
4. `today.py`: previous membership = the signal's latest 16.1 ledger freeze; absent ⇒ plain top-N
   with an on-page note. (16.1 is therefore a precondition for **certifying** a buffered spec;
   dev/val research needs no ledger.)
5. Tests: buffered turnover < unbuffered on a synthetic churny panel; `exit_rank=None` reproduces
   current results bit-for-bit; a certify known-answer where the buffer flips G6.

DoD: all mirrors green; hash regression green; gates green.
**Don't:** count `exit_rank` toward G5's parameter cap (structural, like `top_n`) — but **state
that interpretation in any log entry using it**; don't retrofit the certified TW spec (a buffered
variant is a new version through the full pipeline, family budget and all).

### 17.11 US short-interest provider + features (FINRA, free)  `[ ]`

**Goal:** the best-documented free negative axis for US stocks: high short interest / days-to-
cover predicts underperformance. FINRA publishes consolidated bi-monthly equity short interest
(text archives ≈ 2014→; query API at `api.finra.org`).
**Files:** new `src/heimdall/data/providers/finra.py`, `tests/test_finra.py` (golden from a saved
payload), `src/heimdall/research/dataset.py` features + tests, `docs/DATA_SOURCES.md` one-liner.

Steps:
1. **Probe first, record in the PR:** coverage of exchange-listed names (not only OTC), history
   depth, and the publication calendar (settlement on the 15th/EOM; dissemination ~7–9 business
   days later — FINRA publishes the exact schedule). Listed coverage or per-cycle publication
   dates unavailable free ⇒ stop and ask.
2. Provider method `short_interest(symbol, start, end)` → canonical
   `[symbol, settlement_date, available_at, short_shares, provider, fetched_at]`;
   `available_at` from the official calendar, **never** the settlement date. Rate limiter;
   delta-only per cycle; keep raw payloads per data-discipline.
3. Panel features (US rows; a row at month-end *t* reads cycles with `available_at ≤ t` — **PIT
   leak test on a cycle published after t**): `short_ratio` = short_shares ÷ 21d median share
   volume (days-to-cover on our own volume); `short_ratio_delta_63d`. Direction **−** both.
4. Note for the eventual log entry: features start ~2014 ⇒ dev effectively 2014–2019 (~72
   months); rows before coverage score NaN and drop out automatically.

DoD: goldens + PIT + known-answer tests; gates green. Research = `us-short-interest` via 17.13.
**Don't:** land after 17.7 without re-running 17.7's reproduction gate on the follow-up rebuild
(cite it); don't label this "institutional flow" anywhere (12.4's reality note stands).

### 17.12 TW crowding features (lottery/speculation avoidance)  `[ ]`

**Goal:** the retail-crowding axis on TW: avoid names whose recent trading is speculative froth —
day-trading share and lottery-like payoffs (the MAX effect), both documented negative predictors.
**Files:** `src/heimdall/factors/metrics.py` (one price-only field),
`src/heimdall/research/dataset.py`, `tests/` mirrors.

Steps:
1. `max_ret_21d` in `_technicals` — max single-day `adj_close` pct-change over the last 21 bars
   (NaN under 21 bars). Direction **−** (Bali–Cakici–Whitelaw lottery effect). Zero network; the
   column reaches panels via the next rebuild (17.7 for US, 13.8 for TW — sequence this card
   before both).
2. Day-trading ratio: probe FinMind's datalist for a day-trading dataset (not on the chip docs
   page — check other sections); fallback TWSE OpenAPI daily day-trading statistics. Wire
   whichever serves the whole market free: `day_trade_ratio_21d` = mean(day-traded shares ÷ total
   shares traded) over 21 sessions, **+1 trading-day PIT shift**. Direction **−**. Neither source
   workable free ⇒ ship `max_ret_21d` alone and record the probe outcome on this card.
3. Feature-table doc lines; PIT + known-answer tests.

DoD: tests green; gates green. Research = `tw-crowding` via 17.13 on the 13.8 root.
**Don't:** invent a second cache format; no scraping beyond official/open endpoints.

### 17.13 Research: `us-short-interest` · `tw-crowding` (user-gated)  `[ ]`

Same protocol as 17.8 (DEV → single VAL look at the 13.1 bars; one log entry per family; full
look-count disclosure; **stop and ask the user** before any pre-registration; honest closure
completes the card). Pre-stated candidates:
- `us-short-interest` (needs 17.11 + its panel rebuild): `{short_ratio: −1}`,
  `{short_ratio_delta_63d: −1}`, equal composite.
- `tw-crowding` (needs 17.12 + the 13.8 root): `{max_ret_21d: −1}`, `{day_trade_ratio_21d: −1}`
  (if shipped), equal composite of the two.
**Don't:** blend across families; no candidates beyond this list without a new card.

### 17.14 52-week-high proximity feature (George–Hwang anchoring)  `[ ]`

**Goal:** nearness to the 52-week high predicts continued outperformance (George & Hwang 2004) —
underreaction near a salient reference price. Price-only, both markets in one stroke, 1 parameter,
zero quota. This is the **anchoring** mechanism, not return continuation — the closed momentum
families' verdicts (entries 001/004/010) don't carry over; see the phase-intro family ruling.
**Files:** `src/heimdall/factors/metrics.py`, `tests/test_snapshot.py`,
`src/heimdall/research/dataset.py` (feature-table doc line only).

Steps:
1. `pct_of_52w_high` in `_technicals` — `adj_close[-1] ÷ max(adj_close over the last 252 bars)`
   (current bar included, so the value sits in (0, 1], 1.0 = at the high); NaN under 252 bars
   (the `ret_12_1` rule). Direction **+**. No PIT shift — closes through the row date are
   knowable at that close, like every `_technicals` field.
2. Feature-table doc line (direction + one-line rationale), per playbook §7.
3. Known-answer tests in `tests/test_snapshot.py`: a hand-built path with a known interior peak
   (exact ratio), a monotonically rising series (exactly 1.0), NaN under 252 bars.
4. The column reaches panels via the next rebuild — **sequence this card before 17.7 and 13.8**
   (the 17.12 rule); don't trigger either rebuild here.

Research = its own future `us-52wh`/`tw-52wh` card under the 17.13 protocol (the 13.9 precedent:
feature card ≠ research card). That log entry must additionally report the feature's dev-window
rank correlation with `ret_12_1` and `ret_6m` — descriptive disclosure, not a gate: 52wh is
mechanically momentum-adjacent, and the reader must see how much information is genuinely new.

DoD: known-answer + NaN tests green; doc line present; quality gates green.
**Don't:** research here; no variants (days-since-high, multi-window highs — one feature, one
parameter); don't touch providers; don't trigger a panel rebuild.

### 17.B Backlog — promote to a full card with the user before executing

- **TW insider (董監申報轉讓)** — the Form-4 analog via MOPS; wait for 17.9's findings on MOPS
  access patterns. Family `tw-insider`.
- **Piotroski F-Score composite column** — 9 binary checks as one panel feature (1 parameter);
  candidate use of `us-value-quality`'s 2 remaining attempts (genuinely new data columns) or an
  input to a `us-composite-…` family — needs a user ruling on which budget it bills.
- **Survivorship-lite US panel** — a committed historical S&P 500/1500 membership CSV (public
  datasets exist) as an alternative universe root; would sharpen the `current_universe
  (optimistic)` stamp into a measured bound. TW analog: TWSE delisting lists.
- **TW quarterly gross-margin trend** — FinMind quarterly statements, the 17.4 analog (mind the
  standalone-quarterly income-statement cadence already handled in the provider).

---

**Sequencing:** 7.1 → 7.2 → 7.3 → 8.1 → 8.2 → 8.3 → 9.1 → 9.2 → 10.x → 11.x → 12.x.
The first "north-star moment" is completing 9.2 + one certified 10.x signal. ✅ Reached
2026-07-09 via the TW route (`tw-revenue-momentum v1`).

**Phases 13–17 sequencing (updated 2026-07-11, Phase-17 integration — supersedes the same-day
13–16 plan)** — waves override top-to-bottom; within a wave, any order. The organizing rule:
**feature cards land before the one big panel build of their market** (13.8 for TW,
17.7 for US), so each panel is built once with every column.

- **Wave 1 (independent; 13.1 ✅ / 13.2 ✅ already done):** 15.1 (=11.5) · 13.7 (start early —
  background across quota windows; gains `lending` once 17.1 lands) · 17.3 · 17.1 · 17.9 ·
  16.4 (added 2026-07-14 — **run ASAP**: every unscheduled week of TDCC history is unrecoverable).
- **Wave 2 (features + pages):** 14.1 → 14.2 · 15.2 · 13.3 (=12.4) · 13.4 → 17.4 · 13.5 ·
  17.6 · 17.5 (needs 14.1) · 17.12 · 17.11 · 17.14.
- **Wave 3 (one build per market):** 13.8 (needs 13.7; **must include the 17.1/17.12/17.14 TW
  columns — land those first**) · 17.7 (one `panel_us` rebuild carrying 13.3/13.4/13.5/17.4/
  17.6/17.11/17.12/17.14 + sector; a card that slips past it forces a second rebuild that re-runs
  17.7's reproduction gate).
- **Wave 4 (research; every vault touch user-gated):** 13.6 · 17.8 · 17.2 · 17.13 · 13.9 → 15.3.
- **Wave 5 (trust & mechanisms):** 16.1 → 16.2 → 16.3 · 17.10 (needs 16.1) · 14.3.
- 12.3 stays unscheduled until the user asks. Every vault touch (13.6, 13.8, 17.2, 17.8, 17.13)
  stops for a recorded user go/no-go first. A REJECTED verdict, honestly logged, completes any
  research card. When a **second** signal certifies, promote the 16.B multi-signal combiner to a
  full card with the user.
