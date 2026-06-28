"""Screener page — build {field, op, value} predicates and run them over the snapshot."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.screener import store
from heimdall.screener.engine import evaluate
from heimdall.screener.model import Predicate, Screen
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui._markets import market_radio
from heimdall.ui.i18n import t

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
    st.header(t("📊 Screener"))
    try:
        full = snapshot()
    except FileNotFoundError:
        st.warning(
            t("No snapshot found. Build one first:\n\n`uv run python -m heimdall.screener.build`")
        )
        return

    # US and Taiwan report in different currencies (USD vs TWD); mixing them in one
    # table makes price/market-cap sorts meaningless, so screen one market at a time.
    groups = split_by_region(full)
    if not groups:
        st.warning(t("Snapshot is empty."))
        return
    region = market_radio(list(groups))
    snap = groups[region]
    currency = REGION_CURRENCY[region]

    as_of = pd.to_datetime(snap["as_of"]).max().date() if "as_of" in snap else "n/a"
    st.caption(f"{len(snap)} {t('symbols')} · {currency} · {t('as of')} {as_of}")
    fields = _numeric_fields(snap)

    # --- choose a starting point: preset or saved screen --------------------
    left, right = st.columns(2)
    preset = left.selectbox(t("Start from preset"), list(_PRESETS), format_func=t)
    saved = right.selectbox(t("…or load saved"), ["—", *store.list_screens()])

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
            "field": st.column_config.SelectboxColumn(t("Field"), options=fields, required=True),
            "op": st.column_config.SelectboxColumn(t("Op"), options=_EDITOR_OPS, required=True),
            "value": st.column_config.NumberColumn(t("Value")),
        },
        key="predicates",
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    sort_by = c1.selectbox(t("Rank by"), fields, index=fields.index("pe") if "pe" in fields else 0)
    ascending = c2.toggle(t("Ascending"), value=True)
    limit = int(c3.number_input(t("Limit"), min_value=1, max_value=len(snap), value=len(snap)))

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

    st.subheader(f"{len(results)} {t('matches')}")
    st.dataframe(results, width="stretch", hide_index=True)

    # --- save the current screen --------------------------------------------
    with st.expander(t("Save this screen")):
        name = st.text_input(t("Name"))
        if st.button(t("Save"), disabled=not name):
            store.save_screen(screen.model_copy(update={"name": name}))
            st.success(f"Saved screen {name!r}")
