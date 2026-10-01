"""Declared composites (roadmap 18.22; rules: playbook §12.6, declaration: RESEARCH_LOG 024).

A composite is a fixed, literature-defined list of documented features, each with its a-priori
direction. A spec uses one through the feature key ``cmp:<name>``; scoring (``research.spec``)
averages the members' directional z-scores and z-scores the mean again, so the composite enters a
spec on a single feature's scale. Nothing is fitted, and one composite counts as **one** G5/F5
parameter (the ``f_score`` precedent the user endorsed on 2026-10-02).

This module is data only. Every declaration is **immutable**: a test pins each composite's
:meth:`Composite.canonical_hash`, so editing members or directions fails CI, and a change means a
new name in a new RESEARCH_LOG declaration (§12.6 rule 4). Adding a composite that entry 024 did
not declare is *composite laundering* (§10).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

#: The feature-key prefix a spec uses to reference a composite.
PREFIX = "cmp:"
#: Playbook §12.6 rule 3.
MAX_PER_DECLARATION = 5


@dataclass(frozen=True)
class Composite:
    name: str
    members: tuple[tuple[str, int], ...]  # (feature, a-priori direction ±1), in declared order
    citation: str
    declared: str  # date of the RESEARCH_LOG declaration
    log_entry: str

    def canonical_hash(self) -> str:
        """SHA-256 of the composite's meaning: its name and its signed members (order-free).
        The citation and dates are documentation and do not hash."""
        payload = {"name": self.name, "members": dict(sorted(self.members))}
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    @property
    def key(self) -> str:
        return f"{PREFIX}{self.name}"


def _declare(
    name: str, members: list[tuple[str, int]], citation: str, declared: str, entry: str
) -> Composite:
    return Composite(name, tuple(members), citation, declared, entry)


#: Exactly RESEARCH_LOG 024's declaration — nothing added here (§12.6).
COMPOSITES: dict[str, Composite] = {
    c.name: c
    for c in (
        _declare(
            "value",
            [("pe", -1), ("ps", -1), ("fcf_yield", 1)],
            "Lakonishok, Shleifer & Vishny 1994; Barbee, Mukherji & Raines 1996",
            "2026-10-02",
            "024",
        ),
        _declare(
            "profitability",
            [("roe", 1), ("operating_margin", 1), ("fcf_margin", 1)],
            "Novy-Marx 2013; Fama & French 2015 (RMW); Asness, Frazzini & Pedersen (QMJ)",
            "2026-10-02",
            "024",
        ),
        _declare(
            "investment",
            [("asset_growth", -1), ("share_dilution_yoy", -1)],
            "Cooper, Gulen & Schill 2008; Fama & French 2015 (CMA); Pontiff & Woodgate 2008",
            "2026-10-02",
            "024",
        ),
        _declare(
            "momentum",
            [("ret_12_1", 1), ("pct_of_52w_high", 1), ("ind_mom_6m", 1)],
            "Jegadeesh & Titman 1993; George & Hwang 2004; Moskowitz & Grinblatt 1999",
            "2026-10-02",
            "024",
        ),
        _declare(
            "low_risk",
            [("beta_252d", -1), ("vol_63d", -1), ("max_ret_21d", -1)],
            "Frazzini & Pedersen 2014; Ang, Hodrick, Xing & Zhang 2006; "
            "Bali, Cakici & Whitelaw 2011",
            "2026-10-02",
            "024",
        ),
    )
}


def is_composite(key: str) -> bool:
    return key.startswith(PREFIX)


def get(key: str) -> Composite:
    """The declared composite behind ``cmp:<name>``; an undeclared name raises ``KeyError``."""
    if not is_composite(key):
        raise KeyError(f"{key!r} is not a composite key (prefix {PREFIX!r})")
    name = key[len(PREFIX) :]
    if name not in COMPOSITES:
        raise KeyError(f"composite {name!r} is not declared (RESEARCH_LOG 024, playbook §12.6)")
    return COMPOSITES[name]


def columns(keys: list[str] | tuple[str, ...]) -> list[str]:
    """The panel/snapshot columns behind feature keys: a composite expands to its members, a
    plain feature is itself. Order-preserving, without duplicates."""
    out: list[str] = []
    for key in keys:
        cols = [f for f, _ in get(key).members] if is_composite(key) else [key]
        out.extend(c for c in cols if c not in out)
    return out
