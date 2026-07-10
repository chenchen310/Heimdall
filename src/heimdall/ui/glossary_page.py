"""Indicator Glossary — every metric's definition, direction, and category, searchable.

Seeded entirely from :mod:`heimdall.ui._glossary`, the same data that backs the
inline ``help=`` tooltips across every other page — one source of truth, two
surfaces. Grouped in the app's own 8-lens order so the structure here matches the
mental model the rest of the app already teaches.
"""

from __future__ import annotations

import streamlit as st

from heimdall.ui import _glossary
from heimdall.ui.i18n import current_lang, t

# category -> (icon, English label, Chinese label), in display order.
_CATEGORIES: list[tuple[str, str, str, str]] = [
    ("fundamental", "🏛", "Fundamental (Goldman)", "基本面（高盛視角）"),
    ("technical", "📐", "Technical (Morgan Stanley)", "技術面（Morgan Stanley 視角）"),
    ("risk", "⚖️", "Risk (Bridgewater)", "風險（Bridgewater 視角）"),
    ("earnings", "📰", "Earnings (JPM)", "財報（JPM 視角）"),
    ("rotation", "🔄", "Sector rotation (Citadel)", "產業輪動（Citadel 視角）"),
    ("factors", "🧬", "Multi-factor (RenTech)", "多因子（RenTech 視角）"),
    ("portfolio", "🧺", "ETF portfolio (Vanguard)", "ETF 投組（Vanguard 視角）"),
    ("backtest", "🧪", "Backtest", "回測"),
    ("certification", "🎯", "Today's Picks certification", "今日候選認證"),
]

_DIRECTION_LABEL: dict[str, dict[str, str]] = {
    "higher": {"en": "▲ higher is better", "zh": "▲ 越高越好"},
    "lower": {"en": "▼ lower is better", "zh": "▼ 越低越好"},
    "neutral": {"en": "◆ context-dependent", "zh": "◆ 視情境而定"},
}


def render() -> None:
    st.header(t("📚 Indicator Glossary"))
    st.caption(
        t(
            "What every metric means and how to read it — the same text shown in "
            "the ⓘ tooltips across the app."
        )
    )
    query = st.text_input(t("Search (name or keyword)"), "")

    lang = current_lang()
    entries = _glossary.all_entries()
    if query:
        q = query.strip().lower()
        entries = [e for e in entries if q in e.key.lower() or q in e.text(lang).lower()]

    by_category: dict[str, list[_glossary.Entry]] = {}
    for e in entries:
        by_category.setdefault(e.category, []).append(e)

    shown = False
    for cat, icon, en_label, zh_label in _CATEGORIES:
        rows = by_category.get(cat)
        if not rows:
            continue
        shown = True
        st.subheader(f"{icon} {zh_label if lang == 'zh' else en_label}")
        for e in rows:
            dir_label = _DIRECTION_LABEL[e.direction][lang]
            st.markdown(f"**`{e.key}`** · {dir_label}")
            st.caption(e.text(lang))

    if not shown:
        st.info(t("No indicators match your search."))
