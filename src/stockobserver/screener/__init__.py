"""Declarative screener: snapshot table + predicate evaluation + saved screens."""

from __future__ import annotations

from stockobserver.screener.engine import evaluate
from stockobserver.screener.model import OPERATORS, Predicate, Screen
from stockobserver.screener.snapshot import (
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
