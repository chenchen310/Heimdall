"""Headless smoke test: the screener page renders without exception (no network).

Uses Streamlit's AppTest against a crafted snapshot in a temp data dir. Skipped
if the optional ``ui`` extra (streamlit) isn't installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from heimdall.screener import store
from heimdall.screener.model import Predicate, Screen

pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "heimdall" / "ui" / "app.py")


def _force_english(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the UI to English for a test, bypassing the sidebar's language toggle.

    ``current_lang()`` reads ``st.session_state``, which AppTest can evaluate outside
    an active script run (e.g. while serializing widget state between reruns) — there
    it falls back to the *default* UI language. A page with a ``format_func=t`` widget
    (e.g. the Screener's Market radio) then sees mismatched options between the render
    and that out-of-band check and raises. Patching the function directly keeps ``t()``
    consistently "en" in both contexts, sidestepping the mismatch entirely. Call before
    constructing the ``AppTest``.
    """
    monkeypatch.setattr("heimdall.ui.i18n.current_lang", lambda: "en")


def _nav(at: AppTest, label: str) -> AppTest:
    """Click a grouped sidebar nav button by its (English) label, then rerun."""
    [b for b in at.sidebar.button if b.label == label][0].click().run()
    return at


def _write_snapshot(data_dir: Path) -> None:
    snap = pd.DataFrame(
        {
            "symbol": ["A.US", "B.US"],
            "as_of": [pd.Timestamp("2024-01-01")] * 2,
            "pe": [10.0, 40.0],
            "roe": [0.20, 0.05],
            "net_margin": [0.20, 0.05],
            "rsi_14": [30.0, 70.0],
            "pct_above_sma_200": [0.10, -0.10],
        }
    )
    snap.to_parquet(data_dir / "snapshot.parquet")


def test_default_language_is_traditional_chinese(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No language chosen yet — the sidebar selector's first option (繁體中文) is default.
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    assert [h.value for h in at.header] == ["📊 選股器"]
    lang_select = [s for s in at.sidebar.selectbox if "Language" in s.label][0]
    assert lang_select.value == "繁體中文"


def test_screener_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()  # don't reuse a snapshot cached from another test/dir

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)

    assert not at.exception  # the script ran cleanly (empty ElementList)
    assert [h.value for h in at.header] == ["📊 Screener"]
    # default market is US (USD); the "Cheap & profitable" preset → only A.US
    assert at.radio[0].options == ["US (USD)"]
    results = at.dataframe[-1].value
    assert results["symbol"].tolist() == ["A.US"]


def _write_mixed_snapshot(data_dir: Path) -> None:
    """US + Taiwan rows with varying factor inputs, for the market-split test."""
    snap = pd.DataFrame(
        {
            "symbol": ["A.US", "B.US", "2330.TW", "2317.TW"],
            "as_of": [pd.Timestamp("2024-01-01")] * 4,
            "pe": [10.0, 40.0, 15.0, 25.0],
            "roe": [0.25, 0.05, 0.27, 0.10],
            "net_margin": [0.22, 0.04, 0.40, 0.03],
            "ret_6m": [0.20, -0.10, 0.25, 0.02],
            "revenue_growth_yoy": [0.15, -0.02, 0.18, 0.01],
        }
    )
    snap.to_parquet(data_dir / "snapshot.parquet")


def test_factors_ranking_splits_us_and_taiwan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_mixed_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Factors")  # navigate to the Factors page
    assert not at.exception
    assert [h.value for h in at.header] == ["🧬 Factors"]

    # One market at a time, each labeled with its own currency.
    assert at.radio[0].options == ["US (USD)", "Taiwan (TWD)"]
    assert at.dataframe[-1].value["symbol"].tolist() == ["A.US", "B.US"]  # default US

    at.radio[0].set_value("Taiwan").run()
    assert not at.exception
    assert at.dataframe[-1].value["symbol"].tolist() == ["2330.TW", "2317.TW"]


def test_build_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The page renders its controls without starting a build (no network / subprocess).
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Build data")
    assert not at.exception
    assert [h.value for h in at.header] == ["🗂 Data — build snapshot"]
    assert at.radio  # the quick-tab Universe picker rendered


