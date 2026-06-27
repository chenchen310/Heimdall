"""Technical dashboard (Morgan Stanley lens) — trading plan, levels, and chart."""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st

from stockobserver.analytics import technical_report
from stockobserver.data.symbols import SymbolError, parse_symbol
from stockobserver.factors.indicators import bollinger
from stockobserver.ui._data import get_ohlcv
from stockobserver.ui._personas import ai_report
from stockobserver.ui.i18n import t


def render() -> None:
    st.header(t("📐 Technical — Morgan Stanley lens"))
    symbol = st.text_input(t("Symbol (TICKER.MARKET)"), "AAPL.US")
    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    end = date.today()
    ohlcv = get_ohlcv(symbol, end - timedelta(days=420), end)
    if ohlcv.empty:
        st.warning(f"No price data for {symbol}.")
        return
    tr = technical_report(symbol, ohlcv)
    s = tr.setup

    # --- Trading Plan Summary ---
    st.subheader(t("Trading Plan Summary"))
    box = st.columns(5)
    box[0].metric("Price", f"{tr.price:.2f}")
    box[1].metric("Entry", f"{s.entry:.2f}")
    box[2].metric("Stop", f"{s.stop:.2f}", f"-{s.risk:.2f}")
    box[3].metric("Target 1 (1R)", f"{s.targets[0]:.2f}")
    trend = "/".join(tr.trend[k][0].upper() for k in ("short", "medium", "long"))
    box[4].metric("Trend S/M/L", trend)
    row = st.columns(4)
    row[0].metric("RSI(14)", f"{tr.rsi_14:.0f}")
    row[1].metric("ATR(14)", f"{tr.atr_14:.2f}")
    row[2].metric("Bollinger %B", f"{tr.bollinger['percent_b']:.2f}")
    row[3].metric("MA cross", tr.ma_cross or "—")

    # --- chart: candlestick + Bollinger + support/resistance + setup levels ---
    view = ohlcv.tail(180)
    close = view["adj_close"].reset_index(drop=True)
    up, mid, low = bollinger(close, 20)
    fig = go.Figure(
        go.Candlestick(
            x=view["date"],
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="OHLC",
        )
    )
    for series, name, color in [
        (up, "BB upper", "#90a4ae"),
        (mid, "BB mid", "#42a5f5"),
        (low, "BB lower", "#90a4ae"),
    ]:
        fig.add_trace(
            go.Scatter(x=view["date"], y=series, name=name, line={"width": 1, "color": color})
        )
    for lvl in tr.support:
        fig.add_hline(y=lvl, line_dash="dot", line_color="#26a69a", opacity=0.5)
    for lvl in tr.resistance:
        fig.add_hline(y=lvl, line_dash="dot", line_color="#ef5350", opacity=0.5)
    fig.add_hline(
        y=s.stop,
        line_dash="dash",
        line_color="#ef5350",
        annotation_text="stop",
        annotation_position="right",
    )
    fig.add_hline(
        y=s.targets[0],
        line_dash="dash",
        line_color="#26a69a",
        annotation_text="T1",
        annotation_position="right",
    )
    fig.update_layout(
        height=520, xaxis_rangeslider_visible=False, margin={"l": 0, "r": 0, "t": 10, "b": 0}
    )
    st.plotly_chart(fig, width="stretch")

    cols = st.columns(2)
    cols[0].caption(t("Support / Resistance"))
    cols[0].write({"support": tr.support, "resistance": tr.resistance})
    cols[1].caption(t("Fibonacci retracement"))
    cols[1].write(tr.fibonacci)

    payload = {
        "symbol": symbol,
        "price": round(tr.price, 2),
        "trend": tr.trend,
        "moving_averages": {k: round(v, 2) for k, v in tr.moving_averages.items()},
        "ma_cross": tr.ma_cross,
        "rsi_14": round(tr.rsi_14, 1),
        "macd": {k: round(v, 3) for k, v in tr.macd.items()},
        "bollinger": {k: round(v, 3) for k, v in tr.bollinger.items()},
        "atr_14": round(tr.atr_14, 2),
        "support": tr.support,
        "resistance": tr.resistance,
        "fibonacci": tr.fibonacci,
        "setup": {
            "entry": round(s.entry, 2),
            "stop": round(s.stop, 2),
            "targets": [round(t, 2) for t in s.targets],
            "rr": s.rr,
        },
    }
    ai_report("morgan_stanley", payload, symbol)
