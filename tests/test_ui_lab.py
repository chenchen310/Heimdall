"""Strategy Lab page (roadmap 18.9) — headless AppTest smokes, no network.

Empty state, a fixture factory run with cached engine + walk-forward evidence, and an
incubating strategy. The banner "uncertified" must be on every tab, and nothing from the Lab
may leak onto Today's Picks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("streamlit.testing.v1")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from heimdall.research import factory, ledger, registry  # noqa: E402
from heimdall.research.spec import SignalSpec  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_research_factory import _panel  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "heimdall" / "ui" / "app.py")


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("heimdall.ui.i18n.current_lang", lambda: "en")
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "heimdall.research.registry.registry_path",
        lambda root=None: tmp_path / "signals" / "registry.json",
    )
    pd.DataFrame(
        {"symbol": ["A.US"], "as_of": [pd.Timestamp("2026-09-29")], "price": [10.0]}
    ).to_parquet(tmp_path / "snapshot.parquet")
    st.cache_data.clear()


def _open_lab(tmp_path: Path) -> AppTest:
    at = AppTest.from_file(APP).run(timeout=60)
    [b for b in at.sidebar.button if b.label == "Strategy Lab"][0].click().run(timeout=60)
    return at


def _warnings(at: AppTest) -> list[str]:
    return [w.value for w in at.warning]


def test_lab_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    at = _open_lab(tmp_path)
    assert not at.exception
    assert any("No search run yet" in i.value for i in at.info)
    assert sum("uncertified" in w for w in _warnings(at)) == 6  # one banner per tab


def _fixture_run(tmp_path: Path) -> None:
    cfg = factory.SearchConfig(
        run_id="lab1",
        feature_pool={"good": 1, "n1": 1},
        max_features=1,
        top_n_menu=[10],
        stage2_top_k=0,
    )
    log = tmp_path / "LOG.md"
    log.write_text(f"## 031 — declared\n{cfg.canonical_hash()}\n")
    factory.run_search(
        cfg, _panel(n_syms=40, end="2013-12-31"), log_entry="031", log_path=log, root=tmp_path
    )
    d = factory.engine_dir("lab1", tmp_path)
    d.mkdir(parents=True, exist_ok=True)  # the run's ledger already lives here
    days = pd.bdate_range("2011-01-03", "2013-12-31")
    rng = np.random.default_rng(0)
    rets = pd.DataFrame(
        rng.normal(0.0004, 0.01, (len(days), 3)),
        index=days,
        columns=["strategy", "benchmark", "universe"],
    )
    rets.to_parquet(d / "engine_t00000.parquet")
    pd.DataFrame(
        {
            "decision_date": [days[0]] * 2,
            "fill_date": [days[1]] * 2,
            "symbol": ["A.US", "B.US"],
            "weight": [0.5, 0.5],
        }
    ).to_parquet(d / "engine_t00000_holdings.parquet")
    pd.DataFrame(
        {"Tech": [1.0]}, index=pd.DatetimeIndex([days[0]], name="decision_date")
    ).to_parquet(d / "engine_t00000_sectors.parquet")
    rets.to_parquet(d / "walkforward_top1.parquet")
    (d / "walkforward_top1.json").write_text(
        json.dumps(
            {
                "stats": {"cagr": 0.1, "benchmark_cagr": 0.08, "universe_cagr": 0.09},
                "choices": [{"year": 2014, "trial_ids": [0], "reselected": True}],
            }
        )
    )


def test_lab_renders_a_fixture_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path, monkeypatch)
    _fixture_run(tmp_path)
    at = _open_lab(tmp_path)
    assert not at.exception
    assert any("N = 2 trials" in w for w in _warnings(at))  # trial count travels with the run
    labels = [m.label for m in at.metric]
    assert "Trials (N)" in labels and "PBO" in labels and "CAGR" in labels
    assert len(at.dataframe) >= 3  # runs, leaderboard, yearly returns (+ books)


def test_lab_incubating_tier_is_labeled_and_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, monkeypatch)
    spec = SignalSpec(
        name="lab1-t00000",
        family="us-factory-lab1",
        market="US",
        features={"good": 1.0},
        top_n=10,
        description="Incubating — uncertified",
    )
    rel = Path("signals/specs/factory/lab1-t00000.json")
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_text(spec.model_dump_json())
    registry.add(spec, str(rel), root=tmp_path)
    registry.transition(spec.name, 1, "incubating", root=tmp_path)
    cohort = ledger.cohort_path(spec.name, 1, "2026-10", tmp_path, tier="incubating")
    cohort.parent.mkdir(parents=True)
    cohort.write_text(
        json.dumps({"month": "2026-10", "picks": [{"symbol": "A.US", "signal_score": 1.0}]})
    )

    at = _open_lab(tmp_path)
    assert not at.exception
    assert any("lab1-t00000" in s.value and "未認證・孵化中" in s.value for s in at.subheader)
    # 18.10: the order plan comes from the latest *frozen* cohort, never a live ranking.
    plans = [df.value for df in at.dataframe if "side" in list(df.value.columns)]
    assert plans
    assert list(plans[0]["symbol"]) == ["A.US"] and list(plans[0]["side"]) == ["buy"]
    # Today's Picks must not render it: incubating is not certified.
    at2 = AppTest.from_file(APP).run(timeout=60)
    assert not any("lab1-t00000" in s.value for s in at2.subheader)


def test_lab_run_with_missing_ledger_never_reports_zero_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real-world case: us-f1 ran in another worktree, so this checkout had its config
    and engine outputs but not the gitignored ledger — and the Lab showed "N = 0 trials".
    N is what every factory number is judged against; it must never be misstated."""
    _setup(tmp_path, monkeypatch)
    _fixture_run(tmp_path)
    for name in factory.LEDGER_FILES:  # gone from both the shared and the legacy location
        (factory.ledger_dir("lab1", tmp_path) / name).unlink(missing_ok=True)
        (factory.run_dir("lab1", tmp_path) / name).unlink(missing_ok=True)

    at = _open_lab(tmp_path)
    assert not at.exception  # the leaderboard no longer KeyErrors on a half-present ledger
    assert not any("N = 0" in w for w in _warnings(at))
    assert any("trial ledger missing" in w for w in _warnings(at))
    assert any("trials.parquet" in e.value for e in at.error)
    assert any("factory migrate lab1" in c.value for c in at.code)  # the fix, ready to run
