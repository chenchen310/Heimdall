"""Headless smoke test: the screener page renders without exception (no network).

Uses Streamlit's AppTest against a crafted snapshot in a temp data dir. Skipped
if the optional ``ui`` extra (streamlit) isn't installed.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
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


def _apply(at: AppTest) -> AppTest:
    """Click the Screener's "Apply" button — confirms whichever preset/saved screen
    is previewed in the dropdown, since selecting it alone no longer touches the
    working table (the P2 fix for silently-clobbered edits)."""
    [b for b in at.button if "Apply" in b.label][0].click().run()
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
    _point_registry_at(tmp_path, monkeypatch)  # isolate from the real repo's registry.json
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    assert [h.value for h in at.header] == ["🎯 今日候選"]  # the new default landing page
    lang_select = [s for s in at.sidebar.selectbox if "Language" in s.label][0]
    assert lang_select.value == "繁體中文"


def test_screener_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()  # don't reuse a snapshot cached from another test/dir

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")  # Today's Picks is the default landing page now

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
    _nav(at, "Screener")
    assert not at.exception
    cols = list(at.dataframe[-1].value.columns)
    assert "symbol" in cols  # kept (and pinned via column_config)
    assert "market_cap" not in cols  # not filtered/sorted on — hidden by default (P2 fix)

    # Add it explicitly via "+ Show more columns" — it should then show, labeled with
    # its currency, exactly like the fields shown by default already do.
    [m for m in at.multiselect if m.label == "+ Show more columns"][0].set_value(
        ["market_cap"]
    ).run()
    assert not at.exception
    cols = list(at.dataframe[-1].value.columns)
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
    _nav(at, "Screener")
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
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("explore").run()
    _apply(at)
    assert not at.exception
    out = at.dataframe[-1].value
    assert "added" in out.columns  # the ➕ marker column
    assert bool(out.loc[out["symbol"] == "A.US", "added"].iloc[0]) is True
    assert any("➕" in c.value for c in at.caption)


def test_screener_default_columns_are_narrow_but_include_filtered_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    cols = list(at.dataframe[-1].value.columns)
    assert set(cols) == {"symbol", "pe", "roe", "net_margin"}  # exactly the predicate fields
    assert "rsi_14" not in cols and "pct_above_sma_200" not in cols  # not filtered on — hidden


def test_screener_pool_stats_panel_shows_min_median_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heimdall.ui import _glossary

    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)  # pe = [10.0, 40.0] -> median 25
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    stats = at.dataframe[1].value  # editor is [0]; pool-stats panel is [1]
    row = stats[stats["Field"].str.endswith(_glossary.label("pe"))]
    assert not row.empty
    assert row.iloc[0]["Min"] == "10.00×"
    assert row.iloc[0]["Median"] == "25.00×"
    assert row.iloc[0]["Max"] == "40.00×"


def test_screener_switching_preset_without_apply_does_not_touch_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    assert at.dataframe[0].value["field"].tolist() == ["pe", "roe", "net_margin"]

    # Browsing a different preset previews it (see the caption) but must not silently
    # discard whatever is in the working table — the P2 fix.
    [s for s in at.selectbox if s.label == "Start from preset"][0].set_value(
        "Oversold quality"
    ).run()
    assert not at.exception
    assert any("RSI" in c.value for c in at.caption)  # the preview line updated…
    assert at.dataframe[0].value["field"].tolist() == ["pe", "roe", "net_margin"]  # …editor didn't

    # Only clicking Apply actually swaps the working table.
    _apply(at)
    assert not at.exception
    assert at.dataframe[0].value["field"].tolist() == ["rsi_14", "revenue_growth_yoy"]


def test_screener_between_predicate_filters_a_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pe = 10, 15, 40 — "between 10 and 20" (inclusive) keeps A and B, excludes C.
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_money_snapshot(tmp_path, ["A.US", "B.US", "C.US"])
    store.save_screen(
        Screen(name="mid-pe", predicates=[Predicate(field="pe", op="between", value=[10, 20])]),
        root=tmp_path,
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("mid-pe").run()
    _apply(at)
    assert not at.exception
    assert at.dataframe[-1].value["symbol"].tolist() == ["A.US", "B.US"]


def test_screener_factor_score_preset_runs_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "Start from preset"][0].set_value(
        "All-around (composite)"
    ).run()
    _apply(at)
    assert not at.exception
    # factor_scores() ran over the snapshot, so the composite score is a real column —
    # not just a preset label with nothing behind it.
    assert "composite_score" in at.dataframe[-1].value.columns


def test_screener_result_row_can_open_stock_workbench(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    assert at.dataframe[-1].value["symbol"].tolist() == ["A.US"]  # default preset, one match

    # Programmatically set the results table's selection (the documented way to drive
    # st.dataframe(on_select=...) in tests — mirrors a user clicking the row). Unlike a
    # real frontend, AppTest doesn't keep resubmitting a widget's last state on its own,
    # so the selection has to be re-asserted before every run that depends on it.
    at.session_state["screener_results"] = {"selection": {"rows": [0]}}
    at.run(timeout=60)
    assert not at.exception
    open_buttons = [b for b in at.button if "A.US" in b.label]
    assert open_buttons  # "Open A.US in Stock Workbench →" appeared once the row was selected

    at.session_state["screener_results"] = {"selection": {"rows": [0]}}
    open_buttons[0].click().run(timeout=60)
    assert not at.exception
    assert [h.value for h in at.header] == ["🔎 Stock Workbench"]
    assert at.session_state["wb_symbol"] == "A.US"


def test_screener_sort_follows_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "pe"  # default preset
    assert [t_ for t_ in at.toggle if t_.label == "Ascending"][0].value is True

    [s for s in at.selectbox if s.label == "Start from preset"][0].set_value(
        "Above 200-day trend"
    ).run()
    _apply(at)
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "pct_above_sma_200"
    assert [t_ for t_ in at.toggle if t_.label == "Ascending"][0].value is False


def test_screener_manual_sort_choice_persists_until_preset_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "Rank by"][0].set_value("rsi_14").run()
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "rsi_14"

    # An unrelated interaction (Limit) must not reset the user's manual sort choice.
    [n for n in at.number_input if n.label == "Limit"][0].set_value(2).run()
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "rsi_14"

    # Merely *browsing* a different preset (no Apply yet) must not touch it either.
    [s for s in at.selectbox if s.label == "Start from preset"][0].set_value(
        "All-around (composite)"
    ).run()
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "rsi_14"

    # Only clicking Apply re-applies that preset's own natural sort.
    _apply(at)
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "composite_score"


def test_screener_loading_saved_screen_applies_its_own_sort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    store.save_screen(
        Screen(
            name="by-rsi",
            predicates=[Predicate(field="pe", op="<", value=100)],
            sort_by="rsi_14",
            ascending=False,
        ),
        root=tmp_path,
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("by-rsi").run()
    _apply(at)
    assert not at.exception
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "rsi_14"
    assert [t_ for t_ in at.toggle if t_.label == "Ascending"][0].value is False


def test_screener_saved_screen_with_unknown_sort_field_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    store.save_screen(
        Screen(
            name="stale-sort",
            predicates=[Predicate(field="pe", op="<", value=100)],
            sort_by="some_removed_field",
            ascending=False,
        ),
        root=tmp_path,
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Screener")
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("stale-sort").run()
    _apply(at)
    assert not at.exception  # no crash from a sort field that no longer exists
    assert [s for s in at.selectbox if s.label == "Rank by"][0].value == "pe"


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


def _certify_us_signal(
    tmp_path: Path, *, name: str = "us-mom", generated_at: str = "2024-01-02T00:00:00+00:00"
) -> None:
    """Set up a certified US signal (spec + immutable report + registry) via the real lifecycle."""
    from heimdall.research import registry as reg
    from heimdall.research.spec import SignalSpec

    spec = SignalSpec.model_validate(
        {
            "name": name,
            "family": name,
            "market": "US",
            "version": 1,
            "features": {"ret_12_1": 1.0},
            "top_n": 3,
        }
    )
    specs = tmp_path / "signals" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / f"{name}.json").write_text(spec.model_dump_json())
    report_file = tmp_path / "signals" / "certifications" / f"{name}_v1.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
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
                "generated_at": generated_at,
                "survivorship": "current_universe (optimistic)",
                "gates": [{"gate": "G1_ic", "value": 0.05, "threshold": 0.03, "passed": True}],
            }
        )
    )
    reg.add(spec, f"signals/specs/{name}.json", root=tmp_path)
    reg.transition(name, 1, "registered", root=tmp_path)
    reg.transition(name, 1, "certified", cert_report=str(report_file), oos_attempt=1, root=tmp_path)


def _write_us_panel(tmp_path: Path) -> None:
    rows = [
        {
            "date": pd.Timestamp("2024-01-31"),
            "symbol": sym,
            "eligible": True,
            "fwd_1m": f1,
            "fwd_6m": f6,
            "fwd_6m_rel": f6r,
        }
        for sym, f1, f6, f6r in [
            ("A.US", 0.10, 0.36, 0.30),
            ("B.US", 0.20, 0.12, 0.10),
            ("C.US", 0.00, 0.00, 0.00),
            ("D.US", -0.05, -0.12, -0.10),
            ("E.US", 0.01, 0.02, 0.01),
        ]
    ]
    (tmp_path / "research").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(tmp_path / "research" / "panel_us.parquet")


def _write_ledger_cohort(tmp_path: Path, name: str, month: str, picks: list[str]) -> None:
    from heimdall.research.ledger import cohort_path

    p = cohort_path(name, 1, month, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "name": name,
                "version": 1,
                "market": "US",
                "month": month,
                "as_of": f"{month}-15",
                "picks": [{"symbol": s, "signal_score": 1.0} for s in picks],
            }
        )
    )


def test_today_page_track_record_empty_state_without_cohorts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    _certify_us_signal(tmp_path)
    _write_us_panel(tmp_path)  # panel present, but nothing frozen yet
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    assert any(s.value == "Live track record" for s in at.subheader)
    assert any("No frozen cohorts yet" in i.value for i in at.info)


def test_today_page_track_record_renders_with_frozen_cohorts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    _certify_us_signal(tmp_path)
    _write_us_panel(tmp_path)
    _write_ledger_cohort(tmp_path, "us-mom", "2024-01", ["A.US", "B.US"])
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    assert any(s.value == "Live track record" for s in at.subheader)
    # The track-record table is keyed by the freeze date now, not the month.
    track = next(df.value for df in at.dataframe if "Frozen on" in list(df.value.columns))
    row = track[track["Frozen on"] == "2024-01-15"].iloc[0]  # the cohort's as_of date
    assert row["Frozen"] == 2  # the true frozen count, independent of realization
    # Formatted as a percentage string, never the raw "None"/NaN the pandas default shows.
    assert row["Book 6m (vs benchmark)"].endswith("%")
    assert "None" not in track.to_string()

    from heimdall.ui.i18n import _ZH

    assert "Live track record" in _ZH  # zh strings present


def test_today_page_track_record_shows_unrealized_mark_for_an_open_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact real-world case this closes: a cohort frozen mid-month, before the
    panel has a cross-section for that month at all — was previously an all-"None"
    row with no way to tell it apart from "nothing was frozen"."""
    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    _certify_us_signal(tmp_path)
    _write_us_panel(tmp_path)  # panel's only month is 2024-01 — nothing for 2024-03
    _write_ledger_cohort(tmp_path, "us-mom", "2024-03", ["A.US", "B.US"])

    def _fake_get_ohlcv(symbol: str, start: object, end: object) -> pd.DataFrame:
        # A.US +20%, B.US +10% -> EW +15%; benchmark flat -> alpha = +15%.
        entry_exit = {"A.US": (100.0, 120.0), "B.US": (100.0, 110.0)}.get(symbol, (100.0, 100.0))
        return pd.DataFrame(
            {"date": pd.to_datetime(["2024-03-15", "2024-03-20"]), "adj_close": list(entry_exit)}
        )

    monkeypatch.setattr("heimdall.ui.today_page.get_ohlcv", _fake_get_ohlcv)
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    track = next(df.value for df in at.dataframe if "Frozen on" in list(df.value.columns))
    row = track[track["Frozen on"] == "2024-03-15"].iloc[0]  # keyed by freeze date
    assert row["Frozen"] == 2  # the freeze is visible even though nothing can be scored yet
    assert row["Unrealized (vs benchmark)"] == "+15.0%"
    assert row["Book 6m (vs benchmark)"] == "—"  # not realized — an honest dash, not "None"
    assert bool(row["Realized"]) is False

    # Per-symbol P&L breakdown for the live cohort, best performers first.
    positions = next(df.value for df in at.dataframe if "vs benchmark" in list(df.value.columns))
    assert list(positions["Symbol"]) == ["A.US", "B.US"]  # +20% sorted before +10%
    assert positions.iloc[0]["Return"] == "+20.0%"


