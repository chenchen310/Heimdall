"""Market-wide TW money-flow page (roadmap 15.2) — descriptive lens, NOT a signal.

Where TW money went, day/week/month, market-wide: net-buy by investor type, a
by-sector rollup, top-N net-buy/-sell names, 投信 (trust) streak ranking (the
active-money proxy the user chose over per-ETF PCF scraping), and foreign
holding-ratio Δ ranking. All computation lives in ``analytics.flows``; this file
wires inputs -> tables. NOT a certified signal — Today's Picks ignores this page
(the fixed caption below, both languages).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from heimdall.analytics import (
    holding_ratio_delta,
    market_totals,
    sector_rollup,
    top_net_buy_sell,
    trust_streak,
)
from heimdall.research.flows_cache import build_day, load_window
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui.i18n import t

_DISCLAIMER = "Descriptive data, not a certified signal; Today's Picks ignores this page."
_WINDOWS: dict[str, int] = {"Daily": 1, "Weekly": 5, "Monthly": 21}
_TYPES: dict[str, str] = {"Foreign": "foreign", "Trust": "trust", "Dealer": "dealer"}


@st.cache_data(ttl=300, show_spinner=False)
def _load_window(end: date, n_sessions: int) -> pd.DataFrame:
    return load_window(end, n_sessions)


def _tw_universe_size() -> int:
    try:
        tw = split_by_region(snapshot()).get("Taiwan")
    except FileNotFoundError:
        return 0
    return 0 if tw is None else len(tw)


def render() -> None:
    st.header(t("💰 TW market flows"))
    st.caption(t(_DISCLAIMER))

    window_label = st.radio(
        t("Window"), list(_WINDOWS), format_func=t, horizontal=True, key="flows_window"
    )
    n = _WINDOWS[window_label]
    days = _load_window(date.today(), n)

    if days.empty:
        st.info(t("No flow data cached yet."))
        if st.button(t("Build today's flows")):
            with st.spinner(t("Fetching today's market-wide flows…")):
                _build_today()
            _load_window.clear()
            st.rerun()
        st.caption(t("Fetches every TW snapshot symbol's chip data for today (cached after that)."))
        return

    covered = int(days["symbol"].nunique())
    universe = _tw_universe_size()
    if universe:
        msg = t("Coverage: {covered} of {universe} TW snapshot symbols.").format(
            covered=covered, universe=universe
        )
    else:
        msg = t("Coverage: {covered} symbols.").format(covered=covered)
    st.caption(msg)

    _market_totals_block(days)
    _sector_rollup_block(days)
    _top_names_block(days)
    _trust_streak_block(days)
    _holding_delta_block(days)


def _build_today() -> None:
    from heimdall.data import router
    from heimdall.data.cache import CachedProvider
    from heimdall.data.providers import FinMindProvider
    from heimdall.screener.universe import tw_sector_map

    try:
        tw = split_by_region(snapshot()).get("Taiwan")
    except FileNotFoundError:
        tw = None
    universe = list(tw["symbol"]) if tw is not None and not tw.empty else []
    if not universe:
        st.warning(t("No TW rows in the snapshot — build one first."))
        return
    build_day(
        date.today(),
        universe,
        FinMindProvider(),
        CachedProvider(router.price_provider()),
        tw_sector_map(),
    )


def _market_totals_block(days: pd.DataFrame) -> None:
    st.subheader(t("Market-wide net-buy by investor type"))
    totals = market_totals(days)
    cols = st.columns(3)
    labels = {"foreign": t("Foreign"), "trust": t("Trust"), "dealer": t("Dealer")}
    for col, key in zip(cols, ("foreign", "trust", "dealer"), strict=False):
        col.metric(labels[key], f"NT$ {totals[key]:,.0f}")


def _sector_rollup_block(days: pd.DataFrame) -> None:
    st.subheader(t("Net-buy by sector"))
    table = sector_rollup(days)
    if table.empty:
        return
    st.dataframe(
        table.rename(
            columns={
                "sector": t("Sector"),
                "foreign_ntd": t("Foreign NT$"),
                "trust_ntd": t("Trust NT$"),
                "dealer_ntd": t("Dealer NT$"),
            }
        ),
        width="stretch",
        hide_index=True,
    )


def _top_names_block(days: pd.DataFrame) -> None:
    st.subheader(t("Top net buy / sell names"))
    type_label = st.selectbox(t("Investor type"), list(_TYPES), format_func=t, key="flows_top_type")
    table = top_net_buy_sell(days, _TYPES[type_label])
    if table.empty:
        return
    st.dataframe(
        table.rename(columns={"symbol": t("Symbol"), "ntd": t("NT$"), "side": t("Side")}),
        width="stretch",
        hide_index=True,
    )


def _trust_streak_block(days: pd.DataFrame) -> None:
    st.subheader(t("Trust net-buy streak"))
    st.caption(t("主動資金代理 — 含全體投信基金（主動+被動+非ETF）"))  # the card's fixed label
    st.caption(t("Consecutive net-buy/-sell days, longest streak first."))
    table = trust_streak(days)
    if table.empty:
        return
    st.dataframe(
        table.rename(
            columns={
                "symbol": t("Symbol"),
                "streak_days": t("Streak (days)"),
                "direction": t("Direction"),
            }
        ),
        width="stretch",
        hide_index=True,
    )


def _holding_delta_block(days: pd.DataFrame) -> None:
    st.subheader(t("Foreign holding % change"))
    table = holding_ratio_delta(days)
    if table.empty:
        return
    st.dataframe(
        table.rename(columns={"symbol": t("Symbol"), "delta_pp": t("Δ (pp)")}),
        width="stretch",
        hide_index=True,
    )
