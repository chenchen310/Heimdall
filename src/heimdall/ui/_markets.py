"""Shared US/Taiwan market selector for cross-section pages.

US and Taiwan report in different currencies (USD vs TWD), so any page showing a
cross-section (screener, factor ranking, factor portfolio) renders one market at a
time. Centralizing the selector keeps its label — ``region (currency)`` — identical
across pages.
"""

from __future__ import annotations

import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.ui.i18n import t


def market_label(region: str) -> str:
    """``"US"`` → ``"US (USD)"`` — region translated, currency code left as jargon."""
    return f"{t(region)} ({REGION_CURRENCY.get(region, '')})"


def market_radio(regions: list[str], *, key: str | None = None) -> str:
    """Horizontal US/Taiwan picker; returns the chosen region key."""
    return str(st.radio(t("Market"), regions, format_func=market_label, horizontal=True, key=key))
