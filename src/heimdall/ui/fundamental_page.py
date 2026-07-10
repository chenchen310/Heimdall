"""Fundamental tab (Stock Workbench, Goldman lens) — rating box, history, bull/bear, scenarios.

Takes ``symbol`` from the workbench's shared picker — no header, no symbol input of
its own, so it composes cleanly as one of several ``st.tabs`` bodies.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from heimdall.analytics import fundamental_report
from heimdall.data.symbols import parse_symbol
from heimdall.ui import _glossary
from heimdall.ui._data import get_fundamentals, get_monthly_revenue, get_ohlcv
from heimdall.ui._personas import ai_report
from heimdall.ui.i18n import t


def _f(v: object, n: int = 3) -> float | None:
    return None if v is None or pd.isna(v) else round(float(v), n)  # JSON-safe (no NaN)


def render(symbol: str) -> None:
    fund = get_fundamentals(symbol)
    if fund.empty:
        st.warning(
            t(
                "No fundamentals found. US filers come from EDGAR (e.g. AAPL.US); "
                "Taiwan from FinMind (e.g. 2330.TW)."
            )
        )
        return
    px = get_ohlcv(symbol, date.today() - timedelta(days=10), date.today())
    price = float(px["adj_close"].iloc[-1]) if not px.empty else float("nan")
    rep = fundamental_report(symbol, fund, price)

    # --- Rating Summary Box ---
    st.subheader(t("Rating Summary"))
    box = st.columns(5)
    box[0].metric("Rating", rep.rating, help=_glossary.help("rating_score"))
    box[1].metric(
        "Score",
        f"{rep.rating_score:.0f}/100" if pd.notna(rep.rating_score) else "n/a",
        help=_glossary.help("rating_score"),
    )
    box[2].metric("P/E", f"{rep.valuation.get('pe', float('nan')):.1f}", help=_glossary.help("pe"))
    box[3].metric("P/S", f"{rep.valuation.get('ps', float('nan')):.1f}", help=_glossary.help("ps"))
    box[4].metric(
        "Rev CAGR",
        f"{rep.growth.get('revenue_cagr', float('nan')):.1%}",
        help=_glossary.help("rev_cagr"),
    )

    # --- history ---
    hist = rep.history
    if not hist.empty and "revenue" in hist:
        h = hist.copy()
        h.index = [d.year for d in h.index]
        st.caption(t("Revenue by fiscal year"))
        st.bar_chart(h["revenue"])
        margins = [m for m in ("gross_margin", "operating_margin", "net_margin") if m in h]
        if margins:
            st.caption(t("Margins"))
            st.line_chart(h[margins])

    # --- bull / bear / scenarios ---
    left, right = st.columns(2)
    left.subheader(t("Bull case"))
    left.markdown("\n".join(f"- {x}" for x in rep.bull) or "—")
    right.subheader(t("Bear case"))
    right.markdown("\n".join(f"- {x}" for x in rep.bear) or "—")
    st.caption(t("Scenarios — illustrative P/E bands (15× / 22× / 30× latest EPS)"))
    scen_cols = st.columns(3)
    for i, (key, mult, label) in enumerate(
        [
            ("bear", "15×", t("Bear scenario")),
            ("base", "22×", t("Base scenario")),
            ("bull", "30×", t("Bull scenario")),
        ]
    ):
        if key in rep.scenarios:
            scen_cols[i].metric(f"{label} ({mult})", f"{rep.scenarios[key]:.2f}")

    if parse_symbol(symbol).market in ("TW", "TWO"):
        _monthly_revenue_panel(symbol)

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


def _monthly_revenue_panel(symbol: str) -> None:
    """Taiwan monthly revenue (月營收) with YoY — a signature TW signal."""
    mr = get_monthly_revenue(symbol, date.today() - timedelta(days=365 * 3 + 30), date.today())
    if mr.empty:
        return
    st.subheader(t("Monthly revenue (TW)"))
    s = mr.set_index("month")["revenue"]
    yoy = s.pct_change(12).iloc[-1]
    c1, c2 = st.columns(2)
    c1.metric(t("Latest month revenue"), f"{s.iloc[-1] / 1e8:,.1f} 億")
    c2.metric(t("YoY"), f"{yoy:+.1%}" if pd.notna(yoy) else "n/a")
    st.bar_chart(s)


def _history_records(hist: pd.DataFrame) -> list[dict[str, object]]:
    if hist.empty:
        return []
    keep = [c for c in ("revenue", "net_margin", "fcf", "roe", "debt_to_equity") if c in hist]
    out = hist[keep].copy()
    out.index = [str(d.date()) for d in out.index]
    return out.round(4).reset_index(names="fiscal_end").tail(6).to_dict("records")
