# `factors/` — factor computation & scoring

Computes value/quality/momentum/growth/sentiment factors and combines them into a 0–100 composite.
See `docs/ARCHITECTURE.md` §6.

## Responsibilities
- Compute each raw factor from canonical data (and technical indicators via `pandas-ta`).
- **Cross-sectionally** normalize (z-score/rank), ideally **within sector**, so factors are
  comparable; combine with configurable, explained weights → percentile → 0–100.
- Persist scores in DuckDB keyed by `(symbol, date)` so screener + backtester read the **same
  point-in-time** scores.

## Planned files
```
indicators.py   # pandas-ta wrappers (RSI, MACD, MA, ATR, Bollinger, Fibonacci) → canonical columns
value.py quality.py momentum.py growth.py sentiment.py
composite.py    # normalization + weighting → 0–100
```

## Rules that bite here
- Momentum skips the most recent month; fundamentals use `filed_at` (point-in-time) — never peek.
- **Validate every factor with `alphalens-reloaded` before trusting it** (IC, quantile spread,
  turnover). A factor that fails alphalens does not go into a backtest. (`.claude/rules/backtest-honesty.md`)
