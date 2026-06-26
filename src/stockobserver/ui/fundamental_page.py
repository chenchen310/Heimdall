"""Fundamental dashboard (Goldman lens) — rating box, history, bull/bear, scenarios."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from stockobserver.analytics import fundamental_report
from stockobserver.data.symbols import SymbolError, parse_symbol
from stockobserver.ui._data import get_fundamentals, get_ohlcv
from stockobserver.ui._personas import ai_report


def _f(v: object, n: int = 3) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), n)  # JSON-safe (no NaN)


def render() -> None:
    st.header("🏛 Fundamental — Goldman lens")
    symbol = st.text_input("Symbol (US filer, via EDGAR)", "AAPL.US")
    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    fund = get_fundamentals(symbol)
    if fund.empty:
        st.warning("No fundamentals — EDGAR covers US filers. Try AAPL.US, MSFT.US, KO.US …")
        return
    px = get_ohlcv(symbol, date.today() - timedelta(days=10), date.today())
    price = float(px["adj_close"].iloc[-1]) if not px.empty else float("nan")
    rep = fundamental_report(symbol, fund, price)

    # --- Rating Summary Box ---
    st.subheader("Rating Summary")
    box = st.columns(5)
    box[0].metric("Rating", rep.rating)
    box[1].metric("Score", f"{rep.rating_score:.0f}/100" if pd.notna(rep.rating_score) else "n/a")
    box[2].metric("P/E", f"{rep.valuation.get('pe', float('nan')):.1f}")
    box[3].metric("P/S", f"{rep.valuation.get('ps', float('nan')):.1f}")
    box[4].metric("Rev CAGR", f"{rep.growth.get('revenue_cagr', float('nan')):.1%}")

    # --- history ---
    hist = rep.history
    if not hist.empty and "revenue" in hist:
        h = hist.copy()
        h.index = [d.year for d in h.index]
        st.caption("Revenue by fiscal year")
        st.bar_chart(h["revenue"])
        margins = [m for m in ("gross_margin", "operating_margin", "net_margin") if m in h]
        if margins:
            st.caption("Margins")
            st.line_chart(h[margins])

    # --- bull / bear / scenarios ---
    left, right = st.columns(2)
    left.subheader("Bull case")
    left.markdown("\n".join(f"- {x}" for x in rep.bull) or "—")
    right.subheader("Bear case")
    right.markdown("\n".join(f"- {x}" for x in rep.bear) or "—")
    st.caption("Scenarios — illustrative P/E bands (15× / 22× / 30× latest EPS)")
    st.write({k: round(v, 2) for k, v in rep.scenarios.items()})

    payload = {
        "symbol": symbol,
        "price": _f(price, 2),
        "rating": rep.rating,
        "score": _f(rep.rating_score, 0),
        "valuation": {k: _f(v) for k, v in rep.valuation.items()},
        "growth": {k: _f(v, 4) for k, v in rep.growth.items()},
        "bull": rep.bull,
        "bear": rep.bear,
        "scenarios": {k: _f(v, 2) for k, v in rep.scenarios.items()},
        "history": _history_records(hist),
    }
    ai_report("goldman", payload, symbol)


def _history_records(hist: pd.DataFrame) -> list[dict[str, object]]:
    if hist.empty:
        return []
    keep = [c for c in ("revenue", "net_margin", "fcf", "roe", "debt_to_equity") if c in hist]
    out = hist[keep].copy()
    out.index = [str(d.date()) for d in out.index]
    return out.round(4).reset_index(names="fiscal_end").tail(6).to_dict("records")
