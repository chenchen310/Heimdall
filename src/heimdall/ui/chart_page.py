"""Chart page — Plotly candlestick with MA overlays, RSI, and MACD subplots."""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.factors.indicators import macd, rsi, sma
from heimdall.ui._data import get_ohlcv
from heimdall.ui.i18n import t


def render() -> None:
    st.header(t("📈 Chart"))
    c1, c2 = st.columns([1, 2])
    symbol = c1.text_input(t("Symbol (TICKER.MARKET)"), "AAPL.US")
    lookback = c2.slider(t("Lookback (days)"), 90, 1500, 365)

    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    end = date.today()
    df = get_ohlcv(symbol, end - timedelta(days=lookback), end)
    if df.empty:
        st.warning(t("No price data for {symbol}.").format(symbol=symbol))
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

    # Bind every trace to ONE x-axis so the hover crosshair spans all three panels.
    # ``shared_xaxes=True`` only *matches* the per-row axes (x/x2/x3); ``spikemode="across"``
    # crosses subplots that truly **share** an x-axis, not merely matched ones — so without
    # this the spike stays in the hovered panel. The single axis is anchored under the
    # bottom row (so the date labels sit at the bottom); the now-unused axes are hidden.
    fig.update_traces(xaxis="x")
    for shape in fig.layout.shapes:  # the RSI 30/70 guides were tied to the now-hidden x2
        shape.update(xref="x domain")
    fig.update_layout(
        height=720,
        showlegend=True,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        hovermode="x unified",  # one readout per panel at the cursor's date
        spikedistance=-1,  # the crosshair tracks the cursor anywhere, not only near a point
        xaxis={
            "anchor": "y3",
            "matches": None,  # it now carries all the data, so range to itself (not empty x3)
            "showticklabels": True,  # the single axis is now the bottom one — show the dates
            "rangeslider": {"visible": False},
            "showspikes": True,
            "spikemode": "across",  # the line crosses price / RSI / MACD
            "spikesnap": "cursor",
            "spikethickness": 1,
            "spikedash": "dot",
            "spikecolor": "#888",
        },
        xaxis2={"visible": False},
        xaxis3={"visible": False},
    )
    st.plotly_chart(fig, width="stretch")
