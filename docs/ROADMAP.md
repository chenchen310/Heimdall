# Roadmap

Phased build. Each phase ends in something usable. The quant core is Phases 0–5; the **optional** AI
persona/report layer is a non-blocking module that can slot in any time after Phase 3 (it depends on
computed payloads, not the other way around).

Hardest/riskiest parts are **data correctness** (point-in-time, survivorship) and **backtest
honesty** — not the UI. They are de-risked first, on purpose.

---

## Phase 0 — Foundation + one honest backtest  ← **NEXT**

De-risk the whole vertical slice before building breadth.

- `uv` env on Python 3.12; pre-commit, ruff, mypy, pytest wired.
- `DataProvider` ABC + canonical schema + `TICKER.MARKET` router (`src/stockobserver/data/`).
- `YFinanceProvider` + DuckDB/Parquet **delta cache** (`CachedProvider`).
- **Vertical slice:** pull `AAPL.US` → SMA(20/50) crossover with `pandas-ta` → backtest in `vectorbt`
  **with commissions + slippage, next-bar fills** → `quantstats` tear sheet.
- One **known-answer** backtest test to lock down look-ahead behavior.

**Done when:** `uv run python -m stockobserver.backtest.demo` produces a tear sheet and the
known-answer test passes.

## Phase 1 — Data layer + basic screener (MVP UI)

- Add `SecEdgarProvider` (point-in-time fundamentals) + `FredProvider` (macro).
- Build the **snapshot table** and the declarative `{field,op,value}` screener over US large/mid caps.
- Streamlit: screener page (filter builder + results table) + per-stock chart page (Plotly
  candlestick + MA/RSI/MACD).
- **Done when:** you can screen US stocks by fundamental + technical criteria in the browser.

## Phase 2 — Single-strategy backtesting

- `vectorbt` engine wrapping common strategies (MA crossover, breakout, RSI mean-reversion) with
  costs/slippage; parameter-sweep UI; entry/stop/target/risk-reward viz (Morgan Stanley setup);
  quantstats output.
- **Done when:** any single entry/exit strategy can be validated with realistic costs.

## Phase 3 — Multi-factor scoring + portfolio backtesting

- Compute value/quality/momentum/growth/sentiment; cross-sectional normalization → 0–100 composite.
- `alphalens-reloaded` factor validation; `bt` portfolio backtester with periodic rebalancing (CAGR,
  max drawdown, Sharpe); top-N ranking (RenTech persona).
- **This is where survivorship / point-in-time bias matters most** — see `.claude/rules/`.
- **Done when:** factor-weighted portfolios report honest long-term stats over a survivorship-aware
  universe.

## Phase 4 — Fundamental & technical dashboards

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
