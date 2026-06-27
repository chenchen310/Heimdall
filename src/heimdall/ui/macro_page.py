"""Macro outlook (Two Sigma lens) — FRED indicators, signals, regime read."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from heimdall.analytics import macro_dashboard
from heimdall.ui._data import macro_provider
from heimdall.ui._personas import ai_report
from heimdall.ui.i18n import t


def render() -> None:
    st.header(t("🌐 Macro — Two Sigma lens"))
    try:
        with st.spinner("Pulling FRED indicators…"):
            rep = macro_dashboard(macro_provider())
    except Exception as exc:  # missing/invalid key or network → degrade gracefully
        st.warning(
            f"Macro data unavailable ({exc}). Set a valid `FRED_API_KEY` in `.env` "
            "(free at fred.stlouisfed.org)."
        )
        return

    st.subheader(f"{t('Regime read')}: {rep.regime}")
    if rep.signals:
        for s in rep.signals:
            st.markdown(f"- {s}")
    else:
        st.caption(t("No strong macro signals from the key series right now."))

    table = pd.DataFrame(
        [
            {
                "indicator": i.label,
                "latest": round(i.latest, 2),
                "12m change": round(i.change_yoy, 3),
                "as of": i.as_of.date(),
            }
            for i in rep.indicators
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)

    payload = {
        "regime": rep.regime,
        "signals": rep.signals,
        "indicators": [
            {
                "series_id": i.series_id,
                "label": i.label,
                "latest": round(i.latest, 3),
                "change_yoy": round(i.change_yoy, 4),
            }
            for i in rep.indicators
        ],
    }
    ai_report("two_sigma", payload, "US macro")
