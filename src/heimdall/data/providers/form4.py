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

**Bulk path (roadmap 18.13).** SEC publishes every Form 3/4/5 as quarterly *Insider
Transactions Data Sets* (``{YYYY}q{N}_form345.zip``, 2006 →). :func:`download_bulk` fetches them
(the data-discipline rule: prefer bulk endpoints over per-symbol loops),
:func:`normalize_bulk_quarter` turns one quarter into the same canonical rows, and
:func:`ingest_bulk` writes the per-symbol caches plus a ``_bulk.json`` marker recording the
coverage. Once the marker exists, a symbol with
no cache simply has no Form 4 filings — the provider never falls back to a per-filing crawl. An
issuer is keyed by its **CIK** and mapped to its *current* ticker (EDGAR ``company_tickers.json``),
so a renamed company's history joins its current symbol; an issuer no longer listed keeps its
filing-time ticker.

**Delta path (roadmap 18.19).** The data sets are quarterly, so between releases the newest
filings live only on EDGAR. :func:`ingest_delta` walks EDGAR's **daily index** from the day after
the bulk coverage end. It fetches each Form 4 original that lists a ticker-mapped CIK, parses
the ``ownershipDocument`` embedded in the full submission text with the same transaction parser,
maps the issuer by CIK as the bulk path does, and appends per-symbol caches under
``form4/delta/`` plus a ``_delta.json`` marker. Three rules keep it honest:

- **Bulk is the authority.** Delta rows filed on or before the bulk coverage end are dropped
  whenever the bulk advances (:func:`prune_delta`), and serving reads delta rows only after it.
- **Never vouch across a gap.** :meth:`Form4Provider.coverage_end` extends past the bulk end only
  when the delta starts on the day right after it (:func:`coverage_end_with_delta`).
- **Only complete days.** Today's index (New York time) is never read, because it may still
  grow; a day is marked done only after all of its filings are stored.

See ``.claude/rules/canonical-schema.md`` and ``.claude/rules/data-discipline.md``.
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

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
_BULK_INDEX_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
)
_SEC_ROOT = "https://www.sec.gov"
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


def raw_xml_doc(primary_document: str) -> str:
    """The raw ownership XML behind a submission's ``primaryDocument``.

    EDGAR lists Form 4s as ``xslF345X06/form4.xml`` — the XSL-*rendered* HTML view. The raw
    XML is the same file name without the ``xsl…/`` directory (found in 18.13: the old crawl
    fetched the HTML, failed to parse it, and silently skipped every filing).
    """
    return (
        primary_document.split("/", 1)[1]
        if primary_document.startswith("xsl")
        else primary_document
    )


