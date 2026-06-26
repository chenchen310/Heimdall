"""App state — small, transactional SQLite store (saved screens, watchlists, …).

Distinct from the analytical DuckDB/Parquet cache (``store.py``/``cache.py``):
this is a row store for a little mutable config, not time-series history. A
generic namespaced key→JSON table keeps it trivial. See ARCHITECTURE §3.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stockobserver.data.store import data_root

_DDL = """
CREATE TABLE IF NOT EXISTS kv (
    ns         TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ns, key)
)
"""


def _connect(root: Path | None = None) -> sqlite3.Connection:
    base = root if root is not None else data_root()
    base.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(base / "state.sqlite")
    con.execute(_DDL)
    return con


def put(ns: str, key: str, value: dict[str, Any], root: Path | None = None) -> None:
    con = _connect(root)
    try:
        con.execute(
            "INSERT OR REPLACE INTO kv (ns, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (ns, key, json.dumps(value), datetime.now(UTC).isoformat()),
        )
        con.commit()
    finally:
        con.close()


def get(ns: str, key: str, root: Path | None = None) -> dict[str, Any] | None:
    con = _connect(root)
    try:
        row = con.execute("SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, key)).fetchone()
    finally:
        con.close()
    return json.loads(row[0]) if row else None


def keys(ns: str, root: Path | None = None) -> list[str]:
    con = _connect(root)
    try:
        rows = con.execute("SELECT key FROM kv WHERE ns = ? ORDER BY key", (ns,)).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def delete(ns: str, key: str, root: Path | None = None) -> None:
    con = _connect(root)
    try:
        con.execute("DELETE FROM kv WHERE ns = ? AND key = ?", (ns, key))
        con.commit()
    finally:
        con.close()
