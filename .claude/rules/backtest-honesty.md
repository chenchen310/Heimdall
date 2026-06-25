# Rule: Backtest honesty

Frictionless, in-sample, look-ahead-leaking backtests lie. Every backtest in this project must:

## Costs & fills
- **Always model commissions + slippage** (bid-ask/impact). Frictionless results are not reportable.
- **Fill on the next bar's open**, not the signal bar's close. Acting on the same bar that generated
  the signal imports the future. vectorbt/bt/Backtrader all support this — use it.

## Validation
- Prefer **out-of-sample / walk-forward** over a single in-sample fit.
- **Few parameters.** Over-optimizing to historical noise (curve-fitting) is the default failure mode.
  Be suspicious of suspiciously smooth equity curves and of best-case parameter cherry-picking.
- Validate factors with `alphalens-reloaded` (IC, quantile spread, turnover) **before** backtesting
  them.
- Keep at least one **known-answer backtest** (a strategy whose result you can verify by hand) in the
  test suite to catch look-ahead regressions.

## Reporting
- Treat all backtest figures as **optimistic upper bounds**. State assumptions (costs, universe,
  period, rebalance cadence) alongside results.
- Pair point estimates with drawdown and a tear sheet (`quantstats`), not just CAGR/Sharpe.

See also `.claude/rules/data-discipline.md` (point-in-time & survivorship feed directly into this).
