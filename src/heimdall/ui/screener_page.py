"""Screener page — build {field, op, value} predicates and run them over the snapshot."""

from __future__ import annotations

from typing import cast

import pandas as pd
import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.factors.scoring import FACTOR_NAMES, factor_scores
from heimdall.screener import store
from heimdall.screener.engine import evaluate, funnel
from heimdall.screener.model import Predicate, Screen
from heimdall.screener.snapshot import (
    MONETARY_FIELDS,
    MULTIPLE_FIELDS,
    PERCENT_FIELDS,
    split_by_region,
)
from heimdall.ui import _glossary, workbench_page
from heimdall.ui._data import snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui._markets import market_radio
from heimdall.ui._nav import no_snapshot_cta
from heimdall.ui.i18n import t

# Range operator ("between") is exposed in the table editor via a second value column;
# "in" stays JSON-only (saved-screen territory) — a list doesn't fit one numeric cell.
_EDITOR_OPS = ["<", "<=", ">", ">=", "==", "!=", "between", "notna"]

# category -> icon, matching the Glossary page's icons so the two surfaces feel like one app.
_CATEGORY_ICON: dict[str, str] = {"fundamental": "🏛", "technical": "📐", "factors": "🧬"}
_CATEGORY_ORDER: list[str] = ["fundamental", "technical", "factors"]

# The cross-sectional factor scores computed on the fly (see `factor_scores` below) —
# not part of the persisted snapshot, so they need their own "no unit suffix" handling.
_SCORE_FIELDS: frozenset[str] = frozenset({f"{name}_score" for name in FACTOR_NAMES}) | {
    "composite_score"
}

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
    # Factor-score presets: value/quality/momentum/growth/composite are 0–100
    # percentile scores computed fresh each render (see `factor_scores` in render()) —
    # a plain-language shortcut to the multi-factor ranking the Factors page exposes.
    "Cheap (value)": [
        {"field": "value_score", "op": ">", "value": 70.0},
    ],
    "High quality": [
        {"field": "quality_score", "op": ">", "value": 70.0},
    ],
    "Strong momentum": [
        {"field": "momentum_score", "op": ">", "value": 70.0},
    ],
    "All-around (composite)": [
        {"field": "composite_score", "op": ">", "value": 75.0},
    ],
}

# preset -> (sort_by, ascending) — each preset's natural "most relevant first" order.
# Applied once when the preset is (re)selected; the user's own choice afterward is
# left alone until they pick a different starting point. See render()'s source-change
# check.
_PRESET_SORT: dict[str, tuple[str, bool]] = {
    "Cheap & profitable": ("pe", True),
    "Oversold quality": ("rsi_14", True),
    "Above 200-day trend": ("pct_above_sma_200", False),
    "Cheap (value)": ("value_score", False),
    "High quality": ("quality_score", False),
    "Strong momentum": ("momentum_score", False),
    "All-around (composite)": ("composite_score", False),
}


def _numeric_fields(snap: pd.DataFrame) -> list[str]:
    return [c for c in snap.columns if pd.api.types.is_numeric_dtype(snap[c])]


def _has_monetary(screen: Screen) -> bool:
    """True if any predicate filters a currency-denominated field (market-specific)."""
    return any(p.field in MONETARY_FIELDS for p in screen.predicates)


def _grouped_fields(fields: list[str]) -> list[str]:
    """Field keys ordered fundamental-then-technical (glossary category), then
    alphabetically — so related metrics cluster in the picker instead of following
    whatever order columns happen to sit in the snapshot table."""

    def rank(field: str) -> tuple[int, str]:
        cat = _glossary.category(field)
        idx = _CATEGORY_ORDER.index(cat) if cat in _CATEGORY_ORDER else len(_CATEGORY_ORDER)
        return (idx, field)

    return sorted(fields, key=rank)


def _field_option_label(field: str) -> str:
    """'🏛 P/E (pe)' for the field picker — a name a non-technical user recognizes,
    with the raw key kept in parens so typing "pe" to search still finds it."""
    icon = _CATEGORY_ICON.get(_glossary.category(field), "")
    prefix = f"{icon} " if icon else ""
    return f"{prefix}{_glossary.label(field)} ({field})"


def _is_scalar_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and pd.notna(value)


