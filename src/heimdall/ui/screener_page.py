"""Screener page — build {field, op, value} predicates and run them over the snapshot."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.screener import store
from heimdall.screener.engine import evaluate
from heimdall.screener.model import Predicate, Screen
from heimdall.screener.snapshot import MONETARY_FIELDS, split_by_region
from heimdall.ui import _glossary
from heimdall.ui._data import snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui._markets import market_radio
from heimdall.ui._nav import no_snapshot_cta
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


def _has_monetary(screen: Screen) -> bool:
    """True if any predicate filters a currency-denominated field (market-specific)."""
    return any(p.field in MONETARY_FIELDS for p in screen.predicates)


def render() -> None:
    st.header(t("📊 Screener"))
    try:
        full = snapshot()
    except FileNotFoundError:
        no_snapshot_cta(key="screener_nosnap")
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
    word = freshness_word(snap)
    caption = f"{len(snap)} {t('symbols')} · {currency} · {t('as of')} {as_of}"
    st.caption(f"{caption} · {word}" if word else caption)
    fields = _numeric_fields(snap)

    # --- choose a starting point: preset or saved screen --------------------
    left, right = st.columns(2)
    preset = left.selectbox(t("Start from preset"), list(_PRESETS), format_func=t)
    saved = right.selectbox(t("…or load saved"), ["—", *store.list_screens()])

    if saved != "—":
        loaded = store.load_screen(saved)
        start_rows = [p.model_dump() for p in loaded.predicates]
        meta, action = st.columns([5, 1])
        meta.caption("📝 " + (loaded.description or t("(no description)")))
        if action.button("🗑 " + t("Delete"), key="del_screen"):
            store.delete_screen(saved)
            st.rerun()
        if loaded.market and loaded.market != region and _has_monetary(loaded):
            st.warning(
                t(
                    "This screen was built for {m} ({c}) and uses amount fields "
                    "(e.g. market_cap); its thresholds may not carry over to {cur}."
                ).format(
                    m=t(loaded.market), c=REGION_CURRENCY.get(loaded.market, "?"), cur=currency
                )
            )
    else:
        start_rows = _PRESETS[preset]
    base = pd.DataFrame(start_rows, columns=["enabled", "field", "op", "value"])
    base["enabled"] = [True if pd.isna(v) else bool(v) for v in base["enabled"]]  # presets: on

    # --- editable predicate table -------------------------------------------
    edited = st.data_editor(
        base,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "enabled": st.column_config.CheckboxColumn(t("On"), default=True),
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
        Predicate(
            field=row["field"],
            op=row["op"],
            value=row.get("value"),
            enabled=bool(row["enabled"]) if pd.notna(row.get("enabled")) else True,
        )
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

    # Toggled-off conditions widen the result set; mark the rows they let in so you can
    # see exactly which stocks the relaxed criteria add.
    disabled = [p for p in predicates if not p.enabled]
    added_mask = None
    if disabled and not results.empty:
        strict = screen.model_copy(
            update={"predicates": [p.model_copy(update={"enabled": True}) for p in predicates]}
        )
        try:
            strict_syms = set(evaluate(strict, snap)["symbol"])
            added_mask = ~results["symbol"].isin(strict_syms)
        except (KeyError, ValueError):
            added_mask = None  # a disabled predicate hit a missing field — skip the marking

    st.subheader(f"{len(results)} {t('matches')}")
    if disabled:
        extra = int(added_mask.sum()) if added_mask is not None else 0
        st.caption(
            "🔓 "
            + t("{n} condition(s) off → {m} extra stock(s) (marked ➕).").format(
                n=len(disabled), m=extra
            )
        )
    money = [c for c in results.columns if c in MONETARY_FIELDS]
    if money:
        st.caption(
            "💱 "
            + t("Amount fields are in {currency} — thresholds are market-specific.").format(
                currency=currency
            )
        )
    # Label money columns with the currency; pin `symbol` (and the ➕ marker) so they stay
    # put when the wide table scrolls sideways.
    display = results.rename(columns={c: f"{c} ({currency})" for c in money})
    colcfg: dict[str, object] = {"symbol": st.column_config.Column(pinned=True)}
    if added_mask is not None:
        display.insert(1, "added", added_mask.to_numpy())
        colcfg["added"] = st.column_config.CheckboxColumn(
            "➕", pinned=True, help=t("Appears only because a condition is off")
        )
    for col in display.columns:  # hover help for every field the glossary knows
        if col in colcfg:
            continue
        text = _glossary.help(col.split(" (")[0])  # strip a currency suffix like " (USD)"
        if text:
            colcfg[col] = st.column_config.Column(help=text)
    st.dataframe(display, width="stretch", hide_index=True, column_config=colcfg)

    # --- save the current screen --------------------------------------------
    with st.expander(t("Save this screen")):
        name = st.text_input(t("Name"))
        desc = st.text_area(t("Description (optional)"), height=68)
        if st.button(t("Save"), disabled=not name):
            store.save_screen(
                screen.model_copy(update={"name": name, "description": desc, "market": region})
            )
            st.success(f"{t('Saved screen')} {name!r}")
