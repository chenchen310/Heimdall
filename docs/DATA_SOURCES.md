# Data Sources

Decision reference for which vendor feeds what, and when to pay. All vendors are accessed through the
`DataProvider` ABC, so swapping or adding one is local to `src/heimdall/data/providers/`.

> Pricing gathered mid-2026 and is volatile — verify on official pages before subscribing. FMP quoted
> prices are annual-commitment rates (month-to-month is higher).

## Use these for free regardless of paid tier

- **SEC EDGAR** — gold standard for **point-in-time** US fundamentals. `companyfacts`/`frames` JSON
  give as-reported XBRL with filing dates → the best mitigation for fundamental look-ahead bias. No
  key; descriptive `User-Agent` required (~10 req/s). Feeds Goldman/JPM/RenTech.
- **SEC Form 4** (EDGAR, `data/providers/form4.py`, roadmap 12.4/13.3) — officers/directors report
  their own open-market trades within two business days. The credible *free* US "smart money" stream
  (the US has no public daily institutional flow; 13F is quarterly + 45-day-lagged). Same shared
  `User-Agent`/CIK cache as the fundamentals provider; `ownershipDocument` XML → canonical
  per-transaction rows, keyed on the **filing** timestamp (point-in-time). Feeds the `us-insider`
  research family. No key.
- **FRED** (St. Louis Fed) — 800k+ macro series (GDP, CPI, unemployment, yield curve `T10Y2Y`, Fed
  funds). Free key, 1,000 req/day. Use `fredapi`. Feeds Two Sigma macro + Citadel rate sensitivity.
- **yfinance** — quick prices for US **and** TW (`.TW`/`.TWO`). Unofficial/scraping-based and
  rate-limited — **prototyping only, never a production foundation.**

## US price/fundamental ladder

| Tier            | Pick                | Why                                                            |
| --------------- | ------------------- | ------------------------------------------------------------- |
| **$0** (Ph 0–1) | yfinance + EDGAR + FRED | Enough to build & validate the entire architecture.       |
| **~$30/mo**     | Tiingo Power ($30)  | Cleanest split/dividend-adjusted EOD, 30+ yr — good for backtests. |
| or              | EODHD All-World ($19.99) | 60+ exchanges incl. Taiwan `.TW`; convenient if you want one vendor early. |
| **~$60/mo**     | **FMP Premium ($59)** | **Recommended core.** Income/balance/cashflow (annual+quarter+TTM), ratios, DCF, analyst estimates, price targets, earnings, ETF holdings — consolidates the most personas behind one key. |
| **+~$29/mo**    | Polygon Starter     | Clean intraday/real-time US prices if technical backtests need it. FMP is weak intraday. |

**Why FMP as core:** it single-handedly feeds the Goldman fundamental screener, JPM earnings, RenTech
factor data, and Vanguard ETF modules. The ~$88/mo FMP Premium + Polygon Starter combo covers
essentially every persona for US.

**Sector classification (roadmap 14.1):** no existing cached artifact carries a US sector field
(probed 2026-07-11), so `screener/universe.py`'s `us_sector_map()` fetches EDGAR's free
`submissions` JSON (`sic`/`sicDescription`) per symbol, incrementally cached. The raw
`sicDescription` is far too granular (1000+ distinct strings) to aggregate a sector page over, so
the numeric SIC code is bucketed into one of the 10 standard **SIC Divisions** (public federal
classification) instead — a stable, deterministic ~dozen-group taxonomy. Taiwan reuses FinMind
`TaiwanStockInfo`'s `industry_category` (already fetched for `tw_symbols()`, previously discarded).

## Taiwan (Phase 6) ✅ implemented

`FinMindProvider` (`data/providers/finmind.py`) serves the `.TW`/`.TWO` markets; the market router
(`data/router.py`) sends Taiwan fundamentals there while US stays on EDGAR. Prices route to yfinance
for both markets (it returns **adjusted** TW closes, which matters for honest backtests).

- **FinMind** — recommended TW source. Open-source, 75+ datasets (TWSE+TPEX prices, financials, cash
  flow, **monthly revenue**, institutional flows, margin data). We call the v4 REST API directly
  (`api/v4/data`) — no SDK dependency. **Works anonymously** at a low hourly quota; set
  `FINMIND_TOKEN` for a higher limit and fuller financial-statement history (the free tier skips some
  year-end balance sheets, so ROE/leverage can be NaN for older years).
- **Two cadence traps** handled in the provider (and pinned by `tests/test_finmind.py`): the income
  statement is **standalone-quarterly** (annual = sum of 4 quarters) while the cash-flow statement is
  **cumulative YTD** (annual = year-end value, never summed); the balance sheet is point-in-time
  (year-end). FinMind carries no filing date, so `filed_at` is synthesized as fiscal-end + ~90 days
  (TW annual-report deadline) to stay point-in-time. FinMind's free prices are **unadjusted**, hence
  the yfinance price routing above.
- **EODHD `.TW`** — works if already subscribed; **verify TPEX (OTC) + TW fundamentals depth before
  relying on it.**
- **TWSE/TPEX OpenAPI** — free, authoritative, but raw (Big5 encoding quirks).
- **TEJ** — paid institutional standard; only if you ever need deep TW fundamentals.
- **TDCC open data** (`data/providers/tdcc.py`, roadmap 13.9) — the weekly 集保戶股權分散表
  (shareholding-dispersion table), free, key-less, UTF-8 CSV bulk download
  (`opendata.tdcc.com.tw`, dataset `1-5`). FinMind's equivalent (`TaiwanStockHoldingSharesPer`) is
  paid-tier; this is the free substitute. **No historical backfill** — the endpoint only ever
  serves "the current week," so history must be accumulated by running
  `python -m heimdall.research.tdcc_cache` once a week, over real calendar time. Point-in-time lag
  is not officially documented and a live probe found a ≥9-day gap versus a secondary source's
  "next-day" claim — `available_at` uses a conservative `data_date + 14 days` (user decision
  2026-07-12; full writeup in `docs/RESEARCH_LOG.md` entry 014).

## Caveats baked into the design

- yfinance can break/ban without notice → it is wrapped, cached, and replaceable, never assumed.
- Vendors silently backfill restatements → prefer EDGAR as-reported; snapshot fundamentals with the
  retrieval date (`fetched_at`); see `.claude/rules/data-discipline.md`.
- Most free/cheap tiers prohibit commercial redistribution — this project is personal/non-commercial.
