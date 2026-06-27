"""Headless smoke test: the screener page renders without exception (no network).

Uses Streamlit's AppTest against a crafted snapshot in a temp data dir. Skipped
if the optional ``ui`` extra (streamlit) isn't installed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "heimdall" / "ui" / "app.py")


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
    # default "Cheap & profitable" preset (pe<25, roe>.15, net_margin>.10) → only A.US
    results = at.dataframe[-1].value
    assert results["symbol"].tolist() == ["A.US"]
