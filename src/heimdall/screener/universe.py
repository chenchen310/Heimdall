"""Screener universes — the large, fetched constituent lists.

The small `DEFAULT_UNIVERSE` / `TW_UNIVERSE` lists live in ``snapshot.py``; this
module adds the **whole-market** universes that have to be fetched and cached:

* ``vti_symbols()`` — VTI's holdings (~3,400 US names) from Vanguard's public
  holdings endpoint → canonical ``TICKER.US``.
* ``tw_symbols()`` — every TWSE + TPEX common stock (~2,100) from FinMind's
  ``TaiwanStockInfo`` → ``TICKER.TW`` / ``TICKER.TWO``.

Both cache to disk so a rebuild does not re-hit the source, and both have a pure
parser (``_parse_holdings`` / ``_parse_tw_info``) that is golden-tested offline.

These are *constituent lists*, not market data — they never touch the canonical
OHLCV/fundamentals schema, so they live here rather than behind a `DataProvider`.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from heimdall.data.store import data_root

# Vanguard's investor holdings API for VTI (paginated 500/page; carries ``size``).
_VTI_URL = (
    "https://investor.vanguard.com/investment-products/etfs/profile/api/vti/portfolio-holding/stock"
)
_PAGE = 500
_MAX_PAGES = 40  # safety bound (~20k names) — VTI is ~3.4k


def _canonical(ticker: str) -> str:
    """Vanguard ticker → canonical US symbol. Class shares use a dot (``BRK.B``);
    yfinance/EDGAR use a dash, and ``.`` is our market separator, so swap it."""
    return f"{ticker.strip().upper().replace('.', '-')}.US"


def _parse_holdings(pages: list[dict[str, Any]]) -> list[str]:
    """Pages of Vanguard holdings JSON → de-duplicated canonical symbols (in order)."""
    seen: set[str] = set()
    out: list[str] = []
    for page in pages:
        for entity in page.get("fund", {}).get("entity", []):
            ticker = (entity.get("ticker") or "").strip()
            if not ticker:
                continue  # cash / derivative lines have no ticker
            sym = _canonical(ticker)
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def _fetch_pages(min_interval_s: float = 0.2) -> list[dict[str, Any]]:
    import requests

    pages: list[dict[str, Any]] = []
    start = 1
    for _ in range(_MAX_PAGES):
        resp = requests.get(
            _VTI_URL,
            params={"start": start, "count": _PAGE},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        pages.append(payload)
        entities = payload.get("fund", {}).get("entity", [])
        size = int(payload.get("size", 0))
        if not entities or start - 1 + len(entities) >= size:
            break
        start += _PAGE
        time.sleep(min_interval_s)
    return pages


def _cache_path(root: Path | None) -> Path:
    return (root or data_root()) / "universe" / "vti.json"


def vti_symbols(*, refresh: bool = False, root: Path | None = None) -> list[str]:
    """Canonical symbols for VTI's holdings (total US market), disk-cached.

    Pass ``refresh=True`` to re-fetch from Vanguard and overwrite the cache.
    """
    path = _cache_path(root)
    if not refresh and path.exists():
        return list(json.loads(path.read_text())["symbols"])
    symbols = _parse_holdings(_fetch_pages())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"symbols": symbols}))
    return symbols


# --- Taiwan: the whole TWSE + TPEX common-stock universe (FinMind) ----------
_FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
# Common-stock ids are 4 digits starting 1-9; ETFs (00xx), 5-6-digit codes, and
# warrants are thereby excluded. Industry tags catch the few 4-digit non-stocks.
_TW_COMMON_ID = re.compile(r"[1-9][0-9]{3}")
_TW_EXCLUDE_INDUSTRY = ("ETF", "ETN", "Index", "存託憑證", "受益證券", "所有證券")
_TW_MARKET = {"twse": "TW", "tpex": "TWO"}  # 上市 / 上櫃; 興櫃 (emerging) excluded


def _parse_tw_info(rows: list[dict[str, Any]]) -> list[str]:
    """FinMind ``TaiwanStockInfo`` rows → canonical TW common-stock symbols.

    Keeps TWSE (``.TW``) + TPEX (``.TWO``) 4-digit common stocks, drops ETFs /
    warrants / depositary receipts / emerging-board names, and de-duplicates.
    """
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        sid = str(row.get("stock_id", ""))
        market = _TW_MARKET.get(row.get("type", ""))
        industry = row.get("industry_category") or ""
        if market is None or not _TW_COMMON_ID.fullmatch(sid) or sid in seen:
            continue
        if any(tag in industry for tag in _TW_EXCLUDE_INDUSTRY):
            continue
        seen.add(sid)
        out.append(f"{sid}.{market}")
    return out


def _fetch_tw_info() -> list[dict[str, Any]]:
    import requests

    params = {"dataset": "TaiwanStockInfo"}
    token = os.environ.get("FINMIND_TOKEN")
    if token:
        params["token"] = token
    resp = requests.get(_FINMIND_URL, params=params, timeout=60)
    resp.raise_for_status()
    data: list[dict[str, Any]] = resp.json().get("data", [])
    return data


def tw_symbols(*, refresh: bool = False, root: Path | None = None) -> list[str]:
    """Canonical symbols for all TWSE + TPEX common stocks (~2,100), disk-cached."""
    path = (root or data_root()) / "universe" / "tw_all.json"
    if not refresh and path.exists():
        return list(json.loads(path.read_text())["symbols"])
    symbols = _parse_tw_info(_fetch_tw_info())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"symbols": symbols}))
    return symbols
