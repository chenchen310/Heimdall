"""Screener page — build {field, op, value} predicates and run them over the snapshot."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from stockobserver.screener import store
from stockobserver.screener.engine import evaluate
from stockobserver.screener.model import Predicate, Screen
from stockobserver.ui._data import snapshot

# Scalar-comparison operators exposed in the table editor (lists/between via saved JSON).
_EDITOR_OPS = ["<", "<=", ">", ">=", "==", "!=", "notna"]

_PRESETS: dict[str, list[dict[str, object]]] = {
    "Cheap & profitable": [
        {"field": "pe", "op": "<", "value": 25.0},
        {"field": "roe", "op": ">", "value": 0.15},
        {"field": "net_margin", "op": ">", "value": 0.10},
    ],
    "Oversold quality": [
        {"field": "rsi_14", "op": "<", "value": 40.0},
        {"field": "revenue_growth_yoy", "op": ">", "value": 0.05},
    ],
    "Above 200-day trend": [
        {"field": "pct_above_sma_200", "op": ">", "value": 0.0},
    ],
}


def _numeric_fields(snap: pd.DataFrame) -> list[str]:
    return [c for c in snap.columns if pd.api.types.is_numeric_dtype(snap[c])]


def render() -> None:
    st.header("📊 Screener")
    try:
        snap = snapshot()
    except FileNotFoundError:
        st.warning(
            "No snapshot found. Build one first:\n\n`uv run python -m stockobserver.screener.build`"
        )
        return

    st.caption(
        f"{len(snap)} symbols · snapshot as of "
        f"{pd.to_datetime(snap['as_of']).max().date() if 'as_of' in snap else 'n/a'}"
    )
    fields = _numeric_fields(snap)

    # --- choose a starting point: preset or saved screen --------------------
    left, right = st.columns(2)
    preset = left.selectbox("Start from preset", list(_PRESETS))
    saved = right.selectbox("…or load saved", ["—", *store.list_screens()])

    if saved != "—":
        start_rows = [p.model_dump() for p in store.load_screen(saved).predicates]
    else:
        start_rows = _PRESETS[preset]
    base = pd.DataFrame(start_rows, columns=["field", "op", "value"])

    # --- editable predicate table -------------------------------------------
    edited = st.data_editor(
        base,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "field": st.column_config.SelectboxColumn("Field", options=fields, required=True),
            "op": st.column_config.SelectboxColumn("Op", options=_EDITOR_OPS, required=True),
            "value": st.column_config.NumberColumn("Value"),
        },
        key="predicates",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    sort_by = c1.selectbox("Rank by", fields, index=fields.index("pe") if "pe" in fields else 0)
    ascending = c2.toggle("Ascending", value=True)
    limit = int(c3.number_input("Limit", min_value=1, max_value=len(snap), value=len(snap)))

    predicates = [
        Predicate(field=row["field"], op=row["op"], value=row.get("value"))
        for _, row in edited.iterrows()
        if pd.notna(row.get("field")) and pd.notna(row.get("op"))
    ]
    screen = Screen(
        name="adhoc", predicates=predicates, sort_by=sort_by, ascending=ascending, limit=limit
    )

    try:
        results = evaluate(screen, snap)
    except (KeyError, ValueError) as exc:
        st.error(str(exc))
        return

    st.subheader(f"{len(results)} matches")
    st.dataframe(results, width="stretch", hide_index=True)

    # --- save the current screen --------------------------------------------
    with st.expander("Save this screen"):
        name = st.text_input("Name")
        if st.button("Save", disabled=not name):
            store.save_screen(screen.model_copy(update={"name": name}))
            st.success(f"Saved screen {name!r}")
