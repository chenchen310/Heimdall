"""Strategy Lab (roadmap 18.9) — what the Strategy Factory made, shown honestly.

Every tab carries the same banner: research results, **uncertified**, with the run's trial
count and the survivorship stamp (playbook §10 *trial amnesia*). Certified strategies are not
re-rendered here — they live on Today's Picks. The page only renders; data comes from
:mod:`heimdall.research.lab` and long jobs run as background CLIs (the ``build_page`` pattern).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import streamlit as st

from heimdall.backtest.portfolio_stats import drawdown, portfolio_stats, yearly_returns
from heimdall.data.store import data_root
from heimdall.research import lab
from heimdall.research.rebalance import frozen_weights, orders_to_csv, weighted_plan
from heimdall.ui import _glossary as glossary
from heimdall.ui.i18n import t

_PROC = "_lab_proc"
_JOB = "_lab_job"


def _banner(n_trials: int | None = None) -> None:
    parts = [t("Research results — uncertified")]
    if n_trials is not None:
        parts.append(f"N = {n_trials} {t('trials')}")
    parts.append(f"survivorship: {lab.SURVIVORSHIP}")
    st.warning("🧪 " + " · ".join(parts))


def render() -> None:
    st.header(t("🧪 Strategy Lab"))
    st.caption(
        t(
            "The Strategy Factory searches, backtests and ranks strategies by itself. Nothing "
            "here is a recommendation: only certified signals appear on Today's Picks."
        )
    )
    runs = lab.list_runs()
    tabs = st.tabs(
        [
            t("Search runs"),
            t("Leaderboard"),
            t("Strategy detail"),
            t("Walk-forward"),
            t("Incubating"),
            t("Technical research"),
        ]
    )
    run_id = runs[0].run_id if runs else None
    if runs and len(runs) > 1:
        run_id = st.sidebar.selectbox(t("Factory run"), [r.run_id for r in runs], key="lab_run")
    n_trials = next((r.n_trials for r in runs if r.run_id == run_id), None)
    with tabs[0]:
        _banner(n_trials)
        _runs_tab(runs)
    with tabs[1]:
        _banner(n_trials)
        _leaderboard_tab(run_id)
    with tabs[2]:
        _banner(n_trials)
        _detail_tab(run_id)
    with tabs[3]:
        _banner(n_trials)
        _walkforward_tab(run_id)
    with tabs[4]:
        _banner()
        _incubating_tab()
    with tabs[5]:
        _banner()
        _tech_tab()


# --- search runs ------------------------------------------------------------------------


def _runs_tab(runs: list[lab.RunInfo]) -> None:
    if not runs:
        st.info(
            t(
                "No search run yet. Declare one first: write signals/search/<run_id>/config.json, "
                "commit its hash in a RESEARCH_LOG entry (playbook §12.2), then start it here."
            )
        )
        return
    st.dataframe(
        pd.DataFrame(
            {
                t("Run"): [r.run_id for r in runs],
                t("Trials"): [r.n_trials for r in runs],
                t("VAL looks spent"): [r.val_spent for r in runs],
            }
        ),
        hide_index=True,
        width="stretch",
    )
    proc = st.session_state.get(_PROC)
    if proc is not None and proc.poll() is None:
        st.info(t("Running: ") + str(st.session_state.get(_JOB, "")))
        if st.button(t("Refresh status"), key="lab_refresh"):
            st.rerun()
        return
    with st.expander(t("Start a background job")):
        target = st.selectbox(t("Run"), [r.run_id for r in runs], key="lab_job_run")
        job = st.radio(
            t("Job"),
            ["search", "engine", "walkforward"],
            format_func=lambda k: {
                "search": t("Run the declared search (DEV only)"),
                "engine": t("Cache daily-engine backtests of the top 10"),
                "walkforward": t("Walk-forward meta-backtest (top 1)"),
            }[k],
            key="lab_job_kind",
        )
        entry = st.text_input(t("RESEARCH_LOG entry id (search only)"), key="lab_entry")
        if st.button(t("Start"), key="lab_start"):
            cfg = next(r.config_path for r in runs if r.run_id == target)
            if job == "search" and not entry.strip():
                st.error(t("A search needs its declared RESEARCH_LOG entry id."))
                return
            argv = {
                "search": ["heimdall.research.factory", "run", str(cfg), "--log-entry", entry],
                "engine": ["heimdall.research.factory", "engine", target],
                "walkforward": ["heimdall.research.walkforward", target],
            }[job]
            _start(argv, f"{job} · {target}")


def _start(argv: list[str], label: str) -> None:
    log = data_root() / "logs" / "lab_job.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
        [sys.executable, "-m", *argv],
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    st.session_state[_PROC] = proc
    st.session_state[_JOB] = label
    st.rerun()


# --- leaderboard --------------------------------------------------------------------------


def _leaderboard_tab(run_id: str | None) -> None:
    board = lab.leaderboard(run_id) if run_id else None
    if board is None:
        st.info(t("No trials yet for this run."))
        return
    c1, c2, c3 = st.columns(3)
    c1.metric(t("Trials (N)"), f"{board.n_trials:,}", help=glossary.help("trial_count"))
    c2.metric(
        "PBO",
        f"{board.pbo:.2f}",
        delta=t("passes F2") if board.run_passes_f2 else t("fails F2"),
        delta_color="normal" if board.run_passes_f2 else "inverse",
        help=glossary.help("pbo"),
    )
    c3.metric(t("Candidates"), int(board.table["candidate"].sum()))
    only = st.toggle(t("Candidates only (F1 + F2 + F3 + F5)"), key="lab_only")
    table = board.table[board.table["candidate"]] if only else board.table
    st.dataframe(
        table[lab.LEADERBOARD_COLUMNS].head(200),
        hide_index=True,
        width="stretch",
        column_config={
            "objective": st.column_config.NumberColumn(
                t("DEV IR vs EW universe"), format="%.2f", help=glossary.help("ir")
            ),
            "dsr": st.column_config.NumberColumn("DSR", format="%.3f", help=glossary.help("dsr")),
            # "percent" multiplies by 100 (0.0465 -> 4.65%); a printf "%.2%%" is not applied.
            "alpha_mean": st.column_config.NumberColumn(
                t("Selection alpha (6m)"), format="percent"
            ),
            "turnover": st.column_config.NumberColumn(t("Turnover"), format="percent"),
        },
    )
    st.caption(
        t(
            "DEV 2010–2019 only. DSR is deflated by this run's N; PBO is the run's probability of "
            "backtest overfitting. A candidate still needs its single VAL look (F4) to incubate."
        )
    )


# --- strategy detail ----------------------------------------------------------------------


def _detail_tab(run_id: str | None) -> None:
    trials = lab.cached_trials(run_id) if run_id else []
    if not run_id or not trials:
        st.info(t("No cached engine backtest yet — run the 'engine' job for this run."))
        return
    tid = st.selectbox(t("Trial"), trials, key="lab_trial")
    ev = lab.engine_evidence(run_id, int(tid))
    if ev is None:
        return
    r = ev.returns
    stats = portfolio_stats(r["strategy"], r["benchmark"], r.get("universe"))
    c = st.columns(5)
    c[0].metric("CAGR", f"{stats['cagr']:.1%}", delta=f"SPY {stats['benchmark_cagr']:.1%}")
    c[1].metric("Sharpe", f"{stats['sharpe']:.2f}")
    c[2].metric(t("Max drawdown"), f"{stats['max_drawdown']:.1%}")
    c[3].metric(t("IR vs EW universe"), f"{stats.get('ir_vs_universe', float('nan')):.2f}")
    c[4].metric(t("Beta"), f"{stats['beta']:.2f}")
    st.line_chart((1.0 + r).cumprod(), height=320)
    st.area_chart(drawdown(r["strategy"]).rename(t("Drawdown")), height=160)
    st.subheader(t("Yearly returns"))
    st.dataframe(yearly_returns(r).style.format("{:.1%}"), width="stretch")
    if ev.sectors is not None:
        st.subheader(t("Sector exposure over time"))
        st.area_chart(ev.sectors, height=220)
    if ev.holdings is not None and len(ev.holdings):
        last = ev.holdings[ev.holdings["decision_date"] == ev.holdings["decision_date"].max()]
        st.subheader(t("Last DEV book (historical, not today's)"))
        st.dataframe(last, hide_index=True, width="stretch")
    if ev.trades is not None and len(ev.trades):
        with st.expander(t("Trades")):
            st.dataframe(ev.trades.tail(500), hide_index=True, width="stretch")
    st.caption(
        t(
            "Daily engine: fills at the next open, 20 bps per side, drift between fills. "
            "DEV window only; an optimistic upper bound (current-universe survivorship)."
        )
    )


# --- walk-forward --------------------------------------------------------------------------


def _walkforward_tab(run_id: str | None) -> None:
    mode = st.radio(t("Mode"), ["top1", "top3"], horizontal=True, key="lab_wf_mode")
    summary = lab.walk_forward_summary(run_id, mode) if run_id else None
    curve = lab.walk_forward_curve(run_id, mode) if run_id else None
    if summary is None or curve is None:
        st.info(t("No walk-forward yet — run the 'walkforward' job for this run."))
        return
    stats = summary.get("stats", {})
    if isinstance(stats, dict):
        c = st.columns(3)
        c[0].metric("CAGR", f"{float(stats.get('cagr', float('nan'))):.1%}")
        c[1].metric("SPY CAGR", f"{float(stats.get('benchmark_cagr', float('nan'))):.1%}")
        c[2].metric(t("EW universe CAGR"), f"{float(stats.get('universe_cagr', float('nan'))):.1%}")
    st.line_chart((1.0 + curve).cumprod(), height=300)
    st.dataframe(pd.DataFrame(summary.get("choices", [])), hide_index=True, width="stretch")
    st.caption(
        t(
            "Backtests the factory's own selection procedure: each year re-selects using only "
            "data knowable at the prior year-end. Descriptive, never a gate."
        )
    )


# --- incubating ------------------------------------------------------------------------------


def _incubating_tab() -> None:
    items = lab.incubating()
    st.caption(
        t(
            "Incubating = passed the factory's over-fitting gates and one VAL look; "
            "forward-tracked, not certified."
        )
    )
    if not items:
        st.info(t("No incubating strategy yet."))
        return
    for item in items:
        st.subheader(f"{item.name} v{item.version} — {t('未認證・孵化中')}")
        st.caption(f"{item.family} · {t('since')} {item.since} · {item.description}")
        st.write(f"{t('Frozen forward cohorts')}: {len(item.cohorts)}")
        if item.monitoring:
            lo, hi = item.monitoring.get("trailing_alpha_ci95", [float("nan")] * 2)  # type: ignore[misc]
            st.write(
                f"{t('Forward skill (trailing)')}: "
                f"{float(str(item.monitoring.get('trailing_alpha_mean'))):+.2%} "
                f"(95% CI {float(lo):+.2%}..{float(hi):+.2%})"
            )
        if item.cohorts:
            latest = item.cohorts[-1]
            picks = pd.DataFrame(latest.get("picks", []))  # type: ignore[arg-type]
            with st.expander(
                f"{t('Latest frozen cohort')} {latest.get('month')} ({t('uncertified')})"
            ):
                st.dataframe(picks, hide_index=True, width="stretch")
                _incubating_orders(item)


def _incubating_orders(item: lab.IncubatingInfo) -> None:
    """18.10: an order plan from the latest *frozen* cohort (never a live re-ranking), labeled."""
    st.caption(t("Order plan from the latest frozen cohort (uncertified)"))
    try:
        from heimdall.ui._data import snapshot

        snap = snapshot()
    except FileNotFoundError:
        st.info(t("No snapshot yet — build one on the Build data page."))
        return
    closes = dict(zip(snap["symbol"].astype(str), snap["price"].astype(float), strict=False))
    targets = frozen_weights(list(item.cohorts[-1].get("picks", [])))  # type: ignore[arg-type]
    previous = (
        frozen_weights(list(item.cohorts[-2].get("picks", [])))  # type: ignore[arg-type]
        if len(item.cohorts) > 1
        else {}
    )
    budget = st.number_input(
        t("Budget"), min_value=0.0, value=100_000.0, step=1000.0, key=f"lab_budget_{item.name}"
    )
    frac = st.checkbox(t("Fractional shares (US)"), key=f"lab_frac_{item.name}")
    orders = weighted_plan(targets, previous, closes, float(budget), "US", fractional=frac)
    if not orders:
        return
    st.dataframe(pd.DataFrame([o.__dict__ for o in orders]), hide_index=True, width="stretch")
    st.download_button(
        t("Download order plan (CSV)"),
        orders_to_csv(orders),
        file_name=f"{item.name}_incubating_orders.csv",
        mime="text/csv",
        key=f"lab_csv_{item.name}",
    )


# --- technical research ------------------------------------------------------------------


def _tech_tab() -> None:
    st.caption("研究工具・持有期 < 1 個月，不在認證範圍 — " + t("never tiered, never a pick."))
    res = lab.tech_factory_results()
    if res is None:
        st.info(
            t("No technical-factory run yet: `uv run python -m heimdall.backtest.tech_factory`.")
        )
        return
    per_rule, per_pair = res
    st.dataframe(per_rule, hide_index=True, width="stretch")
    with st.expander(t("Per symbol × rule")):
        st.dataframe(per_pair, hide_index=True, width="stretch")
