"""FINRA **equity short interest** provider (roadmap 17.11), free and keyless.

Member firms report short positions twice a month (FINRA Rule 4560); FINRA's public Query API
dataset ``otcMarket/consolidatedShortInterest`` serves every reported issue, exchange-listed
(NYSE, Nasdaq, NYSE Arca, Cboe BZX, NYSE American) and OTC alike. Probed 2026-10-01:

- **History starts 2017-12-29.** Earlier settlement dates return no records, so the research DEV
  window (2010–2019) has only 2018–2019 for these features.
- The dataset is partitioned by settlement date and allows at most 5,000 records per request, so
  ingest pages through one settlement date at a time (a bulk read per cycle, never per symbol).
- **Availability.** FINRA's current schedule publishes a cycle 7 business days after its
  settlement date. Official publication dates for past years are not on FINRA's site (only the
  current year's schedule is). By the user's decision (2026-10-01), every cycle is therefore
  available **10 weekdays** after settlement (:data:`AVAILABLE_LAG_BDAYS`), which is later than
  every observed official lag. The settlement date itself is never treated as knowable.

Canonical row (one per symbol per cycle; exchange-listed issues only)::

    symbol settlement_date available_at short_shares avg_daily_volume split_flag provider
    fetched_at

``avg_daily_volume`` is FINRA's own average daily volume for the same cycle. Days to cover
should use it rather than our price cache's volume, which yfinance adjusts backwards for later
splits (NVDA's pre-2024-split volume reads 10× its real share count) while the short position is
in the shares of its own date. ``split_flag`` marks a cycle with a split inside it, where the two
quantities may be on different share bases.

Positions are stored **as first published**. A later revision (FINRA's ``revisionFlag``) is not
written back over history (data discipline).

    uv run python -m heimdall.data.providers.finra          # ingest every new cycle
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.store import data_root
from heimdall.data.symbols import parse_symbol

_URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
_PAGE = 5000  # the API's record-max-limit
_FIELDS = [
    "symbolCode",
    "settlementDate",
    "marketClassCode",
    "currentShortPositionQuantity",
    "averageDailyVolumeQuantity",
    "stockSplitFlag",
    "revisionFlag",
]
#: Issues that always carry a short position: their cycles enumerate the settlement dates.
_ANCHORS = ("AAPL", "MSFT")
#: Weekdays from settlement to availability (user decision 2026-10-01; FINRA's own lag is 7).
AVAILABLE_LAG_BDAYS = 10
_OTC = "OTC"

SHORT_INTEREST_COLUMNS: list[str] = [
    "symbol",
    "settlement_date",
    "available_at",
    "short_shares",
    "avg_daily_volume",
    "split_flag",
    "provider",
    "fetched_at",
]

Query = Callable[[dict[str, Any]], list[dict[str, Any]]]  # request body → records


def finra_dir(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "finra"


def table_path(root: Path | None = None) -> Path:
    return finra_dir(root) / "short_interest.parquet"


def marker_path(root: Path | None = None) -> Path:
    return finra_dir(root) / "_short_interest.json"


def available_at(settlement: pd.Timestamp) -> pd.Timestamp:
    """The first day a cycle may be used: settlement + :data:`AVAILABLE_LAG_BDAYS` weekdays."""
    return pd.Timestamp(settlement) + pd.offsets.BDay(AVAILABLE_LAG_BDAYS)


def clean_symbol(raw: str) -> str:
    """FINRA's symbol in the canonical spelling (``BRK.B`` / ``BRK/B`` → ``BRK-B``), or ``""``."""
    t = str(raw).strip().upper().replace("/", "-").replace(".", "-")
    return t if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,9}", t) else ""


def normalize_cycle(records: list[dict[str, Any]], fetched_at: datetime) -> pd.DataFrame:
    """One settlement date's API records → canonical rows (exchange-listed issues only).

    A record without a usable symbol, a negative or missing position is dropped (validated on
    ingest, never guessed). A missing or zero volume is kept as NaN: the position still exists,
    only days to cover is undefined.
    """
    rows: list[dict[str, Any]] = []
    for r in records:
        if r.get("marketClassCode") == _OTC:
            continue
        sym = clean_symbol(r.get("symbolCode") or "")
        shares = r.get("currentShortPositionQuantity")
        if not sym or shares is None or float(shares) < 0:
            continue
        volume = r.get("averageDailyVolumeQuantity")
        settle = pd.Timestamp(r["settlementDate"])
        rows.append(
            {
                "symbol": f"{sym}.US",
                "settlement_date": settle,
                "available_at": available_at(settle),
                "short_shares": float(shares),
                "avg_daily_volume": float(volume) if volume and float(volume) > 0 else float("nan"),
                "split_flag": r.get("stockSplitFlag") == "S",
                "provider": "finra",
                "fetched_at": fetched_at,
            }
        )
    out = pd.DataFrame(rows, columns=SHORT_INTEREST_COLUMNS)
    return out.drop_duplicates(["symbol", "settlement_date"], keep="first").reset_index(drop=True)


def _api(min_interval_s: float = 0.5) -> Query:
    """POST to the FINRA Query API, throttled, with retries on 429/5xx."""
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    last = [0.0]

    def query(body: dict[str, Any]) -> list[dict[str, Any]]:
        for attempt in range(4):
            wait = min_interval_s - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                resp = session.post(_URL, data=json.dumps(body), timeout=120)
            except requests.RequestException:
                time.sleep(2.0 * 2**attempt)
                continue
            if resp.status_code == 200:
                return list(resp.json()) if resp.text.strip() else []
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2.0 * 2**attempt)
                continue
            raise ProviderError(f"FINRA {resp.status_code}: {resp.text[:200]}")
        raise ProviderError("FINRA API unreachable after 4 attempts")

    return query