def test_today_page_rebalance_helper_renders_order_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _force_english(monkeypatch)
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_today_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    _certify_us_signal(tmp_path)
    _write_us_panel(tmp_path)
    # Frozen cohort {A,B}; today's picks are the snapshot's top-3 {A,B,C} ⇒ C is an "added" buy.
    _write_ledger_cohort(tmp_path, "us-mom", "2024-01", ["A.US", "B.US"])
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Today's Picks")
    assert not at.exception
    assert any(s.value == "Rebalance helper" for s in at.subheader)
    # The fixed execution-aid disclaimer is always on screen.
    assert any("not an order system" in c.value for c in at.caption)
    # The order plan lists the added name as a buy.
    plan = next(df.value for df in at.dataframe if "Side" in list(df.value.columns))
    assert "C.US" in list(plan["Symbol"]) and "buy" in list(plan["Side"])


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
    _write_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)  # isolate the default (Today's Picks) landing page
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    # Every page is a sidebar button…
    labels = {b.label for b in at.sidebar.button}
    assert {
        "Guide",
        "Glossary",
        "Today's Picks",
        "Stock Workbench",
        "Build data",
        "Screener",
        "Backtest",
        "Factors",
        "Macro",
    } <= labels
    assert "Chart" not in labels  # folded into Stock Workbench, no longer its own page
    # …under its group header.
    headers = " ".join(m.value for m in at.sidebar.markdown)
    for group in ("Help", "Data", "Stock picking", "Backtest", "Analyst lenses"):
        assert group in headers


