"""Today's Picks — the north-star surface.

Renders **only** signals whose registry status is ``certified``
(`.claude/rules/signal-certification.md`): no certified signal ⇒ an honest
empty state and *nothing else* — no previews, no temporary rankings. For each
certified spec the out-of-sample **evidence box comes first** (beat rate with
CI and cohort count, IC, spread, window, benchmark, the survivorship stamp),
then the ranked picks from ``research.today`` with per-feature z columns
explaining each rank.

All paths resolve through ``registry.registry_path()`` dynamically, so tests
point the page at a scratch registry by monkeypatching that one function.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from heimdall.data.base import ProviderError
from heimdall.data.symbols import REGION_CURRENCY
from heimdall.research import registry
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.dataset import load_panel
from heimdall.research.ledger import (
    RealizedCohort,
    UnrealizedMark,
    load_cohorts,
    realized_track_record,
    unrealized_mark,
)
from heimdall.research.monitor import TRAILING, load_monitoring
from heimdall.research.rebalance import diff_picks, orders_to_csv, rebalance_plan
from heimdall.research.spec import SignalSpec, load_spec
from heimdall.research.today import freshness, todays_picks
from heimdall.screener.snapshot import MONETARY_FIELDS
from heimdall.ui import _glossary
from heimdall.ui._data import get_ohlcv, snapshot
from heimdall.ui._freshness import freshness_word
from heimdall.ui._markets import market_radio
from heimdall.ui._nav import no_snapshot_cta, switch_to
from heimdall.ui.i18n import t

_STALE_BDAYS = 5


def _root() -> Path:
    return registry.registry_path().parent.parent


def _specs_by_status(region: str, status: str) -> list[tuple[SignalSpec, dict[str, object]]]:
    """(spec, registry entry) for every signal of this market in the given lifecycle status."""
    out: list[tuple[SignalSpec, dict[str, object]]] = []
    for entry in cast("list[dict[str, object]]", registry.load_registry()["signals"]):
        if entry["status"] != status:
            continue
        p = Path(str(entry["spec_path"]))
        spec = load_spec(p if p.is_absolute() else _root() / p)
        if spec.market == region:
            out.append((spec, entry))
    return out


def _drift_banner(spec: SignalSpec) -> None:
    """Honest notice for a signal that was certified then flagged by drift monitoring (12.2)."""
    mon = load_monitoring(spec.name, spec.version, _root())
    if mon is not None:
        hi = cast("list[float]", mon["trailing_alpha_ci95"])[1]
        st.warning(
            t(
                "⚠️ {name} v{v} — certified, then flagged by drift monitoring: post-certification "
                "selection skill went significantly negative (trailing-{n} {a:+.1%}, 95% CI upper "
                "{hi:+.1%} < 0). Under review — its ranking is withheld until it re-certifies or "
                "retires."
            ).format(
                name=spec.name,
                v=spec.version,
                n=mon["trailing_n"],
                a=cast("float", mon["trailing_alpha_mean"]),
                hi=hi,
            )
        )
    else:
        st.warning(
            t("⚠️ {name} v{v} — under review (post-certification drift). Ranking withheld.").format(
                name=spec.name, v=spec.version
            )
        )


@st.cache_data(ttl=300, show_spinner=False)
def _panel(market: str) -> pd.DataFrame:
    return load_panel(market)


def _fmt_pct(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.1%}"


@st.cache_data(ttl=3600, show_spinner=False)
def _unrealized_for(market: str, symbols: tuple[str, ...], as_of: str) -> UnrealizedMark | None:
    """Live mark for a not-yet-realized cohort — see ``ledger.unrealized_mark``.

    Gracefully absent (not a page-crashing error) on any provider hiccup: this is
    a nice-to-have interim read, not the certified number.
    """
    if not symbols or not as_of:
        return None
    try:
        start, end = date.fromisoformat(as_of), date.today()
        prices = {sym: get_ohlcv(sym, start, end) for sym in symbols}
        bench = get_ohlcv(BENCHMARK[market], start, end)
    except ProviderError:
        return None
    return unrealized_mark(list(symbols), as_of, prices, bench)


def _track_record(spec: SignalSpec, report: dict[str, object]) -> None:
    """The live, costed track record (16.1): each cohort was frozen the day it was
    shown, then scored on realized returns from the panel — no backfill, no hindsight."""
    st.subheader(t("Live track record"))
    st.caption(
        t("Picks are frozen the day they're shown, then scored on realized returns — no backfill.")
    )
    try:
        panel = _panel(spec.market)
    except FileNotFoundError:
        st.info(t("The track record needs the research panel on disk to score frozen cohorts."))
        return
    cert_month = str(report.get("generated_at", ""))[:7]
    surv = str(report.get("survivorship", "current_universe (optimistic)"))
    tr = realized_track_record(spec, panel, cert_month, survivorship=surv, root=_root())
    if not tr.cohorts:
        st.info(
            t(
                "No frozen cohorts yet — the live track record starts at the first monthly freeze "
                "(the scheduled `ledger freeze`, roadmap 16.2)."
            )
        )
        return

    def _row(c: RealizedCohort) -> dict[str, object]:
        unreal = None if c.realized else _unrealized_for(spec.market, tuple(c.symbols), c.as_of)
        return {
            t("Month"): c.month,
            t("Frozen"): c.n_frozen,
            t("Unrealized (vs benchmark)"): _fmt_pct(unreal.alpha_pct) if unreal else "—",
            t("Book 6m (vs benchmark)"): _fmt_pct(c.book_rel_6m),
            t("Universe 6m (vs benchmark)"): _fmt_pct(c.univ_rel_6m),
            t("Selection skill"): _fmt_pct(c.alpha_6m),
            t("Realized"): c.realized,
        }

    table = pd.DataFrame([_row(c) for c in tr.cohorts])
    st.dataframe(table, width="stretch", hide_index=True)
    st.caption(
        t(
            "Unrealized uses today's prices (gross, benchmark-relative) for cohorts still inside "
            "their 6-month window; the official figures take over once realized."
        )
    )

    if tr.curve:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=[p.month for p in tr.curve],
                y=[p.equity for p in tr.curve],
                mode="lines+markers",
                name=t("Followed every month"),
                line={"color": "#2e7d32"},
            )
        )
        fig.add_hline(y=1.0, line={"color": "#9e9e9e", "width": 1, "dash": "dot"})
        fig.update_layout(
            height=300,
            margin={"l": 0, "r": 0, "t": 10, "b": 0},
            yaxis_title=t("Growth of 1 (net of {bps} bps/side)").format(bps=20),
        )
        st.plotly_chart(fig, width="stretch")

    certified_on = str(report.get("generated_at", ""))[:10]
    st.caption(
        t("Certified {d} · live since {m} · survivorship: current universe (optimistic).").format(
            d=certified_on, m=cert_month
        )
    )


def _rebalance(spec: SignalSpec, snap: pd.DataFrame, picks: pd.DataFrame) -> None:
    """Turn today's picks into an equal-weight order plan vs the last frozen cohort (16.3).

    An execution aid only — no order placement, no advice, no scheme but equal weight.
    """
    st.subheader(t("Rebalance helper"))
    st.caption(
        t("An execution aid, not an order system, not advice; orders are placed at your broker.")
    )
    cohorts = load_cohorts(spec.name, spec.version, _root())
    if not cohorts:
        st.info(t("No frozen cohort yet to diff against — freeze one first (roadmap 16.1/16.2)."))
        return

    previous = [str(p["symbol"]) for p in cast("list[dict[str, object]]", cohorts[-1]["picks"])]
    current = [str(s) for s in picks["symbol"]]
    diff = diff_picks(current, previous)
    st.caption(t("Changes vs last frozen cohort"))
    c1, c2, c3 = st.columns(3)
    c1.metric(t("Added"), len(diff.added))
    c2.metric(t("Dropped"), len(diff.dropped))
    c3.metric(t("Kept"), len(diff.kept))

    default_budget = 1_000_000.0 if spec.market == "Taiwan" else 100_000.0
    budget = st.number_input(
        t("Budget"), min_value=0.0, value=default_budget, step=1000.0, key=f"reb_budget_{spec.name}"
    )
    odd_lot = (
        st.checkbox(t("Allow odd lots (TW)"), value=False, key=f"reb_odd_{spec.name}")
        if spec.market == "Taiwan"
        else False
    )
    closes = dict(zip(snap["symbol"].astype(str), snap["price"].astype(float), strict=False))
    orders = rebalance_plan(current, previous, closes, float(budget), spec.market, odd_lot=odd_lot)
    if not orders:
        return

    st.subheader(t("Order plan (equal-weight)"))
    table = pd.DataFrame(
        [
            {
                t("Symbol"): o.symbol,
                t("Side"): t(o.side),
                t("Shares"): o.shares,
                t("Reference close"): o.ref_close,
                t("Est. cost"): round(o.est_cost, 2),
            }
            for o in orders
        ]
    )
    st.dataframe(table, width="stretch", hide_index=True)
    st.download_button(
        t("Download order plan (CSV)"),
        orders_to_csv(orders),
        file_name=f"{spec.name}_v{spec.version}_rebalance.csv",
        mime="text/csv",
        key=f"reb_csv_{spec.name}",
    )


def _monitoring_line(spec: SignalSpec) -> None:
    """A one-line post-certification health note under a still-certified signal's evidence box."""
    mon = load_monitoring(spec.name, spec.version, _root())
    if mon is None or int(cast("int", mon.get("trailing_n", 0))) < TRAILING:
        return
    st.caption(
        t(
            "Post-cert monitoring: trailing-{n} selection skill {a:+.1%} "
            "— drift alarm not triggered."
        ).format(n=mon["trailing_n"], a=cast("float", mon["trailing_alpha_mean"]))
    )


