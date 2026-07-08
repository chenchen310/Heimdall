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
from pathlib import Path
from typing import cast

import streamlit as st

from heimdall.data.symbols import REGION_CURRENCY
from heimdall.research import registry
from heimdall.research.benchmark import BENCHMARK
from heimdall.research.monitor import TRAILING, load_monitoring
from heimdall.research.spec import SignalSpec, load_spec
from heimdall.research.today import freshness, todays_picks
from heimdall.screener.snapshot import MONETARY_FIELDS
from heimdall.ui._data import snapshot
from heimdall.ui._markets import market_radio
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
    )
    c2.metric(
        t("Selection skill (vs equal-weight)"),
        f"{cast('float', report['selection_alpha_mean']):+.1%}",
        f"NW-t {cast('float', report['selection_alpha_t']):+.1f}",
        delta_color="off",
    )
    c3.metric("IC", f"{_gate_value(report, 'G1_ic'):+.3f}")
    c4.metric(t("OOS cohorts"), str(len(cast("list[object]", report.get("cohorts", [])))))
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
                "No certified signal yet for this market — an honest empty state. "
                "The referee (docs/RESEARCH_PLAYBOOK.md) has passed nothing; the first "
                "candidates are registered in Phase 10 of docs/ROADMAP_V2.md."
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
        st.warning(
            t("No snapshot found. Build one first:\n\n`uv run python -m heimdall.screener.build`")
        )
        return
    stale = freshness(snap)
    if stale > _STALE_BDAYS:
        st.warning(
            t("Snapshot is {n} business days old — refresh it on the Build data page.").format(
                n=stale
            )
        )

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
