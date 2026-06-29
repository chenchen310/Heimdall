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
    chart_page,
    earnings_page,
    etf_page,
    factors_page,
    fundamental_page,
    i18n,
    macro_page,
    risk_page,
    rotation_page,
    screener_page,
    technical_page,
)

PAGES = {
    "Screener": screener_page.render,
    "Build data": build_page.render,
    "Chart": chart_page.render,
    "Fundamental": fundamental_page.render,
    "Technical": technical_page.render,
    "Risk": risk_page.render,
    "Earnings": earnings_page.render,
    "Backtest": backtest_page.render,
    "Factors": factors_page.render,
    "Macro": macro_page.render,
    "Rotation": rotation_page.render,
    "ETF Portfolio": etf_page.render,
}

# Pages grouped by purpose — one labelled section each in the sidebar.
NAV: dict[str, list[str]] = {
    "Data": ["Build data"],
    "Stock picking": ["Screener", "Chart"],
    "Backtest": ["Backtest"],
    "Analyst lenses": [
        "Fundamental",
        "Technical",
        "Risk",
        "Earnings",
        "Rotation",
        "Factors",
        "ETF Portfolio",
        "Macro",
    ],
}

st.sidebar.title("🛡️ Heimdall")
i18n.language_selector()

# Render each group as a header + its page buttons; the active page is highlighted.
st.session_state.setdefault("page", "Screener")
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