def settlement_dates(query: Query) -> list[date]:
    """Every published settlement date: the cycles of issues that always carry a position."""
    found: set[date] = set()
    for anchor in _ANCHORS:
        body = {
            "limit": _PAGE,
            "fields": ["settlementDate"],
            "compareFilters": [
                {"compareType": "equal", "fieldName": "symbolCode", "fieldValue": anchor}
            ],
        }
        found |= {date.fromisoformat(r["settlementDate"]) for r in query(body)}
    return sorted(found)


def fetch_cycle(query: Query, settlement: date) -> list[dict[str, Any]]:
    """Every record of one settlement date, page by page (5,000 per request)."""
    out: list[dict[str, Any]] = []
    while True:
        body = {
            "limit": _PAGE,
            "offset": len(out),
            "fields": _FIELDS,
            "compareFilters": [
                {
                    "compareType": "equal",
                    "fieldName": "settlementDate",
                    "fieldValue": settlement.isoformat(),
                }
            ],
        }
        page = query(body)
        out.extend(page)
        if len(page) < _PAGE:
            return out


@dataclass
class IngestReport:
    cycles: int  # cycles stored in total
    new_cycles: int  # fetched by this run
    first: str
    last: str
    rows: int
    ingested_at: str


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def ingest(root: Path | None = None, query: Query | None = None) -> IngestReport:
    """Fetch every settlement date not yet on disk and rebuild the canonical table.

    Delta-only: a stored cycle is never fetched again, so first-published positions are never
    overwritten by later revisions. Raw API records are kept per cycle under
    ``finra/raw/<date>.json.gz``, and the table is rebuilt from them.
    """
    base = root if root is not None else data_root()
    q = query if query is not None else _api()
    raw_dir = finra_dir(base) / "raw"
    have = {date.fromisoformat(p.name.split(".")[0]) for p in raw_dir.glob("*.json.gz")}
    new = 0
    for settle in settlement_dates(q):
        if settle in have:
            continue
        records = fetch_cycle(q, settle)
        if not records:  # announced but empty: do not store, try again next run
            continue
        payload = {"fetched_at": datetime.now(UTC).isoformat(), "records": records}
        _write_atomic(
            raw_dir / f"{settle.isoformat()}.json.gz", gzip.compress(json.dumps(payload).encode())
        )
        new += 1
    frames = []
    for path in sorted(raw_dir.glob("*.json.gz")):
        payload = json.loads(gzip.decompress(path.read_bytes()))
        stamp = datetime.fromisoformat(payload["fetched_at"]).replace(tzinfo=None)
        frames.append(normalize_cycle(payload["records"], stamp))
    table = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=SHORT_INTEREST_COLUMNS)
    )
    table = table.sort_values(["symbol", "settlement_date"]).reset_index(drop=True)
    tmp = table_path(base).with_name(f"short_interest.{os.getpid()}.tmp")
    table_path(base).parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(tmp, index=False)
    os.replace(tmp, table_path(base))
    dates = sorted(table["settlement_date"].unique()) if len(table) else []
    report = IngestReport(
        cycles=len(dates),
        new_cycles=new,
        first=str(pd.Timestamp(dates[0]).date()) if dates else "",
        last=str(pd.Timestamp(dates[-1]).date()) if dates else "",
        rows=len(table),
        ingested_at=datetime.now(UTC).isoformat(),
    )
    _write_atomic(marker_path(base), (json.dumps(asdict(report), indent=2) + "\n").encode())
    return report


class FinraProvider(DataProvider):
    """US short interest from the ingested FINRA table (no network on the read path).

    Extra method beyond the ABC — :meth:`short_interest`, as Form 4 exposes
    ``get_insider_transactions``. Run :func:`ingest` (the CLI) to refresh the table.
    """

    markets = frozenset({"US"})

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else data_root()
        self._by_symbol: dict[str, pd.DataFrame] | None = None

    def get_ohlcv(self, symbol: str, start: object, end: object) -> pd.DataFrame:
        raise NotSupported("finra serves short interest, not prices")

    def _load(self) -> dict[str, pd.DataFrame]:
        if self._by_symbol is None:
            path = table_path(self._root)
            table = pd.read_parquet(path) if path.exists() else pd.DataFrame()
            self._by_symbol = (
                {str(s): g.reset_index(drop=True) for s, g in table.groupby("symbol")}
                if len(table)
                else {}
            )
        return self._by_symbol

    def short_interest(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Canonical rows for ``symbol`` with a settlement date in ``[start, end]``.

        Filtering on settlement keeps every cycle a caller might need; point-in-time use must
        still read only rows with ``available_at`` on or before its date."""
        sym = parse_symbol(symbol)
        if sym.market not in self.markets:
            raise NotSupported(f"finra does not serve market {sym.market}")
        table = self._load()
        rows = table.get(sym.canonical)
        if rows is None and "-" in sym.ticker:
            # FINRA writes a share class without a separator (BRK-B is ``BRKB``, BF-B is
            # ``BFB``). Only this direction is tried: a code FINRA lists once can't be two issues.
            rows = table.get(f"{sym.ticker.replace('-', '')}.US")
        if rows is None:
            return pd.DataFrame(columns=SHORT_INTEREST_COLUMNS)
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        keep = (rows["settlement_date"] >= lo) & (rows["settlement_date"] <= hi)
        return rows[keep].assign(symbol=sym.canonical).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(description="FINRA equity short interest (roadmap 17.11)").parse_args(
        argv
    )
    rep = ingest()
    print(
        f"short interest: {rep.new_cycles} new cycle(s); {rep.cycles} cycles "
        f"{rep.first} → {rep.last}; {rep.rows:,} rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
