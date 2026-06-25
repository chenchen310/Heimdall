# Package map — `stockobserver`

Import path is `stockobserver.*` (src layout; `pythonpath = ["src"]` for pytest). Business logic
lives here in plain modules — **never** in Streamlit scripts — so the UI stays a thin shell.

Dependency direction is one-way (a module may import from those above it, never below):

```
data/        providers + canonical schema + cache + app state   ← foundation, imports nothing else here
  ↓
factors/     value/quality/momentum/growth/sentiment scoring
screener/    declarative predicate evaluation over the snapshot
  ↓
backtest/    vectorbt (signals) + bt (portfolios)
  ↓
analytics/   risk · macro · portfolio · reporting
  ↓
ui/          Streamlit pages (thin; calls everything above)
personas/    OPTIONAL Claude-API narrative — imported by NOTHING above it
```

Each subdirectory has its own `CLAUDE.md` with its contract. Start at `data/` — everything depends on
its canonical schema (see `docs/ARCHITECTURE.md`). The hard rules in `.claude/rules/` bind every
module here.
