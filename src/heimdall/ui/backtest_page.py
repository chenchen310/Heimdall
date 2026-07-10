"""Backtest page — run a single strategy, view a tear sheet, sweep parameters,
and see an ATR trade setup. All figures are cost-aware, next-bar-open fills."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from heimdall.backtest.costs import Costs
from heimdall.backtest.engine import run_backtest
from heimdall.backtest.report import (
    drawdown_series,
    equity_curve,
    summary_metrics,
    tear_sheet,
)
from heimdall.backtest.setup import trade_setup
from heimdall.backtest.strategies import STRATEGIES, Param, Strategy
from heimdall.backtest.sweep import sweep
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.ui import _glossary
from heimdall.ui._data import get_ohlcv
from heimdall.ui.i18n import t


def _num(container: object, name: str, p: Param, key: str) -> float:
    if p.integer:
        return int(
            container.number_input(
                name,
                min_value=int(p.lo),
                max_value=int(p.hi),
                value=int(p.default),
                step=int(p.step),
                key=key,
            )
        )
    return float(
        container.number_input(
            name,
            min_value=float(p.lo),
            max_value=float(p.hi),
            value=float(p.default),
            step=float(p.step),
            key=key,
        )
    )


def _param_row(strat: Strategy, prefix: str) -> dict[str, float]:
    cols = st.columns(len(strat.params))
    return {
        n: _num(cols[i], n, p, f"{prefix}_{n}") for i, (n, p) in enumerate(strat.params.items())
    }


def _frange(p: Param, lo: float, hi: float, step: float) -> list[float]:
    vals = np.arange(lo, hi + step / 2, step)
    return [int(v) for v in vals] if p.integer else [round(float(v), 4) for v in vals]


def render() -> None:
    st.header(t("🧪 Backtest"))
    c1, c2, c3 = st.columns([1, 1, 1])
    symbol = c1.text_input(t("Symbol (TICKER.MARKET)"), "AAPL.US")
    years = c2.slider(t("Years of history"), 1, 15, 8)
    strat_key = c3.selectbox(
        t("Strategy"), list(STRATEGIES), format_func=lambda k: STRATEGIES[k].label
    )
    strat = STRATEGIES[strat_key]

    try:
        parse_symbol(symbol)
    except SymbolError as exc:
        st.error(str(exc))
        return

    st.caption(t("Parameters"))
    params = _param_row(strat, "bt")
    cc1, cc2 = st.columns(2)
    fee_bps = cc1.number_input(t("Commission (bps)"), 0.0, 100.0, 10.0, step=1.0)
    slip_bps = cc2.number_input(t("Slippage (bps)"), 0.0, 100.0, 5.0, step=1.0)
    costs = Costs(fees=fee_bps / 1e4, slippage=slip_bps / 1e4)

    end = date.today()
    ohlcv = get_ohlcv(symbol, end - timedelta(days=365 * years + 60), end)
    if ohlcv.empty:
        st.warning(t("No price data for {symbol}.").format(symbol=symbol))
        return

    try:
        entries, exits = strat.signals(ohlcv, **params)
    except ValueError as exc:
        st.error(str(exc))
        return
    pf = run_backtest(ohlcv, entries, exits, costs=costs)
    m = summary_metrics(pf)

    # --- headline metrics ---------------------------------------------------
    cols = st.columns(6)
    cols[0].metric("Total return", f"{m['total_return']:.1%}", help=_glossary.help("total_return"))
    cols[1].metric("CAGR", f"{m['cagr']:.1%}", help=_glossary.help("cagr"))
    cols[2].metric("Sharpe", f"{m['sharpe']:.2f}", help=_glossary.help("sharpe"))
    cols[3].metric("Max drawdown", f"{m['max_drawdown']:.1%}", help=_glossary.help("max_drawdown"))
    cols[4].metric("Win rate", f"{m['win_rate']:.0%}", help=_glossary.help("win_rate"))
    cols[5].metric("Trades", f"{int(m['n_trades'])}", help=_glossary.help("n_trades"))
    st.caption(t("Costs and next-bar-open fills applied — treat as an optimistic upper bound."))

    # --- equity + drawdown --------------------------------------------------
    eq, dd = equity_curve(pf), drawdown_series(pf)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.04,
        subplot_titles=("Growth of $1", "Drawdown"),
    )
    fig.add_trace(go.Scatter(x=eq.index, y=eq, name="equity", line={"color": "#2962ff"}), 1, 1)
    fig.add_trace(
        go.Scatter(x=dd.index, y=dd, name="drawdown", fill="tozeroy", line={"color": "#ef5350"}),
        2,
        1,
    )
    fig.update_layout(height=460, showlegend=False, margin={"l": 0, "r": 0, "t": 30, "b": 0})
    st.plotly_chart(fig, width="stretch")

    _trade_setup_panel(ohlcv)
    _sweep_panel(ohlcv, strat_key, strat, params, costs)
    _tear_sheet_download(pf, symbol, strat.label)


def _trade_setup_panel(ohlcv: object) -> None:
    with st.expander(t("📐 Trade setup (ATR-based)")):
        mult = st.slider(t("ATR stop multiple"), 1.0, 5.0, 2.0, step=0.5)
        s = trade_setup(ohlcv, atr_mult=mult)  # type: ignore[arg-type]
        a, b, c, d = st.columns(4)
        a.metric("Entry", f"{s.entry:.2f}", help=_glossary.help("entry_stop_target"))
        b.metric(
            "Stop", f"{s.stop:.2f}", f"-{s.risk:.2f}", help=_glossary.help("entry_stop_target")
        )
        c.metric("ATR(14)", f"{s.atr:.2f}", help=_glossary.help("atr_14"))
        d.metric("Risk/share", f"{s.risk:.2f}")
        target_cols = st.columns(len(s.targets))
        for col, r, price in zip(target_cols, s.rr, s.targets, strict=True):
            col.metric(
                f"Target {int(r)}R", f"{price:.2f}", help=_glossary.help("entry_stop_target")
            )


def _sweep_panel(
    ohlcv: object, strat_key: str, strat: Strategy, params: dict[str, float], costs: Costs
) -> None:
    with st.expander(t("🔬 Parameter sweep")):
        names = list(strat.params)
        chosen = st.multiselect(
            t("Sweep up to 2 parameters"), names, default=names[:2], max_selections=2
        )
        metric = st.selectbox(
            t("Metric"), ["sharpe", "total_return", "cagr", "max_drawdown", "n_trades"]
        )
        ranges: dict[str, list[float]] = {}
        for n in chosen:
            p = strat.params[n]
            lc, hc, sc = st.columns(3)
            lo = lc.number_input(f"{n} from", value=p.lo, key=f"sw_lo_{n}")
            hi = hc.number_input(f"{n} to", value=p.hi, key=f"sw_hi_{n}")
            coarse = float(max(p.step, round((p.hi - p.lo) / 8)))  # ~8 values by default
            step = sc.number_input(f"{n} step", value=coarse, key=f"sw_st_{n}")
            ranges[n] = _frange(p, lo, hi, step)

        if not chosen or not st.button(t("Run sweep")):
            return
        combos = int(np.prod([len(v) for v in ranges.values()]))
        if combos > 400:
            st.warning(f"{combos} combinations — widen the step or narrow the range (max 400).")
            return
        fixed = {k: v for k, v in params.items() if k not in chosen}
        grid = sweep(ohlcv, strat_key, ranges, fixed_params=fixed, costs=costs)  # type: ignore[arg-type]

        if len(chosen) == 2:
            piv = grid.pivot(index=chosen[1], columns=chosen[0], values=metric)
            fig = go.Figure(
                go.Heatmap(z=piv.values, x=piv.columns, y=piv.index, colorscale="Viridis")
            )
            fig.update_layout(
                height=400,
                xaxis_title=chosen[0],
                yaxis_title=chosen[1],
                margin={"l": 0, "r": 0, "t": 10, "b": 0},
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.line_chart(grid.set_index(chosen[0])[metric])

        best = grid.sort_values(metric, ascending=(metric == "max_drawdown")).tail(1)
        st.caption(f"Best by {metric}:")
        st.dataframe(best, width="stretch", hide_index=True)


def _tear_sheet_download(pf: object, symbol: str, label: str) -> None:
    with st.expander(t("📄 Full quantstats tear sheet")):
        if st.button(t("Generate tear sheet")):
            with st.spinner(t("Building tear sheet…")):
                out = Path(tempfile.gettempdir()) / f"{symbol}_tearsheet.html"
                tear_sheet(pf, out, title=f"{symbol} — {label}")  # type: ignore[arg-type]
                st.download_button(
                    t("Download HTML"), out.read_bytes(), file_name=out.name, mime="text/html"
                )
