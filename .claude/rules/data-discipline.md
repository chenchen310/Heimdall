# Rule: Data discipline (point-in-time, no look-ahead, survivorship-aware)

These exist because backtests that violate them look great and lose money. Non-negotiable.

## Point-in-time fundamentals

- Key every fundamental signal off **`filed_at`** (SEC filing/availability date), never `fiscal_end`.
  A period ending June and filed in August is **not knowable in July**.
- Practical lag rule: only act on a fundamental on/after its known filing date (or a fixed N-day lag
  after fiscal-period end when a filing date is unavailable). If a strategy survives an extra
  one-period lag on every input, it is likelier to be real.
- Vendors silently restate/backfill. Prefer EDGAR **as-reported** XBRL; store fundamentals with the
  `fetched_at` retrieval date and do not overwrite history with later revisions.

## Survivorship bias

- A universe of only stocks that exist **today** overstates returns and understates drawdown
  (documented at multiple %/yr). Backtests over a universe must:
  - include delisted/acquired/bankrupt names, **or**
  - be explicitly labeled an optimistic upper bound.
- Once a symbol is seen, **keep it in the cache** even after delisting.
- Prefer a fixed historical index-constituent list over today's winners.

## Fetching & storage

- **Delta-only:** never re-pull full history; fetch the missing date range and append.
- Store **raw immutable** prices + a separate **adjusted** view; timestamp every fetch (`fetched_at`).
- Validate on ingest: no negative prices, no impossible gaps; keep raw API responses long enough to
  reprocess if a bug is found.
- Respect provider rate limits with a limiter inside the provider class; prefer bulk/EOD endpoints
  over per-symbol loops.
