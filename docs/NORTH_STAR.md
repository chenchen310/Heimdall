# North Star — objective, certified stock selection

> **Read this first, every session.** It defines what Heimdall is being built toward, the exact
> success definition, and where the gaps are. The *how* lives in `docs/RESEARCH_PLAYBOOK.md`
> (process + statistical gates), the *what next* in `docs/ROADMAP_V2.md` (one-PR task cards), and
> the hard law in `.claude/rules/signal-certification.md`.

## The goal

**The web app itself surfaces stocks with an objectively validated high probability of rising —
no human judgment and no LLM anywhere in the certified computation.**

Concretely, the end state is a **Today's Picks** page that:

1. shows a ranked list of at most `top_n` stocks produced by a **certified signal** (a frozen,
   versioned recipe that passed the statistical gates on data it was never tuned on);
2. shows the **evidence** beside the picks: the certified out-of-sample beat rate with its
   confidence interval, IC, quantile spread, certification date, and data freshness;
3. shows **nothing** when no signal is certified — an honest empty state, never an
   unvalidated ranking dressed up as a standard.

## Frozen definitions (user decisions, 2026-07-03)

| Question | Decision |
| --- | --- |
| What does "rise" mean? | **Benchmark-relative**: a pick works if its forward **6-month** total return beats the market benchmark (secondary horizon: 3-month). US benchmark `SPY.US`; Taiwan `0050.TW`. |
| Usage pattern | **Monthly rebalance, hold top 10–20** (default `top_n = 20`). |
| Market order | **US first** (real EDGAR filing dates → trustworthy point-in-time), **Taiwan second** (adds monthly-revenue momentum + institutional-flow factors, and must first fix its synthetic `filed_at`). |
| Data budget | **Free sources first.** Certify what free data supports; paid data (FMP estimates/revisions) becomes a data-backed decision afterwards, never a prerequisite. |

The displayed "probability" is therefore: *the certified out-of-sample **portfolio-cohort beat
rate*** — across monthly rebalance cohorts, the fraction whose equal-weight top-N **book** beats the
benchmark over the following 6 months — with a Newey–West 95% confidence interval and the cohort
count. Certification additionally requires **selection skill** (gate G3: the book must beat an
equal-weight eligible-universe book, so the equal-weight/breadth premium alone cannot certify).
Nothing else may be presented as a probability. (Metric redefined 2026-07-08 — RESEARCH_LOG 008 /
ROADMAP 12.5 — after the old individual-pick beat rate proved biased below 50% by
cap-weight-benchmark concentration; see the playbook §5 rationale.)

## Program amendment — US Strategy Factory (user decisions, 2026-09-30)

The user restated the goal as: *「把它打造成一個專業的量化交易選股平台，能夠自動制定交易策略，並有回測數據。（先做在美股上）」*
— a professional quant stock-selection platform that **formulates strategies automatically** and
shows **backtest evidence**, US first. This **extends** the goal above; it does not replace it.

**Why the amendment was needed (state of play on 2026-09-30).** Across RESEARCH_LOG 001–018, 8 US
families and ~30 development evaluations produced **zero** certified US signals (two vault touches,
both `us-fcf-yield`, both rejected). Every candidate was hand-written by a session, 1–8 per session,
in one narrow shape (linear composite → EW top-20 → monthly → full VTI universe). The platform itself
could not search, and its backtests were split across three partial tools. The recurring finding —
real ranking IC without selection skill above the equal-weight universe — is a property of that
narrow shape as much as of the features.

**Decisions (AskUserQuestion answers, recorded verbatim):**

