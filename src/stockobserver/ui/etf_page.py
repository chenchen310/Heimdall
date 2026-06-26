"""ETF portfolio construction (Vanguard lens) — mean-variance optimized weights."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from stockobserver.analytics import optimize_portfolio, prices_wide
from stockobserver.data.symbols import SymbolError, parse_symbol
from stockobserver.ui._data import get_ohlcv
from stockobserver.ui._personas import ai_report


def render() -> None:
    st.header("🧺 ETF portfolio — Vanguard lens")
    tickers = st.text_input("ETF basket (comma-separated)", "SPY.US,TLT.US,GLD.US,QQQ.US,VEA.US")
    c1, c2 = st.columns(2)
    method = c1.selectbox("Method", ["max_sharpe", "min_volatility"])
    years = c2.slider("Years of history", 1, 10, 3)

    if not st.button("Optimize"):
        return
    symbols = [s.strip() for s in tickers.split(",") if s.strip()]
    try:
        for s in symbols:
            parse_symbol(s)
    except SymbolError as exc:
        st.error(str(exc))
        return

    end = date.today()
    start = end - timedelta(days=365 * years + 30)
    with st.spinner("Fetching prices and optimizing…"):
        wide = prices_wide({s: get_ohlcv(s, start, end) for s in symbols})
        if wide.shape[1] < 2:
            st.error("Need at least 2 ETFs with overlapping history.")
            return
        try:
            pw = optimize_portfolio(wide, method)
        except Exception as exc:  # optimizer can fail to converge / bad-method
            st.error(f"Optimization failed: {exc}")
            return

    cols = st.columns(3)
    cols[0].metric("Expected return", f"{pw.expected_return:.1%}")
    cols[1].metric("Volatility", f"{pw.volatility:.1%}")
    cols[2].metric("Sharpe", f"{pw.sharpe:.2f}")
    st.subheader("Weights")
    st.bar_chart(pd.Series(pw.weights))
    st.caption("History-optimized weights are noisy — a starting point, not gospel.")

    payload = {
        "method": pw.method,
        "weights": pw.weights,
        "expected_return": round(pw.expected_return, 4),
        "volatility": round(pw.volatility, 4),
        "sharpe": round(pw.sharpe, 3),
    }
    ai_report("vanguard", payload, "ETF portfolio")
