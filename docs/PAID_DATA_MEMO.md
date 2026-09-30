# Paid-data decision memo (ROADMAP 18.11, executes 12.3)

> Written 2026-09-30. Every price and coverage claim below was checked on the vendor's own site
> (or a search result quoting it) **on that date** — see Sources. Prices change; re-verify before
> paying. **Nothing was bought, no account was created, no key was added.** This memo ends with one
> budget question for the user.

## 1. Why this memo exists

After RESEARCH_LOG 001–018, no US signal has certified on free data. Two gaps free data cannot
close, and both sit under every US number this app shows:

- **(a) Survivorship.** The research universe is *today's* VTI constituents, so every backtest is
  stamped `current_universe (optimistic)`. Delisted, acquired and bankrupt names are missing from
  both the price history and the universe. EDGAR has their fundamentals — they filed — but there is
  no free source of their **prices**, and no free point-in-time **membership** list.
- **(b) Analyst estimates and revisions.** NORTH_STAR limitation 2 names estimate revisions as the
  strongest documented signal family. Free sources carry no as-of history of consensus estimates, so
  a revision signal cannot be built point-in-time.

A third reason is new with Phase 18. The factory's F1 gate deflates by the number of trials, so a
large search needs a **stronger** edge to pass (roadmap 18.5, recorded finding). Better data is the
honest way to find stronger edges; loosening gates is not.

## 2. Gap (a) — survivorship-free US prices (+ PIT fundamentals)

| Vendor / product | What closes the gap | What doesn't | Price (as listed 2026-09-30) | Fit here |
| --- | --- | --- | --- | --- |
| **Sharadar Core US Equities Bundle** (Nasdaq Data Link) | Fundamentals, equity prices, insiders and institutional holdings in one feed. Active **and delisted** coverage ("21,000+ companies", history from **Jan 1998**). Marketed as "point-in-time ready, nearly completely free of survivorship bias". Non-professional license exists. | — | **Not shown without a Nasdaq Data Link login** ("Log in … to view pricing information"). | **Best single fix.** Python API, macOS-friendly. One `DataProvider` would replace the price *and* universe gaps and also cross-check EDGAR. |
| **Norgate Data — Platinum** | Delisted securities + **historical index constituents**, back to 1990 | Fundamentals are **current-only**, with no history. Norgate Data Updater is **Windows-only**, so it would need a Windows VM on this Mac. | US$630 / 12 months (US$346.50 / 6). Diamond (to 1950): US$787.50 / 12. | Strong for prices + PIT index membership. Awkward to integrate on macOS. |
| **EODHD — ALL-IN-ONE** | 30+ yrs EOD; delisted **prices** for "26,000+ US tickers (mostly from January 2000)" | Fundamentals for a delisted company only if it was delisted **after 2018**; before that, EOD only. EDGAR could fill those fundamentals via CIK, but mapping dead tickers to CIKs is extra work. | US$99.99/mo or US$999.90/yr. The **Historian** plan (EOD only, 30+ yrs) is US$19.99/mo or US$199/yr, and EODHD says delisted tickers are available in any package. | **Cheapest price-only fix.** Historian delisted prices + our free EDGAR fundamentals. Needs a historical ticker→CIK map. |
| **Tiingo Power** + Fundamentals add-on | 30+ yrs EOD. The fundamentals add-on is as-reported/PIT and includes some delisted tickers ("≈1,000 delisted tickers with full fundamental history"). | Delisted coverage looks partial. The pricing page does not state whether delisted tickers are in EOD. | Power US$30/mo or US$300/yr. The add-on is quoted at US$49.99/mo or US$299/yr for 20+ yrs in a search result; the pricing page says "contact sales". | Partial fix. |
| **FMP** Premium / Ultimate | "up to 30 years" history; a delisted-companies list | Survivorship completeness is not documented. Bulk access is Ultimate-only. | Premium US$49/mo, Ultimate US$99/mo (billed annually; per search results — the pricing page returned 403 to the fetcher). | Unclear; would need a trial to verify. |

**Free fallback (the 17.B "survivorship-lite" idea):** a committed historical S&P 500 membership
list, from public datasets on GitHub.
- It would fix *membership* survivorship for the large-cap tier (`us_large`).
- It cannot fix *prices*: yfinance has no history for most dead tickers, so those rows would drop
  out. The optimism would become a **measured bound**, not a cure.
