"""The Strategy Factory (roadmap 18.5) — declared runs, DEV-only search, ledger, leaderboard.

The load-bearing test is equivalence: the numpy fast path must reproduce ``research.evaluate``
(the referee's in-sample lens) to 1e-10 for every construction option the factory searches, so
a leaderboard's F3 flag means what the playbook says it means.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from heimdall.research import factory, gates
from heimdall.research.evaluate import evaluate
from heimdall.research.spec import SignalSpec

SECTORS = ["Energy", "Finance", "Health", "Tech", "Retail"]


def _panel(
    n_syms: int = 120,
    planted: float = 0.004,
    start: str = "2010-01-31",
    end: str = "2019-12-31",
    seed: int = 5,
    late_signal: float = 0.0,
    n_noise: int = 16,
    rho: float = 0.9,
) -> pd.DataFrame:
    """Monthly panel: ``good`` predicts fwd returns (strength ``planted``); ``n1``…``n{n_noise}``
    are noise. Every feature is a persistent AR(1) per symbol (``rho``), like real factors, so
    books turn over ~30%/month rather than churning. ``n3`` is coarse (ties), ``n4`` sparse.
    ``late_signal`` plants a strong edge in ``n1`` only from 2020 on (the vault canary)."""
    rng = np.random.default_rng(seed)
    months = pd.date_range(start, end, freq="BME")
    k = n_noise + 1
    state = rng.normal(size=(k, n_syms))
    rows: list[dict[str, object]] = []
    for t in months:
        state = rho * state + np.sqrt(1 - rho**2) * rng.normal(size=(k, n_syms))
        good, noise = state[0], state[1:]
        edge = planted * good + (late_signal * noise[0] if t.year >= 2020 else 0.0)
        rel1 = edge + rng.normal(0, 0.02, n_syms)
        rel6 = 6 * edge + rng.normal(0, 0.05, n_syms)
        bench = float(rng.normal(0.008, 0.03))
        for i in range(n_syms):
            row: dict[str, object] = {
                "date": t,
                "symbol": f"S{i:03d}.US",
                "eligible": bool(i % 17 != 0),  # a few ineligible rows every month
                "good": good[i],
                "vol_63d": 0.1 + 0.3 * rng.random(),
                "market_cap": float(rng.lognormal(22, 1)),
                "sector": SECTORS[i % len(SECTORS)],
                "fwd_1m_rel": rel1[i],
                "fwd_1m": rel1[i] + bench,
                "fwd_6m_rel": rel6[i],
                "fwd_6m": rel6[i] + 6 * bench,
            }
            for j in range(n_noise):
                row[f"n{j + 1}"] = noise[j, i]
            row["n3"] = float(np.round(noise[2, i], 1))  # coarse → many ties
            row["n4"] = noise[3, i] if i % 9 else np.nan  # sparse
            rows.append(row)
    return pd.DataFrame(rows)


NOISE_POOL = {f"n{k}": 1 for k in (1, 2, *range(5, 17))}


def _config(**kw: object) -> factory.SearchConfig:
    base: dict[str, object] = {
        "run_id": "t1",
        "feature_pool": {"good": 1, "n1": 1, "n2": -1, "n3": 1, "n4": 1},
        "max_features": 2,
        "universes": ["", "us_large"],
        "top_n_menu": [10, 20],
        "weighting_menu": ["", "inverse_vol"],
        "exit_rank_multiples": [None, 2],
        "neutralize_menu": ["", "sector"],
        "stage2_top_k": 3,
    }
    base.update(kw)
    return factory.SearchConfig.model_validate(base)


def _declare(tmp_path: Path, cfg: factory.SearchConfig, entry: str = "019") -> Path:
    log = tmp_path / "LOG.md"
    log.write_text(
        f"# log\n\n## {entry} — search declared: {cfg.run_id}\n- sha256: {cfg.canonical_hash()}\n"
    )
    return log


# --- config -----------------------------------------------------------------------


def test_config_space_and_budget() -> None:
    cfg = _config()
    s1 = cfg.stage1()
    assert len(s1) == (5 + 10) * 2  # 1- and 2-feature subsets × 2 universes
    assert all(s.top_n == 10 and s.weighting == "" and s.exit_rank is None for s in s1)
    assert s1[0].features == {"good": 1.0} and s1[0].family == "us-factory-t1"
    assert s1[0].name == "t1-t00000"
    s2 = cfg.stage2(s1[:3], first_id=len(s1))
    assert len(s2) == 3 * (2 * 2 * 2 * 2 - 1)  # every menu combination but the stage-1 one
    assert {s.exit_rank for s in s2} == {None, 20, 40}
    assert cfg.trial_budget() == len(s1) + len(s2)


def test_config_hash_ignores_description_and_validates() -> None:
    assert _config(description="x").canonical_hash() == _config().canonical_hash()
    assert _config(seed=1).canonical_hash() != _config().canonical_hash()
    for bad, match in [
        ({"feature_pool": {"good": 2}}, "direction"),
        ({"feature_pool": {"fwd_1m": 1}}, "label leakage"),
        ({"weight_menu": ["optimized"]}, "only"),
        ({"top_n_menu": [30]}, "top_n_menu"),
        ({"exit_rank_multiples": [1]}, "exit_rank_multiples"),
        ({"max_trials": gates.FACTORY_MAX_TRIALS + 1}, "max_trials"),
        ({"run_id": "Bad Id"}, "slug"),
    ]:
        with pytest.raises(ValidationError, match=match):
            _config(**bad)


# --- the fast path ≡ evaluate() -------------------------------------------------------


@pytest.mark.parametrize(
    "construction",
    [
        {},
        {"universe": "us_large"},
        {"neutralize": "sector"},
        {"weighting": "inverse_vol"},
        {"exit_rank": 20},
        {
            "universe": "us_large",
            "weighting": "inverse_vol",
            "exit_rank": 20,
            "neutralize": "sector",
        },
        {"neutralize": "sector_size"},  # 18.18
        {"weighting": "rank_linear"},  # 18.18
        {"weighting": "rank_linear", "exit_rank": 20, "neutralize": "sector_size"},
        {
            "universe": "us_large",
            "weighting": "rank_linear",
            "exit_rank": 20,
            "neutralize": "sector_size",
            "max_sector_weight": 0.4,
        },
    ],
)
@pytest.mark.parametrize("features", [{"good": 1.0}, {"good": 1.0, "n3": 1.0}, {"n4": 1.0}])
def test_fast_path_reproduces_evaluate(
    monkeypatch: pytest.MonkeyPatch, construction: dict[str, object], features: dict[str, float]
) -> None:
    monkeypatch.setattr(gates, "US_LARGE_N", 60)
    panel = _panel(n_syms=90, end="2014-12-31")
    cfg = _config(neutralize_menu=["", "sector", "sector_size"])
    spec = SignalSpec.model_validate(
        {
            "name": "e",
            "family": "f",
            "market": "US",
            "features": features,
            "top_n": 10,
            **construction,
        }
    )
    fast = factory.evaluate_fast(spec, factory.prepare(panel, cfg))
    ref = evaluate(spec, panel, ("2010-01-01", "2019-12-31"))
    for got, want in [
        (fast.ic_mean, ref.ic_mean),
        (fast.ic_t, ref.ic_t),
        (fast.spread_mean, ref.spread_mean),
        (fast.spread_share, ref.spread_positive_share),
        (fast.alpha_mean, ref.selection_alpha_mean),
        (fast.alpha_t, ref.selection_alpha_t),
        (fast.turnover, ref.mean_turnover),
    ]:
        assert got == pytest.approx(want, abs=1e-10, nan_ok=True)
    assert fast.ic_months == ref.ic_months and fast.n_cohorts == ref.n_cohorts


def test_net_alpha_series_is_book_minus_cost_minus_universe() -> None:
    panel = _panel(n_syms=60, end="2010-06-30")
    dp = factory.prepare(panel, _config(universes=[""], neutralize_menu=[""]))
    spec = SignalSpec(name="x", family="f", market="US", features={"good": 1.0}, top_n=10)
    met = factory.evaluate_fast(spec, dp)
    t0 = panel[(panel["date"] == panel["date"].min()) & panel["eligible"]]
    top = t0.assign(s=t0["good"]).sort_values("s", ascending=False).head(10)
    expected = top["fwd_1m_rel"].mean() - 1.0 * gates.G4_COST_BPS / 1e4 - t0["fwd_1m_rel"].mean()
    assert met.net_alpha[0] == pytest.approx(expected)
    assert len(met.net_alpha) == panel["date"].nunique()


# --- runs, ledger, leaderboard ----------------------------------------------------------


def test_planted_signal_is_found_and_passes_f1_f2(tmp_path: Path) -> None:
    # One persistent, genuinely predictive feature among 14 noise features.
    cfg = _config(
        feature_pool={"good": 1, **NOISE_POOL},
        max_features=1,
        universes=[""],
        neutralize_menu=[""],
        weighting_menu=[""],
        exit_rank_multiples=[None],
        stage2_top_k=1,
    )
    trials = factory.run_search(
        cfg, _panel(), log_entry="019", log_path=_declare(tmp_path, cfg), root=tmp_path
    )
    assert len(trials) == cfg.trial_budget() == 15 + 1  # stage 2: the winner at top_n 20
    board = factory.leaderboard("t1", root=tmp_path)
    best = board.table.iloc[0]
    assert best["features"] == "+good"
    assert board.pbo <= gates.FACTORY_MAX_PBO and board.run_passes_f2
    assert best["dsr"] >= gates.FACTORY_MIN_DSR and bool(best["candidate"])
    assert board.n_trials == len(trials)
    assert not board.table.loc[board.table["features"] != "+good", "candidate"].any()


def test_pure_noise_promotes_nothing(tmp_path: Path) -> None:
    cfg = _config(
        feature_pool=NOISE_POOL,
        max_features=1,
        top_n_menu=[10],
        universes=[""],
        neutralize_menu=[""],
        weighting_menu=[""],
        exit_rank_multiples=[None],
        stage2_top_k=0,
    )
    factory.run_search(
        cfg, _panel(planted=0.0), log_entry="019", log_path=_declare(tmp_path, cfg), root=tmp_path
    )
    board = factory.leaderboard("t1", root=tmp_path)
    assert not board.table["candidate"].any()
    assert board.table["dsr"].max() < 0.5  # the luckiest noise trial is not mistaken for skill


def test_search_never_reads_validation_or_vault_rows(tmp_path: Path) -> None:
    # n1 carries a huge edge from 2020 on; the DEV search must not see a trace of it.
    panel = _panel(end="2024-12-31", late_signal=0.05, planted=0.0)
    cfg = _config(
        feature_pool={"n1": 1, "n2": 1},
        max_features=1,
        universes=[""],
        neutralize_menu=[""],
        weighting_menu=[""],
        exit_rank_multiples=[None],
        top_n_menu=[10],
    )
    dp = factory.prepare(panel, cfg)
    assert max(dp.months) <= pd.Timestamp(factory.DEV_END)
    factory.run_search(cfg, panel, log_entry="019", log_path=_declare(tmp_path, cfg), root=tmp_path)
    series = factory.load_series("t1", root=tmp_path)
    assert series.index.max() <= pd.Timestamp(factory.DEV_END)
    n1 = factory.leaderboard("t1", root=tmp_path).table.set_index("features").loc["+n1"]
    assert abs(float(n1["alpha_t"])) < 3.0  # no leak of the 2020+ edge


def test_refusals(tmp_path: Path) -> None:
    cfg = _config(universes=[""])
    log = _declare(tmp_path, cfg)
    with pytest.raises(ValueError, match="declare the search first"):
        factory.run_search(
            cfg, _panel(end="2011-12-31"), log_entry="999", log_path=log, root=tmp_path
        )
    other = _config(universes=[""], seed=9)
    with pytest.raises(ValueError, match="does not contain this config"):
        factory.run_search(
            other, _panel(end="2011-12-31"), log_entry="019", log_path=log, root=tmp_path
        )
    big = _config(max_trials=10)
    with pytest.raises(ValueError, match="max_trials"):
        factory.run_search(
            big,
            _panel(end="2011-12-31"),
            log_entry="019",
            log_path=_declare(tmp_path, big),
            root=tmp_path,
        )


def test_changed_config_under_the_same_run_id_is_refused(tmp_path: Path) -> None:
    small = _config(
        feature_pool={"good": 1},
        max_features=1,
        universes=[""],
        neutralize_menu=[""],
        weighting_menu=[""],
        exit_rank_multiples=[None],
        top_n_menu=[10],
    )
    factory.run_search(
        small,
        _panel(end="2011-12-31"),
        log_entry="019",
        log_path=_declare(tmp_path, small),
        root=tmp_path,
    )
    changed = small.model_copy(update={"seed": 3})
    log2 = _declare(tmp_path, changed, entry="020")
    with pytest.raises(ValueError, match="different config"):
        factory.run_search(
            changed, _panel(end="2011-12-31"), log_entry="020", log_path=log2, root=tmp_path
        )


def test_resume_is_append_only_and_skips_logged_trials(tmp_path: Path) -> None:
    cfg = _config(
        universes=[""], neutralize_menu=[""], weighting_menu=[""], exit_rank_multiples=[None]
    )
    log = _declare(tmp_path, cfg)
    panel = _panel(end="2012-12-31")
    first = factory.run_search(cfg, panel, log_entry="019", log_path=log, root=tmp_path, batch=7)
    again = factory.run_search(cfg, panel, log_entry="019", log_path=log, root=tmp_path)
    pd.testing.assert_frame_equal(first, again)  # nothing re-evaluated, nothing rewritten
    assert (factory.run_dir("t1", tmp_path) / "config.json").exists()


def test_engine_backtests_for_the_lab_are_dev_only(tmp_path: Path) -> None:
    cfg = _config(
        feature_pool={"good": 1, "n1": 1},
        max_features=1,
        universes=[""],
        neutralize_menu=[""],
        weighting_menu=[""],
        exit_rank_multiples=[None],
        top_n_menu=[10],
        stage2_top_k=0,
    )
    panel = _panel(n_syms=40, end="2020-06-30")
    factory.run_search(cfg, panel, log_entry="019", log_path=_declare(tmp_path, cfg), root=tmp_path)
    days = pd.bdate_range("2009-12-01", "2020-07-31")
    rng = np.random.default_rng(1)
    syms = sorted(panel["symbol"].unique()) + ["SPY.US"]
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.01, (len(days), len(syms))), axis=0),
        index=days,
        columns=syms,
    )
    mats = {"adj_open": close.shift(1), "adj_close": close}
    paths = factory.cache_engine_backtests("t1", panel, mats, top_k=2, root=tmp_path, data=tmp_path)
    assert len(paths) == 2
    for path in paths:
        rets = pd.read_parquet(path)
        assert set(rets.columns) == {"strategy", "benchmark", "universe"}
        assert rets.index.max() <= pd.Timestamp(factory.DEV_END)
