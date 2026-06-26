"""Factors page — multi-factor ranking and a factor-portfolio backtest (RenTech lens)."""

from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import streamlit as st

from stockobserver.backtest.portfolio import backtest_portfolio
from stockobserver.data.cache import CachedProvider
from stockobserver.data.providers import SecEdgarProvider, YFinanceProvider
from stockobserver.factors.panel import PanelData, build_panel
from stockobserver.factors.scoring import DEFAULT_WEIGHTS, FACTOR_NAMES, factor_scores
from stockobserver.factors.validate import information_coefficient, quantile_spread
from stockobserver.screener.snapshot import DEFAULT_UNIVERSE
from stockobserver.ui._data import snapshot

_SURVIVORSHIP = (
    "⚠️ Over a **current** universe these results carry survivorship bias — today's "
    "winners are baked in. Treat returns as an optimistic upper bound, not a forecast."
)


def _weights(prefix: str) -> dict[str, float]:
    cols = st.columns(len(FACTOR_NAMES))
    return {
        name: cols[i].slider(name, 0.0, 2.0, DEFAULT_WEIGHTS[name], 0.25, key=f"w_{prefix}_{name}")
        for i, name in enumerate(FACTOR_NAMES)
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _panel(
    symbols: tuple[str, ...],
    start: date,
    end: date,
    freq: str,
    weights: tuple[tuple[str, float], ...],
) -> PanelData:
    prices = CachedProvider(YFinanceProvider())
    return build_panel(
        list(symbols), prices, SecEdgarProvider(), start, end, freq=freq, weights=dict(weights)
    )


def render() -> None:
    st.header("🧬 Factors")
    ranking, portfolio = st.tabs(["Ranking (current)", "Portfolio backtest"])
    with ranking:
        _ranking_tab()
    with portfolio:
        _portfolio_tab()


def _ranking_tab() -> None:
    try:
        snap = snapshot()
    except FileNotFoundError:
        st.warning("No snapshot. Build one: `uv run python -m stockobserver.screener.build`")
        return
    st.caption("Composite of value / quality / momentum / growth, each scored 0–100.")
    weights = _weights("rank")
    scored = factor_scores(snap, weights).sort_values("composite_score", ascending=False)
    cols = [
        "symbol",
        "composite_score",
        *[f"{f}_score" for f in FACTOR_NAMES],
        "pe",
        "roe",
        "ret_6m",
        "revenue_growth_yoy",
    ]
    show = [c for c in cols if c in scored.columns]
    st.dataframe(
        scored[show].round(1),
        width="stretch",
        hide_index=True,
        column_config={
            "composite_score": st.column_config.ProgressColumn(
                "composite", min_value=0, max_value=100, format="%d"
            )
        },
    )


def _portfolio_tab() -> None:
    st.warning(_SURVIVORSHIP)
    c1, c2, c3, c4 = st.columns(4)
    start_year = c1.slider("Start year", 2016, 2024, 2020)
    freq = "ME" if c2.selectbox("Rebalance", ["Monthly", "Quarterly"]) == "Monthly" else "QE"
    top_n = c3.slider("Top N", 2, 10, 5)
    commission_bps = c4.number_input("Commission (bps)", 0.0, 100.0, 10.0, step=1.0)
    weights = _weights("pf")

    if not st.button("Run factor backtest"):
        return
    with st.spinner("Building point-in-time panel and backtesting…"):
        data = _panel(
            tuple(DEFAULT_UNIVERSE),
            date(start_year, 1, 1),
            date.today(),
            freq,
            tuple(weights.items()),
        )
        if data.panel.empty:
            st.error("No panel data (network/symbol issue).")
            return
        ic = information_coefficient(data.panel)
        res = backtest_portfolio(
            data.prices, data.panel, n=top_n, monthly=(freq == "ME"), commission_bps=commission_bps
        )

    f, b = res.stats["factor_topN"], res.stats["equal_weight"]
    cols = st.columns(4)
    cols[0].metric("Factor CAGR", f"{f['cagr']:.1%}", f"{f['cagr'] - b['cagr']:+.1%} vs benchmark")
    cols[1].metric("Factor Sharpe", f"{f['sharpe']:.2f}", f"{f['sharpe'] - b['sharpe']:+.2f}")
    cols[2].metric("Max drawdown", f"{f['max_drawdown']:.1%}")
    cols[3].metric("Mean IC", f"{ic.mean_ic:+.3f}", f"t={ic.t_stat:.1f}")

    fig = go.Figure()
    for name, color in [("factor_topN", "#2962ff"), ("equal_weight", "#9e9e9e")]:
        fig.add_trace(
            go.Scatter(x=res.equity.index, y=res.equity[name], name=name, line={"color": color})
        )
    fig.update_layout(
        height=380,
        title="Growth of $1 (top-N factor vs equal-weight)",
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
    )
    st.plotly_chart(fig, width="stretch")

    spread = quantile_spread(data.panel, q=3)
    if not spread.empty:
        st.caption("Forward return by composite quantile (low → high) — upward slope is good:")
        st.bar_chart(spread)
