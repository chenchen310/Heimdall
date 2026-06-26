"""Cached data accessors for the UI. Thin wrappers — all logic is in core modules."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from stockobserver.data.cache import CachedProvider
from stockobserver.data.providers import YFinanceProvider
from stockobserver.screener.snapshot import load_snapshot


@st.cache_resource
def price_provider() -> CachedProvider:
    return CachedProvider(YFinanceProvider())


@st.cache_data(ttl=3600, show_spinner=False)
def get_ohlcv(symbol: str, start: date, end: date) -> pd.DataFrame:
    return price_provider().get_ohlcv(symbol, start, end)


@st.cache_data(ttl=300, show_spinner=False)
def snapshot() -> pd.DataFrame:
    return load_snapshot()
