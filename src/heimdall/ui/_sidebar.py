"""Sidebar footer: how fresh each market's data is, at a glance on every page.

Replaces the old "rebuild with this CLI command" caption — the Build data page does that now,
and what a user actually needs while browsing is whether the numbers on screen are current
(and whether a market has any data at all: "Taiwan 0" explains an empty Taiwan ranking).
"""

from __future__ import annotations

import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui.i18n import t


def data_status() -> None:
    st.sidebar.markdown(f"**{t('Data status')}**")
    try:
        groups = split_by_region(snapshot())
    except FileNotFoundError:
        st.sidebar.caption("🔴 " + t("No snapshot yet — open Build data."))
        return
    for region in REGION_CURRENCY:
        rows = groups.get(region)
        if rows is None or rows.empty:
            st.sidebar.caption(f"⚫ {t(region)} · {t('no data')}")
            continue
        word = freshness_word(rows) or ""
        st.sidebar.caption(f"{t(region)} · {len(rows):,} {t('symbols')} · {word}")
