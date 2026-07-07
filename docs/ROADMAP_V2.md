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

### 8.2 Certify harness + gates  `[ ]`

**Goal:** the referee. **Files:** `src/heimdall/research/gates.py` (extend),
`src/heimdall/research/certify.py`, `tests/test_research_certify.py`.

Steps:
1. `gates.py`: G1–G6 thresholds exactly as playbook §5, plus `nw_tstat`/`nw_ci95` copied verbatim
   from the playbook. Add `test_gates_mirror_playbook` asserting the literal numbers (duplication
   is the tripwire: changing either place alone fails CI).
2. `certify(spec, panel, benchmark_adj) -> CertReport` — filter to OOS window (start `2023-01-01`,
   end = last month with non-NaN `fwd_6m`), compute G1–G6 (G4 via `backtest.portfolio` with
   `commission_bps=20`, documented as the all-in per-side cost; G6's 40–60% branch re-runs at 40),
   verdict = all-pass. Report dataclass: every gate's value, threshold, pass flag; cohort series;
   window; the survivorship stamp; spec hash.
3. CLI `uv run python -m heimdall.research.certify signals/specs/<f>.json --log-entry <id>`:
   parse `docs/RESEARCH_LOG.md` for `## <id> —` containing the spec's sha256 → refuse if absent
   (message: "pre-register first, see playbook §4"); refuse if family attempts ≥ 3; write report
   JSON to `signals/certifications/{name}_v{version}.json`; registry → certified/rejected.

DoD: gate math known-answer on tiny hand-computed panels (esp. NW t and turnover); log-entry
enforcement (absent id / wrong hash / attempts=3 all refuse); report file written and immutable
(second run for same entry refuses). **Don't:** let any code path evaluate OOS without an entry.

### 8.3 Canary tests (the harness must have power)  `[ ]`

**Goal:** prove certification rejects noise and would catch leakage-strength signals.
**Files:** `tests/test_research_canary.py` (+ a small synthetic-panel builder in the test).

Steps: build a synthetic 36-month panel (~200 symbols) where `oracle = fwd_1m_rel` rank exactly
and `noise` is seeded random. Assert: noise spec **fails** certification; oracle spec **passes**
G1–G3 overwhelmingly (skip G4 if the synthetic panel lacks price series — document that). Mark the
oracle clearly as test-only; registry code must refuse any spec whose feature list contains a
column starting with `fwd_` (add that guard in 8.1's `score` if not present — belt and braces).

DoD: both canaries in the normal suite, < 5 s runtime, no network.

## Phase 9 — Today's Picks

### 9.1 Picks engine  `[ ]`

**Goal:** certified spec + fresh snapshot → today's ranked cohort. **Files:**
`src/heimdall/research/today.py`, `tests/test_research_today.py`.

Steps: `todays_picks(spec, snapshot) -> pd.DataFrame` — eligibility filter (same gates constants),
spec score, top-N, with per-feature z-scores as columns (so the UI can show *why* each name
ranks); `freshness(snapshot) -> int` returning business-day staleness of `as_of`.

DoD: known-answer ranking on a crafted snapshot; ineligible names excluded with reasons; staleness
math tested. **Don't:** read the registry here (pure function); the page composes.

### 9.2 Today's Picks page  `[ ]`

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

### 10.1 US momentum family (`ret_12_1`, optionally `vol_63d` tilt)  `[ ]`
Hypothesis to register: skip-month momentum ranks 6-month relative winners in the eligible US
universe. Start pure single-feature (1 parameter); a low-vol tilt is v2 *only if* v1 fails on a
pre-stated reason.

### 10.2 US quality/profitability family (`roic`, `fcf_margin`, `operating_margin`)  `[ ]`
Equal weights first (3 parameters). Watch G1 — quality alone is often weak standalone; expect a
possible honest rejection.

### 10.3 US value×quality family (`fcf_yield`, `ev_ebitda`(−), `roic`)  `[ ]`
The composite most literature supports at 6m horizons. Negative weight = lower-is-better.

## Phase 11 — Taiwan enablement

### 11.1 Real TW filing dates  `[ ]`
Probe FinMind for a financial-statement announcement-date dataset (check API docs live; e.g. a
`*FinancialStatementsDate`-like dataset). If found: wire into `filed_at` (golden-test with saved
JSON). If not: keep +90d but validate against ≥ 10 known filings (document the error bound in
`docs/NORTH_STAR.md` accepted limitations). Monthly revenue: set `filed_at = month_end + 10 days`
(statutory deadline) — implement regardless.

### 11.2 TW monthly-revenue momentum feature  `[ ]`
Panel-only feature (TW rows): `rev_mom_yoy` (latest month YoY) and `rev_mom_accel` (3m mean YoY −
prior 3m mean YoY), point-in-time per 11.1's rule. PIT leak test mandatory. This is Taiwan's
signature free signal — treat carefully.

### 11.3 TW chip/flow features (法人買賣超・外資持股・融資融券)  `[ ]`

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

### 11.4 Certify TW families  `[ ]`
Build `panel_tw` (7.3 CLI), then run 10.x-style cards for: monthly-revenue momentum, price
momentum, flows. Benchmark `0050.TW`. Note in the log that TW history via FinMind may start later
than 2010 — splits shrink accordingly (validation/OOS boundaries stay fixed).

### 11.5 TW Chips (籌碼) dashboard — descriptive lens, NOT a signal  `[ ]`
**Goal:** the daily "who is buying" view, kept firmly outside certification. **Files:**
`src/heimdall/ui/chips_page.py` (nav group "Analyst lenses"), `i18n.py`, AppTest smoke.
Per symbol: cumulative 外資/投信 net-buy vs price, foreign holding %, margin balance; market-wide
top-10 net buy/sell lists (bulk per-date query). Requires only 11.3 step 1, so it may be built
right after it. The page must carry a fixed caption — *descriptive chip data, not a certified
signal; Today's Picks ignores this page* — in both languages. **Don't:** render anything that
looks like a recommendation ranking.

## Phase 12 — Operations & evolution

### 12.1 Scheduled refresh  `[ ]`
A `launchd` plist template + `docs/OPERATIONS.md` (weekly: snapshot refresh + panel extension via
the existing resumable CLIs), or extend the Build-data page with a one-click "refresh all
certified inputs". Staleness banners already exist (9.2).

### 12.2 Drift monitoring  `[ ]`
`research/monitor.py` + a monitoring section on Today's Picks: each month append the newest
realized cohort beat rate to the cert's monitoring series; trailing-12 NW CI upper < 0.5 ⇒ auto
`under_review` + banner. Tests with synthetic drift.

### 12.3 Paid-data decision memo  `[ ]`
Only after ≥ 2 Phase-10 families are certified-or-rejected: write `docs/DATA_DECISION.md` — what
free signals achieved, what FMP estimates/revisions would add, cost vs measured gap. A memo, not
an integration; the user decides.

### 12.4 US insider-transactions feature (Form 4) — the honest US "smart money"  `[ ]`
**Reality note (binding):** the US has **no public daily institutional flow**. Retail-app "money
flow" for US stocks is a price/volume proxy (tick-rule buy/sell imbalance) — it may be added as a
*technical* feature but must never be labelled institutional flow. 13F is quarterly with a 45-day
lag (cloning evidence weak). The credible free option is SEC **Form 4** insider transactions
(EDGAR, ~2-business-day lag): provider + panel feature `insider_net_buy_90d` (officer/director
open-market buys − sells ÷ market cap) with a cluster-buy flag; golden-tested from saved filings;
keyed on the filing timestamp (point-in-time). Prior: moderate, event-like, works at long
horizons. Pre-register before any OOS touch, as always.

---

**Sequencing:** 7.1 → 7.2 → 7.3 → 8.1 → 8.2 → 8.3 → 9.1 → 9.2 → 10.x → 11.x → 12.x.
The first "north-star moment" is completing 9.2 + one certified 10.x signal.
