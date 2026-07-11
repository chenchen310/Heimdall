"""Sector-focus page (roadmap 14.2) — "which industries lead, and who inside them",
quant core only. Every number comes from ``analytics.sector_focus``; this file wires
inputs -> charts/tables. Descriptive lens: NOT a certified signal, Today's Picks
ignores this page (the fixed caption below, both languages).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from heimdall.analytics import member_table, sector_rollup, sector_table
from heimdall.analytics.sector_focus import trailing_return
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.flows_cache import flows_cache_path
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import get_ohlcv, snapshot
from heimdall.ui._markets import market_radio
from heimdall.ui._nav import no_snapshot_cta
from heimdall.ui.i18n import t

_DISCLAIMER = "Descriptive data, not a certified signal; Today's Picks ignores this page."
_FLOWS_PENDING_NOTE = (
    "Institutional flow by sector isn't built yet — build it from the Market flows "
    "page (roadmap 15.2) to see this."
)
_WINDOWS: dict[str, int] = {"Daily": 1, "Weekly": 5, "Monthly": 21}
_LOOKBACK_DAYS = 45  # covers 21 trading bars + a weekend/holiday buffer


def render() -> None:
    st.header(t("🏭 Sector focus"))
    st.caption(t(_DISCLAIMER))
    region = market_radio(list(BENCHMARK))

    try:
        snap = split_by_region(snapshot()).get(region)
    except FileNotFoundError:
        no_snapshot_cta(key="sector_nosnap")
        return
    if snap is None or snap.empty:
        st.warning(t("No rows for this market in the snapshot."))
        return
    if "sector" not in snap.columns:
        st.info(t("This snapshot predates sector classification — rebuild it to see sectors."))
        return

    window_label = st.radio(
        t("Window"), list(_WINDOWS), format_func=t, horizontal=True, key="sector_window"
    )
    window = _WINDOWS[window_label]

    if not st.button(t("Run sector scan")):
        st.caption(t("Fetches recent prices for every member (cached after the first run)."))
        return

    with st.spinner(t("Computing sector returns…")):
        wanted = tuple(dict.fromkeys([*snap["symbol"], BENCHMARK[region]]))  # dedup, keep order
        by_window = _member_returns(wanted, date.today())

    member_returns = {sym: w.get(window, float("nan")) for sym, w in by_window.items()}
    bench_ret = member_returns.get(BENCHMARK[region], float("nan"))

    table = sector_table(snap, member_returns, bench_ret)
    if table.empty:
        st.info(t("No sector data to show."))
        return

    st.dataframe(
        table.assign(
            ret=(table["ret"] * 100).round(2),
            ret_vs_benchmark=(table["ret_vs_benchmark"] * 100).round(2),
            breadth=(table["breadth"] * 100).round(1),
        ).rename(
            columns={
                "sector": t("Sector"),
                "n_members": t("Members"),
                "n_priced": t("Priced"),
                "ret": t("Return %"),
                "ret_vs_benchmark": t("vs benchmark %"),
                "breadth": t("Breadth %"),
            }
        ),
        width="stretch",
        hide_index=True,
    )

    _tw_flows_block(region, date.today())

    for sec in table["sector"]:
        with st.expander(f"{sec} — {t('members')}"):
            members = member_table(snap, member_returns, sec)
            st.dataframe(
                members.assign(
                    ret=(members["ret"] * 100).round(2),
                    rs_vs_sector=(members["rs_vs_sector"] * 100).round(2),
                ).rename(
                    columns={
                        "symbol": t("Symbol"),
                        "ret": t("Return %"),
                        "rs_vs_sector": t("RS vs sector %"),
                    }
                ),
                width="stretch",
                hide_index=True,
            )


@st.cache_data(ttl=3600, show_spinner=False)
def _member_returns(symbols: tuple[str, ...], as_of: date) -> dict[str, dict[int, float]]:
    """``{symbol: {window_bars: trailing_return}}`` — one price fetch per symbol
    covering the largest window, so toggling 日/週/月 afterward needs no re-fetch."""
    start, end = as_of - timedelta(days=_LOOKBACK_DAYS), as_of
    out: dict[str, dict[int, float]] = {}
    for sym in symbols:
        df = get_ohlcv(sym, start, end)
        if df.empty:
            continue
        adj = df.set_index("date")["adj_close"].sort_index()
        out[sym] = {w: trailing_return(adj, w) for w in _WINDOWS.values()}
    return out


def _tw_flows_block(region: str, as_of: date) -> None:
    if region != "Taiwan":
        return
    st.subheader(t("Institutional flow by sector"))
    path = flows_cache_path(as_of)  # roadmap 15.2's daily cache — built via that page/CLI
    if not path.exists():
        st.info(t(_FLOWS_PENDING_NOTE))
        return
    rollup = sector_rollup(pd.read_parquet(path))
    if rollup.empty:
        st.info(t(_FLOWS_PENDING_NOTE))
        return
    st.dataframe(
        rollup.rename(
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
