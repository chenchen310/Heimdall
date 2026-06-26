# Roadmap

Phased build. Each phase ends in something usable. The quant core is Phases 0–5; the **optional** AI
persona/report layer is a non-blocking module that can slot in any time after Phase 3 (it depends on
computed payloads, not the other way around).

Hardest/riskiest parts are **data correctness** (point-in-time, survivorship) and **backtest
honesty** — not the UI. They are de-risked first, on purpose.

---

## Phase 0 — Foundation + one honest backtest  ✅ **DONE**

De-risk the whole vertical slice before building breadth.

- [x] `uv` env on Python 3.12; pre-commit, ruff, mypy (strict), pytest wired.
- [x] `DataProvider` ABC + canonical schema + `TICKER.MARKET` router (`src/stockobserver/data/`).
- [x] `YFinanceProvider` + DuckDB/Parquet **delta cache** (`CachedProvider`).
- [x] **Vertical slice:** pull `AAPL.US` → SMA(20/50) crossover with `pandas-ta` → backtest in
  `vectorbt` **with commissions + slippage, next-bar-open fills** → `quantstats` tear sheet
  (`src/stockobserver/backtest/demo.py`).
- [x] **Known-answer** backtest test locking down look-ahead (`tests/test_backtest_known_answer.py`).

**Done:** `uv run python -m stockobserver.backtest.demo` produces a tear sheet; 15 tests pass,
mypy/ruff clean. Deferred to Phase 1: `data/state.py` (SQLite app state) — not needed by the slice.

## Phase 1 — Data layer + basic screener (MVP UI)  ✅ **DONE**

- [x] `SecEdgarProvider` (point-in-time fundamentals, golden-tested) + `FredProvider` (macro, sibling
  `MacroProvider`). `data/state.py` (SQLite) added for saved screens.
- [x] **Snapshot table** (`screener/snapshot.py`, `screener.build`) — point-in-time fundamentals
  (max fiscal-end filed ≤ as-of) + technicals + derived ratios; one row per symbol.
- [x] Declarative `{field, op, value}` **screener** (`screener/model.py`, `engine.py`) with saved
  screens; RSI/MACD added to `factors/indicators.py`.
- [x] **Streamlit UI** (`ui/`): screener page (editable predicates, presets, save/load) + chart page
  (Plotly candlestick + SMA/RSI/MACD). Headless-tested via `AppTest`.

**Done:** build a snapshot then screen/chart in the browser; 34 tests pass, mypy/ruff clean.
Known limits (Phase 3+): multi-class share counts (e.g. META) and a few alternate XBRL equity tags
resolve to NaN and are simply excluded; TTM/quarterly fundamentals and a survivorship-aware universe
are deferred.

## Phase 2 — Single-strategy backtesting  ✅ **DONE**

- [x] Strategy registry (`backtest/strategies.py`) over the `vectorbt` engine: SMA crossover,
  Donchian breakout, RSI mean-reversion — all cost-aware, next-bar-open fills.
- [x] Parameter **sweep** (`backtest/sweep.py`) → heatmap; invalid combos yield NaN, not errors.
- [x] ATR **trade setup** (`backtest/setup.py`): entry/stop/targets/R:R (Morgan Stanley lens).
- [x] Metrics + equity/drawdown (`backtest/report.py`) and a downloadable quantstats tear sheet,
  surfaced on the Streamlit **Backtest page** (`ui/backtest_page.py`).

**Done:** any single entry/exit strategy is validated with realistic costs in the browser; 44 tests
pass, mypy/ruff clean. (TTM fundamentals & survivorship-aware universes still deferred to Phase 3.)

## Phase 3 — Multi-factor scoring + portfolio backtesting  ✅ **DONE**

- [x] value/quality/momentum/growth scoring (`factors/scoring.py`): cross-sectional z-score →
  0–100 composite with configurable weights. (Sentiment deferred — needs analyst data from FMP.)
- [x] Point-in-time factor **panel** (`factors/panel.py`) reusing `screener.snapshot_row`; rank **IC**
  + quantile spread (`factors/validate.py`), with an optional `alphalens-reloaded` path.
- [x] `bt` **portfolio backtester** (`backtest/portfolio.py`): top-N by composite, periodic
  rebalance, commissions, vs an equal-weight benchmark; **Factors** UI page (`ui/factors_page.py`).
- [x] Honesty: selection uses only data filed/observed ≤ the rebalance date.

**Done:** factor portfolios report long-term stats (CAGR/maxDD/Sharpe) against a benchmark; 56 tests
pass, mypy/ruff clean. **Caveat:** over a *current* universe results carry survivorship bias —
surfaced as an optimistic-upper-bound warning. A true survivorship-free universe (delisted names /
historical index constituents) needs a paid source and is still deferred.

## Phase 4 — Fundamental & technical dashboards  ← **NEXT**

- Swap in **FMP Premium** as primary provider (drop-in `DataProvider`).
- Goldman fundamental dashboard (rating/target, revenue structure, profitability, balance sheet, FCF,
  moat, valuation snapshot, bull/bear, scenarios).
- Full Morgan Stanley technical dashboard (S/R, Fibonacci, ATR, Bollinger, patterns, trade setups).
- **(Optional, parallel) AI report layer** can start here: `personas/` renders computed payloads
  through the Claude API.

## Phase 5 — Risk, macro & sector rotation

- Bridgewater risk memo (vol, Beta, max drawdown, VaR/CVaR via `riskfolio-lib`/`quantstats`,
  correlations, recession stress test, hedging).
- JPM earnings module (consensus vs whisper, KPIs, options-implied vol, earnings trade plans).
- Two Sigma macro outlook (FRED indicators, Fed policy, breadth, sentiment).
- Citadel sector rotation (relative-strength 1/3/6m, ETF recs, offense/defense).
- Vanguard ETF construction (`PyPortfolioOpt`).
- **Done when:** the full persona set works for US.

## Phase 6 — Taiwan market support

Cheap because of the Phase 0 design: one `FinMindProvider` mapped to canonical, `.TW/.TWO` router
entry, TWD handling, TW-specific data (institutional flows, margin balances, monthly revenue).
Screener/backtester/dashboards work unchanged.

---

## Spend thresholds

Stay **free** (yfinance + EDGAR + FRED) through Phases 0–1. Buy **FMP Premium ($59/mo)** when factor
scoring/fundamentals outgrow free sources (≈ Phase 3–4) — highest-leverage purchase. Add Tiingo
($30) or Polygon ($29) only on price-quality/intraday walls. Taiwan: FinMind free (600 req/hr),
upgrade only for adjusted prices/bulk. Details in `docs/DATA_SOURCES.md`.
