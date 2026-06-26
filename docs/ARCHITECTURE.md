# Architecture

This is the reference for the design decisions that span multiple modules. If you are adding a data
provider, a screener field, or a factor, read the relevant section first. The root `CLAUDE.md` has
the one-paragraph version; this file is the contract.

## 1. The golden rule: canonical schema everywhere

Providers are the **only** place vendor-specific shapes (raw JSON, vendor column names, vendor symbol
formats) are allowed to exist. Every provider normalizes into one **canonical schema**, and the
screener, factors, backtester, analytics, UI, and personas read **only** that schema. This is what
lets us swap data vendors and add Taiwan without rewrites.

### Canonical symbol: `TICKER.MARKET`

- Format: `AAPL.US`, `MSFT.US`, `2330.TW`, `0050.TW` (TWSE), `.TWO` for TPEX/OTC.
- A `symbol_router` parses `MARKET` and dispatches to the provider that owns it.
- Bare tickers (`AAPL`) must never appear downstream of a provider.

### Canonical OHLCV (one row per symbol per bar)

| column        | type            | notes                                                |
| ------------- | --------------- | ---------------------------------------------------- |
| `symbol`      | str             | canonical `TICKER.MARKET`                            |
| `date`        | date/datetime   | bar timestamp (UTC date for EOD)                     |
| `open/high/low/close` | float   | **raw** prices as traded                             |
| `adj_close`   | float           | split/dividend-adjusted close                        |
| `volume`      | int             | shares                                               |
| `currency`    | str             | ISO 4217 (`USD`, `TWD`) — always carried             |
| `provider`    | str             | source tag, for provenance                           |
| `fetched_at`  | datetime        | when we retrieved it (provenance / point-in-time)    |

Store **raw** prices immutably; expose an **adjusted** view for backtests. Never overwrite raw history
with re-adjusted numbers.

### Canonical fundamentals (point-in-time, **tidy long** — one metric value per row)

| column          | type   | notes                                                            |
| --------------- | ------ | ---------------------------------------------------------------- |
| `symbol`        | str    | canonical                                                        |
| `metric`        | str    | canonical metric name (`revenue`, `net_income`, `equity`, …)     |
| `statement`     | enum   | `income` / `balance` / `cashflow`                                |
| `period`        | enum   | `annual` / `quarter`                                             |
| `fiscal_end`    | date   | end of the fiscal period                                         |
| `filed_at`      | date   | **availability/filing date — this is what prevents look-ahead**  |
| `value`         | float  | metric value in `currency` (or shares for share counts)          |
| `currency`      | str    | reporting currency                                               |
| `provider`      | str    | source tag                                                       |
| `fetched_at`    | date   | retrieval time (provenance)                                      |

Tidy-long (vs a `line_items` mapping) so the snapshot builder and DuckDB can filter/aggregate metrics
directly. "Latest" means the **max `fiscal_end`** among rows with `filed_at ≤ as_of` (a 10-K reports
several comparative years under one filing date).

> **Critical:** strategies and factors must key off `filed_at`, never `fiscal_end`. A Q2 result that
> ends June but is filed in August is not knowable in July. See `.claude/rules/data-discipline.md`.

## 2. The `DataProvider` ABC

`src/stockobserver/data/base.py` (Phase 0) defines the interface every source implements:

```python
class DataProvider(ABC):
    markets: frozenset[str]                # e.g. {"US"} or {"TW"}

    def get_ohlcv(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...        # canonical OHLCV
    def get_fundamentals(self, symbol: str, statement: str, period: str) -> pd.DataFrame: ...
    def get_estimates(self, symbol: str) -> pd.DataFrame: ...     # may raise NotSupported
    def get_earnings_dates(self, symbol: str) -> pd.DataFrame: ...
```

- Methods a source cannot serve raise a `NotSupported` exception rather than returning fake data.
- Each provider owns a **rate limiter** (token bucket) sized to its plan, and is responsible for
  normalization + attaching `provider`/`fetched_at`.
- Providers are **stateless** about caching — the cache layer wraps them (see §4).

