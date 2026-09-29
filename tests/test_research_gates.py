"""Factory gates F1–F6 (roadmap 18.0) mirror docs/RESEARCH_PLAYBOOK.md §12.1.

The duplication is the tripwire: the playbook table is parsed and compared with
``research/gates.py``, so changing either side alone fails (playbook §4 rule 4).
"""

from __future__ import annotations

import re
from pathlib import Path

from heimdall.research import gates

_PLAYBOOK = Path(__file__).resolve().parents[1] / "docs" / "RESEARCH_PLAYBOOK.md"


def _factory_rows() -> dict[str, str]:
    """The §12.1 table as ``{gate id: threshold cell}``."""
    text = _PLAYBOOK.read_text()
    section = text.split("### 12.1", 1)[1].split("### 12.2", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and re.fullmatch(r"F\d", cells[0]):
            rows[cells[0]] = cells[2]
    return rows


def _numbers(cell: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", cell)]


def test_playbook_lists_exactly_f1_to_f6() -> None:
    assert sorted(_factory_rows()) == ["F1", "F2", "F3", "F4", "F5", "F6"]


def test_factory_gates_mirror_playbook() -> None:
    rows = _factory_rows()
    assert _numbers(rows["F1"]) == [gates.FACTORY_MIN_DSR]
    assert _numbers(rows["F2"]) == [gates.FACTORY_MAX_PBO]
    assert _numbers(rows["F3"]) == [gates.FACTORY_MIN_ALPHA_T, gates.FACTORY_MIN_IC_T]
    # F4: "(≤ 5 finalists per run)" sits in the gate cell; the threshold cell holds the ceilings.
    assert _numbers(rows["F4"]) == [0.0, 0.0, round(gates.FACTORY_VAL_MAX_TURNOVER * 100, 6)]
    assert _numbers(rows["F5"]) == [gates.FACTORY_MAX_PARAMS]
    assert _numbers(rows["F6"]) == [gates.FACTORY_MAX_TRIALS]


def test_factory_constants_pinned() -> None:
    # The user-confirmed numbers (RESEARCH_LOG 019) — a change here is a §4-rule-4 process event.
    assert gates.FACTORY_MIN_DSR == 0.95
    assert gates.FACTORY_MAX_PBO == 0.30 and gates.FACTORY_PBO_BLOCKS == 16
    assert gates.FACTORY_MIN_ALPHA_T == 3.0 and gates.FACTORY_MIN_IC_T == 2.0
    assert gates.FACTORY_MAX_VAL_FINALISTS == 5 and gates.FACTORY_VAL_MAX_TURNOVER == 0.60
    assert gates.FACTORY_MAX_PARAMS == 4 and gates.FACTORY_MAX_TRIALS == 5_000
    assert gates.FACTORY_MAX_PREREG_PER_RUN == 1
    assert gates.FACTORY_INCUBATION_MIN_COHORTS == 12
    assert gates.US_LARGE_N == 500


def test_playbook_prose_matches_the_structural_constants() -> None:
    section = " ".join(_PLAYBOOK.read_text().split("## 12.", 1)[1].split())
    assert f"S = **{gates.FACTORY_PBO_BLOCKS}**" in section
    assert f"≤ **{gates.FACTORY_MAX_VAL_FINALISTS}** finalists" in section
    assert f"≥ **{gates.FACTORY_INCUBATION_MIN_COHORTS}** forward cohorts" in section
    assert "at most one finalist per run may be pre-registered" in section


def test_factory_hurdles_are_stricter_than_the_hand_made_bars() -> None:
    # Mined candidates were selected for a high t; their floor must never sit below G1/G3's.
    assert gates.FACTORY_MIN_ALPHA_T > gates.G3_MIN_SKILL_T
    assert gates.FACTORY_MIN_IC_T >= gates.G1_MIN_T
    assert gates.FACTORY_MAX_PARAMS <= gates.G5_MAX_PARAMS
    assert gates.FACTORY_VAL_MAX_TURNOVER <= gates.G6_STRESS_TURNOVER
