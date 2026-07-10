"""Stock Workbench — one shared symbol, every per-stock analyst lens as a tab.

Replaces five standalone pages (Chart, Fundamental, Technical, Risk, Earnings) that
each demanded their own copy of the same symbol. The symbol is entered **once**,
here, and passed as a plain argument into each lens module's ``render(symbol)`` —
those modules no longer render their own header or symbol input, so they compose
as ``st.tabs`` bodies. Business logic is untouched; this file only wires inputs.

Streamlit renders every tab's body on every script run (only the active tab is
*visually* hidden via CSS), so a single symbol input must live outside ``st.tabs``
— two tabs each instantiating a widget with the same key would collide.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from heimdall.analytics import earnings_report, fundamental_report, risk_report, technical_report
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.research.benchmark import BENCHMARK
from heimdall.ui import (
    _glossary,
    chart_page,
    earnings_page,
    fundamental_page,
    risk_page,
    technical_page,
)
from heimdall.ui._data import fmp_provider, get_fundamentals, get_ohlcv, snapshot
from heimdall.ui.i18n import t

_KEY = "wb_symbol"
_QUICKPICK_KEY = "wb_quickpick"


def render() -> None:
    st.header(t("🔎 Stock Workbench"))
    st.caption(t("One symbol, every analyst lens — pick once, explore below."))
    symbol = _symbol_picker()
    if symbol is None:
        return

    tabs = st.tabs(
        [t("Overview"), t("Chart"), t("Fundamental"), t("Technical"), t("Risk"), t("Earnings")]
    )
    with tabs[0]:
        _overview_tab(symbol)
    with tabs[1]:
        chart_page.render(symbol)
    with tabs[2]:
        fundamental_page.render(symbol)
    with tabs[3]:
        technical_page.render(symbol)
    with tabs[4]:
        risk_page.render(symbol)
    with tabs[5]:
        earnings_page.render(symbol)


def _known_symbols() -> list[str]:
    try:
        return sorted(snapshot()["symbol"].dropna().unique().tolist())
    except FileNotFoundError:
        return []


def _apply_quickpick() -> None:
    picked = st.session_state.get(_QUICKPICK_KEY)
    if picked and picked != "—":
        st.session_state[_KEY] = picked


def _symbol_picker() -> str | None:
    st.session_state.setdefault(_KEY, "AAPL.US")
    known = _known_symbols()
    c1, c2 = st.columns([2, 1])
    with c2:
        if known:
            st.selectbox(
                t("Quick pick from snapshot"),
                ["—", *known],
                key=_QUICKPICK_KEY,
                on_change=_apply_quickpick,
            )
        else:
            st.caption(t("No snapshot yet — type a symbol directly."))
    with c1:
        raw = st.text_input(t("Symbol (TICKER.MARKET)"), key=_KEY)
    try:
        return parse_symbol(raw).canonical
    except SymbolError as exc:
        st.error(str(exc))
        return None


def _safe(col: object, fn: Callable[[str], None], symbol: str, fallback_label: str) -> None:
    """Render one overview tile; any lens's failure degrades to '—', never a crash."""
    with col:  # type: ignore[union-attr]
        try:
            fn(symbol)
        except Exception:  # noqa: BLE001 — deliberately broad: an optional preview tile
            st.metric(fallback_label, "—")


def _overview_tab(symbol: str) -> None:
    st.caption(t("A one-line read from each lens — open a tab below for the full picture."))
    cols = st.columns(4)
    _safe(cols[0], _overview_fundamental, symbol, "Rating")
    _safe(cols[1], _overview_technical, symbol, "Trend (S/M/L)")
    _safe(cols[2], _overview_risk, symbol, "Risk (Beta)")
    _safe(cols[3], _overview_earnings, symbol, "Next earnings")


def _overview_fundamental(symbol: str) -> None:
    fund = get_fundamentals(symbol)
    if fund.empty:
        st.metric("Rating", "—")
        return
    px = get_ohlcv(symbol, date.today() - timedelta(days=10), date.today())
    price = float(px["adj_close"].iloc[-1]) if not px.empty else float("nan")
    rep = fundamental_report(symbol, fund, price)
    sub = f"{rep.rating_score:.0f}/100" if pd.notna(rep.rating_score) else None
    st.metric("Rating", rep.rating, sub, delta_color="off", help=_glossary.help("rating_score"))


def _overview_technical(symbol: str) -> None:
    end = date.today()
    ohlcv = get_ohlcv(symbol, end - timedelta(days=420), end)
    if ohlcv.empty:
        st.metric("Trend (S/M/L)", "—")
        return
    tr = technical_report(symbol, ohlcv)
    trend = "/".join(tr.trend[k][0].upper() for k in ("short", "medium", "long"))
    st.metric("Trend (S/M/L)", trend, help=_glossary.help("trend_sml"))


def _overview_risk(symbol: str) -> None:
    benchmark = BENCHMARK[parse_symbol(symbol).region]
    end = date.today()
    start = end - timedelta(days=420)
    o, b = get_ohlcv(symbol, start, end), get_ohlcv(benchmark, start, end)
    if o.empty or b.empty:
        st.metric("Risk (Beta)", "—")
        return
    r = risk_report(symbol, o, b)
    st.metric(
        "Risk (Beta)",
        f"{r.beta:.2f}",
        f"{r.annual_vol:.0%} vol",
        delta_color="off",
        help=_glossary.help("beta"),
    )


def _overview_earnings(symbol: str) -> None:
    earnings = fmp_provider().get_earnings_dates(symbol)
    rep = earnings_report(symbol, earnings)
    val = str(rep.next_date.date()) if rep.next_date is not None else "—"
    st.metric("Next earnings", val, help=_glossary.help("next_earnings_date"))