def normalize_ownership_doc(
    xml_text: str, filed_at: str, symbol: str | None = None
) -> pd.DataFrame:
    """Parse one Form 4 ``ownershipDocument`` XML into canonical transaction rows.

    Pure (no network) — the unit of the golden test. ``filed_at`` is the SEC
    submission's filing date (``YYYY-MM-DD``), supplied by the fetch layer since
    the XML itself does not carry it; it becomes the point-in-time key on every
    row. Only **non-derivative** transactions with a share amount are emitted
    (derivative option mechanics are excluded); a transaction missing its code or
    share count is skipped rather than guessed. ``symbol`` overrides the filing's
    own trading symbol (the delta path keys issuers by CIK, 18.19).
    """
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    root = ET.fromstring(xml_text)

    if symbol is None:
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

    def coverage_end(self) -> pd.Timestamp | None:
        """Last filing date the ingested Form 4 data covers (None before any ingest): the bulk
        coverage end, extended by a contiguous delta (18.19)."""
        return coverage_end_with_delta(self._root)

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
        elif bulk_marker_path(self._root).exists():
            # Bulk-ingested: every Form 4 filer in the data sets has a cache, so no cache means
            # no filings — never fall back to thousands of per-filing requests.
            df = pd.DataFrame(columns=INSIDER_COLUMNS)
        else:
            df = self._crawl(sym.ticker)
            cache.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache, index=False)
        df = self._with_delta(sym.canonical, df)
        if df.empty:
            return df
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        return df[(df["filed_at"] >= lo) & (df["filed_at"] <= hi)].reset_index(drop=True)

    def _cache_path(self, canonical: str) -> Path:
        return self._root / "form4" / f"{canonical.replace('.', '_')}.parquet"

    def _with_delta(self, canonical: str, bulk: pd.DataFrame) -> pd.DataFrame:
        """Bulk rows plus the delta rows filed **after** the bulk coverage end (18.19). Bulk is
        the authority, so a filing in both sources is served once (from the bulk)."""
        bulk_end = bulk_coverage_end(self._root)
        path = delta_dir(self._root) / f"{canonical.replace('.', '_')}.parquet"
        if bulk_end is None or not path.exists():
            return bulk
        extra = pd.read_parquet(path)
        extra = extra[extra["filed_at"] > bulk_end]
        if extra.empty:
            return bulk
        if bulk.empty:
            return extra.reset_index(drop=True)
        return pd.concat([bulk, extra], ignore_index=True)

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
            url = _ARCHIVE_DOC_URL.format(
                cik=cik, acc_nodash=accn.replace("-", ""), doc=raw_xml_doc(doc)
            )
            try:
                xml = self._get(url, as_json=False)
                frames.append(normalize_ownership_doc(xml, filed))
            except (ProviderError, ET.ParseError):
                continue  # a single malformed filing must not kill the crawl
        if not frames:
            return pd.DataFrame(columns=INSIDER_COLUMNS)
        return pd.concat(frames, ignore_index=True).sort_values("filed_at").reset_index(drop=True)


# --- bulk path: SEC Insider Transactions Data Sets (roadmap 18.13) -----------------------


