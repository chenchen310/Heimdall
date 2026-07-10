"""Factors page — multi-factor ranking and a factor-portfolio backtest (RenTech lens)."""

from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import streamlit as st

from heimdall.backtest.portfolio import backtest_portfolio
from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.factors.panel import PanelData, build_panel
from heimdall.factors.scoring import DEFAULT_WEIGHTS, FACTOR_NAMES, factor_scores
from heimdall.factors.validate import information_coefficient, quantile_spread
from heimdall.screener.snapshot import DEFAULT_UNIVERSE, TW_UNIVERSE, split_by_region
from heimdall.ui import _glossary
from heimdall.ui._data import snapshot
from heimdall.ui._markets import market_radio
from heimdall.ui._nav import no_snapshot_cta
from heimdall.ui.i18n import t

# Curated per-market universe for the point-in-time portfolio backtest. Returns are
# relative, but FX would muddy a mixed book — so each backtest is single-currency.
_UNIVERSE_BY_REGION: dict[str, list[str]] = {"US": DEFAULT_UNIVERSE, "Taiwan": TW_UNIVERSE}

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
    # Router dispatches per symbol: US → EDGAR/FMP, Taiwan → FinMind.
    prices = CachedProvider(router.price_provider())
    return build_panel(
        list(symbols),
        prices,
        router.fundamentals_provider(),
        start,
        end,
        freq=freq,
        weights=dict(weights),
    )


def render() -> None:
    st.header(t("🧬 Factors"))
    # US and Taiwan are scored/backtested separately — different currency, and factor
    # z-scores are only comparable within one market's cross-section.
    region = market_radio(list(_UNIVERSE_BY_REGION))
    ranking, portfolio = st.tabs([t("Ranking (current)"), t("Portfolio backtest")])
    with ranking:
        _ranking_tab(region)
    with portfolio:
        _portfolio_tab(region)


def _ranking_tab(region: str) -> None:
    try:
        snap = split_by_region(snapshot()).get(region)
    except FileNotFoundError:
        no_snapshot_cta(key="factors_nosnap")
        return
    if snap is None or snap.empty:
        st.warning(t("No rows for this market in the snapshot."))
        return
    st.caption(t("Composite of value / quality / momentum / growth, each scored 0–100."))
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
    colcfg: dict[str, object] = {
        "composite_score": st.column_config.ProgressColumn(
            "composite",
            min_value=0,
            max_value=100,
            format="%d",
            help=_glossary.help("composite_score"),
        )
    }
    for col in show:
        if col in colcfg:
            continue
        text = _glossary.help(col)
        if text:
            colcfg[col] = st.column_config.Column(help=text)
    st.dataframe(scored[show].round(1), width="stretch", hide_index=True, column_config=colcfg)


def _portfolio_tab(region: str) -> None:
    st.warning(t(_SURVIVORSHIP))
    c1, c2, c3, c4 = st.columns(4)
    start_year = c1.slider(t("Start year"), 2016, 2024, 2020)
    freq = (
        "ME"
        if c2.selectbox(t("Rebalance"), ["Monthly", "Quarterly"], format_func=t) == "Monthly"
        else "QE"
    )
    top_n = c3.slider(t("Top N"), 2, 10, 5)
    commission_bps = c4.number_input(t("Commission (bps)"), 0.0, 100.0, 10.0, step=1.0)
    weights = _weights("pf")

    if not st.button(t("Run factor backtest")):
        return
    with st.spinner("Building point-in-time panel and backtesting…"):
        data = _panel(
            tuple(_UNIVERSE_BY_REGION[region]),
            date(start_year, 1, 1),
            date.today(),
            freq,
            tuple(weights.items()),
        )
        if data.panel.empty:
            st.error(t("No panel data (network/symbol issue)."))
            return
        ic = information_coefficient(data.panel)
        res = backtest_portfolio(
            data.prices, data.panel, n=top_n, monthly=(freq == "ME"), commission_bps=commission_bps
        )

    f, b = res.stats["factor_topN"], res.stats["equal_weight"]
    cols = st.columns(4)
    cols[0].metric(
        "Factor CAGR",
        f"{f['cagr']:.1%}",
        f"{f['cagr'] - b['cagr']:+.1%} vs benchmark",
        help=_glossary.help("cagr"),
    )
    cols[1].metric(
        "Factor Sharpe",
        f"{f['sharpe']:.2f}",
        f"{f['sharpe'] - b['sharpe']:+.2f}",
        help=_glossary.help("sharpe"),
    )
    cols[2].metric("Max drawdown", f"{f['max_drawdown']:.1%}", help=_glossary.help("max_drawdown"))
    cols[3].metric("Mean IC", f"{ic.mean_ic:+.3f}", f"t={ic.t_stat:.1f}", help=_glossary.help("ic"))

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
        st.caption(t("Forward return by composite quantile (low → high) — upward slope is good:"))
        st.bar_chart(spread)
