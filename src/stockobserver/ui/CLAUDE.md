# `ui/` — Streamlit front-end (Phase 1+)

A **thin** shell over the modules above. No business logic here — call `screener`, `factors`,
`backtest`, `analytics` and render. Keeping it thin is what makes a future FastAPI/React migration
mechanical.

## Responsibilities
- Multi-page Streamlit app: screener (filter builder + results), per-stock chart (Plotly candlestick +
  MA/RSI/MACD), backtest (params + tear sheet), and the persona dashboards.
- Use `@st.cache_data` for in-session memoization of computed results.
- Optionally surface the AI report button — only when the `personas` extra is installed **and**
  `ANTHROPIC_API_KEY` is set; absence degrades gracefully to the computed dashboard.

## Planned files
```
app.py             # entrypoint: `streamlit run src/stockobserver/ui/app.py`
pages/             # one file per page (screener, chart, backtest, personas…)
components/        # shared chart/table widgets (Plotly; lightweight-charts optional later)
```

## Notes
- Charts default to **Plotly**; TradingView lightweight-charts is an optional later upgrade.
- Never call a provider or compute factors inline — import from the core modules.
