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

See ``.claude/rules/canonical-schema.md`` and ``.claude/rules/data-discipline.md``.
"""

from __future__ import annotations

import json
import os
import re
import time
import zipfile
from dataclasses import asdict, dataclass
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

    def coverage_end(self) -> pd.Timestamp | None:
        """Last filing date the bulk ingest covers (None before any ingest)."""
        return bulk_coverage_end(self._root)

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
            return pd.DataFrame(columns=INSIDER_COLUMNS)
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
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="SEC Form 4 bulk data sets (roadmap 18.13)")
    p.add_argument("--download", action="store_true", help="fetch quarterly zips not on disk")
    p.add_argument("--first-year", type=int, default=2009)
    args = p.parse_args(argv)
    if args.download:
        new = download_bulk(first_year=args.first_year)
        print(f"downloaded {len(new)} new quarter(s)")
    rep = ingest_bulk()
    print(
        f"ingested {len(rep.quarters)} quarters → {rep.rows:,} transactions over {rep.symbols:,} "
        f"symbols; coverage through {rep.coverage_end}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
