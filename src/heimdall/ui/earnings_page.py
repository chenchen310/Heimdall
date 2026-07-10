"""Earnings dashboard (JPM lens) — surprise history, beat rate, consensus (FMP)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from heimdall.analytics import earnings_report
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.ui import _glossary
from heimdall.ui._data import fmp_provider
from heimdall.ui._personas import ai_report
from heimdall.ui.i18n import t


def _fmt(v: float, pct: bool = False) -> str:
    if pd.isna(v):
        return "—"
    return f"{v:+.1%}" if pct else f"{v:.2f}"


def render() -> None:
    st.header(t("📰 Earnings — JPM lens"))
    st.caption(t("Consensus estimates and the earnings calendar are paid data (via FMP)."))
    symbol = st.text_input(t("Symbol"), "AAPL.US")
    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    try:
        with st.spinner("Fetching earnings (FMP)…"):
            earnings = fmp_provider().get_earnings_dates(symbol)
    except Exception as exc:  # missing/invalid key or network → degrade gracefully
        st.warning(f"Earnings data unavailable ({exc}). Needs a valid `FMP_API_KEY` in `.env`.")
        return
    rep = earnings_report(symbol, earnings)

    st.subheader(t("Decision Summary"))
    cols = st.columns(4)
    cols[0].metric(
        "Next date",
        str(rep.next_date.date()) if rep.next_date is not None else "—",
        help=_glossary.help("next_earnings_date"),
    )
    cols[1].metric(
        "Consensus EPS", _fmt(rep.next_eps_estimate), help=_glossary.help("consensus_eps")
    )
    cols[2].metric(
        "Beat rate",
        "—" if pd.isna(rep.beat_rate) else f"{rep.beat_rate:.0%}",
        help=_glossary.help("beat_rate"),
    )
    cols[3].metric(
        "Avg surprise", _fmt(rep.avg_surprise, pct=True), help=_glossary.help("avg_surprise")
    )

    if not rep.recent.empty:
        st.caption(t("Recent quarters — actual vs estimate"))
        st.dataframe(rep.recent.round(3), width="stretch", hide_index=True)

    nxt_eps = None if pd.isna(rep.next_eps_estimate) else round(rep.next_eps_estimate, 3)
    beat = None if pd.isna(rep.beat_rate) else round(rep.beat_rate, 3)
    surprise = None if pd.isna(rep.avg_surprise) else round(rep.avg_surprise, 4)
    recent = (
        rep.recent.round(4).astype({"date": str}).to_dict("records") if not rep.recent.empty else []
    )
    payload = {
        "symbol": symbol,
        "next_date": str(rep.next_date.date()) if rep.next_date is not None else None,
        "next_eps_estimate": nxt_eps,
        "beat_rate": beat,
        "avg_surprise": surprise,
        "recent": recent,
    }
    ai_report("jpm", payload, symbol)
