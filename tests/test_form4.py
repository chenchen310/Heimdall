"""Golden test: SEC Form 4 ownershipDocument XML → canonical insider rows (no network).

The fixture is a hand-built ``ownershipDocument`` matching the real (namespace-free)
Form 4 schema, exercising an officer open-market **purchase** and a **sale**, plus a
derivative row and an amount-less row that must both be dropped by
:func:`normalize_ownership_doc`.
"""

from __future__ import annotations

import pandas as pd

from heimdall.data.providers.form4 import (
    INSIDER_COLUMNS,
    normalize_ownership_doc,
)

_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2023-05-10</periodOfReport>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001214128</rptOwnerCik>
      <rptOwnerName>DOE JANE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle>CFO</officerTitle>
      <isTenPercentOwner>0</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2023-05-08</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2023-05-09</value></transactionDate>
      <transactionCoding>
        <transactionCode>S</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>400</value></transactionShares>
        <transactionPricePerShare><value>155.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2023-05-09</value></transactionDate>
      <transactionCoding>
        <transactionCode>M</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>9999</value></transactionShares>
      </transactionAmounts>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""


def test_normalize_ownership_doc_golden() -> None:
    df = normalize_ownership_doc(_XML, "2023-05-10")

    assert list(df.columns) == INSIDER_COLUMNS
    # Two non-derivative transactions with amounts survive; the amount-less ``M``
    # and the derivative row are both dropped.
    assert len(df) == 2

    buy = df[df["txn_code"] == "P"].iloc[0]
    assert buy["symbol"] == "AAPL.US"
    assert buy["filed_at"] == pd.Timestamp("2023-05-10")  # keyed on filing, not txn date
    assert buy["txn_date"] == pd.Timestamp("2023-05-08")
    assert bool(buy["is_officer"]) is True
    assert bool(buy["is_director"]) is False
    assert buy["acquired_disposed"] == "A"
    assert buy["shares"] == 1000.0
    assert buy["price_per_share"] == 150.0
    assert buy["currency"] == "USD"
    assert buy["provider"] == "form4"

    sell = df[df["txn_code"] == "S"].iloc[0]
    assert sell["shares"] == 400.0
    assert sell["price_per_share"] == 155.0
    assert sell["acquired_disposed"] == "D"


def test_normalize_ownership_doc_no_trading_symbol_is_empty() -> None:
    xml = (
        "<ownershipDocument><issuer><issuerCik>0000320193</issuerCik></issuer></ownershipDocument>"
    )
    out = normalize_ownership_doc(xml, "2023-05-10")
    assert out.empty
    assert list(out.columns) == INSIDER_COLUMNS


# --- 18.13: the bulk SEC Insider Transactions Data Sets ------------------------------------

import json  # noqa: E402
import zipfile  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from heimdall.data.providers import form4 as f4  # noqa: E402


def _tsv(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(r) for r in rows) + "\n"