def bulk_raw_dir(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "form4" / "raw"


def bulk_marker_path(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "form4" / "_bulk.json"


def bulk_coverage_end(root: Path | None = None) -> pd.Timestamp | None:
    path = bulk_marker_path(root)
    if not path.exists():
        return None
    return pd.Timestamp(json.loads(path.read_text())["coverage_end"])


def download_bulk(root: Path | None = None, first_year: int = 2009) -> list[Path]:
    """Fetch every quarterly ``form345`` zip from ``first_year`` on that is not on disk yet.

    Network path (SEC fair access: declared User-Agent, ~1 request/s). Idempotent — a zip
    already downloaded is never fetched again (raw files are immutable)."""
    out_dir = bulk_raw_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": _user_agent()}
    page = requests.get(_BULK_INDEX_URL, headers=headers, timeout=60).text
    links = sorted(set(re.findall(r'href="([^"]*form345[^"]*\.zip)"', page)))
    written: list[Path] = []
    for link in links:
        m = re.search(r"/(\d{4})q\d_form345\.zip$", link)
        if m is None or int(m.group(1)) < first_year:
            continue
        path = out_dir / link.rsplit("/", 1)[1]
        if path.exists() and path.stat().st_size > 0:
            continue
        resp = requests.get(_SEC_ROOT + link, headers=headers, timeout=300)
        if resp.status_code != 200:
            raise ProviderError(f"SEC {resp.status_code} for {link}")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(resp.content)
        tmp.rename(path)
        written.append(path)
        time.sleep(1.0)
    return written


def _read_tsv(z: zipfile.ZipFile, name: str, cols: list[str]) -> pd.DataFrame:
    with z.open(name) as fh:
        return pd.read_csv(fh, sep="\t", dtype=str, usecols=cols, keep_default_na=False)


def normalize_bulk_quarter(zip_path: Path, cik_to_ticker: dict[int, list[str]]) -> pd.DataFrame:
    """One quarter's data set → canonical rows (``INSIDER_COLUMNS``), Form 4 originals only.

    Mirrors :func:`normalize_ownership_doc`: non-derivative transactions with a code and a
    share count; the **first** reporting owner of each filing carries the relationship flags;
    ``filed_at`` is the submission's filing date. Amendments (``4/A``) and Forms 3/5 are
    excluded, as in the XML path. An issuer whose CIK has current tickers is written once per
    ticker (insider trading is issuer-level, so every share class — ``GOOGL``/``GOOG``,
    ``BRK-A``/``BRK-B`` — carries it); an unmapped issuer keeps its cleaned filing-time ticker.
    """
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    with zipfile.ZipFile(zip_path) as z:
        sub = _read_tsv(
            z,
            "SUBMISSION.tsv",
            [
                "ACCESSION_NUMBER",
                "FILING_DATE",
                "DOCUMENT_TYPE",
                "ISSUERCIK",
                "ISSUERTRADINGSYMBOL",
            ],
        )
        owners = _read_tsv(
            z,
            "REPORTINGOWNER.tsv",
            ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP"],
        )
        trans = _read_tsv(
            z,
            "NONDERIV_TRANS.tsv",
            [
                "ACCESSION_NUMBER",
                "TRANS_DATE",
                "TRANS_CODE",
                "TRANS_SHARES",
                "TRANS_PRICEPERSHARE",
                "TRANS_ACQUIRED_DISP_CD",
            ],
        )
    sub = sub[sub["DOCUMENT_TYPE"] == "4"]
    owners = owners.drop_duplicates("ACCESSION_NUMBER", keep="first")
    df = trans.merge(sub, on="ACCESSION_NUMBER").merge(owners, on="ACCESSION_NUMBER", how="left")
    df = df[(df["TRANS_CODE"] != "") & (df["TRANS_SHARES"] != "")]
    if df.empty:
        return pd.DataFrame(columns=INSIDER_COLUMNS)

    def tickers_for(row_cik: str, filed_ticker: str) -> list[str]:
        current = cik_to_ticker.get(int(row_cik)) if row_cik.strip().isdigit() else None
        cleaned = [clean_ticker(t) for t in current] if current else [clean_ticker(filed_ticker)]
        return [t for t in cleaned if t] or [""]

    lists = [
        tickers_for(c, t) for c, t in zip(df["ISSUERCIK"], df["ISSUERTRADINGSYMBOL"], strict=True)
    ]
    df = df.loc[df.index.repeat([len(x) for x in lists])].reset_index(drop=True)
    tickers = [t for x in lists for t in x]
    rel = df["RPTOWNER_RELATIONSHIP"].fillna("")
    out = pd.DataFrame(
        {
            "symbol": [f"{t}.US" if t else "" for t in tickers],
            "filed_at": pd.to_datetime(df["FILING_DATE"], format="%d-%b-%Y"),
            "txn_date": pd.to_datetime(df["TRANS_DATE"], format="%d-%b-%Y", errors="coerce"),
            "owner_cik": df["RPTOWNERCIK"].str.lstrip("0"),
            "owner_name": df["RPTOWNERNAME"],
            "is_officer": rel.str.contains("Officer"),
            "is_director": rel.str.contains("Director"),
            "is_ten_pct": rel.str.contains("TenPercentOwner"),
            "txn_code": df["TRANS_CODE"],
            "acquired_disposed": df["TRANS_ACQUIRED_DISP_CD"].replace("", None),
            "shares": pd.to_numeric(df["TRANS_SHARES"], errors="coerce"),
            "price_per_share": pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"),
            "currency": "USD",
            "provider": "form4-bulk",
            "fetched_at": fetched_at,
        }
    )
    out = out[(out["symbol"] != "") & out["shares"].notna()]
    return out[INSIDER_COLUMNS].reset_index(drop=True)


def clean_ticker(raw: str) -> str:
    """A filing's ticker in the canonical (yfinance/SEC ``company_tickers``) spelling, or ``""``.

    Class-share separators become ``-`` (``BRK/B``, ``BRK.B`` → ``BRK-B``); anything that is not
    a plausible ticker afterwards (``(N/A)``, ``NONE``, free text) is dropped rather than guessed.
    """
    t = raw.strip().upper().replace("/", "-").replace(".", "-")
    if t in {"NONE", "NA", "N-A"} or not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,9}", t):
        return ""
    return t


@dataclass
class BulkReport:
    quarters: list[str]
    coverage_end: str  # last filing date in the ingested data sets
    rows: int
    symbols: int
    ingested_at: str


def _cik_map(root: Path) -> dict[int, list[str]]:
    """CIK → every current ticker (EDGAR ``company_tickers.json``, cached by the EDGAR provider)."""
    cache = root / "edgar" / "company_tickers.json"
    if not cache.exists():
        return {}
    out: dict[int, list[str]] = {}
    for row in json.loads(cache.read_text()).values():
        out.setdefault(int(row["cik_str"]), []).append(str(row["ticker"]).upper())
    return out


def ingest_bulk(root: Path | None = None) -> BulkReport:
    """Normalize every downloaded quarter and (re)write the per-symbol caches + marker.

    Derived entirely from the immutable raw zips, so re-running is safe and deterministic.
    Symbols that fail canonical parsing (e.g. odd legacy tickers) are skipped and counted.
    """
    base = root if root is not None else data_root()
    zips = sorted(bulk_raw_dir(base).glob("*_form345.zip"))
    if not zips:
        raise FileNotFoundError(f"no form345 zips under {bulk_raw_dir(base)}; download first")
    cik_map = _cik_map(base)
    frames = [normalize_bulk_quarter(z, cik_map) for z in zips]
    allrows = pd.concat(frames, ignore_index=True)
    out_dir = base / "form4"
    out_dir.mkdir(parents=True, exist_ok=True)
    n_sym = 0
    for sym, grp in allrows.groupby("symbol"):
        try:
            canonical = parse_symbol(str(sym)).canonical
        except Exception:  # noqa: BLE001 — a malformed legacy ticker is skipped, not fatal
            continue
        path = out_dir / f"{canonical.replace('.', '_')}.parquet"
        grp.sort_values("filed_at").reset_index(drop=True).to_parquet(path, index=False)
        n_sym += 1
    report = BulkReport(
        quarters=[z.name.split("_", 1)[0] for z in zips],
        coverage_end=str(allrows["filed_at"].max().date()) if len(allrows) else "",
        rows=len(allrows),
        symbols=n_sym,
        ingested_at=datetime.now(UTC).isoformat(),
    )
    bulk_marker_path(base).write_text(json.dumps(asdict(report), indent=2) + "\n")
    prune_delta(base)  # 18.19 seam: the new quarter supersedes the delta rows it now covers
    return report


# --- delta path: EDGAR daily index since the bulk coverage end (roadmap 18.19) -------------

_DAILY_INDEX_DIR = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{q}/index.json"
_DAILY_INDEX_FILE = "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{q}/{name}"
_ARCHIVE_ROOT = "https://www.sec.gov/Archives/"
_ET = ZoneInfo("America/New_York")  # EDGAR's clock: filing dates are New York dates
# One row of ``form.YYYYMMDD.idx``: the form type ends at the first run of ≥ 2 spaces (a form
# type may hold one space, e.g. ``1-A POS``); CIK, date and path are the last three tokens.
_IDX_ROW = re.compile(
    r"^(?P<form>\S+(?: \S+)*?)\s{2,}.*?\s(?P<cik>\d+)\s+(?P<date>\d{8})\s+"
    r"(?P<file>edgar/data/\S+)\s*$"
)
_IDX_NAME = re.compile(r"form\.(\d{8})\.idx")
_OWNERSHIP = re.compile(r"<ownershipDocument>.*?</ownershipDocument>", re.S)
_RETRIES = 4
Fetch = Callable[[str], str]  # URL → body; raises FileNotFoundError when SEC has no such file


def delta_dir(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "form4" / "delta"


def delta_marker_path(root: Path | None = None) -> Path:
    return (root if root is not None else data_root()) / "form4" / "_delta.json"


def read_delta_marker(root: Path | None = None) -> dict[str, Any] | None:
    path = delta_marker_path(root)
    return dict(json.loads(path.read_text())) if path.exists() else None


def _write_marker(root: Path, marker: dict[str, Any]) -> None:
    path = delta_marker_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(marker, indent=2) + "\n")
    os.replace(tmp, path)


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def parse_daily_index(text: str) -> pd.DataFrame:
    """EDGAR ``form.YYYYMMDD.idx`` → ``[form_type, cik, date_filed, file_name]`` (headers skip)."""
    rows = [
        (m["form"], int(m["cik"]), pd.Timestamp(m["date"]), m["file"])
        for m in (_IDX_ROW.match(line) for line in text.splitlines())
        if m is not None
    ]
    return pd.DataFrame(rows, columns=["form_type", "cik", "date_filed", "file_name"])


def _accession(path: str) -> str:
    return path.rsplit("/", 1)[1].removesuffix(".txt")


def form4_filings(index: pd.DataFrame, ciks: set[int]) -> list[str]:
    """Archive paths of the Form 4 **originals** (``4``; amendments excluded, as in the bulk
    path) listing at least one CIK in ``ciks``. A filing is listed once per CIK it involves
    (issuer and each reporting owner); one path per accession is returned, in index order."""
    f4 = index[index["form_type"] == "4"]
    wanted = {_accession(p) for p in f4.loc[f4["cik"].isin(ciks), "file_name"]}
    out: list[str] = []
    seen: set[str] = set()
    for path in f4["file_name"]:
        acc = _accession(str(path))
        if acc in wanted and acc not in seen:
            seen.add(acc)
            out.append(str(path))
    return out


def archive_paths(index: pd.DataFrame) -> dict[str, list[str]]:
    """Accession → every archive path the index lists for it (one per CIK it involves)."""
    out: dict[str, list[str]] = {}
    for path in index["file_name"]:
        out.setdefault(_accession(str(path)), []).append(str(path))
    return out


def extract_ownership_xml(submission: str) -> str | None:
    """The ``ownershipDocument`` embedded in a full-submission text, or None."""
    m = _OWNERSHIP.search(submission)
    return m.group(0) if m else None


def normalize_submission(
    submission: str, filed_at: str, cik_to_ticker: dict[int, list[str]]
) -> pd.DataFrame:
    """One full-submission text → canonical rows keyed like the bulk path.

    Transactions come from :func:`normalize_ownership_doc` (one parser for every path); the
    issuer is then mapped by **CIK** to every current ticker, as :func:`normalize_bulk_quarter`
    does. Only originals (``documentType`` 4) are kept. An issuer with no current ticker is
    dropped: the delta fetches only filings listing a ticker-mapped CIK, so it cannot vouch for
    complete coverage of the others.
    """
    empty = pd.DataFrame(columns=INSIDER_COLUMNS)
    xml = extract_ownership_xml(submission)
    if xml is None:
        return empty
    root = ET.fromstring(xml)
    if (_text(root.find("./documentType")) or "") != "4":
        return empty
    cik = (_text(root.find("./issuer/issuerCik")) or "").strip()
    current = cik_to_ticker.get(int(cik)) if cik.isdigit() else None
    tickers = [t for t in (clean_ticker(x) for x in current or []) if t]
    if not tickers:
        return empty
    base = normalize_ownership_doc(xml, filed_at, symbol=f"{tickers[0]}.US")
    if base.empty:
        return empty
    out = pd.concat([base.assign(symbol=f"{t}.US") for t in tickers], ignore_index=True)
    # The bulk path stores owner CIKs without leading zeros; match it, or one insider would
    # count as two distinct buyers across the seam (``insider_cluster_buy``).
    out["owner_cik"] = out["owner_cik"].map(lambda v: v.lstrip("0") if isinstance(v, str) else v)
    out["provider"] = "form4-delta"
    return out[INSIDER_COLUMNS]


def next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def today_et() -> date:
    return datetime.now(_ET).date()


def now_et() -> datetime:
    return datetime.now(_ET)


#: EDGAR accepts submissions from 06:00 New York time on business days, so before that hour no
#: filing can carry the day's date.
_EDGAR_OPENS_HOUR = 6


def delta_coverage_end(last_index: date, now: datetime) -> date:
    """The last filing date the delta can vouch for, given the last daily index it stored.

    EDGAR dates filings on weekdays only, so every filing up to the day before the next weekday
    is known. That next weekday is vouched for too until EDGAR opens on it (06:00 New York time):
    before then no filing can carry its date. A holiday counts as a weekday, which only shortens
    the claim (missing data stays NaN, never a false zero). ``now`` is a New York datetime.
    """
    nxt = next_weekday(last_index)
    opens = datetime(nxt.year, nxt.month, nxt.day, _EDGAR_OPENS_HOUR, tzinfo=_ET)
    return nxt if now.astimezone(_ET) < opens else nxt - timedelta(days=1)


def coverage_end_with_delta(
    root: Path | None = None, now: datetime | None = None
) -> pd.Timestamp | None:
    """The bulk coverage end, extended by the delta only when the delta is contiguous with it
    (it starts the day after the bulk end) — never across a gap."""
    bulk_end = bulk_coverage_end(root)
    if bulk_end is None:
        return None
    marker = read_delta_marker(root)
    if (
        marker is None
        or marker.get("start") != (bulk_end + pd.Timedelta(days=1)).date().isoformat()
    ):
        return bulk_end
    last = marker.get("last_index") or bulk_end.date().isoformat()
    end = delta_coverage_end(date.fromisoformat(last), now or now_et())
    return max(bulk_end, pd.Timestamp(end))


def prune_delta(root: Path | None = None) -> None:
    """The seam rule: bulk is the authority. Drop delta rows filed on/before the bulk coverage
    end, and re-anchor the marker on the day after it (only when that keeps it contiguous)."""
    base = root if root is not None else data_root()
    bulk_end = bulk_coverage_end(base)
    if bulk_end is None:
        return
    ddir = delta_dir(base)
    for path in sorted(ddir.glob("*.parquet")) if ddir.exists() else []:
        df = pd.read_parquet(path)
        keep = df[df["filed_at"] > bulk_end]
        if keep.empty:
            path.unlink()
        elif len(keep) < len(df):
            _write_parquet(keep.reset_index(drop=True), path)
    marker = read_delta_marker(base)
    if marker is None:
        return
    start = (bulk_end + pd.Timedelta(days=1)).date()
    if date.fromisoformat(str(marker["start"])) <= start:
        last = str(marker.get("last_index") or "")
        if last and date.fromisoformat(last) <= bulk_end.date():
            last = ""
        _write_marker(base, {**marker, "start": start.isoformat(), "last_index": last})


def _sec_fetcher(min_interval_s: float = 0.12) -> Fetch:
    """A throttled SEC GET (~8 req/s, under the 10 req/s fair-access limit) with retries on
    429/5xx. 403/404 mean "no such file" on EDGAR's archive and raise FileNotFoundError."""
    session = requests.Session()
    session.headers["User-Agent"] = _user_agent()
    last = [0.0]

    def get(url: str) -> str:
        for attempt in range(_RETRIES):
            wait = min_interval_s - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                resp = session.get(url, timeout=60)
            except requests.RequestException:
                time.sleep(2.0 * 2**attempt)
                continue
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 404):
                raise FileNotFoundError(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2.0 * 2**attempt)
                continue
            raise ProviderError(f"SEC {resp.status_code} for {url}")
        raise ProviderError(f"SEC unreachable after {_RETRIES} attempts: {url}")

    return get


