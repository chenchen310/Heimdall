"""Navigation for the ``st.navigation`` router defined in ``app.py``.

Every page has a stable English key (``"Today's Picks"``), a URL slug (``/todays-picks``) and a
trust level. ``app.py`` builds the ``st.Page`` objects from :data:`NAV` / :data:`PAGE_META`; pages
never import ``app`` (that would invert the dependency direction — ``app.py`` imports every page
module). A page asks to move elsewhere with :func:`go`, which records the request and reruns;
``app.py`` turns it into ``st.switch_page`` on the next run. Tests use the same door: set
``session_state["_goto"]`` and run.
"""

from __future__ import annotations

import streamlit as st

from heimdall.ui.i18n import t

GOTO_KEY = "_goto"

# Pages grouped by the job the user is doing, in the order a session usually goes: start with
# what is actionable today, then research, then the backdrop; Taiwan is paused (NORTH_STAR
# amendment, 2026-09-30) so its two TW-only pages sit in their own group; data and help last.
# Chart, Fundamental, Technical, Risk, and Earnings are tabs inside Stock Workbench.
NAV: dict[str, list[str]] = {
    "Start here": ["Home", "Today's Picks"],
    "Research a stock": ["Stock Workbench"],
    "Find candidates": ["Screener", "Factors", "Sector Focus"],
    "Test strategies": ["Strategy Lab", "Backtest"],
    "Market backdrop": ["Macro", "Rotation", "ETF Portfolio"],
    "Taiwan (paused)": ["TW Chips", "TW Market Flows"],
    "Data": ["Build data"],
    "Help": ["Guide", "Glossary"],
}

# page key -> (icon, url slug, trust level). Trust levels: "certified" (act on it),
# "incubating" (watch only), "descriptive" (context, not a signal), "" (a tool, not analysis).
PAGE_META: dict[str, tuple[str, str, str]] = {
    "Home": ("🏠", "home", ""),
    "Today's Picks": ("🎯", "todays-picks", "certified"),
    "Stock Workbench": ("🔎", "workbench", "descriptive"),
    "Screener": ("📊", "screener", "descriptive"),
    "Factors": ("🧬", "factors", "descriptive"),
    "Sector Focus": ("🏭", "sector-focus", "descriptive"),
    "Strategy Lab": ("🔬", "strategy-lab", "incubating"),
    "Backtest": ("🧪", "backtest", "descriptive"),
    "Macro": ("🌐", "macro", "descriptive"),
    "Rotation": ("🔄", "rotation", "descriptive"),
    "ETF Portfolio": ("🧺", "etf-portfolio", "descriptive"),
    "TW Chips": ("💰", "tw-chips", "descriptive"),
    "TW Market Flows": ("💸", "tw-flows", "descriptive"),
    "Build data": ("🗂", "build-data", ""),
    "Guide": ("📖", "guide", ""),
    "Glossary": ("📚", "glossary", ""),
}
DEFAULT_PAGE = "Home"

_BADGES: dict[str, tuple[str, str]] = {
    "certified": ("🟢", "Certified — the only page to act on"),
    "incubating": (
        "🟡",
        "Research — incubating strategies are watch-only, nothing here is certified",
    ),
    "descriptive": ("⚪", "Descriptive — helps you understand, but it is not a buy/sell signal"),
}


def trust_badge(page: str) -> None:
    """The page's trust level, right under its header — the same three levels the Guide uses."""
    level = PAGE_META[page][2]
    if level in _BADGES:
        icon, text = _BADGES[level]
        st.caption(f"{icon} **{t(text)}**")


def go(page: str) -> None:
    """Navigate to another page (by its English key) on the next run."""
    st.session_state[GOTO_KEY] = page
    st.rerun()


def switch_to(page: str, *, key: str, label: str | None = None) -> None:
    """A button that, when clicked, navigates to another page.

    ``page`` must be one of :data:`PAGE_META`'s (English) keys — the canonical page
    identifier, not its translated label.
    """
    if st.button(label or f"{t(page)} →", key=key, type="primary"):
        go(page)


def no_snapshot_cta(*, key: str) -> None:
    """Actionable empty state for any page that needs the snapshot to exist."""
    st.warning(t("This page needs a snapshot to work, and none exists yet."))
    switch_to("Build data", key=key, label="🗂 " + t("Go build one"))
    st.caption(t("Or from a terminal: `uv run python -m heimdall.screener.build`"))