def test_default_landing_page_is_todays_picks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The north-star page renders first, with no navigation — the Phase 1 fix for a new
    user's first paint being a dead-end "no snapshot" warning on the Screener."""
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    assert [h.value for h in at.header] == ["🎯 Today's Picks"]


def test_stock_workbench_invalid_symbol_stops_before_any_tab(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared picker validates before ``st.tabs()`` renders, so a symbol that fails
    ``parse_symbol`` never reaches a lens tab — and never triggers that tab's network
    calls. Seeding session_state before the first ``run()`` keeps this test network-free:
    the default "AAPL.US" is replaced before the script ever executes once."""
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))  # no snapshot → quick-pick stays hidden
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP)
    at.session_state["page"] = "Stock Workbench"
    at.session_state["wb_symbol"] = "not-a-symbol"
    at.run(timeout=60)

    assert not at.exception
    assert [h.value for h in at.header] == ["🔎 Stock Workbench"]
    assert any("not canonical" in e.value for e in at.error)


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


def _write_sector_snapshot(data_dir: Path) -> None:
    """TW + US rows carrying a 14.1 ``sector`` column, for the sector-focus page."""
    snap = pd.DataFrame(
        {
            "symbol": ["2330.TW", "2317.TW", "A.US", "B.US"],
            "as_of": pd.Timestamp("2024-01-01"),
            "sector": ["半導體業", "其他電子業", "Manufacturing", "Services"],
            "pct_above_sma_200": [0.10, -0.05, 0.05, 0.02],
        }
    )
    snap.to_parquet(data_dir / "snapshot.parquet")


def _fake_ohlcv(symbol: str, start: object, end: object) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp("2024-06-28"), periods=30)
    base = 100.0 + (hash(symbol) % 5)  # a small per-symbol offset, still deterministic
    close = pd.Series(base + np.linspace(0, 3, len(dates)))
    return pd.DataFrame({"date": dates, "adj_close": close})


def _fake_chips(symbol: str, start: object, end: object) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp("2024-06-28"), periods=30)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": dates,
            "foreign_net_shares": 1000.0,
            "trust_net_shares": 500.0,
            "dealer_net_shares": 100.0,
            "foreign_hold_ratio": 40.0,
            "margin_balance": 2000.0,
            "margin_short_balance": 300.0,
            "currency": "TWD",
            "provider": "finmind",
            "fetched_at": pd.Timestamp.now(),
        }
    )


def test_sector_page_predates_sector_classification_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An older snapshot with no `sector` column (pre-14.1) must not crash — it shows
    # an actionable hint instead of a KeyError.
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)  # the plain fixture: no `sector` column
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Sector Focus")
    assert not at.exception
    assert [h.value for h in at.header] == ["🏭 Sector focus"]
    assert any("predates sector classification" in i.value for i in at.info)
    assert not at.button or "Run sector scan" not in " ".join(b.label for b in at.button)


def test_sector_page_full_flow_and_missing_flows_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_sector_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    monkeypatch.setattr("heimdall.ui.sector_page.get_ohlcv", _fake_ohlcv)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Sector Focus")
    assert not at.exception
    # The fixed non-certified caption must always be on screen.
    assert any("not a certified signal" in c.value for c in at.caption)

    at.radio[0].set_value("Taiwan").run(timeout=60)  # region radio: TW unlocks the flows block
    assert not at.exception
    [b for b in at.button if "Run sector scan" in b.label][0].click().run(timeout=60)
    assert not at.exception

    # Sector table rendered (both TW sectors from the fixture), no network hit (get_ohlcv faked).
    table = at.dataframe[0].value
    assert set(table["Sector"]) == {"半導體業", "其他電子業"}

    # 15.2's cache doesn't exist yet — the missing-flows hint renders, not a crash.
    assert any("roadmap 15.2" in i.value for i in at.info)

    # Drill-down expanders exist, one per sector.
    assert len(at.expander) == 2

    from heimdall.ui.i18n import _ZH

    assert "🏭 產業焦點" in _ZH.values()


def _write_flows_cache(data_dir: Path, d: date, rows: list[dict[str, object]]) -> None:
    from heimdall.research.flows_cache import DAILY_COLUMNS, flows_cache_path

    df = pd.DataFrame(rows, columns=DAILY_COLUMNS)
    path = flows_cache_path(d, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def _write_tdcc_week(
    data_dir: Path, symbol: str, data_date: str, level_pcts: dict[int, float]
) -> None:
    """One real TDCC weekly cache file (roadmap 13.9's canonical shape) for one
    symbol, written directly at the real cache path (delta-merges with whatever
    that week's file already holds, matching how real weekly builds accumulate
    across the whole market one symbol's worth at a time in tests)."""
    from heimdall.data.providers.tdcc import AVAILABILITY_LAG, CANONICAL_COLUMNS, cache_path

    dd = pd.Timestamp(data_date)
    new_rows = pd.DataFrame(
        {
            "symbol": symbol,
            "data_date": dd,
            "available_at": dd + AVAILABILITY_LAG,
            "level": list(level_pcts),
            "holders": 1,
            "shares": 1.0,
            "pct_of_custody": list(level_pcts.values()),
            "currency": "TWD",
            "provider": "tdcc",
            "fetched_at": pd.Timestamp.now(),
        },
        columns=CANONICAL_COLUMNS,
    )
    path = cache_path(dd.date(), data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        new_rows = pd.concat([pd.read_parquet(path), new_rows], ignore_index=True)
    new_rows.to_parquet(path)


def test_flows_page_big_holder_tab_no_cache_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Market Flows")
    [t for t in at.tabs if "Big Holders" in t.label][0]  # the tab exists
    assert not at.exception
    assert any("No TDCC big-holder data cached yet." in i.value for i in at.info)
    assert any("tdcc_cache" in c.value for c in at.caption)  # the CLI hint


def test_flows_page_big_holder_tab_renders_risers_and_fallers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _point_registry_at(tmp_path, monkeypatch)
    dates = ["2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26"]
    risers_pcts = [40.0, 42.0, 44.0, 50.0]
    fallers_pcts = [60.0, 55.0, 52.0, 40.0]
    for d, rp, fp in zip(dates, risers_pcts, fallers_pcts, strict=True):
        _write_tdcc_week(tmp_path, "1101.TW", d, {15: rp})
        _write_tdcc_week(tmp_path, "2801.TW", d, {15: fp})
    # High liquidity so the §3 floor doesn't filter these out.
    snap = pd.DataFrame(
        {
            "symbol": ["1101.TW", "2801.TW"],
            "as_of": pd.Timestamp("2024-01-01"),
            "dollar_vol_21d": [1e9, 1e9],
        }
    )
    snap.to_parquet(tmp_path / "snapshot.parquet")
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Market Flows")
    assert not at.exception
    assert not any("No TDCC big-holder data cached yet." in i.value for i in at.info)
    risers = at.dataframe[-2].value.set_index("Symbol")
    fallers = at.dataframe[-1].value.set_index("Symbol")
    assert risers.loc["1101.TW", "Δ (pp)"] == pytest.approx(10.0)  # 50 - 40
    assert fallers.loc["2801.TW", "Δ (pp)"] == pytest.approx(-20.0)  # 40 - 60


def test_chips_page_big_holder_overlay_no_data_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    monkeypatch.setattr("heimdall.ui.chips_page.get_daily_chips", _fake_chips)
    monkeypatch.setattr("heimdall.ui.chips_page.get_ohlcv", _fake_ohlcv)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Chips")
    [b for b in at.button if "Load chip data" in b.label][0].click().run(timeout=60)
    assert not at.exception
    assert any("No TDCC big-holder data cached yet for this symbol." in i.value for i in at.info)


def test_chips_page_big_holder_overlay_renders_with_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)
    _write_tdcc_week(tmp_path, "2330.TW", "2024-01-05", {15: 40.0})  # the page's default symbol
    st.cache_data.clear()

    _force_english(monkeypatch)
    monkeypatch.setattr("heimdall.ui.chips_page.get_daily_chips", _fake_chips)
    monkeypatch.setattr("heimdall.ui.chips_page.get_ohlcv", _fake_ohlcv)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Chips")
    [b for b in at.button if "Load chip data" in b.label][0].click().run(timeout=60)
    assert not at.exception
    assert not any(
        "No TDCC big-holder data cached yet for this symbol." in i.value for i in at.info
    )


def test_sector_page_flows_block_renders_real_rollup_once_cache_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15.2's DoD: re-verify 14.2's TW flows block once real data exists — it must
    show a genuine by-sector rollup, not the pending hint, and not a raw per-symbol
    dump (the block was upgraded from a passthrough to analytics.flows.sector_rollup
    as part of 15.2)."""
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_sector_snapshot(tmp_path)  # 2330.TW=半導體業, 2317.TW=其他電子業
    _point_registry_at(tmp_path, monkeypatch)
    _write_flows_cache(
        tmp_path,
        date.today(),
        [
            {
                "symbol": "2330.TW",
                "sector": "半導體業",
                "date": pd.Timestamp(date.today()),
                "foreign_net_shares": 1000.0,
                "trust_net_shares": 0.0,
                "dealer_net_shares": 0.0,
                "foreign_hold_ratio": 73.0,
                "close": 10.0,
            },
            {
                "symbol": "2317.TW",
                "sector": "其他電子業",
                "date": pd.Timestamp(date.today()),
                "foreign_net_shares": -500.0,
                "trust_net_shares": 0.0,
                "dealer_net_shares": 0.0,
                "foreign_hold_ratio": 40.0,
                "close": 20.0,
            },
        ],
    )
    st.cache_data.clear()

    _force_english(monkeypatch)
    monkeypatch.setattr("heimdall.ui.sector_page.get_ohlcv", _fake_ohlcv)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Sector Focus")
    at.radio[0].set_value("Taiwan").run(timeout=60)
    [b for b in at.button if "Run sector scan" in b.label][0].click().run(timeout=60)
    assert not at.exception

    assert not any("roadmap 15.2" in i.value for i in at.info)  # the hint is gone
    flows_table = next(df.value for df in at.dataframe if "Foreign NT$" in df.value.columns)
    row = flows_table.set_index("Sector")
    assert row.loc["半導體業", "Foreign NT$"] == pytest.approx(1000.0 * 10.0)
    assert row.loc["其他電子業", "Foreign NT$"] == pytest.approx(-500.0 * 20.0)


def test_flows_page_no_cache_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _point_registry_at(tmp_path, monkeypatch)
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Market Flows")
    assert not at.exception
    assert [h.value for h in at.header] == ["💰 TW market flows"]
    assert any("not a certified signal" in c.value for c in at.caption)
    assert any("No flow data cached yet" in i.value for i in at.info)
    assert any("Build today's flows" in b.label for b in at.button)  # the fetch is opt-in


def test_flows_page_renders_all_blocks_from_a_precomputed_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _point_registry_at(tmp_path, monkeypatch)
    today = date.today()
    yesterday = today - timedelta(days=1)

    def _rows(
        d: date, foreign_ratio_2330: float, foreign_ratio_2882: float
    ) -> list[dict[str, object]]:
        return [
            {
                "symbol": "2330.TW",
                "sector": "半導體業",
                "date": pd.Timestamp(d),
                "foreign_net_shares": 1000.0,
                "trust_net_shares": 500.0,
                "dealer_net_shares": -100.0,
                "foreign_hold_ratio": foreign_ratio_2330,
                "close": 600.0,
            },
            {
                "symbol": "2882.TW",
                "sector": "金融保險業",
                "date": pd.Timestamp(d),
                "foreign_net_shares": -200.0,
                "trust_net_shares": 50.0,
                "dealer_net_shares": 10.0,
                "foreign_hold_ratio": foreign_ratio_2882,
                "close": 50.0,
            },
        ]

    # Two days so holding_ratio_delta (needs >=2 observations) has something to show.
    _write_flows_cache(tmp_path, yesterday, _rows(yesterday, 72.0, 39.0))
    _write_flows_cache(tmp_path, today, _rows(today, 73.0, 40.0))
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Market Flows")
    at.radio[0].set_value("Weekly").run(timeout=60)  # pull in both cached days
    assert not at.exception
    assert not any("No flow data cached yet" in i.value for i in at.info)  # cache found, no hint
    # market-wide totals (3 metrics: foreign/trust/dealer).
    assert len(at.metric) == 3
    # every downstream table rendered without exception.
    assert len(at.dataframe) >= 4  # sector rollup, top names, trust streak, holding delta

    from heimdall.ui.i18n import _ZH

    assert "💰 台股資金流向" in _ZH.values()


def test_glossary_page_renders_and_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))  # glossary needs no snapshot
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "Glossary")
    assert not at.exception
    assert [h.value for h in at.header] == ["📚 Indicator Glossary"]
    assert len(at.subheader) >= 5  # one per populated category, unfiltered

    at.text_input[0].set_value("sharpe").run()
    assert not at.exception
    body = " ".join(m.value for m in at.markdown)
    assert "`sharpe`" in body
    assert "`pe`" not in body  # narrowed away by the search


def test_chips_page_renders_without_fetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The TW chips lens renders its inputs + the fixed non-certified disclaimer, and does NOT
    # touch the network until "Load chip data" is clicked (the button gates every fetch).
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    _point_registry_at(tmp_path, monkeypatch)  # keep the default landing page network-free
    st.cache_data.clear()

    _force_english(monkeypatch)
    at = AppTest.from_file(APP).run(timeout=60)
    _nav(at, "TW Chips")
    assert not at.exception
    assert [h.value for h in at.header] == ["💰 TW Chips — who is buying"]

    # The rule for every descriptive lens: the "not a certified signal" caption is on screen.
    captions = " ".join(c.value for c in at.caption)
    assert "not a certified signal" in captions
    # Pre-fetch (no Load click) → the market-wide-flows pointer shows and nothing was fetched.
    infos = " ".join(i.value for i in at.info)
    assert "Market flows page" in infos
    assert not at.dataframe  # no ranking table — this is descriptive, not a recommendation

    from heimdall.ui.i18n import _ZH

    assert "台股籌碼" in _ZH.values()  # zh strings present
