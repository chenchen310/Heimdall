"""Declarative screener: snapshot table + predicate evaluation + saved screens."""

from __future__ import annotations

from heimdall.screener.engine import evaluate
from heimdall.screener.model import OPERATORS, Predicate, Screen
from heimdall.screener.snapshot import (
    DEFAULT_UNIVERSE,
    build_snapshot,
    load_snapshot,
    save_snapshot,
)

__all__ = [
    "evaluate",
    "Predicate",
    "Screen",
    "OPERATORS",
    "DEFAULT_UNIVERSE",
    "build_snapshot",
    "load_snapshot",
    "save_snapshot",
]
