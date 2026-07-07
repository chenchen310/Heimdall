"""Today's Picks engine — certified spec + fresh snapshot → today's ranked cohort.

Pure functions only (roadmap 9.1): the page (9.2) composes the registry with
these — nothing here reads registry state, so the certified-only rule stays
enforceable in one place. Scoring reuses ``spec.score`` and the same
``_zscore`` it is built from, so the per-feature breakdown reconciles exactly
with the total.

Eligibility mirrors the research panel's hygiene (``gates`` constants), mapped
to what a snapshot row carries:

- **history** — ``ret_12_1`` non-NaN is exactly the ≥ 252-bar requirement
  (7.1 defines it as NaN under 252 bars);
- **price** — the snapshot ``price`` is the latest adjusted close, which equals
  the raw close up to same-day corporate actions — fine for a $2/NT$10 floor;
- **liquidity** — ``dollar_vol_21d`` as in the panel.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from heimdall.data.symbols import parse_symbol
from heimdall.factors.scoring import _zscore
from heimdall.research import gates
from heimdall.research.spec import SignalSpec, score

_REQUIRED = {"symbol", "as_of", "price", "dollar_vol_21d", "ret_12_1"}


def eligibility(snapshot: pd.DataFrame, market: str) -> pd.DataFrame:
    """Per-row hygiene verdicts: ``symbol``, ``eligible``, ``inelig_reason``.

    Same first-failing-reason order as the panel: history → price → liquidity.
    NaN inputs fail their check (a missing dollar volume is not liquid).
    """
    hist_ok = snapshot["ret_12_1"].notna()
    price_ok = snapshot["price"] >= gates.MIN_PRICE[market]
    liq_ok = snapshot["dollar_vol_21d"] >= gates.MIN_DOLLAR_VOL_21D[market]

    reason = pd.Series("", index=snapshot.index, dtype="object")
    reason[~liq_ok] = "liquidity"
    reason[~price_ok] = "price"  # written later ⇒ earlier checks win
    reason[~hist_ok] = "history"
    return pd.DataFrame(
        {
            "symbol": snapshot["symbol"],
            "eligible": hist_ok & price_ok & liq_ok,
            "inelig_reason": reason,
        }
    )


def todays_picks(spec: SignalSpec, snapshot: pd.DataFrame) -> pd.DataFrame:
    """The spec's top-N for today, with per-feature z-scores explaining each rank.

    Filters the snapshot to the spec's market (a snapshot holds every market),
    applies hygiene, scores the eligible pool, and returns the ranked head —
    columns: ``symbol``, ``signal_score``, ``z_<feature>`` …, then the rest of
    the row. Rows missing any feature value score NaN and never rank (missing
    data excludes). Raises ``ValueError`` when the snapshot lacks required
    columns (e.g. built before the 7.1 fields) — rebuild it rather than guess.
    """
    missing = sorted((_REQUIRED | set(spec.features)) - set(snapshot.columns))
    if missing:
        raise ValueError(
            f"snapshot is missing {missing}; rebuild it (Build data page or "
            "`uv run python -m heimdall.screener.build`)"
        )

    region = snapshot["symbol"].map(lambda s: parse_symbol(str(s)).region)
    df = snapshot[region == spec.market].copy()
    if df.empty:
        return df.assign(signal_score=pd.Series(dtype=float))

    df["eligible"] = eligibility(df, spec.market)["eligible"]
    df["signal_score"] = score(spec, df)

    pool = df[df["eligible"]]
    for feat in spec.features:
        df.loc[pool.index, f"z_{feat}"] = _zscore(pool[feat])

    picks = (
        df[df["signal_score"].notna()]
        .sort_values("signal_score", ascending=False)
        .head(spec.top_n)
        .reset_index(drop=True)
    )
    lead = ["symbol", "signal_score", *[f"z_{f}" for f in spec.features], *spec.features]
    rest = [c for c in picks.columns if c not in lead]
    return picks[lead + rest]


def freshness(snapshot: pd.DataFrame, today: date | None = None) -> int:
    """Business-day staleness of the snapshot's ``as_of`` (0 = built today)."""
    if "as_of" not in snapshot.columns or snapshot["as_of"].isna().all():
        raise ValueError("snapshot has no usable as_of column")
    as_of = pd.to_datetime(snapshot["as_of"]).max().date()
    return int(np.busday_count(as_of, today if today is not None else date.today()))