Phase 0/1 providers: `YFinanceProvider` (US+TW prices), `SecEdgarProvider` (US point-in-time
fundamentals), `FredProvider` (macro series). Later: `FmpProvider`, `FinMindProvider`. See
`docs/DATA_SOURCES.md`.

## 3. Storage split

- **DuckDB + partitioned Parquet** for analytical data (price/fundamental history, the snapshot
  table, factor scores). Columnar, compresses ~60–70% vs row stores, and DuckDB queries Parquet
  directly — ideal for "10 years of adjusted closes for 500 tickers" scans the backtester needs.
  Partition Parquet by market/symbol (and year for prices).
- **SQLite** for app state: saved screens, watchlists, factor-weight configs, job metadata. ACID,
  zero-config, easy to back up.

Everything lives under `data/` (gitignored). Treat it as a regenerable cache, not a source of truth.

## 4. Caching (three layers — the main defense against rate limits)

1. **Persistent cache (primary).** Once fetched, write OHLCV/fundamentals to Parquet/DuckDB and only
   fetch **deltas** (new dates) thereafter. A `CachedProvider` wrapper checks the local store, asks
   the underlying provider only for the gap, appends, and returns canonical data.
2. **In-session memoization.** Streamlit `@st.cache_data` for computed results (factor scores, screen
   outputs) within a session.
3. **Request-level cache.** `requests-cache` for repeated identical API calls during development.

## 5. Screener model (declarative)

A screen is a list of predicate objects evaluated over a **snapshot table** (one row per symbol per
date holding every metric — fundamental, technical, factor — all in canonical units):

```json
{ "name": "cheap-and-oversold",
  "predicates": [
    { "field": "pe_ratio",          "op": "<",  "value": 15 },
    { "field": "rsi_14",            "op": "<",  "value": 30 },
    { "field": "revenue_growth_yoy","op": ">",  "value": 0.15 } ] }
```

Because fundamental + technical + factor fields share one canonical table, a new criterion is a
one-line config change. Evaluation is vectorized DuckDB/pandas. Screens persist as JSON in SQLite
(name + timestamp) for reproducibility and so the backtester can replay "what this screen would have
selected" historically.

## 6. Factor scoring

For each factor, compute the raw metric, then **cross-sectionally** rank or z-score within the
universe (and ideally within sector, to neutralize sector bias) so factors are comparable. Combine
into a 0–100 composite with configurable, explained weights:

```
composite = percentile( Σ wᵢ · zscore(factorᵢ) )
```

Default factor families:
- **Value** — inverse PE/PS/EV-EBITDA + FCF yield
- **Quality** — ROE, gross-margin stability, low debt/equity, Piotroski F-score
- **Momentum** — 3/6/12-month returns (skip most recent month)
- **Growth** — revenue/EPS growth
- **Sentiment** — analyst revisions, news sentiment (qualitative early)

Validate every factor with `alphalens-reloaded` (IC, quantile returns, turnover) **before** trusting
it in a backtest. Store computed scores in DuckDB keyed by `(symbol, date)` so the screener and the
portfolio backtester read the **same point-in-time** scores.

## 7. Optional persona / AI report layer

`src/stockobserver/personas/` is the only module allowed to call an LLM, and **nothing in the core
imports it**. Contract: a persona function receives a fully-computed payload (dict of the numbers its
dashboard already shows) plus the persona prompt template, calls the Claude API, and returns text.
The platform is fully usable with this module absent or `ANTHROPIC_API_KEY` unset. See the
`claude-api` skill for current model IDs.

## 8. Taiwan readiness (why it's a day-one decision, not a feature)

Because everything downstream reads the canonical schema and `TICKER.MARKET` symbols, adding Taiwan is
localized to: one `FinMindProvider` (maps FinMind's 75+ datasets into canonical), a `.TW/.TWO` entry
in the symbol router, TWD currency handling, and the different fiscal cadence (TW monthly revenue is a
valuable extra signal). The screener, factors, backtester, and dashboards work unchanged. This only
holds if the golden rule (§1) is never violated — hence it is rule #1.
