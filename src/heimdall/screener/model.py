"""Declarative screen model: a screen is a list of ``{field, op, value}`` predicates.

Because fundamental, technical, and factor fields all live in one canonical
snapshot, a new criterion is just another predicate — no code change. Screens are
pydantic models so they serialize to/from JSON for saving. See ARCHITECTURE §5.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

#: Supported comparison operators.
OPERATORS: frozenset[str] = frozenset({"<", "<=", ">", ">=", "==", "!=", "between", "in", "notna"})


class Predicate(BaseModel):
    """One filter, e.g. ``Predicate(field="pe", op="<", value=15)``.

    ``between`` expects ``value=[lo, hi]``; ``in`` expects a list; ``notna``
    ignores ``value``. ``enabled=False`` keeps the predicate on the screen (still
    saved and editable) but makes it a no-op — the UI uses this to toggle a
    criterion off and see which extra rows appear, without deleting it.
    """

    field: str
    op: str
    value: Any = None
    enabled: bool = True

    @field_validator("op")
    @classmethod
    def _known_op(cls, v: str) -> str:
        if v not in OPERATORS:
            raise ValueError(f"unknown operator {v!r}; allowed: {sorted(OPERATORS)}")
        return v


class Screen(BaseModel):
    """A named set of predicates plus optional ranking.

    ``market`` records the region the screen was built for (``US`` / ``Taiwan``);
    currency-denominated thresholds (e.g. ``market_cap``) are in that market's
    currency, so the UI warns when such a screen is loaded under a different market.
    New optional fields default safely, so screens saved before they existed still load.
    """

    name: str
    description: str = ""
    predicates: list[Predicate] = []
    sort_by: str | None = None
    ascending: bool = True
    limit: int | None = None
    market: str | None = None
