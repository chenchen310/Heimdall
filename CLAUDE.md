# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Status:** Phase 2 complete. On top of Phase 0–1, there is now a **single-strategy backtest UI**:
> three strategies (SMA crossover, Donchian breakout, RSI mean-reversion) behind a registry, a
> parameter **sweep** (heatmap), an ATR **trade setup** (entry/stop/targets/R:R), headline metrics +
> equity/drawdown charts, and a downloadable quantstats tear sheet — all cost-aware, next-bar-open
> fills. `uv run streamlit run src/stockobserver/ui/app.py` → Screener / Chart / Backtest pages.
> Next is **Phase 3** (multi-factor scoring + portfolio backtesting) — see `docs/ROADMAP.md`.

## What this is

A **personal, single-user** web tool to screen stocks, decide entry/exit timing, and **backtest
strategies**. US market first; Taiwan is supported by design (not bolted on later). It is a Python
monolith with a provider-agnostic data layer, a two-engine backtester, and a Streamlit UI.

It is built around 8 institutional "analyst persona" lenses (Goldman fundamental, Morgan Stanley
technical, Bridgewater risk, JPM earnings, Citadel sector rotation, RenTech multi-factor, Vanguard
ETF, Two Sigma macro). **Each persona is a computed dashboard.** An AI narrative report that turns
those computed numbers into prose (via the Claude API) is an **optional, decoupled** layer — the
quant core never imports it. See the persona→module map below.

## Toolchain & commands

Managed with **`uv`**. The repo pins **Python 3.12** (`.python-version`); the machine's default
`python3` is conda 3.8 and must not be used here — `uv` provisions an isolated 3.12.

```bash
# Environment (installs core + all feature extras + dev group into .venv)
uv sync --all-extras

# Install a single feature area instead (extras: data, backtest, analytics, ui, personas)
uv sync --extra data --extra ui

# Phase 0 vertical-slice backtest (writes a quantstats tear sheet to reports/)
uv run python -m stockobserver.backtest.demo
uv run python -m stockobserver.backtest.demo --symbol MSFT.US --fast 20 --slow 50

# Phase 1: build the screener snapshot (set SEC_EDGAR_USER_AGENT in .env first), then run the UI
uv run python -m stockobserver.screener.build
uv run streamlit run src/stockobserver/ui/app.py   # screener + chart pages

# Tests
uv run pytest                                # whole suite
uv run pytest tests/test_yfinance.py         # one file
uv run pytest tests/test_yfinance.py::test_get_ohlcv_canonical   # one test
uv run pytest -k cache -q                    # by keyword

# Quality gates (run before declaring work done)
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy                    # type-check (strict; package = stockobserver)

# Dependency resolution sanity check (no install, no run)
uv lock
```

There is no build step — it is an application, not a published package.

## Architecture (the big picture)

Data flows **one direction**, and everything downstream speaks the **canonical schema** only — never
a vendor's raw JSON. This is the single most important rule (see `.claude/rules/canonical-schema.md`).

```
            providers (yfinance, EDGAR, FRED, …)          ← vendor-specific, the ONLY place raw JSON lives
                          │  normalize → canonical schema
                          ▼
   data/  ── cache (DuckDB + partitioned Parquet) ───────┐  market/fundamental history (delta-fetched)
        └── app state (SQLite: saved screens, watchlists) │
                          │  canonical reads               │
        ┌─────────────────┼─────────────────────────────┐ │
        ▼                 ▼                               ▼ │
   screener/          factors/                      backtest/
   {field,op,value}   value/quality/momentum/       vectorbt (signals) + bt (portfolios)
   over snapshot      growth/sentiment → 0–100       costs + slippage modeled, next-bar fills
        │                 │                               │
        └────────┬────────┴───────────────┬──────────────┘
                 ▼                         ▼
            analytics/                  ui/  (Streamlit pages, Plotly charts)
   risk · macro · portfolio · reporting       │
                 │                              │
                 └──────────── optional ───────►  personas/  (Claude API narrative; NEVER imported by core)
```