#: A new quarter's daily-index directory appears with its first index, so it may be missing for
#: this many days into the quarter; any other missing directory is an error.
_NEW_QUARTER_GRACE_DAYS = 7


def _index_days(get: Fetch, after: date, until: date) -> list[tuple[date, str]]:
    """Daily ``form`` indexes dated in (``after``, ``until``], oldest first.

    SEC answers 403 both for a missing path and for a request without a proper User-Agent, so a
    missing quarter directory is accepted only for a quarter that began in the last few days;
    otherwise it raises instead of silently reporting "no filings"."""
    out: list[tuple[date, str]] = []
    year, q = after.year, (after.month - 1) // 3 + 1
    while (year, q) <= (until.year, (until.month - 1) // 3 + 1):
        try:
            listing = json.loads(get(_DAILY_INDEX_DIR.format(year=year, q=q)))
        except FileNotFoundError:
            quarter_start = date(year, 3 * q - 2, 1)
            if (until - quarter_start).days > _NEW_QUARTER_GRACE_DAYS:
                raise ProviderError(
                    f"EDGAR daily index {year} QTR{q} unavailable (403/404); "
                    "check SEC_EDGAR_USER_AGENT"
                ) from None
            listing = {"directory": {"item": []}}
        for item in listing["directory"]["item"]:
            m = _IDX_NAME.fullmatch(str(item["name"]))
            if m is None:
                continue
            day = datetime.strptime(m.group(1), "%Y%m%d").date()
            if after < day <= until:
                url = _DAILY_INDEX_FILE.format(year=year, q=q, name=item["name"])
                out.append((day, url))
        year, q = (year + 1, 1) if q == 4 else (year, q + 1)
    return sorted(out)


def _store_day(base: Path, day: date, rows: pd.DataFrame) -> int:
    """Append one day's rows to the per-symbol delta caches (idempotent: the day's rows are
    replaced, so a re-run after a crash never double counts). Returns the rows written."""
    if rows.empty:
        return 0
    stamp = pd.Timestamp(day)
    written = 0
    for sym, grp in rows.groupby("symbol"):
        try:
            canonical = parse_symbol(str(sym)).canonical
        except Exception:  # noqa: BLE001 — a malformed ticker is skipped, as in the bulk ingest
            continue
        path = delta_dir(base) / f"{canonical.replace('.', '_')}.parquet"
        old = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=INSIDER_COLUMNS)
        old = old[old["filed_at"] != stamp] if not old.empty else old
        new = grp if old.empty else pd.concat([old, grp], ignore_index=True)
        _write_parquet(new.sort_values("filed_at").reset_index(drop=True), path)
        written += len(grp)
    return written


