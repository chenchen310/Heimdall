"""SEC **Form 4** insider-transaction provider (roadmap 12.4 / 13.3).

The honest US "smart money" stream: officers and directors must report their own
open-market trades on **Form 4** within two business days, and every filing
carries a filing timestamp — so, exactly like :mod:`heimdall.data.providers.edgar`
fundamentals, we know what was knowable when. This is the credible *free*
alternative to institutional-flow data (which the US has no public daily feed
for; see card 12.4's reality note): 13F is quarterly with a 45-day lag and weak
cloning evidence, whereas insider buying is event-like and works at long
horizons.

Normalization (:func:`normalize_ownership_doc`) is **pure** and golden-tested
without the network — it turns one Form 4 ``ownershipDocument`` XML into
canonical per-transaction rows. The filing date is **not** inside the XML (it is
submission metadata), so it is passed in alongside; every canonical row is keyed
on ``filed_at`` for point-in-time correctness, never on ``txn_date`` (the trade
happened up to two business days before it was knowable).

Canonical row (one per reported non-derivative transaction)::

    symbol filed_at txn_date owner_cik owner_name is_officer is_director
    is_ten_pct txn_code acquired_disposed shares price_per_share currency
    provider fetched_at

The provider **does not editorialize**: it emits every non-derivative
transaction with its raw ``txn_code``; the *feature* layer
(``research.dataset._insider_features``) is what filters to open-market
purchases (``P``) and sales (``S``). Derivative transactions (option grants and
exercises) are intentionally excluded — they are compensation mechanics, not the
discretionary open-market signal.

See ``.claude/rules/canonical-schema.md`` and ``.claude/rules/data-discipline.md``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.store import data_root
from heimdall.data.symbols import parse_symbol

# Open-market transaction codes (SEC Form 4, Table I). ``P`` = open-market or
# private purchase (an acquisition), ``S`` = open-market or private sale (a
# disposition). These are the discretionary trades the insider-buying literature
# keys off; every other code (``A`` grant, ``M`` option exercise, ``F`` tax
# withholding, ``G`` gift, …) is compensation/mechanical and excluded by the
# feature, not the provider.
BUY_CODE = "P"
SELL_CODE = "S"
OPEN_MARKET_CODES = frozenset({BUY_CODE, SELL_CODE})

INSIDER_COLUMNS: list[str] = [
    "symbol",
    "filed_at",
    "txn_date",
    "owner_cik",
    "owner_name",
    "is_officer",
    "is_director",
    "is_ten_pct",
    "txn_code",
    "acquired_disposed",
    "shares",
    "price_per_share",
    "currency",
    "provider",
    "fetched_at",
]

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"


def _user_agent() -> str:
    # SEC fair-access policy requires a descriptive UA with contact info (shared
    # with the EDGAR fundamentals provider).
    return os.environ.get("SEC_EDGAR_USER_AGENT", "heimdall (set SEC_EDGAR_USER_AGENT)")


def _text(node: ET.Element | None) -> str | None:
    """Inner text of an element, or of its nested ``<value>`` wrapper (the Form 4
    schema wraps most leaf data in ``<value>``), stripped; ``None`` if absent."""
    if node is None:
        return None
    value = node.find("value")
    target = value if value is not None else node
    return target.text.strip() if target.text is not None else None


def _flag(node: ET.Element | None, tag: str) -> bool:
    """A Form 4 relationship boolean: ``<isOfficer>1</isOfficer>`` → True."""
    if node is None:
        return False
    return (_text(node.find(tag)) or "0").strip() in {"1", "true", "True"}


def normalize_ownership_doc(xml_text: str, filed_at: str) -> pd.DataFrame:
    """Parse one Form 4 ``ownershipDocument`` XML into canonical transaction rows.

    Pure (no network) — the unit of the golden test. ``filed_at`` is the SEC
    submission's filing date (``YYYY-MM-DD``), supplied by the fetch layer since
    the XML itself does not carry it; it becomes the point-in-time key on every
    row. Only **non-derivative** transactions with a share amount are emitted
    (derivative option mechanics are excluded); a transaction missing its code or
    share count is skipped rather than guessed.
    """
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    root = ET.fromstring(xml_text)

    trading_symbol = _text(root.find("./issuer/issuerTradingSymbol"))
    if not trading_symbol:
        return pd.DataFrame(columns=INSIDER_COLUMNS)
    symbol = parse_symbol(f"{trading_symbol.upper()}.US").canonical

    rel = root.find("./reportingOwner/reportingOwnerRelationship")
    owner_id = root.find("./reportingOwner/reportingOwnerId")
    owner_cik = _text(owner_id.find("rptOwnerCik")) if owner_id is not None else None
    owner_name = _text(owner_id.find("rptOwnerName")) if owner_id is not None else None
    is_officer = _flag(rel, "isOfficer")
    is_director = _flag(rel, "isDirector")
    is_ten_pct = _flag(rel, "isTenPercentOwner")

    rows: list[dict[str, Any]] = []
    for txn in root.findall("./nonDerivativeTable/nonDerivativeTransaction"):
        coding = txn.find("transactionCoding")
        amounts = txn.find("transactionAmounts")
        code = _text(coding.find("transactionCode")) if coding is not None else None
        shares = _text(amounts.find("transactionShares")) if amounts is not None else None
        if code is None or shares is None:
            continue  # a Form 4 amendment can carry holding-only rows with no trade
        price = _text(amounts.find("transactionPricePerShare")) if amounts is not None else None
        ad = _text(amounts.find("transactionAcquiredDisposedCode")) if amounts is not None else None
        rows.append(
            {
                "symbol": symbol,
                "filed_at": filed_at,
                "txn_date": _text(txn.find("transactionDate")),
                "owner_cik": owner_cik,
                "owner_name": owner_name,
                "is_officer": is_officer,
                "is_director": is_director,
                "is_ten_pct": is_ten_pct,
                "txn_code": code,
                "acquired_disposed": ad,
                "shares": float(shares),
                "price_per_share": float(price) if price else float("nan"),
                "currency": "USD",
                "provider": "form4",
                "fetched_at": fetched_at,
            }
        )

    if not rows:
        return pd.DataFrame(columns=INSIDER_COLUMNS)
    df = pd.DataFrame(rows, columns=INSIDER_COLUMNS)
    df["filed_at"] = pd.to_datetime(df["filed_at"])
    df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


class Form4Provider(DataProvider):
    """US insider transactions via EDGAR Form 4 XML (free, no key).

    Extra method beyond the ABC — :meth:`get_insider_transactions` — mirroring how
    :class:`~heimdall.data.providers.finmind.FinMindProvider` exposes
    ``daily_chips`` / ``daily_lending``. Prices/fundamentals are not served here.
    """

    markets = frozenset({"US"})

    def __init__(self, root: Path | None = None, min_interval_s: float = 0.12) -> None:
        self._root = root if root is not None else data_root()
        self._min_interval_s = min_interval_s  # SEC allows ~10 req/s
        self._last_call = 0.0
        self._cik: dict[str, int] | None = None

    def get_ohlcv(self, symbol: str, start: object, end: object) -> pd.DataFrame:
        raise NotSupported("form4 serves insider transactions, not prices")

    def get_insider_transactions(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Canonical insider-transaction rows for ``symbol`` filed within ``[start, end]``.

        Delta-cached per symbol as parquet. Fetches the issuer's Form 4 filings
        from the EDGAR submissions index, parses each ``ownershipDocument`` XML,
        and concatenates the normalized rows. ``start``/``end`` filter on
        ``filed_at`` (the point-in-time key).
        """
        sym = parse_symbol(symbol)
        if sym.market not in self.markets:
            raise NotSupported(f"form4 does not serve market {sym.market}")
        cache = self._cache_path(sym.canonical)
        if cache.exists():
            df = pd.read_parquet(cache)
        else:
            df = self._crawl(sym.ticker)
            cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache, index=False)
        if df.empty:
            return df
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df["filed_at"] >= lo) & (df["filed_at"] <= hi)].reset_index(drop=True)

    def _cache_path(self, canonical: str) -> Path:
        return self._root / "form4" / f"{canonical.replace('.', '_')}.parquet"

    # -- network -------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self._min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, url: str, *, as_json: bool) -> Any:
        self._throttle()
        resp = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=60)
        if resp.status_code != 200:
            raise ProviderError(f"EDGAR {resp.status_code} for {url}")
        return resp.json() if as_json else resp.text

    def _cik_for(self, ticker: str) -> int:
        if self._cik is None:
            cache = self._root / "edgar" / "company_tickers.json"  # shared with edgar provider
            if cache.exists():
                raw = json.loads(cache.read_text())
            else:
                raw = self._get(_TICKERS_URL, as_json=True)
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(raw))
            self._cik = {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}
        try:
            return self._cik[ticker.upper()]
        except KeyError:
            raise ProviderError(f"no SEC CIK for ticker {ticker!r}") from None

    def _crawl(self, ticker: str) -> pd.DataFrame:
        """Fetch + normalize every Form 4 the issuer has filed. Network path — not
        exercised by the golden test (which drives :func:`normalize_ownership_doc`
        directly). Kept simple: the recent-submissions page, which covers the
        modern XML-era Form 4s the feature reads."""
        cik = self._cik_for(ticker)
        subs = self._get(_SUBMISSIONS_URL.format(cik=cik), as_json=True)
        recent = subs.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accns = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        docs = recent.get("primaryDocument", [])
        frames: list[pd.DataFrame] = []
        for form, accn, filed, doc in zip(forms, accns, dates, docs, strict=False):
            if form != "4" or not doc.endswith(".xml"):
                continue
            url = _ARCHIVE_DOC_URL.format(cik=cik, acc_nodash=accn.replace("-", ""), doc=doc)
            try:
                xml = self._get(url, as_json=False)
                frames.append(normalize_ownership_doc(xml, filed))
            except (ProviderError, ET.ParseError):
                continue  # a single malformed filing must not kill the crawl
        if not frames:
            return pd.DataFrame(columns=INSIDER_COLUMNS)
        return pd.concat(frames, ignore_index=True).sort_values("filed_at").reset_index(drop=True)