def _write_money_snapshot(data_dir: Path, symbols: list[str]) -> None:
    """US/TW snapshot with a monetary column + the fields the default preset needs."""
    n = len(symbols)
    snap = pd.DataFrame(
        {
            "symbol": symbols,
            "as_of": [pd.Timestamp("2024-01-01")] * n,
            "market_cap": [3.0e12, 6.0e11, 1.0e9][:n],
            "pe": [10.0, 15.0, 40.0][:n],
            "roe": [0.25, 0.27, 0.05][:n],
            "net_margin": [0.22, 0.40, 0.04][:n],
            "rsi_14": [30.0, 50.0, 70.0][:n],
            "pct_above_sma_200": [0.10, 0.10, -0.10][:n],
        }
    )
    snap.to_parquet(data_dir / "snapshot.parquet")


def test_screener_labels_money_columns_and_keeps_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_money_snapshot(tmp_path, ["A.US", "B.US"])
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    cols = list(at.dataframe[-1].value.columns)
    assert "symbol" in cols  # kept (and pinned via column_config)
    assert "market_cap (USD)" in cols and "market_cap" not in cols  # labelled with currency


def test_screener_warns_loading_money_screen_in_other_market(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_money_snapshot(tmp_path, ["A.US", "2330.TW"])
    store.save_screen(
        Screen(
            name="us-bigcap",
            market="US",
            predicates=[Predicate(field="market_cap", op=">", value=1e11)],
        ),
        root=tmp_path,
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("us-bigcap").run()
    at.radio[0].set_value("Taiwan").run()  # a different-currency market
    assert any("market_cap" in w.value for w in at.warning)


def test_screener_disabled_condition_widens_and_marks_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_money_snapshot(tmp_path, ["A.US", "B.US"])
    # pe<25 stays on; roe>0.5 is saved OFF, so disabling it surfaces rows as "extra".
    store.save_screen(
        Screen(
            name="explore",
            predicates=[
                Predicate(field="pe", op="<", value=25),
                Predicate(field="roe", op=">", value=0.5, enabled=False),
            ],
        ),
        root=tmp_path,
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("explore").run()
    assert not at.exception
    out = at.dataframe[-1].value
    assert "added" in out.columns  # the ➕ marker column
    assert bool(out.loc[out["symbol"] == "A.US", "added"].iloc[0]) is True
    assert any("➕" in c.value for c in at.caption)


def _write_today_snapshot(data_dir: Path) -> None:
    """Snapshot with the 9.1 hygiene fields + the default screener preset fields."""
    snap = pd.DataFrame(
        {
            "symbol": [f"{s}.US" for s in "ABCDE"],
            "as_of": pd.Timestamp("2024-01-02"),
            "price": 100.0,
            "dollar_vol_21d": 1e8,
            "ret_12_1": [0.5, 0.4, 0.3, 0.2, 0.1],
            "pe": 10.0,
            "roe": 0.20,
            "net_margin": 0.20,
            "rsi_14": 50.0,
            "pct_above_sma_200": 0.10,
        }
    )
    snap.to_parquet(data_dir / "snapshot.parquet")


def _point_registry_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "heimdall.research.registry.registry_path",
        lambda root=None: tmp_path / "signals" / "registry.json",
    )


def test_today_page_honest_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)  # empty registry → nothing may render
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    assert [h.value for h in at.header] == ["🎯 Today's Picks"]
    assert any("No certified signal" in i.value for i in at.info)
    assert not at.dataframe  # the rule: no ranking without a certified registry row


def test_today_page_renders_certified_evidence_then_picks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heimdall.research import registry as reg
    from heimdall.research.spec import SignalSpec

    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)

    spec = SignalSpec.model_validate(
        {
            "name": "us-mom",
            "family": "us-momentum",
            "market": "US",
            "version": 1,
            "features": {"ret_12_1": 1.0},
            "top_n": 3,
        }
    )
    (tmp_path / "signals" / "specs").mkdir(parents=True)
    (tmp_path / "signals" / "specs" / "us-mom.json").write_text(spec.model_dump_json())
    report_file = tmp_path / "signals" / "certifications" / "us-mom_v1.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text(
        json.dumps(
            {
                "verdict": "CERTIFIED",
                "portfolio_beat_rate": 0.72,
                "portfolio_beat_ci95": [0.58, 0.86],
                "selection_alpha_mean": 0.031,
                "selection_alpha_t": 2.4,
                "cohorts": [{"date": "2023-01-31"}] * 30,
                "window_start": "2023-01-31",
                "window_end": "2025-06-30",
                "generated_at": "2026-07-07T00:00:00+00:00",
                "gates": [
                    {"gate": "G1_ic", "value": 0.05, "threshold": 0.03, "passed": True},
                    {"gate": "G2_mean", "value": 0.012, "threshold": 0.0, "passed": True},
                ],
            }
        )
    )
    # Dogfood the real lifecycle — no hand-edited registry, even in tests.
    reg.add(spec, "signals/specs/us-mom.json", root=tmp_path)
    reg.transition("us-mom", 1, "registered", root=tmp_path)
    reg.transition(
        "us-mom", 1, "certified", cert_report=str(report_file), oos_attempt=1, root=tmp_path
    )
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    assert any(m.value == "72%" for m in at.metric)  # portfolio beat rate — evidence box first
    assert any(m.value == "+3.1%" for m in at.metric)  # the selection-skill (alpha) metric
    assert any("business days old" in w.value for w in at.warning)  # stale-snapshot banner
    picks = at.dataframe[-1].value
    assert picks["symbol"].tolist() == ["A.US", "B.US", "C.US"]  # top-3 by ret_12_1
    assert "z_ret_12_1" in picks.columns  # the why-it-ranks breakdown
    captions = " ".join(c.value for c in at.caption)
    assert "optimistic" in captions  # the survivorship stamp is always on screen

    from heimdall.ui.i18n import _ZH

    assert "🎯 Today's Picks" in _ZH  # zh strings present


