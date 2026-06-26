# Stock Observer

A personal platform for **screening stocks, timing entries/exits, and backtesting strategies** —
US-first, Taiwan-ready. Built as a Python monolith: a provider-agnostic data layer, a two-engine
backtester (vectorbt for signals, bt for portfolios), DuckDB + Parquet storage, and a Streamlit UI.

It organizes analysis around 8 institutional "analyst persona" lenses — fundamental (Goldman),
technical (Morgan Stanley), risk (Bridgewater), earnings (JPM), sector rotation (Citadel),
multi-factor (RenTech), ETF portfolio (Vanguard), and macro (Two Sigma). Each is a **computed
dashboard**; an AI-written narrative report on top is an **optional** add-on.

> **Status: scaffolding.** This repo currently contains the architecture, docs, and project skeleton.
> No engine is implemented yet. Implementation starts at Phase 0 — see [docs/ROADMAP.md](docs/ROADMAP.md).

## Quickstart (once Phase 0 lands)

Requires [`uv`](https://docs.astral.sh/uv/). Python 3.12 is pinned and provisioned by uv.

```bash
uv sync --all-extras          # set up the environment
uv run pytest                 # run tests
uv run streamlit run src/stockobserver/ui/app.py   # launch the app (Phase 1+)
```

No API keys are needed to start (yfinance + SEC EDGAR + FRED are free). Copy `.env.example` to `.env`
when you add paid data sources or the optional AI report layer.

## Documentation

- [CLAUDE.md](CLAUDE.md) — architecture overview, commands, and conventions (start here)
- [docs/功能說明.md](docs/功能說明.md) — 繁體中文使用者功能總覽（逐一說明每個分頁怎麼用）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — canonical schema, `DataProvider` contract, storage, caching
- [docs/ROADMAP.md](docs/ROADMAP.md) — phased build plan (Phase 0 → 6)
- [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) — data-vendor ladder, budget thresholds, Taiwan (FinMind)

## Disclaimer

For personal, non-commercial research. Backtested results are optimistic by nature — treat them as
upper bounds and forward-test before risking real money. Not investment advice.
