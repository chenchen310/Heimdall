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
from heimdall.data.symbols import parse_symbol

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


def _parse_tw_rows(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """FinMind ``TaiwanStockInfo`` rows → de-duplicated ``(canonical symbol, industry)``
    pairs for common TWSE/TPEX stocks.

    Keeps TWSE (``.TW``) + TPEX (``.TWO``) 4-digit common stocks, drops ETFs /
    warrants / depositary receipts / emerging-board names. The shared core behind
    :func:`_parse_tw_info` (symbols only) and :func:`_parse_tw_sector` (roadmap
    14.1 — the industry string, discarded by the former, kept by the latter).
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for row in rows:
        sid = str(row.get("stock_id", ""))
        market = _TW_MARKET.get(row.get("type", ""))
        industry = row.get("industry_category") or ""
        if market is None or not _TW_COMMON_ID.fullmatch(sid) or sid in seen:
            continue
        if any(tag in industry for tag in _TW_EXCLUDE_INDUSTRY):
            continue
        seen.add(sid)
        out.append((f"{sid}.{market}", industry))
    return out


def _parse_tw_info(rows: list[dict[str, Any]]) -> list[str]:
    """FinMind ``TaiwanStockInfo`` rows → canonical TW common-stock symbols."""
    return [sym for sym, _industry in _parse_tw_rows(rows)]


def _parse_tw_sector(rows: list[dict[str, Any]]) -> dict[str, str]:
    """The same rows, keyed to their FinMind ``industry_category`` (roadmap 14.1) —
    e.g. ``{"2330.TW": "半導體業"}``. Already zh, so no i18n gloss is needed."""
    return {sym: (industry or "Unknown") for sym, industry in _parse_tw_rows(rows)}


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


def tw_sector_map(*, refresh: bool = False, root: Path | None = None) -> dict[str, str]:
    """Canonical TW symbol → FinMind ``industry_category`` (roadmap 14.1).

    ``TaiwanStockInfo`` already carries this per row (``tw_symbols()`` discards
    it after filtering) — persisted as its own cache beside ``tw_all.json``
    instead of re-fetched, so any caller wanting sector data for the TW
    universe (the snapshot builder here, the 17.5 panel later) shares one
    artifact and one FinMind request.
    """
    path = (root or data_root()) / "universe" / "tw_sector.json"
    if not refresh and path.exists():
        return dict(json.loads(path.read_text()))
    mapping = _parse_tw_sector(_fetch_tw_info())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False))
    return mapping


# --- US: broad sector via EDGAR SIC code (roadmap 14.1, option (b)) ---------
# No cached artifact already carries a US sector field (probed 2026-07-11 — option
# (a) is a dead end), so this fetches EDGAR's ``submissions`` JSON (verified live:
# {"sic": 3571, "sicDescription": "Electronic Computers", ...} for AAPL). The raw
# ``sicDescription`` is far too granular (1000+ distinct strings) to aggregate a
# sector page over, so the numeric ``sic`` is bucketed into one of the 10 standard
# SIC **Divisions** (public federal classification, stable since the 1987 manual —
# https://www.osha.gov/data/sic-manual) instead: a well-documented, deterministic
# ~dozen-group taxonomy, matching this card's i18n expectation.
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_TICKERS_META_URL = "https://www.sec.gov/files/company_tickers.json"

# (low, high) inclusive bounds on the SIC 2-digit major group -> Division name.
_SIC_DIVISIONS: list[tuple[int, int, str]] = [
    (1, 9, "Agriculture, Forestry & Fishing"),
    (10, 14, "Mining"),
    (15, 17, "Construction"),
    (20, 39, "Manufacturing"),
    (40, 49, "Transportation, Communications & Utilities"),
    (50, 51, "Wholesale Trade"),
    (52, 59, "Retail Trade"),
    (60, 67, "Finance, Insurance & Real Estate"),
    (70, 89, "Services"),
    (91, 99, "Public Administration"),
]


def _sic_division(sic: int) -> str:
    """4-digit SIC code -> one of the 10 standard SIC Divisions, or ``"Unknown"``
    for an out-of-range/unassigned code (e.g. the reserved 90 major group)."""
    major = sic // 100
    for lo, hi, name in _SIC_DIVISIONS:
        if lo <= major <= hi:
            return name
    return "Unknown"


def _edgar_user_agent() -> str:
    # Mirrors data.providers.edgar's UA convention (SEC fair-access requires a
    # descriptive UA); duplicated rather than imported since universe.py's own
    # precedent is fetching directly (constituent/reference data, not canonical
    # market data — see the module docstring).
    return os.environ.get("SEC_EDGAR_USER_AGENT", "heimdall (set SEC_EDGAR_USER_AGENT)")


def _cik_map(root: Path | None) -> dict[str, int]:
    """Ticker -> CIK, from EDGAR's public mapping. Shares the exact cache path
    ``data/edgar/company_tickers.json`` with ``data.providers.edgar`` — whichever
    module fetches it first, the other reuses it for free."""
    import requests

    cache = (root or data_root()) / "edgar" / "company_tickers.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
    else:
        resp = requests.get(
            _TICKERS_META_URL, headers={"User-Agent": _edgar_user_agent()}, timeout=30
        )
        resp.raise_for_status()
        raw = resp.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw))
    return {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}


def _us_sector_cache_path(root: Path | None) -> Path:
    return (root or data_root()) / "universe" / "us_sector.json"


def us_sector_map(
    symbols: list[str],
    *,
    refresh: bool = False,
    root: Path | None = None,
    min_interval_s: float = 0.12,
) -> dict[str, str]:
    """Canonical US symbol -> broad SIC-division sector (roadmap 14.1).

    One EDGAR ``submissions`` request per symbol not already cached (~10 req/s,
    EDGAR's fair-access limit — mirrors ``data.providers.edgar``'s throttle),
    incrementally persisted so a later, larger build never re-fetches a known
    symbol. A symbol with no resolvable CIK, or a request that errors, is
    skipped — its sector falls back to "Unknown" at the snapshot layer, never a
    fatal build.
    """
    import requests

    path = _us_sector_cache_path(root)
    mapping: dict[str, str] = (
        dict(json.loads(path.read_text())) if (not refresh and path.exists()) else {}
    )
    missing = [s for s in symbols if s not in mapping]
    if not missing:
        return mapping

    cik_by_ticker = _cik_map(root)
    ua = _edgar_user_agent()
    last_call = 0.0
    for sym in missing:
        cik = cik_by_ticker.get(parse_symbol(sym).ticker.upper())
        if cik is None:
            continue
        wait = min_interval_s - (time.monotonic() - last_call)
        if wait > 0:
            time.sleep(wait)
        last_call = time.monotonic()
        try:
            resp = requests.get(
                _SUBMISSIONS_URL.format(cik=cik), headers={"User-Agent": ua}, timeout=30
            )
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        sic = resp.json().get("sic")
        if sic:
            mapping[sym] = _sic_division(int(sic))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False))
    return mapping
