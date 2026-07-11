"""TW Chips (籌碼) dashboard — descriptive "who is buying" lens, NOT a signal (roadmap 11.5).

Per Taiwan symbol: cumulative 外資/投信 net-buy vs price, foreign holding %, and margin balance —
the daily "who is accumulating" view, kept firmly outside certification (Today's Picks ignores this
page). Computation lives in ``analytics.cumulative_flows``; this file only wires inputs → charts.

Market-wide top-10 net-buy/sell lists (the other half of card 11.5) need FinMind's per-**date** bulk
query, which is **paid-tier** (probed 2026-07-08; see ``FinMindProvider.daily_chips``). On the free
tier that means looping the whole ~2,000-name market per day — quota-prohibitive for an interactive
page — so market-wide flows are deferred to the Market flows page (roadmap 15.2), which builds a
cached per-date store. This page stays per-symbol and quota-safe.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from heimdall.analytics import cumulative_flows
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.ui._data import get_daily_chips, get_ohlcv
from heimdall.ui.i18n import t

_DISCLAIMER = "Descriptive chip data, not a certified signal; Today's Picks ignores this page."
_MARKET_NOTE = (
    "Market-wide top-10 net-buy/sell lists live on the upcoming Market flows page (roadmap 15.2): "
    "FinMind's per-date bulk query is paid-tier, so free-tier market-wide flows are built there "
    "from a cached store. This page is per-symbol."
)


def render() -> None:
    st.header(t("💰 TW Chips — who is buying"))
    st.caption(t(_DISCLAIMER))

    raw = st.text_input(t("Taiwan symbol (TICKER.TW / .TWO)"), value="2330.TW", key="chips_symbol")
    years = int(st.number_input(t("Years of history"), min_value=1, max_value=3, value=1))

    try:
        sym = parse_symbol(raw.strip())
    except SymbolError:
        st.error(t("Not a canonical symbol — use e.g. 2330.TW."))
        return
    if sym.market not in {"TW", "TWO"}:
        st.info(t("Taiwan only — this lens uses TW institutional/margin data."))
        return

    if not st.button(t("Load chip data")):
        st.caption(
            t("Fetches 法人買賣超・外資持股・融資 for one Taiwan symbol (cached after first run).")
        )
        st.info(t(_MARKET_NOTE))
        return

    end = date.today()
    start = end - timedelta(days=years * 365 + 10)
    with st.spinner(t("Fetching chip data…")):
        chips = get_daily_chips(sym.canonical, start, end)
        price = get_ohlcv(sym.canonical, start, end)

    if chips.empty:
        st.warning(t("No chip data for {symbol}.").format(symbol=sym.canonical))
        st.info(t(_MARKET_NOTE))
        return

    _metrics(chips)
    _flows_vs_price(chips, price)
    _holding_and_margin(chips)
    st.info(t(_MARKET_NOTE))


def _metrics(chips: pd.DataFrame) -> None:
    """A quick latest-state read from the raw daily panel."""
    hold = chips["foreign_hold_ratio"].dropna()
    last20 = chips.tail(20)
    cols = st.columns(3)
    cols[0].metric(
        t("Latest foreign holding %"),
        f"{hold.iloc[-1]:.2f}%" if len(hold) else t("n/a"),
    )
    cols[1].metric(
        t("Foreign net-buy (20d)"),
        f"{last20['foreign_net_shares'].fillna(0).sum():,.0f}",
        help=t("Sum of daily 外資 net-buy shares over the last 20 trading days."),
    )
    cols[2].metric(
        t("Trust net-buy (20d)"),
        f"{last20['trust_net_shares'].fillna(0).sum():,.0f}",
        help=t("Sum of daily 投信 net-buy shares over the last 20 trading days."),
    )


def _flows_vs_price(chips: pd.DataFrame, price: pd.DataFrame) -> None:
    st.subheader(t("Institutional net-buy vs price"))
    flows = cumulative_flows(chips)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=flows["date"],
            y=flows["foreign_cum_net"],
            name=t("外資 cumulative net-buy"),
            line={"color": "#2962ff"},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=flows["date"],
            y=flows["trust_cum_net"],
            name=t("投信 cumulative net-buy"),
            line={"color": "#ff6d00"},
        ),
        secondary_y=False,
    )
    if not price.empty:
        fig.add_trace(
            go.Scatter(
                x=price["date"],
                y=price["adj_close"],
                name=t("Price"),
                line={"color": "#9e9e9e", "width": 1},
            ),
            secondary_y=True,
        )
    fig.update_yaxes(title_text=t("Cumulative net-buy (shares)"), secondary_y=False)
    fig.update_yaxes(title_text=t("Price"), secondary_y=True)
    fig.update_layout(height=420, hovermode="x unified", margin={"l": 0, "r": 0, "t": 10, "b": 0})
    st.plotly_chart(fig, width="stretch")


def _holding_and_margin(chips: pd.DataFrame) -> None:
    st.subheader(t("Foreign holding % and margin balance"))
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=(t("Foreign holding %"), t("Margin balance")),
    )
    fig.add_trace(
        go.Scatter(
            x=chips["date"],
            y=chips["foreign_hold_ratio"],
            name=t("Foreign holding %"),
            line={"color": "#00897b"},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=chips["date"],
            y=chips["margin_balance"],
            name=t("Margin balance"),
            line={"color": "#8e24aa"},
        ),
        row=2,
        col=1,
    )
    fig.update_layout(height=420, showlegend=False, margin={"l": 0, "r": 0, "t": 30, "b": 0})
    st.plotly_chart(fig, width="stretch")
