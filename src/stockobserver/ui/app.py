"""Streamlit entrypoint:  uv run streamlit run src/stockobserver/ui/app.py

A thin shell — each page's logic lives in its own module and calls the core
screener/factors/data packages.
"""

from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Stock Observer", page_icon="📉", layout="wide")

from stockobserver.ui import chart_page, screener_page  # noqa: E402  (after set_page_config)

PAGES = {"Screener": screener_page.render, "Chart": chart_page.render}

st.sidebar.title("📉 Stock Observer")
choice = st.sidebar.radio("Page", list(PAGES))
st.sidebar.caption(
    "Rebuild the snapshot any time:\n\n`uv run python -m stockobserver.screener.build`"
)

PAGES[choice]()
