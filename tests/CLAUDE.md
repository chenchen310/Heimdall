# `tests/`

Run with `uv run pytest` (config in `pyproject.toml`; `pythonpath = ["src"]`). Tests must not hit the
network — use saved fixtures.

## Strategy
- **Golden/fixture provider tests** — saved vendor JSON → assert the provider emits the exact
  canonical schema (columns, dtypes, `TICKER.MARKET` symbol, currency, `filed_at`/`fetched_at`). One
  per provider.
- **Known-answer backtest** — a strategy whose result you can verify by hand, used to catch
  **look-ahead** regressions (e.g. that fills happen on the next bar, costs are applied). This is the
  most important test in the repo; keep it green. (`.claude/rules/backtest-honesty.md`)
- **Property tests** for factor normalization — e.g. z-scored factor has ~0 mean/unit variance
  cross-sectionally; composite stays in [0, 100]; ranking is order-preserving.
- **Cache tests** — delta fetch requests only the missing date range and appends without dupes.

## Conventions
- Fixtures (saved API responses) live in `tests/fixtures/`.
- Mock providers at the boundary; never call live APIs in CI.
- Mirror source layout: `tests/test_<module>.py`.
