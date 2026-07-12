"""TDCC (集保結算所) shareholding-dispersion provider — the weekly big-holder file
(roadmap 13.9).

Free, official open-data source for Taiwan's 集保戶股權分散表: per-security holder
counts, shares, and % of TDCC custody across 17 standard brackets, published
weekly (a snapshot as of the last business day of the week). FinMind's equivalent
(``TaiwanStockHoldingSharesPer``) is paid-tier; TDCC's own bulk CSV endpoint
(``opendata.tdcc.com.tw``, dataset ``1-5``) serves the same underlying data free,
key-less — verified live 2026-07-11/12.

**Bracket table** (live-derived — the endpoint documents field *names* but not
the level→range mapping; no attached code table was fetchable). Confirmed by
two independent means: (a) a public listing of the 15 ordered display labels
(wantgoo.com, 2026-07-11); (b) direct arithmetic on real data (the full
2026-07-03 file, 4,001 securities) — for every stock checked, summing holder
counts *and* shares across levels 1–16 equals level 17's totals exactly (e.g.
1101.TW: 516,224 holders both ways), proving level 17 is a **summary row**,
never a distinct tier.

    level  1: 1–999 shares            level  9: 50,001–100,000
    level  2: 1,000–5,000             level 10: 100,001–200,000
    level  3: 5,001–10,000            level 11: 200,001–400,000
    level  4: 10,001–15,000           level 12: 400,001–600,000
    level  5: 15,001–20,000           level 13: 600,001–800,000
    level  6: 20,001–30,000           level 14: 800,001–1,000,000
    level  7: 30,001–40,000           level 15: 1,000,001+ ("1,000張以上")
    level  8: 40,001–50,000           level 17: 合計 (total — always dropped)

**Level 16 is deliberately excluded from every mapping/aggregation here — not
because it is unused, but because its meaning does not fit the ordered
15-tier scale above.** Checked across the full universe: 78 of 4,001
securities carry a nonzero level 16, including plain common stocks (not just
ETFs) with no obvious pattern connecting them. In every populated case
observed, level 16 has **exactly one holder** and a small, often round share
count (e.g. 1,000–376,000 shares across four spot-checked names) — far below
level 15's holdings and inconsistent with "an even-higher ownership tier."
This looks like a technical/administrative single-account bucket (a
plausible guess: an unconsolidated or suspense account), not a size-ordered
bracket — but the true meaning is genuinely unresolved. Excluding it from
:data:`BIG_HOLDER_LEVELS` is a safe default either way (its observed
magnitudes never approach 400 lots); revisit if a future `tw-bigholder`
research card needs more precision.

"大戶" (big holder), per this card's definition, is **≥400 board lots**
(400,000 shares) — levels 12–15 (400–600張, 600–800張, 800–1000張, 1000張以上).

**Point-in-time (`available_at`).** TDCC does not publish an explicit lag; a
secondary source claims "every Saturday 09:00" (~1-day lag), but a live probe
(2026-07-12) found the bulk file still serving 2026-07-03 data nine days later,
with no official delay notice — a genuine, unresolved discrepancy (see
``docs/RESEARCH_LOG.md``). **User decision (2026-07-11): the conservative
bound, `available_at = data_date + 14 days`** — mirroring this project's TW
`filed_at` precedent (a safely-late legal/practical bound beats a possibly-too-
early guess; the wrong-direction error here is look-ahead bias, never mere
staleness).

**No historical backfill exists.** The endpoint always serves "the current
week" — there is no date parameter. Building history means calling
:func:`fetch_and_cache_latest_week` once a week, over real calendar time (the
same operational shape as ``research.mops_probe``'s daily accumulation,
roadmap 17.9); there is no way to retroactively fetch an old week.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from heimdall.data.store import data_root

_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"

#: level -> (lower shares inclusive, upper shares inclusive or None for open-ended).
BRACKETS: dict[int, tuple[int, int | None]] = {
    1: (1, 999),
    2: (1_000, 5_000),
    3: (5_001, 10_000),
    4: (10_001, 15_000),
    5: (15_001, 20_000),
    6: (20_001, 30_000),
    7: (30_001, 40_000),
    8: (40_001, 50_000),
    9: (50_001, 100_000),
    10: (100_001, 200_000),
    11: (200_001, 400_000),
    12: (400_001, 600_000),
    13: (600_001, 800_000),
    14: (800_001, 1_000_000),
    15: (1_000_001, None),
}
_TOTAL_LEVEL = 17  # a summary row (Σ levels 1-16), never a distinct holder tier
#: 400,000 shares = 400 board lots — this card's "大戶" definition (levels whose
#: entire range sits at/above 400 lots: 400-600張, 600-800張, 800-1000張, 1000張以上).
BIG_HOLDER_LEVELS = frozenset({12, 13, 14, 15})

#: Conservative PIT lag (user decision 2026-07-11) — see the module docstring.
AVAILABILITY_LAG = timedelta(days=14)

CANONICAL_COLUMNS = [
    "symbol",
    "data_date",
    "available_at",
    "level",
    "holders",
    "shares",
    "pct_of_custody",
    "currency",
    "provider",
    "fetched_at",
]


def normalize(rows: list[dict[str, Any]], market_by_id: dict[str, str]) -> pd.DataFrame:
    """Raw TDCC CSV rows (dicts keyed by the Chinese column names) -> canonical
    weekly shareholding rows. Pure — the golden-test unit.

    ``market_by_id`` maps a bare 4-digit stock_id to ``"TW"``/``"TWO"`` — TDCC's
    bulk file carries no market-type field of its own (unlike FinMind's
    ``TaiwanStockInfo``), so the canonical symbol suffix must come from the
    caller (``screener.universe.tw_symbols()``, stripped of its own suffix — see
    ``research.tdcc_cache``, which does this wiring; ``data/`` may not import
    ``screener/``). A stock_id absent from ``market_by_id`` is **dropped, never
    guessed** — this also naturally filters out ETFs/warrants/bonds sharing the
    same bulk file, since ``market_by_id`` only contains common stocks.

    Drops the level-17 total row (see the module docstring for why it's a
    summary, not a tier) and rows for stock_ids TDCC pads with trailing
    whitespace to a fixed width (stripped before lookup).
    """
    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    out: list[dict[str, Any]] = []
    for r in rows:
        level = int(r["持股分級"])
        if level == _TOTAL_LEVEL:
            continue
        sid = str(r["證券代號"]).strip()
        market = market_by_id.get(sid)
        if market is None:
            continue
        data_dt = datetime.strptime(str(r["資料日期"]).strip(), "%Y%m%d").date()
        out.append(
            {
                "symbol": f"{sid}.{market}",
                "data_date": pd.Timestamp(data_dt),
                "available_at": pd.Timestamp(data_dt + AVAILABILITY_LAG),
                "level": level,
                "holders": int(r["人數"]),
                "shares": float(r["股數"]),
                "pct_of_custody": float(r["占集保庫存數比例%"]),
                "currency": "TWD",
                "provider": "tdcc",
                "fetched_at": fetched_at,
            }
        )
    return pd.DataFrame(out, columns=CANONICAL_COLUMNS)


def fetch_raw() -> list[dict[str, Any]]:
    """Hit the live open-data endpoint — always "the current week"; no date
    parameter exists (probed 2026-07-12). Network; not unit-tested, matching
    this repo's convention of golden-testing only the pure :func:`normalize`.
    """
    import requests

    resp = requests.get(_URL, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")  # BOM-prefixed UTF-8, confirmed live
    return list(csv.DictReader(io.StringIO(text)))


def cache_path(data_date: date, root: Path | None = None) -> Path:
    return (root or data_root()) / "tdcc" / f"shareholding_{data_date.isoformat()}.parquet"


def _save_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def fetch_and_cache_latest_week(
    market_by_id: dict[str, str], *, root: Path | None = None, refresh: bool = False
) -> pd.DataFrame:
    """Fetch + normalize the current week; cache atomically, delta-only (a week
    already on disk is reused untouched unless ``refresh=True``)."""
    raw = fetch_raw()
    df = normalize(raw, market_by_id)
    if df.empty:
        return df
    data_dt = pd.Timestamp(df["data_date"].iloc[0]).date()
    path = cache_path(data_dt, root)
    if not refresh and path.exists():
        return pd.read_parquet(path)
    _save_atomic(df, path)
    return df


def load_cached_weeks(root: Path | None = None) -> pd.DataFrame:
    """Every accumulated weekly file, concatenated — whatever has been fetched
    over real calendar time (no backfill exists; see the module docstring)."""
    base = (root or data_root()) / "tdcc"
    if not base.exists():
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    paths = sorted(base.glob("shareholding_*.parquet"))
    if not paths:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


__all__ = [
    "AVAILABILITY_LAG",
    "BIG_HOLDER_LEVELS",
    "BRACKETS",
    "CANONICAL_COLUMNS",
    "cache_path",
    "fetch_and_cache_latest_week",
    "fetch_raw",
    "load_cached_weeks",
    "normalize",
]