def _to_editor_value(field: str, value: object) -> object:
    """Percent fields are stored as a fraction (0.15); the editor shows/accepts
    percentage points (15) instead, since that's what a person actually types."""
    if field in PERCENT_FIELDS and _is_scalar_number(value):
        return float(cast("float", value)) * 100.0
    return value


def _from_editor_value(field: str, value: object) -> object:
    """Inverse of :func:`_to_editor_value` — back to the fraction the snapshot stores."""
    if field in PERCENT_FIELDS and _is_scalar_number(value):
        return float(cast("float", value)) / 100.0
    return value


def _split_between(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Flatten a loaded `between` predicate's ``[lo, hi]`` value into scalar
    ``value``/``value2`` columns — the editor is a spreadsheet, so one cell can't hold
    a 2-element list. Every other row just gets a blank ``value2``."""
    out = []
    for row in rows:
        row = dict(row)
        v = row.get("value")
        if row.get("op") == "between" and isinstance(v, (list, tuple)) and len(v) == 2:
            row["value"], row["value2"] = v[0], v[1]
        else:
            row.setdefault("value2", None)
        out.append(row)
    return out


def _predicate_value(row: pd.Series) -> object:
    """The value(s) a Predicate needs for this row — a ``[lo, hi]`` pair for `between`,
    else the single (already unit-converted) ``value`` cell."""
    field = row["field"]
    if row["op"] == "between":
        return [
            _from_editor_value(field, row.get("value")),
            _from_editor_value(field, row.get("value2")),
        ]
    return _from_editor_value(field, row.get("value"))


def _format_value(field: str, value: object, currency: str) -> str:
    """A predicate's true-unit value, rendered with the suffix that matches its field."""
    if not _is_scalar_number(value):
        return "—" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    v = cast("float", value)
    if field in PERCENT_FIELDS:
        return f"{v * 100:.1f}%"
    if field in MULTIPLE_FIELDS:
        return f"{v:.2f}×"
    if field in MONETARY_FIELDS:
        return f"{v:,.0f} {currency}"
    if field in _SCORE_FIELDS:
        return f"{v:.1f}"
    return f"{v:g}"


def _condition_text(p: Predicate, currency: str) -> str:
    """Plain-language rendering of one predicate, e.g. '🏛 ROE (股東權益報酬率) > 15%'."""
    icon = _CATEGORY_ICON.get(_glossary.category(p.field), "")
    prefix = f"{icon} " if icon else ""
    label = _glossary.label(p.field)
    if p.op == "notna":
        return f"{prefix}{label} {t('has a value')}"
    if p.op == "between" and isinstance(p.value, (list, tuple)) and len(p.value) == 2:
        lo = _format_value(p.field, p.value[0], currency)
        hi = _format_value(p.field, p.value[1], currency)
        return f"{prefix}{label} {t('between')} {lo} {t('and')} {hi}"
    return f"{prefix}{label} {p.op} {_format_value(p.field, p.value, currency)}"


def _preview_text(rows: list[dict[str, object]], currency: str) -> str:
    """Plain-language preview of a preset/saved screen's predicates — shown before
    "Apply" overwrites the working table with them, so switching the dropdown alone
    never silently discards whatever you were already editing."""
    parts = [_condition_text(Predicate(**row), currency) for row in rows]
    return " · ".join(parts) if parts else t("(no conditions)")


def _pool_stats(field: str, snap: pd.DataFrame, currency: str) -> dict[str, str]:
    """One field's min/median/max across the current pool — context for picking a
    threshold instead of guessing it blind."""
    icon = _CATEGORY_ICON.get(_glossary.category(field), "")
    prefix = f"{icon} " if icon else ""
    col = snap[field].dropna() if field in snap.columns else pd.Series(dtype=float)
    if col.empty:
        lo = med = hi = "—"
    else:
        lo = _format_value(field, float(col.min()), currency)
        med = _format_value(field, float(col.median()), currency)
        hi = _format_value(field, float(col.max()), currency)
    return {
        t("Field"): f"{prefix}{_glossary.label(field)}",
        t("Min"): lo,
        t("Median"): med,
        t("Max"): hi,
    }


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
    # Add the 0–100 value/quality/momentum/growth/composite scores (percentile-ranked
    # within this region's cross-section, same as the Factors page) so they're
    # screenable fields too, not just something you see on a different tab.
    snap = factor_scores(groups[region])
    currency = REGION_CURRENCY[region]

    as_of = pd.to_datetime(snap["as_of"]).max().date() if "as_of" in snap else "n/a"
    word = freshness_word(snap)
    caption = f"{len(snap)} {t('symbols')} · {currency} · {t('as of')} {as_of}"
    st.caption(f"{caption} · {word}" if word else caption)
    fields = _numeric_fields(snap)

    # --- choose a starting point: preset or saved screen --------------------
    # Selecting either dropdown only *previews* it — nothing overwrites the working
    # table below until "Apply" is clicked, so browsing presets never silently
    # discards an edit in progress (the P2 fix: no more surprise resets).
    left, right = st.columns(2)
    preset = left.selectbox(t("Start from preset"), list(_PRESETS), format_func=t)
    saved = right.selectbox(t("…or load saved"), ["—", *store.list_screens()])

    loaded: Screen | None = None
    if saved != "—":
        loaded = store.load_screen(saved)
        candidate_rows = [p.model_dump() for p in loaded.predicates]
        st.caption("📝 " + (loaded.description or t("(no description)")))
        st.caption("👁 " + _preview_text(candidate_rows, currency))
        meta, action = st.columns([5, 1])
        apply_clicked = meta.button(
            "✅ " + t('Apply "{name}"').format(name=saved), key="apply_start", type="primary"
        )
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
        candidate_rows = _PRESETS[preset]
        st.caption("👁 " + _preview_text(candidate_rows, currency))
        apply_clicked = st.button(
            "✅ " + t('Apply "{name}"').format(name=t(preset)), key="apply_start", type="primary"
        )

    # First visit ever (no working table yet) auto-applies the default preset, same as
    # before; afterward, only an explicit Apply click updates the working table and the
    # starting point's natural sort — see _PRESET_SORT.
    first_visit = "screener_working_rows" not in st.session_state
    if first_visit or apply_clicked:
        st.session_state["screener_working_rows"] = candidate_rows
        if loaded is not None and loaded.sort_by:
            st.session_state["sort_by"] = loaded.sort_by
            st.session_state["ascending"] = loaded.ascending
        else:
            st.session_state["sort_by"], st.session_state["ascending"] = _PRESET_SORT.get(
                preset, ("pe", True)
            )
        # The editor's own key-bound edit history (cell overrides, added/deleted rows)
        # is a diff applied on top of `data=`; without clearing it, Applying a screen
        # with a different row count would reapply stale per-row edits onto the wrong
        # rows instead of cleanly starting over.
        st.session_state.pop("predicates", None)
    # Defend against a field the current market doesn't have — e.g. a saved screen's
    # sort_by that no longer exists — since the widgets below take their value from
    # session_state alone (no index/value default) once a key is set.
    if st.session_state.get("sort_by") not in fields:
        st.session_state["sort_by"] = "pe" if "pe" in fields else fields[0]
    st.session_state.setdefault("ascending", True)

    start_rows = _split_between(st.session_state["screener_working_rows"])
    base = pd.DataFrame(start_rows, columns=["enabled", "field", "op", "value", "value2"])
    base["enabled"] = [True if pd.isna(v) else bool(v) for v in base["enabled"]]  # presets: on
    # Percent-like fields (roe, margins, growth…) are stored as a fraction (0.15); show/edit
    # them as percentage points (15) instead — see _to_editor_value for why.
    base["value"] = [
        _to_editor_value(f, v) for f, v in zip(base["field"], base["value"], strict=True)
    ]
    base["value2"] = [
        _to_editor_value(f, v) for f, v in zip(base["field"], base["value2"], strict=True)
    ]

    # --- editable predicate table -------------------------------------------
    edited = st.data_editor(
        base,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "enabled": st.column_config.CheckboxColumn(t("On"), default=True),
            "field": st.column_config.SelectboxColumn(
                t("Field"),
                options=_grouped_fields(fields),
                format_func=_field_option_label,
                required=True,
                help=t("Grouped: fundamental fields first, then technical."),
            ),
            "op": st.column_config.SelectboxColumn(t("Op"), options=_EDITOR_OPS, required=True),
            "value": st.column_config.NumberColumn(
                t("Value"),
                help=t(
                    "Percent-like fields (ROE, margins, growth…) are in percentage "
                    "points — type 15 for 15%, not 0.15."
                ),
            ),
            "value2": st.column_config.NumberColumn(
                t("…to"), help=t('The range\'s upper bound — only used when Op is "between".')
            ),
        },
        key="predicates",
    )

    # A threshold shouldn't be a blind guess: show this pool's min/median/max for
    # whatever fields are currently in play, right where you're about to type a number.
    active_fields = sorted({f for f in edited["field"] if pd.notna(f) and f in snap.columns})
    if active_fields:
        with st.expander(t("📏 Pool context for your fields (min / median / max)"), expanded=True):
            st.dataframe(
                pd.DataFrame([_pool_stats(f, snap, currency) for f in active_fields]),
                width="stretch",
                hide_index=True,
            )

    c1, c2, c3 = st.columns([2, 1, 1])
    sort_by = c1.selectbox(t("Rank by"), fields, key="sort_by")
    ascending = c2.toggle(t("Ascending"), key="ascending")
    limit = int(c3.number_input(t("Limit"), min_value=1, max_value=len(snap), value=len(snap)))

    predicates = [
        Predicate(
            field=row["field"],
            op=row["op"],
            value=_predicate_value(row),
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
        steps = funnel(screen, snap)
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
    if steps:
        title = t("🔻 Funnel — which condition narrows the most")
        with st.expander(title, expanded=len(results) == 0):
            funnel_df = pd.DataFrame(
                [
                    {
                        t("Condition"): _condition_text(s.predicate, currency),
                        t("Alone"): s.alone,
                        t("Remaining"): s.remaining,
                    }
                    for s in steps
                ]
            )
            st.dataframe(funnel_df, width="stretch", hide_index=True)
            if len(steps) > 1:
                prev = len(snap)
                worst_drop, worst_step = -1, steps[0]
                for s in steps:
                    if (drop := prev - s.remaining) > worst_drop:
                        worst_drop, worst_step = drop, s
                    prev = s.remaining
                if worst_drop > 0:
                    st.caption(
                        "✂️ "
                        + t("Biggest cut: {cond} ({drop} stock(s) removed).").format(
                            cond=_condition_text(worst_step.predicate, currency), drop=worst_drop
                        )
                    )
    if disabled:
        extra = int(added_mask.sum()) if added_mask is not None else 0
        st.caption(
            "🔓 "
            + t("{n} condition(s) off → {m} extra stock(s) (marked ➕).").format(
                n=len(disabled), m=extra
            )
        )
    # Default to `symbol` + whatever you're actually screening/ranking on + price — not
    # all ~48 columns at once. Anything else is one multiselect away, never hidden for
    # good.
    headline = dict.fromkeys(["symbol", *active_fields, sort_by, "price"])
    default_cols = [c for c in headline if c in results.columns]
    hidden = {*default_cols, "as_of", "currency"}
    other_cols = [c for c in results.columns if c not in hidden]
    extra_cols = st.multiselect(
        t("+ Show more columns"),
        other_cols,
        format_func=_field_option_label,
        key="screener_extra_cols",
    )
    show_cols = [*default_cols, *[c for c in extra_cols if c not in default_cols]]

    money = [c for c in show_cols if c in MONETARY_FIELDS]
    if money:
        st.caption(
            "💱 "
            + t("Amount fields are in {currency} — thresholds are market-specific.").format(
                currency=currency
            )
        )
    # Label money columns with the currency; pin `symbol` (and the ➕ marker) so they stay
    # put when the wide table scrolls sideways.
    display = results[show_cols].rename(columns={c: f"{c} ({currency})" for c in money})
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
    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config=colcfg,
        on_select="rerun",
        selection_mode="single-row",
        key="screener_results",
    )

    # A result is a dead end without this: click a row, then hop straight to the
    # full per-stock picture instead of re-typing the ticker on another page.
    selected = event["selection"]["rows"]
    if selected and "symbol" in display.columns:
        chosen = str(display.iloc[selected[0]]["symbol"])
        if st.button(
            "🔎 " + t("Open {symbol} in Stock Workbench →").format(symbol=chosen),
            key="screener_open_workbench",
            type="primary",
        ):
            workbench_page.open_symbol(chosen)

    # --- save the current screen --------------------------------------------
    with st.expander(t("Save this screen")):
        name = st.text_input(t("Name"))
        desc = st.text_area(t("Description (optional)"), height=68)
        if st.button(t("Save"), disabled=not name):
            store.save_screen(
                screen.model_copy(update={"name": name, "description": desc, "market": region})
            )
            st.success(f"{t('Saved screen')} {name!r}")
