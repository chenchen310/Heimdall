"""UI edge for the OPTIONAL persona AI reports.

The only UI module that imports ``stockobserver.personas``. Degrades gracefully:
if ``ANTHROPIC_API_KEY`` is unset (or the optional extra is missing) it shows a
hint instead of the button — the computed dashboard works regardless.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st

from stockobserver.ui.i18n import t


def ai_report(persona_key: str, payload: dict[str, Any], title: str) -> None:
    with st.expander(t("🤖 AI report (optional)")):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.caption(
                t(
                    "Set `ANTHROPIC_API_KEY` in `.env` and install the `personas` extra "
                    "(`uv sync --extra personas`) to generate an AI-written report."
                )
            )
            return
        if not st.button(t("Generate report"), key=f"ai_{persona_key}"):
            return
        from stockobserver.personas import render_report

        try:
            with st.spinner(t("Writing report via Claude…")):
                text = render_report(persona_key, {"title": title, **payload})
            st.markdown(text)
        except Exception as exc:  # surface API/key/availability failures in-app
            st.error(f"Report unavailable: {exc}")
