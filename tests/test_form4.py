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
