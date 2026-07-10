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
   exposure is late filers, which are rare and typically trading-sanctioned. Per-filing empirical
   validation would require a MOPS (公開資訊觀測站) integration — revisit only if a TW family
   reaches pre-registration.

## File map of the institution

| File | Role |
| --- | --- |
| `docs/NORTH_STAR.md` | This file — goal, definitions, gaps. Update only when the goal itself changes. |
| `docs/RESEARCH_PLAYBOOK.md` | The process: signal lifecycle, splits, gates (numbers + code), checklists, anti-patterns. |
| `docs/RESEARCH_LOG.md` | Append-only experiment registry. Every OOS touch is logged **before** it happens. |
| `docs/ROADMAP_V2.md` | Executable task cards (one PR each), Phases 7–16. |
| `.claude/rules/signal-certification.md` | The short hard law binding every session. |
| `signals/registry.json` | (Phase 8.1) machine-readable signal statuses; Today's Picks reads only `certified`. |
| `signals/certifications/` | (Phase 8.2) immutable certification reports, committed to git as evidence. |
