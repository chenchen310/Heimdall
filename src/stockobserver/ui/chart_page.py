"""Chart page — Plotly candlestick with MA overlays, RSI, and MACD subplots."""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stockobserver.data.symbols import SymbolError, parse_symbol
from stockobserver.factors.indicators import macd, rsi, sma
from stockobserver.ui._data import get_ohlcv


def render() -> None:
    st.header("📈 Chart")
    c1, c2 = st.columns([1, 2])
    symbol = c1.text_input("Symbol (TICKER.MARKET)", "AAPL.US")
    lookback = c2.slider("Lookback (days)", 90, 1500, 365)

    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    end = date.today()
    df = get_ohlcv(symbol, end - timedelta(days=lookback), end)
    if df.empty:
        st.warning(f"No price data for {symbol}.")
        return

    dates = df["date"]
    close = df["adj_close"].reset_index(drop=True)
    macd_line, macd_sig, macd_hist = macd(close)

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=(f"{symbol} price", "RSI(14)", "MACD"),
    )

    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
        ),
        row=1,
        col=1,
    )
    for length, color in [(20, "#2962ff"), (50, "#ff6d00"), (200, "#9c27b0")]:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=sma(close, length),
                name=f"SMA{length}",
                line={"width": 1, "color": color},
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(x=dates, y=rsi(close, 14), name="RSI", line={"color": "#26a69a"}), row=2, col=1
    )
    fig.add_hline(y=70, line_dash="dot", line_color="gray", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="gray", row=2, col=1)

    fig.add_trace(go.Bar(x=dates, y=macd_hist, name="hist", marker_color="#90a4ae"), row=3, col=1)
    fig.add_trace(
        go.Scatter(x=dates, y=macd_line, name="MACD", line={"color": "#2962ff"}), row=3, col=1
    )
    fig.add_trace(
        go.Scatter(x=dates, y=macd_sig, name="signal", line={"color": "#ff6d00"}), row=3, col=1
    )

    fig.update_layout(
        height=720,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
    )
    st.plotly_chart(fig, width="stretch")
