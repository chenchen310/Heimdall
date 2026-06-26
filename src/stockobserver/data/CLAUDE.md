# `data/` — providers, canonical schema, cache, app state

The foundation. Everything else depends on this module's **canonical schema** (see
`docs/ARCHITECTURE.md` §1–2). This is the **only** module allowed to know vendor-specific shapes.

## Responsibilities
- Define the `DataProvider` ABC and the canonical schemas (OHLCV, fundamentals).
- Implement one provider per source; normalize raw vendor data → canonical; attach
  `provider`/`fetched_at`; own a rate limiter; raise `NotSupported` for unserved methods.
- The `symbol_router` parses `TICKER.MARKET` and dispatches to the owning provider.
- The cache layer (DuckDB + partitioned Parquet) does **delta-only** fetching; SQLite holds app state.

## Planned files
```
base.py            # DataProvider ABC, NotSupported, canonical dtypes
schema.py          # canonical column names / pydantic models
symbols.py         # TICKER.MARKET parsing + symbol_router
cache.py           # CachedProvider (delta fetch), DuckDB/Parquet store
state.py           # SQLite: saved screens, watchlists, configs
providers/
  yfinance.py      # Phase 0 — US+TW prices (prototyping-grade)
  edgar.py         # Phase 1 — SEC point-in-time fundamentals
  fred.py          # Phase 1 — FRED macro
  fmp.py           # Phase 4 — paid core (gated on FMP_API_KEY)
  finmind.py       # Phase 6 — Taiwan
```

## Rules that bite here
- `.claude/rules/canonical-schema.md` — never leak vendor shapes upward.
- `.claude/rules/data-discipline.md` — point-in-time (`filed_at`), delta-only, survivorship-aware,
  raw vs adjusted prices kept separate.
- Paid/optional providers are gated on env keys and must never be a hard import for the core.