def _gate_value(report: dict[str, object], gate: str) -> float:
    for g in cast("list[dict[str, object]]", report.get("gates", [])):
        if g.get("gate") == gate:
            return float(cast("float", g.get("value", float("nan"))))
    return float("nan")


def _evidence_box(region: str, report: dict[str, object]) -> None:
    """The certified out-of-sample evidence — always shown before any ranking."""
    lo, hi = cast("list[float]", report["portfolio_beat_ci95"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        t("Beat rate (6m book vs benchmark)"),
        f"{cast('float', report['portfolio_beat_rate']):.0%}",
        f"95% CI {lo:.0%}–{hi:.0%}",
        delta_color="off",
        help=_glossary.help("beat_rate_book"),
    )
    c2.metric(
        t("Selection skill (vs equal-weight)"),
        f"{cast('float', report['selection_alpha_mean']):+.1%}",
        f"NW-t {cast('float', report['selection_alpha_t']):+.1f}",
        delta_color="off",
        help=_glossary.help("selection_skill"),
    )
    c3.metric("IC", f"{_gate_value(report, 'G1_ic'):+.3f}", help=_glossary.help("ic"))
    c4.metric(
        t("OOS cohorts"),
        str(len(cast("list[object]", report.get("cohorts", [])))),
        help=_glossary.help("oos_cohorts"),
    )
    st.caption(
        t(
            "Beat rate = how often the equal-weight book beat the benchmark (includes the "
            "equal-weight premium); selection skill = return above an equal-weight universe "
            "book (the certified edge, G3)."
        )
    )
    certified_on = str(report.get("generated_at", ""))[:10]
    st.caption(
        t("Certified {d} · OOS window {a} → {b} · benchmark {bench}").format(
            d=certified_on,
            a=report.get("window_start", "?"),
            b=report.get("window_end", "?"),
            bench=BENCHMARK[region],
        )
        + " · "
        + t("survivorship: current universe (optimistic upper bound)")
    )


def render() -> None:
    st.header(t("🎯 Today's Picks"))
    st.caption(
        t("Only signals that passed out-of-sample certification render here — nothing else, ever.")
    )
    region = market_radio(["US", "Taiwan"], key="today_market")

    specs = _specs_by_status(region, "certified")
    under_review = _specs_by_status(region, "under_review")
    if not specs and not under_review:
        st.info(
            t(
                "No certified signal yet for this market. Every ranking shown here must first "
                "pass strict statistical testing on data it has never been tuned on — most "
                "candidate signals fail, and none currently qualifies. This is intentional "
                "honesty, not a bug: nothing is shown here until a signal has actually earned it."
            )
        )
        return  # the rule: nothing renders without a certified registry row

    for spec, _entry in under_review:  # drift-flagged signals get an honest banner, no ranking
        _drift_banner(spec)
    if not specs:
        return  # only under-review signals — the banner is the whole story

    try:
        snap = snapshot()
    except FileNotFoundError:
        no_snapshot_cta(key="today_nosnap")
        return
    word = freshness_word(snap)
    if word:
        st.caption(word)
    stale = freshness(snap)
    if stale > _STALE_BDAYS:
        st.warning(
            t("Snapshot is {n} business days old — refresh it on the Build data page.").format(
                n=stale
            )
        )
        switch_to("Build data", key="today_stale_cta", label="🗂 " + t("Refresh it now"))

    currency = REGION_CURRENCY[region]
    for spec, entry in specs:
        st.subheader(f"{spec.name} v{spec.version}")
        try:
            report = json.loads(Path(str(entry["cert_report"])).read_text())
        except OSError as exc:
            st.error(f"certification report unreadable: {exc}")
            continue
        _evidence_box(region, report)
        _monitoring_line(spec)

        try:
            picks = todays_picks(spec, snap)
        except ValueError as exc:  # e.g. a snapshot predating the 7.1 fields
            st.error(str(exc))
            continue
        if picks.empty:
            st.info(t("No eligible names to rank right now."))
            continue
        lead = ["symbol", "signal_score", *(f"z_{f}" for f in spec.features), *spec.features]
        cols = [c for c in [*lead, "price", "market_cap"] if c in picks.columns]
        display = picks[cols].rename(
            columns={c: f"{c} ({currency})" for c in cols if c in MONETARY_FIELDS}
        )
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            column_config={"symbol": st.column_config.Column(pinned=True)},
        )
        st.caption(
            t("z = strength vs today's eligible pool; the score is the weighted sum of z columns.")
        )
        _track_record(spec, report)
        _rebalance(spec, snap, picks)
