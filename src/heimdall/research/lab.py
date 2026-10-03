"""Strategy Lab data (roadmap 18.9) — everything the Lab page shows, prepared as plain data.

The page (``ui.lab_page``) only renders; this module reads the factory's run directories
(``signals/search/<run_id>/``), the gitignored engine / walk-forward / technical-factory outputs
under ``data/research/``, and the **incubating** tier (registry + its own ledger and monitoring
namespaces). Nothing here writes, and nothing here reads the certified tier's holdings — a
certified strategy links to Today's Picks instead (no tier leakage, playbook §10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd

from heimdall.data.store import data_root
from heimdall.research import factory, ledger, monitor, registry

SURVIVORSHIP = "current_universe (optimistic)"


def _signals_root() -> Path:
    return registry.registry_path().parent.parent


@dataclass
class RunInfo:
    run_id: str
    n_trials: int
    val_spent: bool  # promote() has run — the run's VAL budget is closed
    config_path: Path
    #: Ledger files this run must have but this checkout can't see (see ``missing_ledger``).
    missing: list[Path] = field(default_factory=list)


def missing_ledger(run_id: str) -> list[Path]:
    """The trial-ledger files a run that has evidently **run** is missing on this disk.

    The ledger (``trials.parquet`` + the per-month series) is gitignored; it now lives in the
    shared data root, but a run executed before that move left it only in the checkout that ran
    it (``signals/search/<run_id>/``) — fixable with ``factory migrate --from``. A
    run whose VAL look was spent, or whose engine outputs exist, cannot have zero trials — so
    reporting "N = 0" there would misstate N, the number every factory claim is judged by.
    A declared run that simply hasn't started returns ``[]``.
    """
    ran = factory.val_looks_path(run_id).exists() or any(
        factory.engine_dir(run_id).glob("engine_*.parquet")
    )
    if not ran:
        return []
    return factory.ledger_files_missing(run_id)  # absent from both the new and legacy place


def list_runs() -> list[RunInfo]:
    """Every declared run with a config on disk, newest first by config mtime."""
    base = _signals_root() / "signals" / "search"
    if not base.exists():
        return []
    out: list[RunInfo] = []
    for cfg in sorted(base.glob("*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        run_id = cfg.parent.name
        trials = factory.load_trials(run_id)
        out.append(
            RunInfo(
                run_id,
                len(trials),
                factory.val_looks_path(run_id).exists(),
                cfg,
                missing_ledger(run_id),
            )
        )
    return out


def leaderboard(run_id: str) -> factory.Leaderboard | None:
    try:
        return factory.leaderboard(run_id)
    except FileNotFoundError:
        return None


LEADERBOARD_COLUMNS: list[str] = [
    "trial_id",
    "features",
    "universe",
    "top_n",
    "weighting",
    "exit_rank",
    "neutralize",
    "objective",
    "dsr",
    "ic_t",
    "alpha_mean",
    "alpha_t",
    "turnover",
    "candidate",
]


@dataclass
class EngineEvidence:
    returns: pd.DataFrame  # daily strategy / benchmark / universe (DEV)
    holdings: pd.DataFrame | None
    trades: pd.DataFrame | None
    sectors: pd.DataFrame | None


def engine_evidence(run_id: str, trial_id: int) -> EngineEvidence | None:
    """The cached DEV daily-engine backtest for a trial (``factory engine``), if present."""
    stem = factory.engine_dir(run_id) / f"engine_t{trial_id:05d}"
    path = stem.with_suffix(".parquet")
    if not path.exists():
        return None

    def _opt(suffix: str) -> pd.DataFrame | None:
        extra = stem.parent / f"{stem.name}_{suffix}.parquet"
        return pd.read_parquet(extra) if extra.exists() else None

    return EngineEvidence(pd.read_parquet(path), _opt("holdings"), _opt("trades"), _opt("sectors"))


def cached_trials(run_id: str) -> list[int]:
    """Trial ids with a cached engine backtest (the ones the detail view can show)."""
    d = factory.engine_dir(run_id)
    if not d.exists():
        return []
    ids = []
    for p in d.glob("engine_t*.parquet"):
        stem = p.stem.removeprefix("engine_t")
        if stem.isdigit():
            ids.append(int(stem))
    return sorted(ids)


def walk_forward_summary(run_id: str, mode: str = "top1") -> dict[str, object] | None:
    """The saved 18.6 walk-forward summary (DEV, or its VAL extension when present)."""
    d = factory.engine_dir(run_id)
    for tag in (f"walkforward_{mode}_val", f"walkforward_{mode}"):
        path = d / f"{tag}.json"
        if path.exists():
            return cast("dict[str, object]", json.loads(path.read_text()))
    return None


def walk_forward_curve(run_id: str, mode: str = "top1") -> pd.DataFrame | None:
    d = factory.engine_dir(run_id)
    for tag in (f"walkforward_{mode}_val", f"walkforward_{mode}"):
        path = d / f"{tag}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    return None


@dataclass
class IncubatingInfo:
    name: str
    version: int
    family: str
    since: str  # the incubation month
    description: str
    cohorts: list[dict[str, object]]  # frozen forward cohorts (incubating ledger)
    monitoring: dict[str, object] | None  # the incubating monitor's last result


def incubating() -> list[IncubatingInfo]:
    """Every ``incubating`` strategy with its forward ledger — uncertified, Lab-only."""
    reg = registry.load_registry()
    out: list[IncubatingInfo] = []
    for e in cast("list[dict[str, object]]", reg["signals"]):
        if e.get("status") != "incubating":
            continue
        name, version = str(e["name"]), int(cast("int", e["version"]))
        p = Path(str(e["spec_path"]))
        path = p if p.is_absolute() else _signals_root() / p
        try:
            description = str(json.loads(path.read_text()).get("description", ""))
        except (OSError, ValueError):
            description = ""
        out.append(
            IncubatingInfo(
                name=name,
                version=version,
                family=str(e.get("family", "")),
                since=str(e.get("updated_at", ""))[:7],
                description=description,
                cohorts=ledger.load_cohorts(name, version, _signals_root(), tier="incubating"),
                monitoring=monitor.load_monitoring(
                    name, version, _signals_root(), tier="incubating"
                ),
            )
        )
    return out


def tech_factory_results() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """The last technical-rule factory run (``backtest.tech_factory``): (per_rule, per_pair)."""
    d = data_root() / "research" / "tech_factory"
    per_rule, per_pair = d / "per_rule.parquet", d / "per_pair.parquet"
    if not per_rule.exists() or not per_pair.exists():
        return None
    return pd.read_parquet(per_rule), pd.read_parquet(per_pair)
