"""Citadel sector rotation — relative strength across the 11 SPDR sector ETFs.

Ranks sectors by a blended 1/3/6-month momentum composite and reads an
offense (cyclical) vs defense tilt. Free data (ETF prices via yfinance).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# SPDR sector ETFs → sector name.
SECTOR_ETFS: dict[str, str] = {
    "XLK.US": "Technology",
    "XLF.US": "Financials",
    "XLE.US": "Energy",
    "XLV.US": "Health Care",
    "XLY.US": "Consumer Discretionary",
    "XLP.US": "Consumer Staples",
    "XLI.US": "Industrials",
    "XLB.US": "Materials",
    "XLRE.US": "Real Estate",
    "XLU.US": "Utilities",
    "XLC.US": "Communication Svcs",
}
_OFFENSE = {"XLK.US", "XLY.US", "XLF.US", "XLI.US", "XLB.US", "XLC.US", "XLE.US"}
_DEFENSE = {"XLP.US", "XLV.US", "XLU.US", "XLRE.US"}


@dataclass(frozen=True)
class RotationReport:
    ranks: pd.DataFrame  # index=etf: sector, ret_1m, ret_3m, ret_6m, score, rank
    offense_score: float  # mean composite of cyclical sectors
    defense_score: float  # mean composite of defensive sectors
    tilt: str  # offense / defense / neutral
    leaders: list[str]
    laggards: list[str]


def _ret(close: pd.Series, n: int) -> float:
    price = float(close.iloc[-1])
    return price / float(close.iloc[-1 - n]) - 1.0 if len(close) > n else float("nan")


def sector_rotation(etf_ohlcv: dict[str, pd.DataFrame], tol: float = 0.005) -> RotationReport:
    """Rank sector ETFs by a 1/3/6-month relative-strength composite."""
    rows = []
    for etf, ohlcv in etf_ohlcv.items():
        if ohlcv.empty:
            continue
        close = ohlcv["adj_close"].reset_index(drop=True)
        r1, r3, r6 = _ret(close, 21), _ret(close, 63), _ret(close, 126)
        score = float(pd.Series([r1, r3, r6]).mean(skipna=True))
        rows.append(
            {
                "etf": etf,
                "sector": SECTOR_ETFS.get(etf, etf),
                "ret_1m": r1,
                "ret_3m": r3,
                "ret_6m": r6,
                "score": score,
            }
        )

    ranks = pd.DataFrame(rows).set_index("etf").sort_values("score", ascending=False)
    ranks["rank"] = range(1, len(ranks) + 1)

    offense = float(ranks.loc[ranks.index.isin(_OFFENSE), "score"].mean())
    defense = float(ranks.loc[ranks.index.isin(_DEFENSE), "score"].mean())
    if offense > defense + tol:
        tilt = "offense"
    elif defense > offense + tol:
        tilt = "defense"
    else:
        tilt = "neutral"

    return RotationReport(
        ranks=ranks,
        offense_score=offense,
        defense_score=defense,
        tilt=tilt,
        leaders=ranks.index[:3].tolist(),
        laggards=ranks.index[-3:].tolist(),
    )
