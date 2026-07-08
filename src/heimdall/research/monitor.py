"""Post-certification drift monitoring (roadmap 12.2 / playbook §9).

Recomputes a certified signal's realized OOS cohorts from the current panel and
watches **the certified edge** — the G3 selection alpha (EW top-N book 6m minus
EW eligible-universe 6m), shared with :mod:`heimdall.research.certify` via
``cohort_alpha`` so the metric has one home. When the **trailing-12-cohort NW 95%
CI upper bound falls below 0** — the skill has gone significantly negative — the
signal auto-flips ``certified → under_review`` and Today's Picks shows a warning
banner instead of its ranking. No silent decay; no network (the alpha is
panel-only, the benchmark cancels).

    uv run python -m heimdall.research.monitor [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from heimdall.research import gates, registry
from heimdall.research.certify import cohort_alpha
from heimdall.research.dataset import load_panel
from heimdall.research.spec import SignalSpec, load_spec

#: The trailing window (cohorts) the drift verdict is judged on (playbook §9).
TRAILING: int = 12


@dataclass
class CohortPoint:
    date: str
    alpha: float  # selection skill: EW top-N book 6m rel − EW eligible-universe 6m rel
    beat: float  # 1.0 if the book beat the benchmark this cohort (book 6m rel > 0)


@dataclass
class MonitorResult:
    name: str
    version: int
    status: str  # registry status AFTER this run
    n_cohorts: int  # realized OOS cohorts available
    trailing_n: int  # cohorts in the trailing window (≤ TRAILING)
    trailing_alpha_mean: float
    trailing_alpha_ci95: tuple[float, float]
    trailing_beat_rate: float
    drift: bool  # full trailing window AND NW 95% CI upper < 0 (skill significantly negative)
    flipped: bool  # did this run transition certified → under_review?
    generated_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def realized_cohorts(spec: SignalSpec, panel: pd.DataFrame) -> list[CohortPoint]:
    """Every OOS cohort (≥ ``OOS_START``) with complete 6m labels: selection alpha + book beat."""
    out: list[CohortPoint] = []
    for t in sorted(pd.Timestamp(x) for x in panel["date"].unique()):
        if t < pd.Timestamp(gates.OOS_START):
            continue
        cross = panel[panel["date"] == t]
        if not bool(cross["fwd_6m"].notna().any()):
            continue  # the 6m forward window is still open — not yet realized
        ca = cohort_alpha(spec, cross)
        if ca is None:
            continue
        book_ret, univ_ret = ca
        out.append(CohortPoint(t.date().isoformat(), book_ret - univ_ret, float(book_ret > 0)))
    return out


def monitoring_path(name: str, version: int, root: Path | None = None) -> Path:
    base = root if root is not None else registry.registry_path().parent.parent
    return base / "signals" / "monitoring" / f"{name}_v{version}.json"


def load_monitoring(name: str, version: int, root: Path | None = None) -> dict[str, object] | None:
    path = monitoring_path(name, version, root)
    return json.loads(path.read_text()) if path.exists() else None


def _save(result: MonitorResult, cohorts: list[CohortPoint], root: Path | None) -> None:
    path = monitoring_path(result.name, result.version, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**result.to_dict(), "cohorts": [asdict(c) for c in cohorts]}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)


def monitor_signal(
    spec: SignalSpec, panel: pd.DataFrame, *, root: Path | None = None, apply: bool = False
) -> MonitorResult:
    """Score the current panel, judge the trailing-12 skill, and (if ``apply``) flip on drift.

    Idempotent: the series is recomputed from the panel each run (not hand-appended), so re-runs
    never double-count. A drift verdict is only rendered on a **full** trailing window.
    """
    cohorts = realized_cohorts(spec, panel)
    trailing = cohorts[-TRAILING:]
    alphas = np.asarray([c.alpha for c in trailing], dtype=float)
    mean = float(alphas.mean()) if len(alphas) else float("nan")
    lo, hi = (
        gates.nw_ci95(alphas, lag=gates.NW_LAG) if len(alphas) > 1 else (float("nan"), float("nan"))
    )
    beat = float(np.mean([c.beat for c in trailing])) if trailing else float("nan")
    drift = bool(len(trailing) >= TRAILING and hi < 0.0)  # judge only on a full window

    entry = registry.get(spec.name, spec.version, root=root)
    status = str(entry["status"])
    flipped = False
    if drift and status == "certified" and apply:
        registry.transition(spec.name, spec.version, "under_review", root=root)
        status, flipped = "under_review", True

    result = MonitorResult(
        name=spec.name,
        version=spec.version,
        status=status,
        n_cohorts=len(cohorts),
        trailing_n=len(trailing),
        trailing_alpha_mean=mean,
        trailing_alpha_ci95=(lo, hi),
        trailing_beat_rate=beat,
        drift=drift,
        flipped=flipped,
        generated_at=datetime.now(UTC).isoformat(),
    )
    _save(result, cohorts, root)
    return result


def monitor_all(*, root: Path | None = None, apply: bool = False) -> list[MonitorResult]:
    """Monitor every certified signal against its market's current panel."""
    base = root if root is not None else registry.registry_path().parent.parent
    reg = registry.load_registry(root)
    panels: dict[str, pd.DataFrame] = {}
    out: list[MonitorResult] = []
    for entry in cast("list[dict[str, object]]", reg["signals"]):
        if entry["status"] != "certified":
            continue
        p = Path(str(entry["spec_path"]))
        spec = load_spec(p if p.is_absolute() else base / p)
        if spec.market not in panels:
            panels[spec.market] = load_panel(spec.market)
        out.append(monitor_signal(spec, panels[spec.market], root=root, apply=apply))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Post-certification drift monitoring (playbook §9)")
    p.add_argument(
        "--apply", action="store_true", help="auto-flip drifting signals to under_review"
    )
    args = p.parse_args(argv)
    results = monitor_all(apply=args.apply)
    if not results:
        print("No certified signals to monitor.")
        return 0
    for r in results:
        lo, hi = r.trailing_alpha_ci95
        flag = "DRIFT" if r.drift else "ok"
        tail = "  → flipped to under_review" if r.flipped else ""
        print(
            f"{r.name} v{r.version}: {flag} | trailing-{r.trailing_n} skill "
            f"{r.trailing_alpha_mean:+.2%} (95% CI {lo:+.2%}..{hi:+.2%}) | "
            f"beat {r.trailing_beat_rate:.0%} | status {r.status}{tail}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
