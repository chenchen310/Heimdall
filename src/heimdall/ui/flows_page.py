"""Market-wide TW money-flow page (roadmap 15.2/15.3) — descriptive lens, NOT a signal.

Two tabs. **Institutional Flows** (day/week/month, market-wide): net-buy by
investor type, a by-sector rollup, top-N net-buy/-sell names, 投信 (trust)
streak ranking (the active-money proxy the user chose over per-ETF PCF
scraping), and foreign holding-ratio Δ ranking. **Big Holders (大戶)**: weekly/
monthly risers-and-fallers in TDCC's ≥400-lot concentration (roadmap 15.3),
liquidity-floored so micro-caps don't dominate, on its honest weekly cadence —
never interpolated to daily. All computation lives in ``analytics.flows``/
``analytics.big_holder``; this file wires inputs -> tables. NOT a certified
signal — Today's Picks ignores this page (the fixed caption below, both
languages).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from heimdall.analytics import (
    holding_ratio_delta,
    market_totals,
    monthly_delta_ranking,
    sector_rollup,
    top_net_buy_sell,
    trust_streak,
    weekly_delta_ranking,
)
from heimdall.data.providers.tdcc import AVAILABILITY_LAG, load_cached_weeks
from heimdall.research import gates
from heimdall.research.flows_cache import build_day, load_window
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui.i18n import t

_DISCLAIMER = "Descriptive data, not a certified signal; Today's Picks ignores this page."
_WINDOWS: dict[str, int] = {"Daily": 1, "Weekly": 5, "Monthly": 21}
_TYPES: dict[str, str] = {"Foreign": "foreign", "Trust": "trust", "Dealer": "dealer"}
_BIG_HOLDER_PERIODS: tuple[str, ...] = ("Weekly", "Monthly")
_TOP_N = 10


@st.cache_data(ttl=300, show_spinner=False)
def _load_window(end: date, n_sessions: int) -> pd.DataFrame:
    return load_window(end, n_sessions)


@st.cache_data(ttl=300, show_spinner=False)
def _load_tdcc_weeks() -> pd.DataFrame:
    return load_cached_weeks()


def _tw_universe_size() -> int:
    try:
        tw = split_by_region(snapshot()).get("Taiwan")
    except FileNotFoundError:
        return 0
    return 0 if tw is None else len(tw)


def render() -> None:
    st.header(t("💰 TW market flows"))
    st.caption(t(_DISCLAIMER))

    flows_tab, big_holder_tab = st.tabs([t("Institutional Flows"), t("Big Holders (大戶)")])
    with flows_tab:
        _flows_tab()
    with big_holder_tab:
        _big_holder_tab()


def _flows_tab() -> None:
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


def _big_holder_tab() -> None:
    st.caption(
        t(
            "TDCC publishes this weekly, with a conservative {lag}-day availability lag — "
            "never interpolated to daily."
        ).format(lag=AVAILABILITY_LAG.days)
    )
    period = st.radio(
        t("Period"),
        list(_BIG_HOLDER_PERIODS),
        format_func=t,
        horizontal=True,
        key="big_holder_period",
    )
    weeks = _load_tdcc_weeks()
    if weeks.empty:
        st.info(t("No TDCC big-holder data cached yet."))
        st.caption(t("Build it with: `uv run python -m heimdall.research.tdcc_cache`"))
        return

    as_of = pd.Timestamp(date.today())
    rank_fn = weekly_delta_ranking if period == "Weekly" else monthly_delta_ranking
    ranking = rank_fn(weeks, as_of)
    if ranking.empty:
        st.info(t("Not enough accumulated weeks yet for this view."))
        return
    ranking = _apply_liquidity_floor(ranking)
    if ranking.empty:
        st.info(t("No liquid (≥ the §3 floor) names in this ranking yet."))
        return

    cols = {"symbol": t("Symbol"), "delta_pp": t("Δ (pp)"), "latest_pct": t("Latest 大戶 %")}
    st.subheader(t("Risers — rising concentration"))
    st.dataframe(ranking.head(_TOP_N).rename(columns=cols), width="stretch", hide_index=True)
    st.subheader(t("Fallers — falling concentration"))
    st.dataframe(
        ranking.tail(_TOP_N).sort_values("delta_pp").rename(columns=cols),
        width="stretch",
        hide_index=True,
    )


def _apply_liquidity_floor(ranking: pd.DataFrame) -> pd.DataFrame:
    """§3 hygiene floor (NT$50M 21-day dollar volume) so illiquid names — which
    can swing a tiny-float big-holder % wildly — don't dominate the ranking."""
    try:
        snap = snapshot()
    except FileNotFoundError:
        return ranking  # no snapshot to filter against — show unfiltered rather than empty
    if "dollar_vol_21d" not in snap.columns:
        return ranking
    floor = gates.MIN_DOLLAR_VOL_21D["Taiwan"]
    liquid = set(snap.loc[snap["dollar_vol_21d"] >= floor, "symbol"])
    return ranking[ranking["symbol"].isin(liquid)].reset_index(drop=True)


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
