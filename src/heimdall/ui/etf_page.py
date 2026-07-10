"""ETF portfolio construction (Vanguard lens) — mean-variance optimized weights."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from heimdall.analytics import optimize_portfolio, prices_wide
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.ui import _glossary
from heimdall.ui._data import get_ohlcv
from heimdall.ui._personas import ai_report
from heimdall.ui.i18n import t


def render() -> None:
    st.header(t("🧺 ETF portfolio — Vanguard lens"))
    tickers = st.text_input(t("ETF basket (comma-separated)"), "SPY.US,TLT.US,GLD.US,QQQ.US,VEA.US")
    c1, c2 = st.columns(2)
    method = c1.selectbox(t("Method"), ["max_sharpe", "min_volatility"])
    years = c2.slider(t("Years of history"), 1, 10, 3)

    if not st.button(t("Optimize")):
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
            st.error(t("Need at least 2 ETFs with overlapping history."))
            return
        try:
            pw = optimize_portfolio(wide, method)
        except Exception as exc:  # optimizer can fail to converge / bad-method
            st.error(f"Optimization failed: {exc}")
            return

    cols = st.columns(3)
    cols[0].metric(
        "Expected return", f"{pw.expected_return:.1%}", help=_glossary.help("expected_return")
    )
    cols[1].metric("Volatility", f"{pw.volatility:.1%}", help=_glossary.help("annual_vol"))
    cols[2].metric("Sharpe", f"{pw.sharpe:.2f}", help=_glossary.help("sharpe"))
    st.subheader(t("Weights"))
    st.bar_chart(pd.Series(pw.weights))
    st.caption(t("History-optimized weights are noisy — a starting point, not gospel."))

    payload = {
        "method": pw.method,
        "weights": pw.weights,
        "expected_return": round(pw.expected_return, 4),
        "volatility": round(pw.volatility, 4),
        "sharpe": round(pw.sharpe, 3),
    }
    ai_report("vanguard", payload, "ETF portfolio")
