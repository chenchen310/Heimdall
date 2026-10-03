"""Suite-wide safety net: no test may read or write the user's real data directory.

``data_root()`` defaults to ``./data`` — the real cache, panels and the factory's trial
ledgers. Every test starts with ``HEIMDALL_DATA_DIR`` pointed at its own ``tmp_path``; a test
that sets the variable itself (``monkeypatch.setenv``) simply overrides this default.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
