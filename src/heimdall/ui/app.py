"""Streamlit entrypoint:  uv run streamlit run src/heimdall/ui/app.py

A thin shell — each page's logic lives in its own module and calls the core
screener/factors/data packages.
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Heimdall", page_icon="🛡️", layout="wide")

from heimdall.ui import (  # noqa: E402  (after set_page_config)
    backtest_page,
    build_page,
    chips_page,
    etf_page,
    factors_page,
    flows_page,
    glossary_page,
    help_page,
    i18n,
    macro_page,
    rotation_page,
    screener_page,
    sector_page,
    today_page,
    workbench_page,
)

PAGES = {
    "Guide": help_page.render,
    "Glossary": glossary_page.render,
    "Today's Picks": today_page.render,
    "Stock Workbench": workbench_page.render,
    "Screener": screener_page.render,
    "Build data": build_page.render,
    "Backtest": backtest_page.render,
    "Factors": factors_page.render,
    "Macro": macro_page.render,
    "Rotation": rotation_page.render,
    "ETF Portfolio": etf_page.render,
    "TW Chips": chips_page.render,
    "Sector Focus": sector_page.render,
    "TW Market Flows": flows_page.render,
}

# Pages grouped by purpose — one labelled section each in the sidebar. Chart,
# Fundamental, Technical, Risk, and Earnings are no longer separate entries: they
# are tabs inside Stock Workbench (one shared symbol instead of five copies of it).
NAV: dict[str, list[str]] = {
    "Help": ["Guide", "Glossary"],
    "Data": ["Build data"],
    "Stock picking": ["Today's Picks", "Stock Workbench", "Screener"],
    "Backtest": ["Backtest"],
    "Analyst lenses": [
        "Rotation",
        "Factors",
        "ETF Portfolio",
        "Macro",
        "TW Chips",
        "Sector Focus",
        "TW Market Flows",
    ],
}

st.sidebar.title("🛡️ Heimdall")
i18n.language_selector()

# Render each group as a header + its page buttons; the active page is highlighted.
st.session_state.setdefault("page", "Today's Picks")
for _group, _names in NAV.items():
    st.sidebar.markdown(f"**{i18n.t(_group)}**")
    for _name in _names:
        if st.sidebar.button(
            i18n.t(_name),
            key=f"nav_{_name}",
            width="stretch",
            type="primary" if st.session_state.page == _name else "secondary",
        ):
            st.session_state.page = _name
            st.rerun()

st.sidebar.caption(
    i18n.t("Rebuild the snapshot any time:\n\n`uv run python -m heimdall.screener.build`")
)
PAGES[st.session_state.page]()
