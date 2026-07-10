# Heimdall

A personal platform for **screening stocks, timing entries/exits, and backtesting strategies** —
US-first, Taiwan-ready. Built as a Python monolith: a provider-agnostic data layer, a two-engine
backtester (vectorbt for signals, bt for portfolios), DuckDB + Parquet storage, and a Streamlit UI.

It organizes analysis around 8 institutional "analyst persona" lenses — fundamental (Goldman),
technical (Morgan Stanley), risk (Bridgewater), earnings (JPM), sector rotation (Citadel),
multi-factor (RenTech), ETF portfolio (Vanguard), and macro (Two Sigma). Each is a **computed
dashboard**; an AI-written narrative report on top is an **optional** add-on.

> **Status: Phases 0–6 complete.** All 8 persona dashboards work for the **US** market, and **Taiwan**
> (`.TW`/`.TWO`) is live via FinMind behind a market router. 11 Streamlit pages; an English / 繁體中文
> toggle; ~88 tests, mypy strict, ruff clean. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/). Python 3.12 is pinned and provisioned by uv.

```bash
uv sync --all-extras                              # set up the environment
uv run pytest                                     # run tests
uv run python -m heimdall.screener.build          # small US default (15 names)
uv run python -m heimdall.screener.build --market vti     # whole US market (~3.4k, VTI holdings)
uv run python -m heimdall.screener.build --market tw      # 10 Taiwan large caps (fast)
uv run python -m heimdall.screener.build --market tw-all  # all TWSE+TPEX (~2.1k common stocks)
uv run streamlit run src/heimdall/ui/app.py       # launch the app
```

`--market vti` (~3,400 US) and `--market tw-all` (~2,130 Taiwan) pull the full constituent lists for
the screener. Both are long, **resumable** one-time crawls on free providers — re-run to continue
where it left off (names already built are skipped, prices are cached). For fundamentals at that
scale, an `FMP_API_KEY` (US) or a free `FINMIND_TOKEN` (Taiwan) is strongly recommended — without one
the free quota runs out partway and the rest of the snapshot is price-only.

No API keys are needed to start — yfinance (US + TW prices), SEC EDGAR (US fundamentals), FRED
(macro), and FinMind (Taiwan) are all free. Copy `.env.example` to `.env` for higher quotas
(`FINMIND_TOKEN`), paid sources (`FMP_API_KEY`), or the optional AI report layer (`ANTHROPIC_API_KEY`).

## Deploying (Streamlit Community Cloud)

Community Cloud natively detects `uv.lock` (it takes priority over `requirements.txt` and
`pyproject.toml` if more than one is present) and installs with a **bare `uv sync`** — there is no
way to make it pass `--extra`/`--all-extras`/`--group`. Because `ui/app.py` eagerly imports every
page (backtest, factors, ETF, macro, rotation…) at startup, the app needs `data` + `backtest` +
`analytics` + `ui` just to boot, not only `ui`. That's why those four live in `pyproject.toml` as
PEP 735 **dependency groups**, set as `[tool.uv] default-groups` — a bare `uv sync` (local or on
Cloud) installs them automatically, no flags required. `personas` is the one real optional extra
(lazy-imported, gated on `ANTHROPIC_API_KEY`); Cloud will **not** install it, so the in-app AI report
button stays inert there unless you add `"personas"` to `default-groups` too.

No `requirements.txt` needed — don't add one back; it would just be ignored (`uv.lock` wins) or,
worse, drift out of sync and mislead the next person. If `pyproject.toml`'s dependencies change, run
`uv lock` and commit the updated `uv.lock`; that's the only file Cloud reads.

Set the app's main file to `src/heimdall/ui/app.py` and add any secrets (`FINMIND_TOKEN`,
`FMP_API_KEY`, `ANTHROPIC_API_KEY`, `FRED_API_KEY`) via the Cloud app's Secrets, not `.env` (which
is gitignored and never deployed).

## Documentation

- [CLAUDE.md](CLAUDE.md) — architecture overview, commands, and conventions (start here)
- [docs/功能說明.md](docs/功能說明.md) — 繁體中文使用者功能總覽（逐一說明每個分頁怎麼用）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — canonical schema, `DataProvider` contract, storage, caching
- [docs/ROADMAP.md](docs/ROADMAP.md) — phased build plan (Phase 0 → 6)
- [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) — data-vendor ladder, budget thresholds, Taiwan (FinMind)

## Disclaimer

For personal, non-commercial research. Backtested results are optimistic by nature — treat them as
upper bounds and forward-test before risking real money. Not investment advice.
