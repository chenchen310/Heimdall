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
    ignores ``value``.
    """

    field: str
    op: str
    value: Any = None

    @field_validator("op")
    @classmethod
    def _known_op(cls, v: str) -> str:
        if v not in OPERATORS:
            raise ValueError(f"unknown operator {v!r}; allowed: {sorted(OPERATORS)}")
        return v


class Screen(BaseModel):
    """A named set of predicates plus optional ranking."""

    name: str
    predicates: list[Predicate] = []
    sort_by: str | None = None
    ascending: bool = True
    limit: int | None = None
