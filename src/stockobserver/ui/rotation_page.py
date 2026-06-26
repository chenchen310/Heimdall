"""Sector rotation dashboard (Citadel lens) — sector-ETF relative strength."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from stockobserver.analytics import SECTOR_ETFS, sector_rotation
from stockobserver.ui._data import get_ohlcv
from stockobserver.ui._personas import ai_report


def render() -> None:
    st.header("🔄 Sector rotation — Citadel lens")
    st.caption("The 11 SPDR sector ETFs, ranked by a blended 1/3/6-month relative-strength score.")
    if not st.button("Run rotation scan"):
        st.info("Fetches ~11 sector ETFs (cached after the first run).")
        return

    end = date.today()
    start = end - timedelta(days=420)
    with st.spinner("Fetching sector ETFs…"):
        etfs = {s: get_ohlcv(s, start, end) for s in SECTOR_ETFS}
        rep = sector_rotation(etfs)

    cols = st.columns(3)
    cols[0].metric("Tilt", rep.tilt)
    cols[1].metric("Offense score", f"{rep.offense_score:.1%}")
    cols[2].metric("Defense score", f"{rep.defense_score:.1%}")
    st.dataframe(
        rep.ranks[["sector", "ret_1m", "ret_3m", "ret_6m", "score", "rank"]].round(3),
        width="stretch",
    )
    st.bar_chart(rep.ranks["score"])

    payload = {
        "tilt": rep.tilt,
        "offense_score": round(rep.offense_score, 4),
        "defense_score": round(rep.defense_score, 4),
        "leaders": rep.leaders,
        "laggards": rep.laggards,
        "ranks": rep.ranks[["sector", "ret_1m", "ret_3m", "ret_6m", "score"]]
        .round(4)
        .reset_index()
        .to_dict("records"),
    }
    ai_report("citadel", payload, "US sectors")
