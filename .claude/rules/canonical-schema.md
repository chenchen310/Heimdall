# Rule: Canonical schema only

The single most load-bearing rule in the codebase. It is what makes data vendors swappable and
Taiwan a plug-in instead of a rewrite.

- **Providers are the only place** vendor-specific shapes may exist (raw JSON, vendor column names,
  vendor symbol formats). Each provider normalizes into the canonical schema before returning.
- **Everything downstream of a provider** — cache, screener, factors, backtest, analytics, ui,
  personas — reads and writes **only** the canonical schema. No module outside `data/providers/` may
  import a vendor SDK or branch on `provider ==`.
- **Symbols are always `TICKER.MARKET`** (`AAPL.US`, `2330.TW`). Bare tickers never appear downstream.
- **Currency is always carried** on price and fundamental rows; never assume USD.
- A source that cannot serve a method raises `NotSupported` — it must not fabricate or silently
  substitute data.

If you find yourself special-casing a vendor outside `data/providers/`, stop — the normalization
belongs in that provider instead. See `docs/ARCHITECTURE.md` §1–2 for the schema and ABC.
