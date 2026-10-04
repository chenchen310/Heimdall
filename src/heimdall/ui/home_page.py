"""Home — "what should I do today?", answered from live state.

The landing page. It ranks nothing: it reads the registry (how many certified / under-review /
incubating signals each market has), the snapshot (does each market have fresh data?) and the
factory runs, then points to the one page that answers the user's next question. Certified
rankings stay on Today's Picks alone (``.claude/rules/signal-certification.md``).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.research import lab
from heimdall.research.today import freshness
from heimdall.screener.snapshot import split_by_region
from heimdall.ui._data import snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui._nav import switch_to
from heimdall.ui.i18n import t
from heimdall.ui.today_page import specs_by_status

_STALE_BDAYS = 5


def render() -> None:
    st.header("🛡️ Heimdall")
    st.caption(
        t(
            "A personal stock-picking tool built on one rule: only trust evidence that has "
            "been validated. Start here — this page shows what needs your attention today."
        )
    )
    st.subheader(t("Today"))
    try:
        groups = split_by_region(snapshot())
    except FileNotFoundError:
        groups = {}
    for region in REGION_CURRENCY:
        _market_card(region, groups.get(region))
    _lab_card()

    st.subheader(t("I want to…"))
    tasks = [
        ("Stock Workbench", "research one stock in depth", "home_go_wb"),
        ("Screener", "find stocks that match my own conditions", "home_go_screener"),
        ("Macro", "understand the market backdrop", "home_go_macro"),
        ("Guide", "learn what each page does and how far to trust it", "home_go_guide"),
    ]
    for page, what, key in tasks:
        left, right = st.columns([3, 1])
        left.markdown(f"… {t(what)}")
        with right:
            switch_to(page, key=key)


def _market_card(region: str, rows: pd.DataFrame | None) -> None:
    """One market: its certified signals, and whether today's data can rank them."""
    certified = specs_by_status(region, "certified")
    review = specs_by_status(region, "under_review")
    has_rows = rows is not None and not rows.empty
    with st.container(border=True):
        st.markdown(f"**{t(region)} ({REGION_CURRENCY[region]})**")
        if certified:
            names = ", ".join(f"{s.name} v{s.version}" for s, _ in certified)
            st.markdown("🟢 " + t("Certified signals: {names}").format(names=names))
        else:
            st.markdown("⚪ " + t("No certified signal — Today's Picks stays empty, by design."))
        for spec, _entry in review:
            st.markdown(
                "🟠 "
                + t("{name} v{v} is under review — its ranking is withheld.").format(
                    name=spec.name, v=spec.version
                )
            )
        if not has_rows:
            st.markdown("🔴 " + t("No {market} stocks in the snapshot.").format(market=t(region)))
        else:
            st.markdown(
                f"{t('Data')}: {len(rows):,} {t('symbols')} · {freshness_word(rows) or ''}"  # type: ignore[arg-type]
            )
        stale = has_rows and freshness(rows) > _STALE_BDAYS  # type: ignore[arg-type]
        if certified and (not has_rows or stale):
            st.warning(
                t("Today's ranking needs fresh {market} data first.").format(market=t(region))
            )
        if not has_rows or stale:  # every page reads the snapshot, certified signal or not
            switch_to(
                "Build data",
                key=f"home_build_{region}",
                label="🗂 " + t("Build {market} data").format(market=t(region)),
            )
        elif certified:
            switch_to(
                "Today's Picks", key=f"home_picks_{region}", label="🎯 " + t("Open Today's Picks")
            )


def _lab_card() -> None:
    runs = lab.list_runs()
    incubating = lab.incubating()
    with st.container(border=True):
        st.markdown(f"**{t('Strategy research')}**")
        if incubating:
            names = ", ".join(f"{i.name} v{i.version}" for i in incubating)
            st.markdown("🟡 " + t("Incubating (watch only): {names}").format(names=names))
        else:
            st.markdown("⚪ " + t("No incubating strategy right now."))
        if runs:
            latest = runs[0]
            n = "?" if latest.missing else f"{latest.n_trials:,}"
            st.caption(
                t("Latest factory run: {run} · N = {n} trials").format(run=latest.run_id, n=n)
            )
        switch_to("Strategy Lab", key="home_lab", label="🔬 " + t("Open Strategy Lab"))
