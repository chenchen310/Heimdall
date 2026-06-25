# `analytics/` — risk, macro, portfolio, reporting

Higher-level analysis on top of computed prices/factors/backtests. Produces the numeric payloads the
persona dashboards (and the optional AI reports) display.

## Responsibilities & libs
- **risk** — volatility, Beta, max drawdown, VaR/CVaR, correlations, recession stress tests
  (`riskfolio-lib`, `quantstats`). → Bridgewater.
- **macro** — FRED indicators, rate/inflation regime, breadth (`data.providers.fred`). → Two Sigma,
  Citadel rate sensitivity.
- **portfolio** — allocation/efficient frontier, core-satellite, rebalancing (`PyPortfolioOpt`). →
  Vanguard.
- **rotation** — relative-strength rankings (1/3/6m), offense/defense tilt. → Citadel.
- **earnings** — consensus vs estimates, KPI deltas, options-implied move. → JPM.
- **reporting** — assemble per-persona computed payloads (dicts) consumed by `ui/` and, optionally,
  by `personas/`.

## Planned files
```
risk.py  macro.py  portfolio.py  rotation.py  earnings.py  reporting.py
```

## Notes
- Returns plain numbers/DataFrames + structured payloads — **no LLM calls here** (that is
  `personas/`, and it is optional).
- Reads canonical data via `data` / `factors` / `backtest`; never hits a provider directly.
