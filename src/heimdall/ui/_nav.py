"""Cross-page navigation helpers for the session-state router defined in ``app.py``.

Pages set ``st.session_state["page"]`` and call ``st.rerun()`` directly, mirroring
``app.py``'s own routing convention, so no page needs to import ``app`` (which
would invert the dependency direction — ``app.py`` imports every page module).
"""

from __future__ import annotations

import streamlit as st

from heimdall.ui.i18n import t


def switch_to(page: str, *, key: str, label: str | None = None) -> None:
    """A button that, when clicked, navigates to another sidebar page.

    ``page`` must be one of ``app.PAGES``'s (English) keys — the canonical page
    identifier, not its translated label.
    """
    if st.button(label or f"{t(page)} →", key=key, type="primary"):
        st.session_state["page"] = page
        st.rerun()


def no_snapshot_cta(*, key: str) -> None:
    """Actionable empty state for any page that needs the snapshot to exist."""
    st.warning(t("This page needs a snapshot to work, and none exists yet."))
    switch_to("Build data", key=key, label="🗂 " + t("Go build one"))
    st.caption(t("Or from a terminal: `uv run python -m heimdall.screener.build`"))
