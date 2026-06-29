"""Headless smoke test: the screener page renders without exception (no network).

Uses Streamlit's AppTest against a crafted snapshot in a temp data dir. Skipped
if the optional ``ui`` extra (streamlit) isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from heimdall.screener import store
from heimdall.screener.model import Predicate, Screen

pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "heimdall" / "ui" / "app.py")


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


def test_screener_page_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)
    st.cache_data.clear()  # don't reuse a snapshot cached from another test/dir

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

    at = AppTest.from_file(APP).run(timeout=60)
    [s for s in at.selectbox if s.label == "…or load saved"][0].set_value("explore").run()
    assert not at.exception
    out = at.dataframe[-1].value
    assert "added" in out.columns  # the ➕ marker column
    assert bool(out.loc[out["symbol"] == "A.US", "added"].iloc[0]) is True
    assert any("➕" in c.value for c in at.caption)


def test_sidebar_nav_is_grouped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    _write_snapshot(tmp_path)  # default Screener page renders cleanly
    st.cache_data.clear()

    at = AppTest.from_file(APP).run(timeout=60)
    assert not at.exception
    # Every page is a sidebar button…
    labels = {b.label for b in at.sidebar.button}
    assert {"Build data", "Screener", "Chart", "Backtest", "Factors", "Macro"} <= labels
    # …under its group header.
    headers = " ".join(m.value for m in at.sidebar.markdown)
    for group in ("Data", "Stock picking", "Backtest", "Analyst lenses"):
        assert group in headers
