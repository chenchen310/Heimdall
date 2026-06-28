"""Build / refresh the screener + factors snapshot from inside the app.

Thin shell over two core paths:

- **Quick** — curated or pasted symbols, run *in-process* with a live progress bar
  (``screener.snapshot.build_snapshot_iter``). Fine for tens–hundreds of symbols.
- **Whole market** — VTI (~3.4k) / all-Taiwan (~2.1k) are too long to block on, so we
  launch the existing ``screener.build`` CLI as a *background subprocess*; the page
  polls the (atomically written) snapshot for progress. It survives reruns and is
  resumable, so leaving the page — or even a restart — does not lose work.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import date

import pandas as pd
import streamlit as st

from heimdall.data import router
from heimdall.data.cache import CachedProvider
from heimdall.data.symbols import SymbolError, parse_symbol
from heimdall.screener.snapshot import (
    UNIVERSES,
    build_snapshot_iter,
    load_snapshot,
    snapshot_path,
    split_by_region,
)
from heimdall.ui import _data
from heimdall.ui.i18n import t

_PROC = "_build_proc"  # st.session_state key holding the running background Popen
_TARGET = "_build_target"

# Curated universes for the in-process path (small enough to block on).
_SMALL: dict[str, str] = {"US default (15)": "us", "Taiwan large caps (10)": "tw"}
# Whole-market universes for the background path: CLI flag + approx size (progress %).
_BIG: dict[str, tuple[str, int]] = {
    "VTI — whole US market (~3,400)": ("vti", 3400),
    "All TWSE + TPEX (~2,100)": ("tw-all", 2100),
}


def render() -> None:
    st.header(t("🗂 Data — build snapshot"))
    st.caption(
        t(
            "The snapshot is the data behind the Screener and Factors pages. "
            "Build or refresh it here."
        )
    )
    _current_status()
    _prereqs()
    quick, whole = st.tabs([t("Quick (curated / custom)"), t("Whole market (background)")])
    with quick:
        _quick_tab()
    with whole:
        _whole_tab()


def _current_status() -> None:
    try:
        snap = load_snapshot()
    except FileNotFoundError:
        st.info(t("No snapshot yet — build one below."))
        return
    parts = " · ".join(f"{r} {len(g)}" for r, g in split_by_region(snap).items())
    as_of = pd.to_datetime(snap["as_of"]).max().date() if "as_of" in snap else "n/a"
    st.caption(f"{t('Current snapshot')}: {len(snap)} ({parts}) · {t('as of')} {as_of}")


def _prereqs() -> None:
    edgar = bool(os.environ.get("SEC_EDGAR_USER_AGENT"))
    finmind = bool(os.environ.get("FINMIND_TOKEN"))
    a, b = st.columns(2)
    a.caption(
        ("✅ `SEC_EDGAR_USER_AGENT` " + t("set"))
        if edgar
        else ("⚠️ `SEC_EDGAR_USER_AGENT` " + t("missing — US fundamentals may be price-only"))
    )
    b.caption(
        ("✅ `FINMIND_TOKEN` " + t("set"))
        if finmind
        else ("ℹ️ `FINMIND_TOKEN` " + t("unset — Taiwan runs on a low free quota"))
    )


def _parse_symbols(raw: str) -> list[str]:
    """Canonical symbols from free text (comma/space/newline); silently drops junk."""
    out: list[str] = []
    for tok in re.split(r"[\s,]+", raw.strip()):
        if not tok:
            continue
        try:
            out.append(parse_symbol(tok).canonical)
        except SymbolError:
            continue
    return out


def _quick_tab() -> None:
    st.caption(t("Runs in the app with a progress bar — best for tens to a few hundred symbols."))
    if _running():
        st.warning(t("A background build is running — wait for it to finish or stop it first."))
        return

    custom = t("Custom symbols")
    choice = st.radio(t("Universe"), [*_SMALL, custom], horizontal=True)
    if choice == custom:
        raw = st.text_area(t("Symbols (comma / space / newline, e.g. AAPL.US 2330.TW)"), height=80)
        symbols = _parse_symbols(raw)
    else:
        symbols = list(UNIVERSES[_SMALL[choice]])

    rebuild = st.toggle(t("Re-fetch symbols already in the snapshot"), value=False)
    st.caption(
        f"{len(symbols)} {t('symbols')} — " + (t("refresh all") if rebuild else t("new only"))
    )

    if st.button(t("Build now"), type="primary", disabled=not symbols):
        _run_in_process(symbols, resume=not rebuild)


def _run_in_process(symbols: list[str], *, resume: bool) -> None:
    prices = CachedProvider(router.price_provider())
    funds = router.fundamentals_provider()
    bar = st.progress(0.0, text=t("Starting…"))
    done = built = total = 0
    failures: dict[str, int] = {}
    for p in build_snapshot_iter(symbols, prices, funds, date.today(), resume=resume):
        done, built, total, failures = p.done, p.built, p.total, p.failures
        if total:
            bar.progress(min(done / total, 1.0), text=f"{done}/{total} · {p.last_symbol}")
    bar.progress(1.0, text=t("Done"))
    _data.snapshot.clear()  # let the Screener / Factors pages pick up the new data

    if total == 0:
        st.info(t("Already up to date — nothing to fetch."))
        return
    msg = f"{t('Built')} {built}/{total}"
    if failures:
        msg += (
            " · " + t("skipped") + " " + ", ".join(f"{k}×{v}" for k, v in sorted(failures.items()))
        )
    st.success(msg)


def _whole_tab() -> None:
    st.caption(
        t(
            "Launches a background crawl. Long and one-time — you can leave this page; it keeps "
            "running and is resumable. Prices are cached, so a later refresh is far faster."
        )
    )
    proc = st.session_state.get(_PROC)
    if proc is not None and proc.poll() is None:
        _render_running(proc)
        return
    if proc is not None:  # finished since the last view
        code = proc.poll()
        st.session_state.pop(_PROC, None)
        _data.snapshot.clear()
        (st.success if code == 0 else st.warning)(
            t("Background build finished.") + f" (exit {code})"
        )

    choice = st.selectbox(t("Universe"), list(_BIG))
    market, approx = _BIG[choice]
    rebuild = st.toggle(t("Rebuild from scratch (re-fetch everything)"), value=False, key="big_reb")
    if st.button(t("Start background build"), type="primary"):
        _start_background(market, rebuild, approx)
        st.rerun()


def _start_background(market: str, rebuild: bool, approx: int) -> None:
    cmd = [sys.executable, "-m", "heimdall.screener.build", "--market", market]
    if rebuild:
        cmd.append("--rebuild")
    log = snapshot_path().with_name("build.log")
    # Detached: child gets its own stdout (the log); survives our reruns.
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell, no user input in cmd
        cmd, stdout=log.open("w"), stderr=subprocess.STDOUT, env=os.environ.copy()
    )
    st.session_state[_PROC] = proc
    st.session_state[_TARGET] = approx


def _render_running(proc: subprocess.Popen[bytes]) -> None:
    target = int(st.session_state.get(_TARGET, 1)) or 1
    try:
        cur = len(load_snapshot())
    except FileNotFoundError:
        cur = 0
    st.progress(min(cur / target, 0.99), text=f"~{cur}/{target} {t('symbols')}")
    st.caption(t("Building in the background — safe to switch pages; come back any time."))
    if st.button(t("Stop"), type="secondary"):
        proc.terminate()
        st.session_state.pop(_PROC, None)
        st.warning(t("Stopped. The partial snapshot is kept; start again to resume."))
        st.rerun()
    time.sleep(2)  # poll cadence
    st.rerun()


def _running() -> bool:
    proc = st.session_state.get(_PROC)
    return proc is not None and proc.poll() is None
