"""Risk dashboard (Bridgewater lens) — vol, Beta, drawdown, VaR/CVaR, stress."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from heimdall.analytics import risk_report
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.ui import _glossary
from heimdall.ui._data import get_ohlcv
from heimdall.ui._personas import ai_report
from heimdall.ui.i18n import t


def render() -> None:
    st.header(t("⚖️ Risk — Bridgewater lens"))
    c1, c2 = st.columns([2, 1])
    symbol = c1.text_input(t("Symbol"), "AAPL.US")
    benchmark = c2.text_input(t("Benchmark"), "SPY.US")
    try:
        parse_symbol(symbol)
        parse_symbol(benchmark)
    except SymbolError as exc:
        st.error(str(exc))
        return

    end = date.today()
    start = end - timedelta(days=420)
    o, b = get_ohlcv(symbol, start, end), get_ohlcv(benchmark, start, end)
    if o.empty or b.empty:
        st.warning(t("No price data for the symbol or benchmark."))
        return
    r = risk_report(symbol, o, b)

    st.subheader(t("Risk dashboard"))
    row1 = st.columns(4)
    row1[0].metric("Annual vol", f"{r.annual_vol:.1%}", help=_glossary.help("annual_vol"))
    row1[1].metric(f"Beta vs {benchmark}", f"{r.beta:.2f}", help=_glossary.help("beta"))
    row1[2].metric("Max drawdown", f"{r.max_drawdown:.1%}", help=_glossary.help("max_drawdown"))
    row1[3].metric("Liquidity", r.liquidity, help=_glossary.help("liquidity"))
    row2 = st.columns(4)
    row2[0].metric("VaR 95% (1-day)", f"{r.var_95:.2%}", help=_glossary.help("var_95"))
    row2[1].metric("CVaR 95% (1-day)", f"{r.cvar_95:.2%}", help=_glossary.help("cvar_95"))
    row2[2].metric("Sharpe", f"{r.sharpe:.2f}", help=_glossary.help("sharpe"))
    row2[3].metric(
        "Recession stress",
        f"{r.recession_stress:.1%}",
        help=_glossary.help("recession_stress"),
    )
    st.caption(
        f"Correlation to {benchmark}: {r.correlation:.2f} · recession stress = Beta × a −30% "
        "market shock (illustrative). Treat all figures as point estimates."
    )

    payload = {
        "symbol": symbol,
        "benchmark": benchmark,
        "annual_vol": round(r.annual_vol, 4),
        "beta": round(r.beta, 3),
        "correlation": round(r.correlation, 3),
        "max_drawdown": round(r.max_drawdown, 4),
        "var_95_daily": round(r.var_95, 4),
        "cvar_95_daily": round(r.cvar_95, 4),
        "downside_vol": round(r.downside_vol, 4),
        "sharpe": round(r.sharpe, 3),
        "recession_stress": round(r.recession_stress, 4),
        "liquidity": r.liquidity,
    }
    ai_report("bridgewater", payload, symbol)
