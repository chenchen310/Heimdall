"""Promotion (roadmap 18.7) — the single VAL look, the incubating tier, and its guard rails.

Pins playbook §12.2/§12.3: ≤ 5 finalists and one VAL look per run, only F1/F3/F5 candidates of
an F2-passing run, no respins of a registry hash, incubating strategies in their own ledger and
monitoring namespaces (never on a certified list), demotion after ≥ 12 forward cohorts, and a
pre-registration draft that carries every disclosure — never a commit, never a vault run.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.research import factory, gates, ledger, monitor, registry, walkforward
from heimdall.research.spec import SignalSpec

sys.path.insert(0, str(Path(__file__).parent))
from test_research_factory import NOISE_POOL, _panel  # noqa: E402


def _config(**kw: object) -> factory.SearchConfig:
    base: dict[str, object] = {
        "run_id": "p1",
        "feature_pool": {"good": 1, **NOISE_POOL},
        "max_features": 1,
        "top_n_menu": [10],
        "stage2_top_k": 0,
    }
    base.update(kw)
    return factory.SearchConfig.model_validate(base)


def _run(tmp_path: Path, **kw: object) -> tuple[factory.SearchConfig, pd.DataFrame]:
    cfg = _config(**kw)
    panel = _panel(end="2022-12-31")
    log = tmp_path / "LOG.md"
    log.write_text(f"## 030 — search declared\n{cfg.canonical_hash()}\n")
    factory.run_search(cfg, panel, log_entry="030", log_path=log, root=tmp_path)
    return cfg, panel


def _bench() -> pd.Series:
    days = pd.bdate_range("2009-01-01", "2023-06-30")
    return pd.Series(np.linspace(100, 300, len(days)), index=days)


# --- promote -----------------------------------------------------------------------


def test_promote_spends_the_val_look_and_incubates_f4_passers(tmp_path: Path) -> None:
    _, panel = _run(tmp_path)
    rep = factory.promote("p1", panel, root=tmp_path)
    assert rep.run_passes_f2 and len(rep.looks) == 1  # only the planted signal is a candidate
    look = rep.looks[0]
    assert look["f4_pass"] and look["promoted"]
    assert rep.promoted == [look["spec_name"]]
    entry = registry.get(str(look["spec_name"]), 1, root=tmp_path)
    assert entry["status"] == "incubating"
    spec_file = tmp_path / str(entry["spec_path"])
    assert "uncertified" in json.loads(spec_file.read_text())["description"]
    record = json.loads(factory.val_looks_path("p1", tmp_path).read_text())
    assert (
        record["n_trials"] == rep.n_trials and record["looks"][0]["val"]["window_start"] >= "2020"
    )
    with pytest.raises(FileExistsError, match="already spent"):
        factory.promote("p1", panel, root=tmp_path)


def test_an_f2_failing_run_takes_no_look_but_closes_its_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, panel = _run(tmp_path)
    monkeypatch.setattr(gates, "FACTORY_MAX_PBO", -1.0)  # force the run over the PBO ceiling
    rep = factory.promote("p1", panel, root=tmp_path)
    assert not rep.run_passes_f2 and rep.looks == [] and rep.promoted == []
    assert factory.val_looks_path("p1", tmp_path).exists()
    assert registry.load_registry(tmp_path)["signals"] == []


def test_finalists_must_be_candidates_and_at_most_five(tmp_path: Path) -> None:
    _, panel = _run(tmp_path)
    board = factory.leaderboard("p1", root=tmp_path).table
    noise_id = int(board.loc[~board["candidate"], "trial_id"].iloc[0])
    with pytest.raises(ValueError, match="candidates"):
        factory.promote("p1", panel, finalists=[noise_id], root=tmp_path)
    with pytest.raises(ValueError, match="at most"):
        factory.promote("p1", panel, finalists=list(range(6)), root=tmp_path)
    assert not factory.val_looks_path("p1", tmp_path).exists()  # a refusal costs no look


def test_a_registry_recipe_is_never_respun(tmp_path: Path) -> None:
    _, panel = _run(tmp_path)
    best = factory.leaderboard("p1", root=tmp_path).table.iloc[0]
    spec = SignalSpec.model_validate_json(str(best["spec_json"]))
    # The same recipe under another name, family and version: a different canonical hash …
    hand = spec.model_copy(update={"name": "hand-made", "family": "us-other", "version": 3})
    assert hand.canonical_hash() != spec.canonical_hash()
    assert hand.recipe_hash() == spec.recipe_hash()  # … but the same recipe.
    (tmp_path / "x.json").write_text(hand.model_dump_json())
    registry.add(hand, "x.json", root=tmp_path)
    rep = factory.promote("p1", panel, root=tmp_path)
    assert rep.looks == [] and rep.skipped[0]["reason"] == "recipe already in registry"


def test_overlay_twins_are_reported_not_searched(tmp_path: Path) -> None:
    _, panel = _run(tmp_path, overlay_menu=["", "spy_sma200_cash"])
    with pytest.raises(ValueError, match="benchmark_adj"):
        factory.promote("p1", panel, root=tmp_path)
    rep = factory.promote("p1", panel, benchmark_adj=_bench(), root=tmp_path)
    views = rep.looks[0]["overlay_views_dev"]
    assert set(views) == {"", "spy_sma200_cash"}  # type: ignore[arg-type]
    assert factory.leaderboard("p1", root=tmp_path).n_trials == len(NOISE_POOL) + 1  # no twins


def test_g4_view_overlay_cash_months_earn_nothing(tmp_path: Path) -> None:
    panel = _panel(n_syms=40, end="2012-12-31")
    base = SignalSpec(name="g", family="f", market="US", features={"good": 1.0}, top_n=10)
    falling = pd.Series(
        np.linspace(300, 100, 1200), index=pd.bdate_range("2008-01-01", periods=1200)
    )
    plain = factory.g4_view(base, panel, falling)
    timed = factory.g4_view(base.model_copy(update={"overlay": "spy_sma200_cash"}), panel, falling)
    assert plain["cash_months"] == 0 and timed["cash_months"] > 0
    assert timed["cagr"] != pytest.approx(plain["cagr"])


# --- the incubating ledger + monitoring namespaces ---------------------------------------


def _snapshot(syms: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": syms,
            "as_of": pd.Timestamp("2026-10-15"),
            "price": 50.0,
            "dollar_vol_21d": 1e8,
            "ret_12_1": 0.1,
            "good": np.arange(len(syms), 0, -1, dtype=float),
            "vol_63d": 0.2,
            "market_cap": 1e10,
            "sector": "Tech",
        }
    )


def test_incubating_freezes_into_its_own_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, panel = _run(tmp_path)
    rep = factory.promote("p1", panel, root=tmp_path)
    name = rep.promoted[0]
    syms = [f"S{i:03d}.US" for i in range(30)]
    monkeypatch.setattr("heimdall.screener.snapshot.load_snapshot", lambda: _snapshot(syms))
    assert ledger.freeze_all(root=tmp_path, today=date(2026, 10, 15)) == []  # certified only
    written = ledger.freeze_incubating(root=tmp_path, today=date(2026, 10, 15))
    assert len(written) == 1 and "incubating" in written[0].parts
    assert ledger.load_cohorts(name, 1, tmp_path) == []  # nothing in the certified ledger
    frozen = ledger.load_cohorts(name, 1, tmp_path, tier="incubating")
    assert frozen[0]["tier"] == "incubating" and len(frozen[0]["picks"]) == 10  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tier"):
        ledger.ledger_dir(name, 1, tmp_path, tier="certifed")


def _drift_panel(sign: float, n_months: int = 20) -> pd.DataFrame:
    rows = []
    for t in pd.date_range("2026-01-31", periods=n_months, freq="BME"):
        for i in range(30):
            good = float(30 - i)
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:03d}.US",
                    "eligible": True,
                    "good": good,
                    "fwd_6m": 0.0,
                    "fwd_6m_rel": sign * 0.001 * good + 0.0001 * (t.month % 3),
                }
            )
    return pd.DataFrame(rows)


def test_incubating_demotion_arms_after_twelve_cohorts(tmp_path: Path) -> None:
    spec = SignalSpec(
        name="inc", family="us-factory-p1", market="US", features={"good": 1.0}, top_n=5
    )
    registry.add(spec, "inc.json", root=tmp_path)
    registry.transition("inc", 1, "incubating", root=tmp_path)
    early = monitor.monitor_incubating_signal(
        spec, _drift_panel(-1.0, 8), "2026-01", root=tmp_path, apply=True
    )
    assert not early.drift and early.status == "incubating"  # < 12 cohorts: not armed
    good = monitor.monitor_incubating_signal(
        spec, _drift_panel(+1.0), "2026-01", root=tmp_path, apply=True
    )
    assert not good.drift
    bad = monitor.monitor_incubating_signal(
        spec, _drift_panel(-1.0), "2026-01", root=tmp_path, apply=True
    )
    assert bad.drift and bad.flipped and bad.status == "incubation_retired"
    assert monitor.monitoring_path("inc", 1, tmp_path, tier="incubating").exists()
    assert not monitor.monitoring_path("inc", 1, tmp_path).exists()


# --- the pre-registration draft ------------------------------------------------------------


def test_draft_preregistration_carries_every_disclosure(tmp_path: Path) -> None:
    cfg, panel = _run(tmp_path)
    name = factory.promote("p1", panel, root=tmp_path).promoted[0]
    text = factory.draft_preregistration("p1", name, root=tmp_path)
    entry = registry.get(name, 1, root=tmp_path)
    for needle in (
        str(entry["spec_hash"]),
        cfg.canonical_hash(),
        "N = ",
        "run PBO",
        "DSR",
        "Validation result (2020–2022, the single look)",
        "Cumulative US vault touches before this one: 0",
        "≤ 1 pre-registration per factory run",
        "incubating → registered",
    ):
        assert needle in text, needle
    assert registry.get(name, 1, root=tmp_path)["status"] == "incubating"  # nothing was done
    with pytest.raises(ValueError, match="not an incubating finalist"):
        factory.draft_preregistration("p1", "p1-t99999", root=tmp_path)
    registry.transition(name, 1, "registered", root=tmp_path)
    with pytest.raises(ValueError, match="≤ 1 per run"):
        factory.draft_preregistration("p1", name, root=tmp_path)


def test_walkforward_val_extension_unlocks_after_promotion(tmp_path: Path) -> None:
    _, panel = _run(tmp_path)
    assert not walkforward.val_looks_path("p1", tmp_path).exists()
    factory.promote("p1", panel, root=tmp_path)
    assert walkforward.val_looks_path("p1", tmp_path).exists()


def test_weekly_digest_names_incubating_freezes_as_uncertified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heimdall.ops.notify import run_weekly

    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("heimdall.research.ledger.freeze_all", lambda **k: [])
    fake = tmp_path / "signals" / "ledger" / "incubating" / "x_v1" / "2026-10.json"
    monkeypatch.setattr("heimdall.research.ledger.freeze_incubating", lambda **k: [fake])
    events = run_weekly(today=date(2026, 10, 5), root=tmp_path, env={}, run=lambda s: (0, "ok"))
    titles = [e.title for e in events]
    assert any("incubating (uncertified)" in t for t in titles)
