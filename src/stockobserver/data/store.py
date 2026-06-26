"""Storage substrate: partitioned Parquet on disk, queried with DuckDB.

Parquet is the storage format (columnar, compresses well); DuckDB is the query
engine for analytical scans (it reads Parquet directly). See
``docs/ARCHITECTURE.md`` §3. The keyed price cache (``cache.py``) writes the
Parquet files; this module is the read/query side and path policy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import duckdb
import pandas as pd

from stockobserver.data.symbols import Symbol


def data_root() -> Path:
    """Resolve the on-disk data directory (env-overridable, gitignored)."""
    root = os.environ.get("STOCKOBSERVER_DATA_DIR")
    return Path(root) if root else Path.cwd() / "data"


def prices_path(root: Path, sym: Symbol) -> Path:
    """Parquet location for one symbol's OHLCV: ``prices/{market}/{ticker}.parquet``."""
    return root / "prices" / sym.market / f"{sym.ticker}.parquet"


def query(sql: str, root: Path | None = None) -> pd.DataFrame:
    """Run a DuckDB query over the data root. ``{prices}`` expands to the Parquet glob.

    Example::

        query("SELECT symbol, count(*) FROM {prices} GROUP BY 1")
    """
    base = root if root is not None else data_root()
    glob = str(base / "prices" / "**" / "*.parquet")
    sql = sql.replace("{prices}", f"read_parquet('{glob}')")
    con = duckdb.connect()
    try:
        return cast("pd.DataFrame", con.sql(sql).df())
    finally:
        con.close()
