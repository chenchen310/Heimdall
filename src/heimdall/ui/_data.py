"""Cached data accessors for the UI. Thin wrappers — all logic is in core modules."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from heimdall.data import router
from heimdall.data.base import DataProvider
from heimdall.data.cache import CachedProvider
from heimdall.data.providers import FinMindProvider, FmpProvider, FredProvider
from heimdall.screener.snapshot import load_snapshot


@st.cache_resource
def price_provider() -> CachedProvider:
    # yfinance serves US + Taiwan (adjusted); routed so a market can be repointed later.
    return CachedProvider(router.price_provider())


@st.cache_resource
def fundamentals_provider() -> DataProvider:
    # Routes by market: EDGAR for US, FinMind for Taiwan.
    return router.fundamentals_provider()


@st.cache_resource
def macro_provider() -> FredProvider:
    return FredProvider()


@st.cache_resource
def fmp_provider() -> FmpProvider:
    return FmpProvider()


@st.cache_resource
def finmind_provider() -> FinMindProvider:
    return FinMindProvider()


@st.cache_data(ttl=3600, show_spinner=False)
def get_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    return price_provider().get_ohlcv(symbol, start, end)


@st.cache_data(ttl=86400, show_spinner=False)
def get_fundamentals(symbol: str) -> pd.DataFrame:
    return fundamentals_provider().get_fundamentals(symbol, "all", "annual")


@st.cache_data(ttl=86400, show_spinner=False)
def get_monthly_revenue(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Taiwan monthly revenue (月營收) — empty for non-TW symbols."""
    return finmind_provider().monthly_revenue(symbol, start, end)


@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_chips(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Taiwan daily 籌碼 panel (法人買賣超・外資持股・融資) — one TW symbol per call."""
    return finmind_provider().daily_chips(symbol, start, end)


@st.cache_data(ttl=300, show_spinner=False)
def snapshot() -> pd.DataFrame:
    return load_snapshot()