@dataclass
class DeltaReport:
    start: str  # first filing date the delta covers (the day after the bulk coverage end)
    last_index: str  # last daily index stored ("" = none yet)
    days: int  # daily indexes processed by this run
    filings: int  # Form 4 submissions fetched by this run
    rows: int  # canonical rows written by this run
    unparsed: int  # submissions without a parseable ownership document (skipped, counted)
    withdrawn: int  # listed in the index but gone from the archive under every CIK (skipped)
    ingested_at: str


def ingest_delta(
    root: Path | None = None, until: date | None = None, fetch: Fetch | None = None
) -> DeltaReport:
    """Store every Form 4 original filed after the bulk coverage end, day by day.

    Reads the daily indexes dated after the last stored day up to ``until`` (default: yesterday
    in New York, since today's index may still grow). A day is marked done only once all of its
    filings are stored; a fetch failure stops the run with every earlier day intact. Raw
    indexes and submissions are kept per day under ``form4/delta/raw/`` (data discipline).

    A filing the index lists but the archive no longer has under **any** of its CIK paths was
    removed by SEC after dissemination (seen 2026-08-06). The bulk data sets are built from the
    archive and are not expected to carry it either, so it is skipped and counted as
    ``withdrawn`` (and listed in that day's raw zip), never retried forever.
    """
    base = root if root is not None else data_root()
    bulk_end = bulk_coverage_end(base)
    if bulk_end is None:
        raise FileNotFoundError("no bulk Form 4 coverage yet; run `--download` first")
    prune_delta(base)
    start = (bulk_end + pd.Timedelta(days=1)).date()
    marker = read_delta_marker(base)
    if marker is not None and date.fromisoformat(str(marker["start"])) != start:
        # Not contiguous with the bulk (cannot happen while the bulk only advances): rebuild.
        for path in delta_dir(base).glob("*.parquet"):
            path.unlink()
        marker = None
    last = str(marker.get("last_index") or "") if marker else ""
    after = date.fromisoformat(last) if last else bulk_end.date()
    stop = until if until is not None else today_et() - timedelta(days=1)
    get = fetch if fetch is not None else _sec_fetcher()
    cik_map = _cik_map(base)
    ciks = set(cik_map)

    days = filings = rows = unparsed = withdrawn = 0
    for day, url in _index_days(get, after, stop):
        index_text = get(url)
        index = parse_daily_index(index_text)
        paths = archive_paths(index)
        raw: dict[str, str] = {url.rsplit("/", 1)[1]: index_text}
        frames: list[pd.DataFrame] = []
        gone: list[str] = []
        for filing in form4_filings(index, ciks):
            acc = _accession(filing)
            text = None
            for candidate in paths[acc]:
                try:
                    text = get(_ARCHIVE_ROOT + candidate)
                    break
                except FileNotFoundError:
                    continue
            if text is None:
                gone.append(acc)
                withdrawn += 1
                continue
            raw[f"{acc}.txt"] = text
            filings += 1
            try:
                frames.append(normalize_submission(text, day.isoformat(), cik_map))
            except (ET.ParseError, ValueError):
                unparsed += 1  # one malformed filing must not stop the day
        raw_zip = delta_dir(base) / "raw" / str(day.year) / f"{day:%Y%m%d}.zip"
        raw_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(raw_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for name, body in raw.items():
                z.writestr(name, body)
            if gone:
                z.writestr("withdrawn.txt", "\n".join(gone) + "\n")
        found = [f for f in frames if not f.empty]
        day_rows = pd.concat(found, ignore_index=True) if found else pd.DataFrame()
        rows += _store_day(base, day, day_rows)
        days += 1
        last = day.isoformat()
        _write_marker(
            base,
            {
                "start": start.isoformat(),
                "last_index": last,
                "ingested_at": datetime.now(UTC).isoformat(),
            },
        )
    if marker is None and days == 0:
        _write_marker(
            base,
            {
                "start": start.isoformat(),
                "last_index": "",
                "ingested_at": datetime.now(UTC).isoformat(),
            },
        )
    return DeltaReport(
        start=start.isoformat(),
        last_index=last,
        days=days,
        filings=filings,
        rows=rows,
        unparsed=unparsed,
        withdrawn=withdrawn,
        ingested_at=datetime.now(UTC).isoformat(),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from dotenv import load_dotenv

    load_dotenv()  # SEC_EDGAR_USER_AGENT: SEC refuses requests without a descriptive UA
    p = argparse.ArgumentParser(description="SEC Form 4 bulk data sets (18.13) + daily delta")
    p.add_argument("--download", action="store_true", help="fetch quarterly zips not on disk")
    p.add_argument("--first-year", type=int, default=2009)
    p.add_argument(
        "--delta", action="store_true", help="store filings after the bulk coverage end (18.19)"
    )
    p.add_argument("--until", default=None, help="last index day for --delta (YYYY-MM-DD)")
    args = p.parse_args(argv)
    if args.delta:
        until = date.fromisoformat(args.until) if args.until else None
        drep = ingest_delta(until=until)
        print(
            f"delta: {drep.days} day(s), {drep.filings:,} filings → {drep.rows:,} rows "
            f"({drep.unparsed} unparsed, {drep.withdrawn} withdrawn); "
            f"stored through {drep.last_index or 'nothing yet'}; "
            f"coverage end {coverage_end_with_delta()}"
        )
        return 0
    if args.download:
        new = download_bulk(first_year=args.first_year)
        print(f"downloaded {len(new)} new quarter(s)")
        if not new and bulk_marker_path().exists():
            print(f"up to date — coverage through {bulk_coverage_end()} (nothing to ingest)")
            return 0
    rep = ingest_bulk()
    print(
        f"ingested {len(rep.quarters)} quarters → {rep.rows:,} transactions over {rep.symbols:,} "
        f"symbols; coverage through {rep.coverage_end}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
