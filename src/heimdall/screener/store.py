"""Persist screens as JSON in the SQLite app-state store (reproducibility)."""

from __future__ import annotations

from pathlib import Path

from heimdall.data import state
from heimdall.screener.model import Screen

_NS = "screen"


def save_screen(screen: Screen, root: Path | None = None) -> None:
    state.put(_NS, screen.name, screen.model_dump(), root)


def load_screen(name: str, root: Path | None = None) -> Screen:
    data = state.get(_NS, name, root)
    if data is None:
        raise KeyError(f"no saved screen named {name!r}")
    return Screen(**data)


def list_screens(root: Path | None = None) -> list[str]:
    return state.keys(_NS, root)


def delete_screen(name: str, root: Path | None = None) -> None:
    state.delete(_NS, name, root)