def _quarter_zip(path: Path) -> Path:
    sub = _tsv(
        [
            [
                "ACCESSION_NUMBER",
                "FILING_DATE",
                "PERIOD_OF_REPORT",
                "DOCUMENT_TYPE",
                "ISSUERCIK",
                "ISSUERNAME",
                "ISSUERTRADINGSYMBOL",
            ],
            ["a1", "15-MAY-2023", "12-MAY-2023", "4", "0000000001", "Alpha", "OLDA"],
            ["a2", "16-MAY-2023", "12-MAY-2023", "4/A", "0000000001", "Alpha", "OLDA"],  # amendment
            ["a3", "17-MAY-2023", "12-MAY-2023", "3", "0000000001", "Alpha", "OLDA"],  # Form 3
            ["a4", "18-MAY-2023", "12-MAY-2023", "4", "0000000099", "Gone", "BRK/B"],  # unmapped
            ["a5", "19-MAY-2023", "12-MAY-2023", "4", "0000000098", "Junk", "(N/A)"],  # junk
        ]
    )
    owners = _tsv(
        [
            ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP"],
            ["a1", "0000000500", "FIRST OWNER", "Director,Officer"],
            ["a1", "0000000501", "SECOND OWNER", "TenPercentOwner"],  # not the first: ignored
            ["a2", "0000000500", "FIRST OWNER", "Director"],
            ["a4", "0000000600", "FUND", "TenPercentOwnerOther"],
            ["a5", "0000000700", "X", "Officer"],
        ]
    )
    trans = _tsv(
        [
            [
                "ACCESSION_NUMBER",
                "TRANS_DATE",
                "TRANS_CODE",
                "TRANS_SHARES",
                "TRANS_PRICEPERSHARE",
                "TRANS_ACQUIRED_DISP_CD",
            ],
            ["a1", "12-MAY-2023", "P", "100", "10.5", "A"],
            ["a1", "12-MAY-2023", "", "5", "1", "A"],  # no code: dropped
            ["a2", "12-MAY-2023", "S", "7", "11", "D"],
            ["a4", "11-MAY-2023", "S", "50", "300", "D"],
            ["a5", "11-MAY-2023", "P", "1", "1", "A"],
        ]
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("SUBMISSION.tsv", sub)
        z.writestr("REPORTINGOWNER.tsv", owners)
        z.writestr("NONDERIV_TRANS.tsv", trans)
    return path


def test_normalize_bulk_quarter_golden(tmp_path: Path) -> None:
    df = f4.normalize_bulk_quarter(
        _quarter_zip(tmp_path / "2023q2_form345.zip"), {1: ["NEWA", "NEWA-B"]}
    )
    assert list(df.columns) == INSIDER_COLUMNS
    # a1's one valid trade, written under both current tickers of CIK 1; a4 under BRK-B.
    assert sorted(df["symbol"]) == ["BRK-B.US", "NEWA-B.US", "NEWA.US"]
    alpha = df[df["symbol"] == "NEWA.US"].iloc[0]
    assert alpha["filed_at"] == pd.Timestamp("2023-05-15")  # the filing date, not the trade
    assert alpha["txn_date"] == pd.Timestamp("2023-05-12")
    assert alpha["owner_cik"] == "500" and bool(alpha["is_director"]) and bool(alpha["is_officer"])
    assert not bool(alpha["is_ten_pct"])  # the second owner's flags never apply
    assert alpha["txn_code"] == "P" and alpha["shares"] == 100 and alpha["price_per_share"] == 10.5
    fund = df[df["symbol"] == "BRK-B.US"].iloc[0]
    assert bool(fund["is_ten_pct"]) and not bool(fund["is_director"])


def test_clean_ticker() -> None:
    assert f4.clean_ticker("brk/b") == "BRK-B"
    assert f4.clean_ticker("BRK.A") == "BRK-A"
    assert f4.clean_ticker("(N/A)") == "" and f4.clean_ticker("NONE") == ""
    assert f4.clean_ticker("free text here") == ""


def test_raw_xml_doc_strips_the_xsl_rendering_dir() -> None:
    assert f4.raw_xml_doc("xslF345X06/form4.xml") == "form4.xml"
    assert f4.raw_xml_doc("wf-form4_1.xml") == "wf-form4_1.xml"


def test_ingest_writes_caches_marker_and_stops_crawling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f4.bulk_raw_dir(tmp_path).mkdir(parents=True)
    _quarter_zip(f4.bulk_raw_dir(tmp_path) / "2023q2_form345.zip")
    (tmp_path / "edgar").mkdir()
    (tmp_path / "edgar" / "company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 1, "ticker": "NEWA", "title": "Alpha"}})
    )
    rep = f4.ingest_bulk(tmp_path)
    assert rep.quarters == ["2023q2"] and rep.coverage_end == "2023-05-18" and rep.symbols == 2
    prov = f4.Form4Provider(root=tmp_path)
    assert prov.coverage_end() == pd.Timestamp("2023-05-18")
    got = prov.get_insider_transactions("NEWA.US", date(2023, 1, 1), date(2023, 12, 31))
    assert len(got) == 1 and got["txn_code"].iloc[0] == "P"

    def boom(_: str) -> pd.DataFrame:
        raise AssertionError("must not crawl once the bulk data sets are ingested")

    monkeypatch.setattr(prov, "_crawl", boom)
    assert prov.get_insider_transactions("ZZZ.US", date(2023, 1, 1), date(2023, 12, 31)).empty


def test_insider_features_are_nan_past_coverage() -> None:
    from heimdall.research.dataset import _insider_features

    rows = pd.DataFrame(
        {
            "filed_at": [pd.Timestamp("2023-05-15")],
            "is_officer": [True],
            "is_director": [False],
            "txn_code": ["P"],
            "owner_cik": ["1"],
            "shares": [100.0],
            "price_per_share": [10.0],
        }
    )
    end = pd.Timestamp("2023-06-30")
    inside = _insider_features(rows, pd.Timestamp("2023-06-30"), 1e6, end)
    assert inside["insider_net_buy_90d"] == pytest.approx(1000 / 1e6)
    after = _insider_features(rows, pd.Timestamp("2023-07-31"), 1e6, end)
    assert all(pd.isna(v) for v in after.values())


def test_cli_download_skips_ingest_when_nothing_is_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    f4.bulk_marker_path(tmp_path).parent.mkdir(parents=True)
    f4.bulk_marker_path(tmp_path).write_text(json.dumps({"coverage_end": "2026-06-30"}))
    monkeypatch.setattr(f4, "download_bulk", lambda **k: [])

    def no_ingest(*a: object, **k: object) -> None:
        raise AssertionError("nothing new: must not re-ingest")

    monkeypatch.setattr(f4, "ingest_bulk", no_ingest)
    assert f4.main(["--download"]) == 0


# --- 18.19: the daily delta (EDGAR daily index + full submission text) ---------------------

from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from heimdall.data.base import ProviderError  # noqa: E402

# Trimmed from the real ``form.20260929.idx``: a two-word form type, a filing listed under two
# owner CIKs, the issuer + owner rows of one filing, an amendment, a name ending in a digit.
_IDX = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Last Data Received:    Sep 29, 2026
Comments:              webmaster@sec.gov
Anonymous FTP:         ftp://ftp.sec.gov/edgar/

Form Type   Company Name                                                  CIK
      Date Filed  File Name
---------------------------------------------------------------------------------------------
1-A POS          Wellstreet Realty, Inc.                                       2041878     20260929    edgar/data/2041878/0001493152-26-044913.txt
4                3D Investment Partners Pte. Ltd.                              1841538     20260929    edgar/data/1841538/0001213900-26-104739.txt
4                3D Opportunity Master Fund                                    1841536     20260929    edgar/data/1841536/0001213900-26-104739.txt
4                ABEONA THERAPEUTICS INC.                                      318306      20260929    edgar/data/318306/0001493152-26-044971.txt
4                Vasanthavada Madhav                                           2106295     20260929    edgar/data/2106295/0001493152-26-044971.txt
4/A              ABEONA THERAPEUTICS INC.                                      318306      20260929    edgar/data/318306/0001493152-26-044999.txt
4                FUND 2                                                        12345678    20260929    edgar/data/12345678/0000000000-26-000001.txt
"""  # noqa: E501

# Trimmed from the real submission 0001493152-26-044971.txt (header + the ownership XML).
_SUBMISSION = """<SEC-DOCUMENT>0001493152-26-044971.txt : 20260929
<SEC-HEADER>0001493152-26-044971.hdr.sgml : 20260929
<ACCEPTANCE-DATETIME>20260929214740
ACCESSION NUMBER:\t\t0001493152-26-044971
CONFORMED SUBMISSION TYPE:\t4
FILED AS OF DATE:\t\t20260929
</SEC-HEADER>
<DOCUMENT>
<TYPE>4
<SEQUENCE>1
<FILENAME>ownership.xml
<TEXT>
<XML>
<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2026-09-29</periodOfReport>
    <issuer>
        <issuerCik>0000318306</issuerCik>
        <issuerName>ABEONA THERAPEUTICS INC.</issuerName>
        <issuerTradingSymbol>ABEO</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0002106295</rptOwnerCik>
            <rptOwnerName>Vasanthavada Madhav</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector>
            <isOfficer>1</isOfficer>
            <isTenPercentOwner>0</isTenPercentOwner>
            <isOther>0</isOther>
            <officerTitle>Chief Commercial Officer</officerTitle>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-09-29</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>S</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>4902</value></transactionShares>
                <transactionPricePerShare><value>5.1556</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>
"""

_ABEO_PATH = "edgar/data/318306/0001493152-26-044971.txt"


def test_parse_daily_index_golden() -> None:
    idx = f4.parse_daily_index(_IDX)
    assert list(idx.columns) == ["form_type", "cik", "date_filed", "file_name"]
    assert len(idx) == 7  # header lines never match
    assert idx["form_type"].tolist() == ["1-A POS", "4", "4", "4", "4", "4/A", "4"]
    assert idx["cik"].tolist()[-1] == 12345678  # a company name ending in a digit
    assert (idx["date_filed"] == pd.Timestamp("2026-09-29")).all()


def test_form4_filings_dedupes_and_skips_amendments() -> None:
    idx = f4.parse_daily_index(_IDX)
    # Listed under the issuer and the owner: fetched once. The 4/A is never fetched.
    assert f4.form4_filings(idx, {318306}) == [_ABEO_PATH]
    assert f4.form4_filings(idx, {2106295, 318306}) == [_ABEO_PATH]
    assert f4.form4_filings(idx, {1841536}) == ["edgar/data/1841538/0001213900-26-104739.txt"]
    assert f4.form4_filings(idx, {999}) == []


def test_normalize_submission_keys_issuers_like_the_bulk_path() -> None:
    xml = f4.extract_ownership_xml(_SUBMISSION)
    assert xml is not None and xml.startswith("<ownershipDocument>")
    df = f4.normalize_submission(_SUBMISSION, "2026-09-29", {318306: ["ABEO"]})
    assert list(df.columns) == INSIDER_COLUMNS
    row = df.iloc[0]
    assert len(df) == 1 and row["symbol"] == "ABEO.US"
    assert row["filed_at"] == pd.Timestamp("2026-09-29")
    assert row["txn_code"] == "S" and row["shares"] == 4902.0
    assert row["price_per_share"] == 5.1556 and row["acquired_disposed"] == "D"
    assert bool(row["is_officer"]) and not bool(row["is_director"])
    assert row["owner_cik"] == "2106295"  # leading zeros stripped, exactly as the bulk path
    assert row["provider"] == "form4-delta"
    # The XML path parses the same transaction (one parser for every path).
    via_xml = normalize_ownership_doc(xml, "2026-09-29")
    assert via_xml[["txn_code", "shares", "price_per_share"]].equals(
        df[["txn_code", "shares", "price_per_share"]]
    )
    # Every current ticker of the issuer's CIK carries it; an unmapped issuer yields nothing.
    two = f4.normalize_submission(_SUBMISSION, "2026-09-29", {318306: ["ABEO", "ABEO.W"]})
    assert sorted(two["symbol"]) == ["ABEO-W.US", "ABEO.US"]
    assert f4.normalize_submission(_SUBMISSION, "2026-09-29", {1: ["X"]}).empty
    amended = _SUBMISSION.replace("<documentType>4<", "<documentType>4/A<")
    assert f4.normalize_submission(amended, "2026-09-29", {318306: ["ABEO"]}).empty
    assert f4.extract_ownership_xml("<SEC-DOCUMENT>no xml</SEC-DOCUMENT>") is None


def _ny(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00").replace(
        tzinfo=ZoneInfo("America/New_York")
    )


def test_delta_coverage_end_rule() -> None:
    fri = date(2026, 9, 25)
    # Weekend: no filing can carry a weekend date; Monday is vouched for until EDGAR opens on it.
    assert f4.delta_coverage_end(fri, _ny("2026-09-26")) == date(2026, 9, 28)
    assert f4.delta_coverage_end(fri, _ny("2026-09-27", 20)) == date(2026, 9, 28)  # Mon 08:00 TW
    assert f4.delta_coverage_end(fri, _ny("2026-09-28", 5)) == date(2026, 9, 28)  # before 06:00
    assert f4.delta_coverage_end(fri, _ny("2026-09-28", 6)) == date(2026, 9, 27)  # EDGAR open
    assert f4.delta_coverage_end(fri, _ny("2026-10-05")) == date(2026, 9, 27)  # a stale delta
    wed = date(2026, 9, 30)
    assert f4.delta_coverage_end(wed, _ny("2026-10-01", 3)) == date(2026, 10, 1)  # TW afternoon
    assert f4.delta_coverage_end(wed, _ny("2026-10-01", 9)) == date(2026, 9, 30)
    # A Taipei clock is converted: Thu 2026-10-01 15:00 in Taipei is 03:00 in New York.
    taipei = datetime(2026, 10, 1, 15, tzinfo=ZoneInfo("Asia/Taipei"))
    assert f4.delta_coverage_end(wed, taipei) == date(2026, 10, 1)


def _bulk_marker(root: Path, end: str) -> None:
    f4.bulk_marker_path(root).parent.mkdir(parents=True, exist_ok=True)
    f4.bulk_marker_path(root).write_text(json.dumps({"coverage_end": end}))


def _delta_marker(root: Path, start: str, last: str) -> None:
    f4.delta_marker_path(root).write_text(json.dumps({"start": start, "last_index": last}))


def test_coverage_extends_only_with_a_contiguous_delta(tmp_path: Path) -> None:
    _bulk_marker(tmp_path, "2026-06-30")
    sun = _ny("2026-09-27")
    assert f4.coverage_end_with_delta(tmp_path, now=sun) == pd.Timestamp("2026-06-30")
    _delta_marker(tmp_path, "2026-07-01", "2026-09-25")
    assert f4.coverage_end_with_delta(tmp_path, now=sun) == pd.Timestamp("2026-09-28")
    _delta_marker(tmp_path, "2026-07-02", "2026-09-25")  # a one-day gap after the bulk end
    assert f4.coverage_end_with_delta(tmp_path, now=sun) == pd.Timestamp("2026-06-30")


def _row(symbol: str, filed: str, code: str = "P", cik: str = "500") -> dict[str, object]:
    return {
        "symbol": symbol,
        "filed_at": pd.Timestamp(filed),
        "txn_date": pd.Timestamp(filed),
        "owner_cik": cik,
        "owner_name": "OWNER",
        "is_officer": True,
        "is_director": False,
        "is_ten_pct": False,
        "txn_code": code,
        "acquired_disposed": "A",
        "shares": 100.0,
        "price_per_share": 10.0,
        "currency": "USD",
        "provider": "x",
        "fetched_at": pd.Timestamp("2026-10-01"),
    }


def test_seam_bulk_is_the_authority(tmp_path: Path) -> None:
    # The delta stored July 1 and October 1; then the Q3 bulk arrives covering through Sept 30
    # and carries the same July 1 filing.
    _bulk_marker(tmp_path, "2026-06-30")
    _delta_marker(tmp_path, "2026-07-01", "2026-10-01")
    delta = f4.delta_dir(tmp_path)
    delta.mkdir(parents=True)
    pd.DataFrame([_row("ABEO.US", "2026-07-01"), _row("ABEO.US", "2026-10-01")]).to_parquet(
        delta / "ABEO_US.parquet", index=False
    )
    pd.DataFrame([_row("ABEO.US", "2026-07-01")]).to_parquet(
        tmp_path / "form4" / "ABEO_US.parquet", index=False
    )
    prov = f4.Form4Provider(root=tmp_path)
    span = (date(2026, 1, 1), date(2026, 12, 31))

    _bulk_marker(tmp_path, "2026-09-30")
    # Even before the prune, serving reads delta rows only after the bulk end: one row per filing.
    served = prov.get_insider_transactions("ABEO.US", *span)
    assert sorted(served["filed_at"].dt.strftime("%m-%d")) == ["07-01", "10-01"]

    f4.prune_delta(tmp_path)
    kept = pd.read_parquet(delta / "ABEO_US.parquet")
    assert kept["filed_at"].tolist() == [pd.Timestamp("2026-10-01")]
    marker = f4.read_delta_marker(tmp_path)
    assert marker is not None and marker["start"] == "2026-10-01"
    assert marker["last_index"] == "2026-10-01"
    assert len(prov.get_insider_transactions("ABEO.US", *span)) == 2


def test_delta_rows_after_as_of_never_move_a_feature(tmp_path: Path) -> None:
    from heimdall.research.dataset import _insider_features

    rows = pd.DataFrame([_row("ABEO.US", "2026-08-03"), _row("ABEO.US", "2026-09-29", cik="9")])
    as_of = pd.Timestamp("2026-09-15")
    end = pd.Timestamp("2026-09-30")
    with_future = _insider_features(rows, as_of, 1e6, end)
    without = _insider_features(rows[rows["filed_at"] <= as_of], as_of, 1e6, end)
    assert with_future == without
    assert with_future["insider_net_buy_90d"] == pytest.approx(1000 / 1e6)


def _fake_sec(pages: dict[str, str], calls: list[str], fail: str | None = None) -> f4.Fetch:
    def get(url: str) -> str:
        calls.append(url)
        if url == fail:
            raise ProviderError("SEC 500")
        if url not in pages:
            raise FileNotFoundError(url)
        return pages[url]

    return get


def _sec_pages() -> dict[str, str]:
    base = "https://www.sec.gov/Archives/edgar/daily-index/2026/"
    listing = {
        "directory": {
            "item": [
                {"name": "form.20260701.idx"},
                {"name": "form.20260702.idx"},
                {"name": "master.20260701.idx"},
            ]
        }
    }
    day1 = _IDX.replace("20260929", "20260701")
    day2 = "\n".join(line for line in day1.splitlines() if not line.startswith("4 "))
    return {
        base + "QTR2/index.json": json.dumps(
            {"directory": {"item": [{"name": "form.20260630.idx"}]}}
        ),
        base + "QTR3/index.json": json.dumps(listing),
        base + "QTR3/form.20260701.idx": day1,
        base + "QTR3/form.20260702.idx": day2,
        "https://www.sec.gov/Archives/" + _ABEO_PATH.replace("20260929", "20260701"): _SUBMISSION,
    }


def _seed(root: Path) -> None:
    _bulk_marker(root, "2026-06-30")
    (root / "edgar").mkdir()
    (root / "edgar" / "company_tickers.json").write_text(
        json.dumps({"0": {"cik_str": 318306, "ticker": "ABEO", "title": "Abeona"}})
    )


def test_ingest_delta_end_to_end_and_resume(tmp_path: Path) -> None:
    _seed(tmp_path)
    calls: list[str] = []
    get = _fake_sec(_sec_pages(), calls)
    rep = f4.ingest_delta(tmp_path, until=date(2026, 7, 2), fetch=get)
    assert (rep.start, rep.last_index, rep.days, rep.filings, rep.rows) == (
        "2026-07-01",
        "2026-07-02",
        2,
        1,
        1,
    )
    stored = pd.read_parquet(f4.delta_dir(tmp_path) / "ABEO_US.parquet")
    assert stored["filed_at"].tolist() == [pd.Timestamp("2026-07-01")]  # the index day, PIT key
    with zipfile.ZipFile(f4.delta_dir(tmp_path) / "raw" / "2026" / "20260701.zip") as z:
        assert sorted(z.namelist()) == ["0001493152-26-044971.txt", "form.20260701.idx"]

    prov = f4.Form4Provider(root=tmp_path)
    got = prov.get_insider_transactions("ABEO.US", date(2026, 1, 1), date(2026, 12, 31))
    assert len(got) == 1 and got["provider"].iloc[0] == "form4-delta"  # no bulk cache: delta only
    assert f4.coverage_end_with_delta(tmp_path, now=_ny("2026-07-02", 23)) == pd.Timestamp(
        "2026-07-03"
    )
    assert f4.coverage_end_with_delta(tmp_path, now=_ny("2026-07-06")) == pd.Timestamp("2026-07-02")

    calls.clear()  # a re-run fetches only the listings: stored days are never fetched again
    again = f4.ingest_delta(tmp_path, until=date(2026, 7, 2), fetch=get)
    assert again.days == 0 and again.last_index == "2026-07-02"
    assert all(u.endswith("index.json") for u in calls)


def test_ingest_delta_failure_keeps_earlier_days(tmp_path: Path) -> None:
    _seed(tmp_path)
    pages = _sec_pages()
    day2 = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR3/form.20260702.idx"
    with pytest.raises(ProviderError):
        f4.ingest_delta(tmp_path, until=date(2026, 7, 2), fetch=_fake_sec(pages, [], fail=day2))
    marker = f4.read_delta_marker(tmp_path)
    assert marker is not None and marker["last_index"] == "2026-07-01"
    assert f4.coverage_end_with_delta(tmp_path, now=_ny("2026-07-06")) == pd.Timestamp("2026-07-01")


def test_ingest_delta_refuses_without_bulk(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        f4.ingest_delta(tmp_path, until=date(2026, 7, 2), fetch=_fake_sec({}, []))


def test_a_missing_old_quarter_listing_is_an_error_not_silence(tmp_path: Path) -> None:
    # SEC answers 403 to a request without a User-Agent: that must not read as "no filings".
    _seed(tmp_path)
    with pytest.raises(ProviderError, match="SEC_EDGAR_USER_AGENT"):
        f4.ingest_delta(tmp_path, until=date(2026, 9, 29), fetch=_fake_sec({}, []))
    # A quarter that began days ago may not have a directory yet: that is fine.
    pages = _sec_pages()
    rep = f4.ingest_delta(tmp_path, until=date(2026, 7, 2), fetch=_fake_sec(pages, []))
    assert rep.days == 2
    later = f4.ingest_delta(tmp_path, until=date(2026, 7, 5), fetch=_fake_sec(pages, []))
    assert later.days == 0


def test_a_filing_gone_from_the_archive_is_tried_under_every_cik_then_skipped(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    pages = _sec_pages()
    issuer_path = "https://www.sec.gov/Archives/" + _ABEO_PATH
    owner_path = "https://www.sec.gov/Archives/edgar/data/2106295/0001493152-26-044971.txt"
    # The issuer's path is gone but the owner's still serves it: the filing is stored.
    pages[owner_path] = pages.pop(issuer_path)
    calls: list[str] = []
    rep = f4.ingest_delta(tmp_path, until=date(2026, 7, 1), fetch=_fake_sec(pages, calls))
    assert (rep.filings, rep.rows, rep.withdrawn) == (1, 1, 0)
    assert calls.count(issuer_path) == 1 and calls.count(owner_path) == 1

    # Gone under every CIK (SEC removed it after dissemination): skipped, counted, day done.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _seed(fresh)
    del pages[owner_path]
    rep2 = f4.ingest_delta(fresh, until=date(2026, 7, 1), fetch=_fake_sec(pages, []))
    assert (rep2.days, rep2.filings, rep2.withdrawn, rep2.last_index) == (1, 0, 1, "2026-07-01")
    with zipfile.ZipFile(f4.delta_dir(fresh) / "raw" / "2026" / "20260701.zip") as z:
        assert z.read("withdrawn.txt").decode().split() == ["0001493152-26-044971"]
