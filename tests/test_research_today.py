"""Today's Picks engine (roadmap 9.1) — ranking, exclusions, freshness.

The known-answer uses b = reversed(a) so z_b = −z_a exactly and the score is
2·z_a by hand; the breakdown columns must reconcile with the total. Exclusion
paths each get a row: too cheap, too thin, too young, wrong market, missing a
feature value — none may ever rank.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from heimdall.research.spec import SignalSpec
from heimdall.research.today import eligibility, freshness, todays_picks


def _spec(top_n: int = 3) -> SignalSpec:
    return SignalSpec.model_validate(
        {
            "name": "today-test",
            "family": "today",
            "market": "US",
            "version": 1,
            "features": {"a": 1.0, "b": -1.0},
            "top_n": top_n,
        }
    )


def _snapshot() -> pd.DataFrame:
    nan = float("nan")
    rows = [
        # symbol, price, dollar_vol, ret_12_1, a, b
        ("A.US", 100.0, 1e8, 0.10, 1.0, 5.0),
        ("B.US", 100.0, 1e8, 0.10, 2.0, 4.0),
        ("C.US", 100.0, 1e8, 0.10, 3.0, 3.0),
        ("D.US", 100.0, 1e8, 0.10, 4.0, 2.0),
        ("E.US", 100.0, 1e8, 0.10, 5.0, 1.0),
        ("F.US", 100.0, 1e8, 0.10, nan, nan),  # eligible, missing features → never ranks
        ("LOWP.US", 1.0, 1e8, 0.10, 9.0, 9.0),  # under the $2 floor
        ("THIN.US", 100.0, 1e4, 0.10, 9.0, 9.0),  # $10k/day traded
        ("NEW.US", 100.0, 1e8, nan, 9.0, 9.0),  # < 252 bars (ret_12_1 proxy)
        ("2330.TW", 1000.0, 1e10, 0.10, 9.0, 9.0),  # wrong market entirely
    ]
    return pd.DataFrame(
        {
            "symbol": [r[0] for r in rows],
            "as_of": pd.Timestamp("2026-07-03"),
            "price": [r[1] for r in rows],
            "dollar_vol_21d": [r[2] for r in rows],
            "ret_12_1": [r[3] for r in rows],
            "a": [r[4] for r in rows],
            "b": [r[5] for r in rows],
        }
    )


def test_known_answer_ranking_and_breakdown() -> None:
    picks = todays_picks(_spec(top_n=3), _snapshot())
    assert picks["symbol"].tolist() == ["E.US", "D.US", "C.US"]

    # Hand z over the 5-value pool (F's NaNs don't move mean/std): std = √2.5.
    z_a = np.array([-2.0, -1.0, 0.0, 1.0, 2.0]) / np.sqrt(2.5)
    assert picks["z_a"].tolist() == pytest.approx([z_a[4], z_a[3], z_a[2]])
    assert picks["z_b"].tolist() == pytest.approx([-z_a[4], -z_a[3], -z_a[2]])
    assert picks["signal_score"].tolist() == pytest.approx([2 * z_a[4], 2 * z_a[3], 0.0])
    # The breakdown must reconcile with the total: Σ weight × z == score.
    recon = 1.0 * picks["z_a"] + (-1.0) * picks["z_b"]
    assert picks["signal_score"].tolist() == pytest.approx(recon.tolist())


def test_exclusion_paths_never_rank() -> None:
    picks = todays_picks(_spec(top_n=20), _snapshot())  # room for everyone
    assert set(picks["symbol"]) == {"A.US", "B.US", "C.US", "D.US", "E.US"}

    ver = eligibility(_snapshot(), "US").set_index("symbol")
    assert bool(ver.loc["A.US", "eligible"]) and ver.loc["A.US", "inelig_reason"] == ""
    assert ver.loc["LOWP.US", "inelig_reason"] == "price"
    assert ver.loc["THIN.US", "inelig_reason"] == "liquidity"
    assert ver.loc["NEW.US", "inelig_reason"] == "history"


def test_fewer_eligible_than_top_n_returns_what_exists() -> None:
    assert len(todays_picks(_spec(top_n=10), _snapshot())) == 5


def test_wrong_market_snapshot_returns_empty() -> None:
    spec = _spec().model_copy(update={"market": "Taiwan"})
    picks = todays_picks(spec, _snapshot().head(5))  # US-only rows
    assert len(picks) == 0 and "signal_score" in picks.columns


def test_missing_columns_raise_with_guidance() -> None:
    spec = SignalSpec.model_validate(
        {"name": "x", "family": "f", "market": "US", "features": {"nope": 1.0}}
    )
    with pytest.raises(ValueError, match="nope"):
        todays_picks(spec, _snapshot())
    with pytest.raises(ValueError, match="dollar_vol_21d"):
        todays_picks(_spec(), _snapshot().drop(columns=["dollar_vol_21d"]))  # pre-7.1 snapshot


def test_freshness_business_day_math() -> None:
    snap = _snapshot()  # as_of = Friday 2026-07-03
    assert freshness(snap, today=date(2026, 7, 3)) == 0
    assert freshness(snap, today=date(2026, 7, 6)) == 1  # the weekend doesn't count
    assert freshness(snap, today=date(2026, 7, 10)) == 5
    with pytest.raises(ValueError, match="as_of"):
        freshness(snap.drop(columns=["as_of"]))