| Question | Answer | Meaning |
| --- | --- | --- |
| Which strategies may reach a picking screen? | 「雙層制 (Recommended)」 | **Certified** tier = unchanged (vault gates → Today's Picks). New **incubating** tier = factory finalists that pass the playbook §12 over-fitting gates are forward-paper-tracked and shown **only** on the Strategy Lab page, labeled 「未認證・孵化中」. Never on Today's Picks. |
| Data budget | 「免費優先＋付費評估並行 (Recommended)」 | Build the factory on free data; the 12.3 paid-data memo is **now scheduled** (ROADMAP 18.11). No spend without a separate user decision. |
| Strategy types the factory generates | 「多因子選股, 大盤擇時濾網, 投組建構變化, 個股技術進出場」 | Multi-factor selection; a market-regime overlay; construction variants (weighting, sector cap, rank buffer); single-stock technical entry/exit rules — the last is **research-only** (the < 1-month horizon non-goal below stands, so technical rules are never tiered). |
| Universe | 「大型股＋全市場都搜 (Recommended)」 | Universe becomes a search dimension: `us_large` (point-in-time top 500 eligible names by market cap) and `us_all` (today's eligible VTI set). |

**What changes:** candidate generation moves from sessions to the platform (systematic search over
a pre-declared, hash-committed space, **every trial counted**, multiple-testing-corrected); a
professional daily backtest engine becomes the single place any strategy's evidence is shown;
**US-only focus** — Taiwan work is paused (the certified `tw-revenue-momentum v1` keeps its
monitoring and ledger; no new TW cards unless the user asks).

**What does not change:** G1–G6 and their numbers; the 2023+ vault and its pre-registration
discipline; 3 OOS attempts per family; no LLM anywhere in a tiered computation; the 6-month
benchmark-relative definition; monthly rebalance holding 10–20; the `current_universe (optimistic)`
stamp on every number.

Execution: `docs/ROADMAP_V2.md` **Phase 18**. Process rules for automated search:
`docs/RESEARCH_PLAYBOOK.md` §12 (written by card 18.0).

## Non-goals / hard boundaries

- **No LLM in the loop.** The `personas/` reports stay optional commentary; no certified number may
  depend on LLM output. The pipeline must produce identical results with `personas/` uninstalled.
- **No discretionary overrides.** If a certified signal ranks a stock top, it is shown; taste-based
  exclusions are a spec change requiring re-certification.
- **Not short-term trading.** Horizons under ~1 month are out of scope for certification (free
  daily data + monthly fundamentals cannot support them honestly).
- **No promise of absolute gains.** The standard is benchmark-relative; in a bear market the
  certified claim is "falls less than the index", and the UI must say so.
- **No black-box weight optimizers** until the plain-weights institution has produced at least two
  certified-or-rejected families. Hand-set weights, ≤ 4 free parameters per signal.
  *Amended 2026-09-30:* the precondition is met (`us-value-quality` rejected twice,
  `tw-revenue-momentum` certified). The Strategy Factory may run **systematic grid/random search
  over pre-declared menus** — feature directions fixed a priori (never searched), equal or
  menu-listed weights, ≤ 4 free parameters per strategy — under playbook §12's trial counting and
  over-fitting gates. Continuous weight optimizers and ML models (e.g. gradient-boosted rankers)
  still require a further amendment.

## Gap analysis — current state vs the goal

What exists is a clean, honest **calculator**; what is missing is the **referee** layer that turns
computations into standards. Status as of 2026-07-03 (Phases 0–6 delivered, see `docs/ROADMAP.md`):

| Layer | Have | Missing (→ roadmap phase) |
| --- | --- | --- |
| Point-in-time data | EDGAR `filed_at` (real), canonical schema, delta cache; TW `filed_at` = statutory §36 deadlines (11.1 ✅ — see accepted limitation 5) | — |
| Labels | `fwd_return` computed on the fly in the UI panel, never persisted | Persisted research dataset with 1m/3m/6m **benchmark-relative** labels → 7.3 |
| Features | value/quality/momentum/growth ratios in the snapshot | No liquidity fields (can't exclude untradeable names) → 7.1; skip-month momentum (12-1), realized vol → 7.1; TW monthly-revenue momentum → 11.2; TW institutional flows (free, unwired) → 11.3; earnings revisions (paid, deferred) → 12.3 |
| Validation | IC + quantile spread functions (`factors/validate.py`), eyeballed in the UI | Walk-forward splits, gates with numbers, turnover/cost integration → 8.2 |
| Certification | **Nothing** — weights are sliders; any combination renders | SignalSpec + registry + certify CLI + pre-registration enforcement → 8.1–8.3 |
| Presentation | Factors page (exploratory) | Today's Picks page bound to certified signals only → 9.1–9.2 |
| Honesty ledger | Rules in `.claude/rules/`, survivorship warnings in UI | Research log (append-only experiments), drift monitoring after certification → 12.2 |
| Universe | VTI ~3.4k US + all TWSE/TPEX ~2.1k TW, current constituents | Survivorship: current-members-only ⇒ results are optimistic upper bounds; every report must carry the stamp (accepted limitation, see below) |
| Ops | In-app snapshot builder (resumable) | Scheduled refresh + staleness banners → 12.1 |

## Accepted limitations (state them, don't hide them)

1. **Survivorship bias.** The research universe is today's constituents; certified numbers are
   optimistic upper bounds and every report/UI must carry
   `survivorship: current_universe (optimistic)`. Mitigation (cache-forever of once-seen names)
   accrues value over time; a true delisted-inclusive history needs paid data — revisit in 12.3.
2. **Free-data ceiling.** Without analyst estimates, the strongest documented signal family
   (estimate revisions) is unavailable. If the free families all fail certification honestly, that
   is the institution working — the next step is 12.3, not gate-loosening.
3. **EDGAR XBRL coverage thins before ~2012** for smaller filers; months with too few eligible
   names are dropped and reported, not silently kept.
4. **yfinance is unofficial.** Acceptable for research cadence (monthly); a certified signal's
   ops doc must note the refresh dependency.
5. **TW filing dates are statutory deadlines, not actual announcement dates.** FinMind carries no
   announcement-date dataset (verified 2026-07-08 against both the API and the official docs), so
   `filed_at` is synthesized from the Securities and Exchange Act §36 deadlines: annual =
   fiscal-end + 90 days (exactly 3/31 for a December fiscal year), monthly revenue = the 10th of
   the following month. Deadlines are the *latest legal* availability — on-time filers are never
   seen early (no look-ahead); early filers only make features conservative; the sole look-ahead
   exposure is late filers, which are rare and typically trading-sanctioned.
   **Debt-collection status (roadmap 17.9, probed 2026-07-11 — `tw-revenue-momentum v1` is now
   certified, so this validation was due):** three candidate historical per-filing sources were
   probed live and all three ruled out — FinMind's `TaiwanStockMonthRevenue.create_time` (empty
   before some retention horizon; contaminated by a batch-reprocessing timestamp for at least one
   older period); MOPS's compiled monthly-revenue archive (no per-company date column at all);
   TWSE OpenAPI's `t187ap05_L` (serves only the single latest period, one report-generation date
   shared by every company). Full dated findings: `docs/RESEARCH_LOG.md` entry 013. The card's
   live-observation fallback is built (`heimdall.research.mops_probe`, unit-tested) but not yet
   run — it needs a real 12-day calendar window (days 1–12 of a month), the next being
   **2026-08-01 → 2026-08-12**. This limitation is not yet closed; revisit after that window.

## File map of the institution

| File | Role |
| --- | --- |
| `docs/NORTH_STAR.md` | This file — goal, definitions, gaps. Update only when the goal itself changes. |
| `docs/RESEARCH_PLAYBOOK.md` | The process: signal lifecycle, splits, gates (numbers + code), checklists, anti-patterns. |
| `docs/RESEARCH_LOG.md` | Append-only experiment registry. Every OOS touch is logged **before** it happens. |
| `docs/ROADMAP_V2.md` | Executable task cards (one PR each), Phases 7–18 (Phase 18 = US Strategy Factory, current). |
| `.claude/rules/signal-certification.md` | The short hard law binding every session. |
| `signals/registry.json` | (Phase 8.1) machine-readable signal statuses; Today's Picks reads only `certified`. |
| `signals/certifications/` | (Phase 8.2) immutable certification reports, committed to git as evidence. |