Key design decisions and their rationale live in **`docs/ARCHITECTURE.md`** (canonical schema,
`DataProvider` ABC contract, symbol format, storage split, caching, screener/factor models). Read it
before touching `data/` or adding a provider. Data-vendor strategy and budget thresholds are in
**`docs/DATA_SOURCES.md`**.

### The two abstractions that make the rest work

- **`DataProvider` ABC** (`src/stockobserver/data/`) — every source (yfinance, EDGAR, FRED, later FMP,
  FinMind) implements `get_ohlcv`, `get_fundamentals`, `get_estimates`, `get_earnings_dates` and
  normalizes into the canonical schema. Adding Taiwan = writing **one** `FinMindProvider` + a symbol
  router; nothing downstream changes.
- **Canonical symbol `TICKER.MARKET`** — e.g. `AAPL.US`, `2330.TW`. Every row carries a currency
  field. Decided day one; do not introduce bare tickers anywhere downstream.

### Persona → module map

| Persona (lens)              | Primarily computed in                                  |
| --------------------------- | ------------------------------------------------------ |
| Goldman — fundamental       | `data` (EDGAR/FMP fundamentals) + `analytics`          |
| Morgan Stanley — technical  | `factors` (pandas-ta indicators) + `backtest` (setups) + `ui` charts |
| Bridgewater — risk          | `analytics` (vol, Beta, VaR/CVaR, drawdown via riskfolio-lib/quantstats) |
| JPM — earnings              | `data` (estimates, earnings dates) + `analytics`       |
| Citadel — sector rotation   | `analytics` (relative strength) + `factors` + ETF data |
| RenTech — multi-factor      | `factors` + `screener` + `backtest` (bt) + alphalens   |
| Vanguard — ETF portfolio    | `analytics` (PyPortfolioOpt allocation)                |
| Two Sigma — macro           | `data` (FRED) + `analytics` (macro)                    |

The optional `personas/` module takes a persona's computed payload and renders the matching prompt
(the 8 prompts in `docs/` / persona templates) through the Claude API. See `claude-api` skill for
current model IDs; default to a current Claude model and treat reports as optional output.

## Non-negotiables (hard rules — details in `.claude/rules/`)

These are the parts that are hard to get right and easy to fool yourself on. Do not relax them.

- **No look-ahead bias.** Fundamentals are point-in-time: lag every fundamental to its actual SEC
  filing/availability date, never the fiscal-period-end date. (`data-discipline.md`)
- **Survivorship-aware.** Backtests over a universe must include delisted/acquired names or be
  explicitly labeled optimistic upper bounds. Keep delisted symbols in cache once seen.
- **Honest backtests.** Always model commissions + slippage; fill on the **next** bar's open, not the
  signal bar's close; prefer walk-forward / out-of-sample; distrust suspiciously smooth equity
  curves. (`backtest-honesty.md`)
- **Canonical schema only** downstream of providers; carry currency everywhere. (`canonical-schema.md`)
- **Delta-only fetching.** Never re-pull full history; fetch new dates and append. Respect provider
  rate limits with a limiter inside each provider class.

## Conventions

- **Business logic stays in plain modules** under `src/stockobserver/`, not in Streamlit scripts, so a
  future FastAPI/React migration is mechanical.
- **Free providers by default** (yfinance + EDGAR + FRED). Paid providers (FMP, etc.) are
  drop-in `DataProvider` implementations gated behind env keys — never a hard dependency.
- **Tests are fixture/golden-based:** saved vendor JSON → assert canonical output; plus at least one
  **known-answer backtest** to catch look-ahead regressions. See `tests/CLAUDE.md`.
- Secrets via `.env` (see `.env.example`); loaded with `python-dotenv`. Phase 0/1 needs no keys.

## Where to look first

- Adding/with a data source → `src/stockobserver/data/CLAUDE.md` + `docs/ARCHITECTURE.md`
- Writing a strategy/backtest → `src/stockobserver/backtest/CLAUDE.md` + `.claude/rules/backtest-honesty.md`
- Factor scoring → `src/stockobserver/factors/CLAUDE.md`
- What to build next → `docs/ROADMAP.md` (Phase 0 is the current target)
