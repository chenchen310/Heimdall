"""Walk-forward meta-backtest (roadmap 18.6) — PIT selection, stitching, VAL gating.

The load-bearing test is invariance: a year's choice may depend only on ledger values knowable
at the end of the previous year (1m series ≤ Nov, 6m series ≤ Jun). Scrambling everything after
those cutoffs must leave the choice untouched; a change before them must be able to move it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.research import factory, walkforward
from heimdall.research.spec import SignalSpec

MONTHS = pd.date_range("2010-01-31", "2019-12-31", freq="ME")


def _spec(tid: int, feat: str) -> str:
    return SignalSpec(
        name=f"w-t{tid:05d}", family="us-factory-w", market="US", features={feat: 1.0}, top_n=10
    ).model_dump_json()


def _ledger(
    root: Path, net: dict[int, np.ndarray], ic: dict[int, np.ndarray], a6: dict[int, np.ndarray]
) -> None:
    rows = [
        {
            "trial_id": t,
            "stage": 1,
            "spec_hash": str(t),
            "spec_json": _spec(t, "good"),
            "n_params": 1,
        }
        for t in net
    ]
    series = {
        "net": {str(t): list(v) for t, v in net.items()},
        "ic": {str(t): list(v) for t, v in ic.items()},
        "alpha6": {str(t): list(v) for t, v in a6.items()},
    }
    factory._append("w", rows, series, list(MONTHS), root)


def _series(mean: float, seed: int, sd: float = 0.01) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, sd, len(MONTHS))


def _two_trials(root: Path) -> None:
    # Trial 0 is solidly skilled; trial 1 is slightly worse but also eligible.
    _ledger(
        root,
        net={0: _series(0.006, 1), 1: _series(0.004, 2)},
        ic={0: _series(0.05, 3, 0.05), 1: _series(0.05, 4, 0.05)},
        a6={0: _series(0.03, 5, 0.03), 1: _series(0.03, 6, 0.03)},
    )


def _choices(root: Path, year: int, mode: str = "top1") -> list[int]:
    trials = factory.load_trials("w", root)
    net, ic, a6 = (factory.load_series("w", root, k) for k in ("net", "ic", "alpha6"))
    return walkforward.choose(walkforward.trailing_scores(trials, net, ic, a6, year), mode)[0]


def test_cutoffs() -> None:
    assert walkforward.cutoffs(2016) == (pd.Timestamp("2015-11-30"), pd.Timestamp("2015-06-30"))


def test_choice_ignores_everything_after_the_cutoffs(tmp_path: Path) -> None:
    _two_trials(tmp_path)
    before = {y: _choices(tmp_path, y) for y in walkforward.DEV_YEARS}
    assert all(c == [0] for c in before.values())
    for year in walkforward.DEV_YEARS:
        end1, end6 = walkforward.cutoffs(year)
        for kind, end in (("net", end1), ("ic", end1), ("alpha6", end6)):
            path = factory.series_path("w", tmp_path, kind)
            s = pd.read_parquet(path)
            late = s.index > end
            s.loc[late, "1"] = 10.0  # trial 1 becomes "amazing" — but only after the cutoff
            s.to_parquet(path)
        assert _choices(tmp_path, year) == [0], year
        # restore for the next year's check
        for kind in ("net", "ic", "alpha6"):
            factory.series_path("w", tmp_path, kind).unlink()
        factory.ledger_path("w", tmp_path).unlink()
        _two_trials(tmp_path)


def test_a_change_before_the_cutoff_can_move_the_choice(tmp_path: Path) -> None:
    _two_trials(tmp_path)
    path = factory.series_path("w", tmp_path, "net")
    s = pd.read_parquet(path)
    s.loc[s.index <= pd.Timestamp("2014-11-30"), "1"] = _series(0.03, 9)[
        : int((s.index <= "2014-11-30").sum())
    ]
    s.to_parquet(path)
    assert _choices(tmp_path, 2015) == [1]


def test_ineligible_trials_are_never_chosen(tmp_path: Path) -> None:
    _ledger(
        tmp_path,
        net={0: _series(0.02, 1)},  # great objective …
        ic={0: _series(0.0, 3, 0.05)},  # … but no IC skill → fails trailing F3
        a6={0: _series(0.03, 5, 0.03)},
    )
    assert _choices(tmp_path, 2016) == []


def test_top3_blends_up_to_three(tmp_path: Path) -> None:
    _two_trials(tmp_path)
    assert _choices(tmp_path, 2016, "top3") == [0, 1]
    blend = walkforward._blend([pd.Series({"A": 0.5, "B": 0.5}), pd.Series({"B": 1.0})])
    assert blend.to_dict() == pytest.approx({"A": 0.25, "B": 0.75})


# --- end to end ------------------------------------------------------------------


def _panel_and_matrices() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from test_research_factory import NOISE_POOL, _panel  # noqa: F401

    panel = _panel(n_syms=60, end="2020-12-31")
    days = pd.bdate_range("2009-12-01", "2023-01-31")
    rng = np.random.default_rng(2)
    syms = sorted(panel["symbol"].unique()) + ["SPY.US"]
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.01, (len(days), len(syms))), axis=0),
        index=days,
        columns=syms,
    )
    return panel, {"adj_open": close.shift(1), "adj_close": close}


def _run(tmp_path: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    panel, mats = _panel_and_matrices()
    cfg = factory.SearchConfig(
        run_id="w",
        feature_pool={"good": 1, "n1": 1, "n2": 1},
        max_features=1,
        top_n_menu=[10],
        stage2_top_k=0,
    )
    log = tmp_path / "LOG.md"
    log.write_text(f"## 019 — declared\n{cfg.canonical_hash()}\n")
    factory.run_search(cfg, panel, log_entry="019", log_path=log, root=tmp_path)
    return panel, mats


def test_end_to_end_dev_walk_forward(tmp_path: Path) -> None:
    panel, mats = _run(tmp_path)
    res = walkforward.walk_forward("w", panel, mats, root=tmp_path)
    assert [c.year for c in res.choices] == list(walkforward.DEV_YEARS)
    assert all(c.reselected for c in res.choices)
    assert res.returns.index.max() <= pd.Timestamp("2019-12-31")
    assert set(res.yearly.index) <= set(walkforward.DEV_YEARS)
    assert {"cagr", "benchmark_cagr", "universe_cagr", "ir_vs_universe"} <= set(res.stats)
    top3 = walkforward.walk_forward("w", panel, mats, root=tmp_path, mode="top3")
    assert len(top3.returns) == len(res.returns)
    out = walkforward.save(res, data=tmp_path)
    assert json.loads(out.read_text())["mode"] == "top1"


def test_val_extension_is_gated_and_never_reselects(tmp_path: Path) -> None:
    panel, mats = _run(tmp_path)
    with pytest.raises(ValueError, match="VAL looks"):
        walkforward.walk_forward("w", panel, mats, root=tmp_path, include_val=True)
    walkforward.val_looks_path("w", tmp_path).write_text("[]")
    res = walkforward.walk_forward("w", panel, mats, root=tmp_path, include_val=True)
    val = [c for c in res.choices if c.year >= 2020]
    assert [c.year for c in val] == list(walkforward.VAL_YEARS)
    assert not any(c.reselected for c in val)
    assert all(c.trial_ids == res.choices[len(walkforward.DEV_YEARS) - 1].trial_ids for c in val)


def test_selection_years_must_be_dev(tmp_path: Path) -> None:
    panel, mats = _run(tmp_path)
    with pytest.raises(ValueError, match="DEV years"):
        walkforward.walk_forward("w", panel, mats, root=tmp_path, years=(2019, 2020))


def test_no_eligible_year_holds_the_benchmark(tmp_path: Path) -> None:
    panel, mats = _panel_and_matrices()
    cfg = factory.SearchConfig(
        run_id="w", feature_pool={"n1": 1, "n2": 1}, max_features=1, top_n_menu=[10], stage2_top_k=0
    )
    log = tmp_path / "LOG.md"
    log.write_text(f"## 019 — declared\n{cfg.canonical_hash()}\n")
    factory.run_search(cfg, panel.assign(good=0.0), log_entry="019", log_path=log, root=tmp_path)
    res = walkforward.walk_forward("w", panel, mats, root=tmp_path)
    assert all(c.trial_ids == [] for c in res.choices)
    assert any("benchmark is held" in f for f in res.flags)
    strat, bench = res.returns["strategy"], res.returns["benchmark"]
    # Identical to buy-and-hold SPY except the first fill, which pays 20 bps to buy it.
    first = int(np.flatnonzero(bench.to_numpy() != 0)[0])
    assert strat.iloc[first] == pytest.approx((1 - 0.002) * (1 + bench.iloc[first]) - 1)
    np.testing.assert_allclose(strat.iloc[first + 1 :], bench.iloc[first + 1 :], atol=1e-12)
