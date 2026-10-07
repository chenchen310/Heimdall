"""The data-status line under every page's trust badge: how fresh each market's data is.

Replaces the old sidebar "rebuild with this CLI command" caption — the Build data page does
that now, and what a user needs while browsing is whether the numbers on screen are current
(and whether a market has any data at all: "Taiwan 0" explains an empty Taiwan ranking). It
sits at the top of the page, not in the sidebar: with all 16 pages listed, anything below the
navigation is off-screen.
"""

from __future__ import annotations

import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui.i18n import t


def data_status() -> None:
    try:
        groups = split_by_region(snapshot())
    except FileNotFoundError:
        st.caption("🔴 " + t("No snapshot yet — open Build data."))
        return
    parts = []
    for region in REGION_CURRENCY:
        rows = groups.get(region)
        if rows is None or rows.empty:
            parts.append(f"⚫ {t(region)} · {t('no data')}")
        else:
            parts.append(
                f"{t(region)} · {len(rows):,} {t('symbols')} · {freshness_word(rows) or ''}"
            )
    st.caption(f"{t('Data status')}: " + "　|　".join(parts))