def test_today_page_shows_drift_banner_for_under_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heimdall.research import registry as reg
    from heimdall.research.spec import SignalSpec

    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)

    spec = SignalSpec.model_validate(
        {
            "name": "us-x",
            "family": "us-fam",
            "market": "US",
            "version": 1,
            "features": {"ret_12_1": 1.0},
            "top_n": 3,
        }
    )
    (tmp_path / "signals" / "specs").mkdir(parents=True)
    (tmp_path / "signals" / "specs" / "us-x.json").write_text(spec.model_dump_json())
    reg.add(spec, "signals/specs/us-x.json", root=tmp_path)
    reg.transition("us-x", 1, "registered", root=tmp_path)
    reg.transition("us-x", 1, "certified", cert_report="r.json", oos_attempt=1, root=tmp_path)
    reg.transition("us-x", 1, "under_review", root=tmp_path)  # drift monitor flipped it
    mondir = tmp_path / "signals" / "monitoring"
    mondir.mkdir(parents=True)
    (mondir / "us-x_v1.json").write_text(
        json.dumps(
            {
                "name": "us-x",
                "version": 1,
                "status": "under_review",
                "n_cohorts": 20,
                "trailing_n": 12,
                "trailing_alpha_mean": -0.05,
                "trailing_alpha_ci95": [-0.12, -0.01],
                "trailing_beat_rate": 0.4,
                "drift": True,
                "flipped": True,
                "generated_at": "2026-08-01T00:00:00+00:00",
                "cohorts": [],
            }
        )
    )
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    warnings = " ".join(w.value.lower() for w in at.warning)
    assert "under review" in warnings and "skill" in warnings  # the honest drift banner
    assert not at.dataframe  # an under-review signal's ranking is withheld


def test_sidebar_nav_is_grouped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)  # default Screener page renders cleanly
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    # Every page is a sidebar button…
    labels = {b.label for b in at.sidebar.button}
    assert {
        "Today's Picks",
        "Build data",
        "Screener",
        "Chart",
        "Backtest",
        "Factors",
        "Macro",
    } <= labels
    # …under its group header.
    headers = " ".join(m.value for m in at.sidebar.markdown)
    for group in ("Help", "Data", "Stock picking", "Backtest", "Analyst lenses"):
        assert group in headers


def test_guide_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))  # guide needs no snapshot
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Guide")
    assert not at.exception
    assert [h.value for h in at.header] == ["📖 User guide"]
    # one collapsible guide per page (12) + the conventions expander
    assert len(at.expander) >= 12