- Cost is one data file plus one universe option.

## 3. Gap (b) — analyst estimate revision history

| Vendor / product | Coverage | PIT? | Price | Fit |
| --- | --- | --- | --- | --- |
| **Zacks — North American Consensus Earnings Estimate History (ZEEH)**, Nasdaq Data Link | "23,000+ US, Canadian companies", history **Jan 1979**, daily, 1-day reporting lag. Mean/median/high/low, number of analysts, and counts of **revisions up / down**. | **Yes** — a dated history of the consensus. This is exactly what a revision signal needs. | **Login required** to view. | **The** candidate for a revisions family. |
| **FMP** analyst-estimates endpoint | Estimates per fiscal period | The public docs describe estimates per period, not a dated as-of history of consensus. Without as-of snapshots, a revision signal cannot be backtested point-in-time. **Verify before relying on it.** | Included in paid plans (above) | Probably unsuitable for certification research. |
| FactSet / Refinitiv I/B/E/S | Institutional gold standard | Yes | Enterprise pricing (out of scope for a personal budget) | — |

## 4. What each purchase would change in this program

- **Survivorship-free universe (gap a).**
  - Every certified number could drop the `current_universe (optimistic)` stamp and become an honest estimate.
  - Hand-tested families could be **reopened with new data**, which playbook §4 rule 2 allows: reopening requires new *data*, not new weights. That includes fcf_yield, whose in-sample skill failed OOS.
  - Integration: one provider, one `panel_us` rebuild with a reproduction gate, plus a new universe root (dead names included).
- **Estimate revisions (gap b).** A new, documented, orthogonal family (`us-revisions`) with its own 3-attempt budget, and new factory pool features. Integration: one provider (a `get_estimates` history), PIT-keyed on the vendor's publication date, plus one rebuild.
- **Neither purchase** changes a gate, a vault rule, or an existing certification.

## 5. Recommendation

1. **First, look up two prices while logged in to Nasdaq Data Link** (free account, non-professional license):
   - the Sharadar Core US Equities Bundle;
   - Zacks ZEEH.

   Sharadar is the single most complete fix for gap (a) that works natively on macOS/Python, and ZEEH is the proper PIT source for gap (b).
2. **If budget is tight:** EODHD Historian (US$199/yr) for delisted prices plus our free EDGAR fundamentals is the cheapest route to a survivorship-free universe. The cost is building a historical ticker→CIK map.
3. **If there is no budget:** implement the free S&P 500 membership fallback, which turns the survivorship stamp into a measured bound, and accept the free-data ceiling.

## 6. The budget question for the user

> **How much per year are you willing to spend on data?**
> - **≈ US$0**: free S&P 500 membership fallback only.
> - **≈ US$200–300/yr**: EODHD Historian — delisted prices + EDGAR fundamentals.
> - **Whatever Sharadar's non-professional bundle costs**: check it while logged in. This is the most complete survivorship fix.
> - **Plus Zacks ZEEH**: adds an estimate-revisions family.

## Sources (accessed 2026-09-30)

- Norgate packages and prices: https://norgatedata.com/stockmarketpackages.php
- Norgate fundamentals are current-only, and the updater is Windows-only: https://norgatedata.com/data-package-faq.php, https://norgatedata.com/ndu-overview.php
- Sharadar coverage: https://sharadar.com/ and https://data.nasdaq.com/databases/SFA (pricing behind login)
- Sharadar datasheet: https://resources.quandl.com/a/res-hub/Sharadar_Datasheet_final.pdf
- Zacks ZEEH: https://data.nasdaq.com/databases/ZEEH (pricing behind login)
- EODHD plans: https://eodhd.com/pricing
- EODHD delisted coverage: https://eodhd.com/financial-academy/financial-faq/historical-stock-prices-for-delisted-companies
- Tiingo plans: https://www.tiingo.com/about/pricing
- Tiingo fundamentals: https://www.tiingo.com/products/fundamental-data-api
- FMP plans: https://site.financialmodelingprep.com/pricing-plans (403 to the fetcher; figures via search results)
