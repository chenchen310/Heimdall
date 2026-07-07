"""Signal registry — statuses live in git, transitions live in code.

``signals/registry.json`` is version-controlled evidence: which specs exist,
what state they are in, and how much of each family's out-of-sample budget is
spent. Per ``.claude/rules/signal-certification.md`` the file is **never**
hand-edited (draft creation via :func:`add` is the one entry point); every
status change goes through :func:`transition`, which enforces the lifecycle
graph of ``docs/RESEARCH_PLAYBOOK.md`` §6:

    draft → registered → certified | rejected
    certified → under_review → retired

``rejected`` and ``retired`` are terminal — resurrection is a **new version**
with its own pre-registration, never an edit. Today's Picks (9.x) may read
only entries whose status is ``certified``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from heimdall.research.spec import SignalSpec

#: Playbook §4: three shots at the OOS vault per family, ever.
MAX_OOS_ATTEMPTS_PER_FAMILY: int = 3

STATUSES: frozenset[str] = frozenset(
    {"draft", "registered", "certified", "rejected", "under_review", "retired"}
)

_LEGAL: dict[str, frozenset[str]] = {
    "draft": frozenset({"registered"}),
    "registered": frozenset({"certified", "rejected"}),
    "certified": frozenset({"under_review"}),
    "under_review": frozenset({"retired"}),
    "rejected": frozenset(),  # terminal
    "retired": frozenset(),  # terminal
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def registry_path(root: Path | None = None) -> Path:
    base = root if root is not None else _repo_root()
    return base / "signals" / "registry.json"


def load_registry(root: Path | None = None) -> dict[str, object]:
    path = registry_path(root)
    reg: dict[str, object] = json.loads(path.read_text()) if path.exists() else {"signals": []}
    reg.setdefault("signals", [])
    reg.setdefault("families", {})
    return reg


def _save(reg: dict[str, object], root: Path | None = None) -> None:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(reg, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, path)


def _entries(reg: dict[str, object]) -> list[dict[str, object]]:
    return reg["signals"]  # type: ignore[return-value]


def _find(reg: dict[str, object], name: str, version: int) -> dict[str, object]:
    for entry in _entries(reg):
        if entry["name"] == name and entry["version"] == version:
            return entry
    raise KeyError(f"no registry entry for {name!r} v{version}")


def add(spec: SignalSpec, spec_path: str, root: Path | None = None) -> dict[str, object]:
    """Create the ``draft`` entry for a spec. The only way entries are born."""
    reg = load_registry(root)
    for entry in _entries(reg):
        if entry["name"] == spec.name and entry["version"] == spec.version:
            raise ValueError(f"{spec.name!r} v{spec.version} already exists in the registry")
    entry = {
        "name": spec.name,
        "family": spec.family,
        "version": spec.version,
        "spec_path": spec_path,
        "spec_hash": spec.canonical_hash(),
        "status": "draft",
        "oos_attempts_family": None,  # set to the attempt number this entry consumed (8.2)
        "cert_report": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _entries(reg).append(entry)
    _save(reg, root)
    return entry


def get(name: str, version: int | None = None, root: Path | None = None) -> dict[str, object]:
    """The entry for ``name`` — a specific version, or the latest when omitted."""
    reg = load_registry(root)
    if version is not None:
        return _find(reg, name, version)
    matches = [e for e in _entries(reg) if e["name"] == name]
    if not matches:
        raise KeyError(f"no registry entry named {name!r}")
    return max(matches, key=lambda e: cast("int", e["version"]))


def transition(
    name: str,
    version: int,
    to: str,
    *,
    cert_report: str | None = None,
    oos_attempt: int | None = None,
    root: Path | None = None,
) -> dict[str, object]:
    """Move an entry along the lifecycle graph; anything else raises.

    ``certified``/``rejected`` are certification outcomes and therefore require
    the ``cert_report`` path — evidence or it didn't happen.
    """
    if to not in STATUSES:
        raise ValueError(f"unknown status {to!r}; expected one of {sorted(STATUSES)}")
    reg = load_registry(root)
    entry = _find(reg, name, version)
    frm = str(entry["status"])
    if to not in _LEGAL[frm]:
        raise ValueError(
            f"illegal transition {frm!r} → {to!r} for {name} v{version}; "
            f"legal: {sorted(_LEGAL[frm]) or 'none (terminal — resurrect as a new version)'}"
        )
    if to in {"certified", "rejected"} and not cert_report:
        raise ValueError(f"transition to {to!r} requires the certification report path")
    entry["status"] = to
    if cert_report is not None:
        entry["cert_report"] = cert_report
    if oos_attempt is not None:
        entry["oos_attempts_family"] = oos_attempt
    entry["updated_at"] = datetime.now(UTC).isoformat()
    _save(reg, root)
    return entry


def family_attempts(family: str, root: Path | None = None) -> int:
    families: dict[str, dict[str, int]] = load_registry(root)["families"]  # type: ignore[assignment]
    return int(families.get(family, {}).get("oos_attempts", 0))


def spend_attempt(family: str, root: Path | None = None) -> int:
    """Consume one of the family's OOS attempts; raises once the budget is gone.

    Called by the certify CLI **before** the vault is evaluated, so even an
    aborted run costs an attempt — peeking is spending.
    """
    reg = load_registry(root)
    families: dict[str, dict[str, int]] = reg["families"]  # type: ignore[assignment]
    n = int(families.get(family, {}).get("oos_attempts", 0)) + 1
    if n > MAX_OOS_ATTEMPTS_PER_FAMILY:
        raise ValueError(
            f"family {family!r} has exhausted its {MAX_OOS_ATTEMPTS_PER_FAMILY} OOS attempts "
            "(playbook §4) — the family is closed; reopening requires new data and a "
            "user sign-off logged in docs/RESEARCH_LOG.md"
        )
    families[family] = {"oos_attempts": n}
    _save(reg, root)
    return n
