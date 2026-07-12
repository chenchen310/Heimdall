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
