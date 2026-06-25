# `backtest/` — strategy & portfolio backtesting

Two engines for two genuinely different jobs. Do not force one to do the other's work.

- **`vectorbt`** — single-strategy entry/exit signals + parameter sweeps (MA crossover, breakout, RSI
  mean-reversion). Numba-vectorized, fast for sweeps.
- **`bt`** — multi-factor **portfolio** backtests with periodic rebalancing (compose select/weigh/
  rebalance algos). Used for RenTech factor sleeves, Citadel rotation, Vanguard baskets.
- `Zipline-Reloaded` is deferred until true Pipeline point-in-time factor selection is needed.

## Planned files
```
signals/        # vectorbt strategy wrappers (one per strategy)
portfolio/      # bt strategy trees (rebalance cadences, weighting)
costs.py        # commission + slippage models (shared, mandatory)
report.py       # quantstats tear sheets
demo.py         # Phase 0 vertical slice: AAPL SMA(20/50) → tear sheet
```

## Rules that bite here — `.claude/rules/backtest-honesty.md` (mandatory)
- **Always** apply `costs.py` (commissions + slippage). No frictionless runs.
- **Fill on next bar's open**, never the signal bar's close.
- Walk-forward / OOS over single in-sample fits; few parameters; distrust smooth equity curves.
- Keep the **known-answer backtest** test green (catches look-ahead regressions).
- Universe backtests must be survivorship-aware or labeled optimistic upper bounds.
