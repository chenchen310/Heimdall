# Data Sources

Decision reference for which vendor feeds what, and when to pay. All vendors are accessed through the
`DataProvider` ABC, so swapping or adding one is local to `src/heimdall/data/providers/`.

> Pricing gathered mid-2026 and is volatile — verify on official pages before subscribing. FMP quoted
> prices are annual-commitment rates (month-to-month is higher).

## Use these for free regardless of paid tier

- **SEC EDGAR** — gold standard for **point-in-time** US fundamentals. `companyfacts`/`frames` JSON
  give as-reported XBRL with filing dates → the best mitigation for fundamental look-ahead bias. No
  key; descriptive `User-Agent` required (~10 req/s). Feeds Goldman/JPM/RenTech.
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

## Taiwan (Phase 6)

- **FinMind** — recommended TW source. Open-source, 75+ datasets (TWSE+TPEX prices, financials, cash
  flow, **monthly revenue**, institutional flows, margin data). Free 300 req/hr (600 registered);
  paid Backer ≈ US$14/mo, Sponsor ≈ US$31/mo unlock adjusted prices/real-time/bulk. Python SDK
  (`FinMind.data.DataLoader`).
- **EODHD `.TW`** — works if already subscribed; **verify TPEX (OTC) + TW fundamentals depth before
  relying on it.**
- **TWSE/TPEX OpenAPI** — free, authoritative, but raw (Big5 encoding quirks).
- **TEJ** — paid institutional standard; only if you ever need deep TW fundamentals.

## Caveats baked into the design

- yfinance can break/ban without notice → it is wrapped, cached, and replaceable, never assumed.
- Vendors silently backfill restatements → prefer EDGAR as-reported; snapshot fundamentals with the
  retrieval date (`fetched_at`); see `.claude/rules/data-discipline.md`.
- Most free/cheap tiers prohibit commercial redistribution — this project is personal/non-commercial.
