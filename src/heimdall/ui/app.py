"""Streamlit entrypoint:  uv run streamlit run src/heimdall/ui/app.py

A thin shell — each page's logic lives in its own module and calls the core
screener/factors/data packages. Routing is ``st.navigation``: every page has its own
URL (``/todays-picks``…), so a refresh stays put and the browser's back button works.
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Heimdall", page_icon="🛡️", layout="wide")

from heimdall.ui import (  # noqa: E402  (after set_page_config)
    _status,
    backtest_page,
    build_page,
    chips_page,
    etf_page,
    factors_page,
    flows_page,
    glossary_page,
    help_page,
    home_page,
    i18n,
    lab_page,
    macro_page,
    rotation_page,
    screener_page,
    sector_page,
    today_page,
    workbench_page,
)
from heimdall.ui._nav import DEFAULT_PAGE, GOTO_KEY, NAV, PAGE_META, trust_badge  # noqa: E402

RENDER: dict[str, Callable[[], None]] = {
    "Home": home_page.render,
    "Guide": help_page.render,
    "Glossary": glossary_page.render,
    "Today's Picks": today_page.render,
    "Stock Workbench": workbench_page.render,
    "Screener": screener_page.render,
    "Strategy Lab": lab_page.render,
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


def _page(key: str) -> st.Page:
    icon, slug, _trust = PAGE_META[key]

    def run() -> None:
        trust_badge(key)  # every page states how far its numbers can be trusted, first
        _status.data_status()  # …and how fresh each market's data is
        RENDER[key]()

    return st.Page(run, title=i18n.t(key), icon=icon, url_path=slug, default=key == DEFAULT_PAGE)


# The language choice is read before the pages are built (their titles are translated);
# Streamlit draws the navigation first, so the selector shows below the page list.
i18n.language_selector()
PAGES = {key: _page(key) for keys in NAV.values() for key in keys}
nav = st.navigation(
    {i18n.t(group): [PAGES[k] for k in keys] for group, keys in NAV.items()},
    expanded=True,  # all 16 pages visible — the task groups are the map, don't hide half of it
)

pending = st.session_state.pop(GOTO_KEY, None)  # a page's `go(...)` request (or a test's)
if pending in PAGES:
    st.switch_page(PAGES[pending])
nav.run()
