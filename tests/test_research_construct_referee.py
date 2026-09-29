"""The referee prices the constructed book (roadmap 18.2).

``certify`` / ``evaluate`` / ``monitor`` / ``today`` / the ledger all build the book through
:mod:`heimdall.research.construct`. These tests pin what changes when a construction option is
set — weighted G3, the tier as the G3 universe, the rank buffer's turnover, the overlay touching
G4 only — while the existing certify/evaluate/monitor/today suites pin that a default spec's
numbers did not move.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from heimdall.research import gates
from heimdall.research.certify import (
    _book_mean,
    certify,
    cohort_book,
    traded_fractions,
    weight_turnover,
)
from heimdall.research.evaluate import evaluate
from heimdall.research.ledger import cohort_path, freeze, latest_members
from heimdall.research.monitor import realized_cohorts
from heimdall.research.spec import SignalSpec
from heimdall.research.today import todays_picks


def _spec(**kw: object) -> SignalSpec:
    base: dict[str, object] = {
        "name": "ref",
        "family": "ref-fam",
        "market": "US",
        "features": {"sig": 1.0},
        "top_n": 5,
    }
    base.update(kw)
    return SignalSpec.model_validate(base)


# --- small pieces, by hand -----------------------------------------------------


def test_weight_turnover_and_traded_fractions_hand_answers() -> None:
    a = pd.Series({"A": 0.5, "B": 0.5})
    b = pd.Series({"A": 0.25, "C": 0.75})
    # |0.25−0.5| + |0−0.5| + |0.75−0| = 1.5 → one-way 0.75
    assert weight_turnover([a, b]) == [pytest.approx(0.75)]
    # equal-weight books of equal size agree with the set formula (2 of 4 replaced = 0.5)
    ew1 = pd.Series(0.25, index=list("ABCD"))
    ew2 = pd.Series(0.25, index=list("ABEF"))
    assert weight_turnover([ew1, ew2]) == [pytest.approx(0.5)]
    cash = pd.Series(dtype=float)
    # buy the book (1.0), sell to cash (1.0), buy back (1.0), hold (0.0)
    assert traded_fractions([a, cash, a, a]) == pytest.approx([1.0, 1.0, 1.0, 0.0])


def test_book_mean_weighted_with_missing_label_and_cash() -> None:
    scored = pd.DataFrame({"symbol": ["A", "B", "C"], "r": [0.10, 0.04, float("nan")]})
    w = pd.Series({"A": 2 / 3, "B": 1 / 3})
    assert _book_mean(scored, w, "r", equal=False) == pytest.approx(0.08)
    # C has no label: its weight is renormalized away (A and B keep their 2:1 ratio)
    w3 = pd.Series({"A": 0.5, "B": 0.25, "C": 0.25})
    assert _book_mean(scored, w3, "r", equal=False) == pytest.approx(0.08)
    # an infeasible sector cap left 40% cash: the invested 60% earns 0.08 → 0.048
    wc = pd.Series({"A": 0.4, "B": 0.2})
    assert _book_mean(scored, wc, "r", equal=False) == pytest.approx(0.048)
    # equal-weight books use the plain mean (the legacy path)
    assert _book_mean(scored, pd.Series({"A": 0.5, "B": 0.5}), "r", equal=True) == pytest.approx(
        0.07
    )


# --- one cross-section ---------------------------------------------------------


def _cross() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E", "F"],
            "sig": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "vol_63d": [0.1, 0.2, 0.3, 0.3, 0.3, 0.3],
            "market_cap": [1e9, 6e9, 5e9, 4e9, 3e9, 2e9],
            "fwd_6m_rel": [0.10, 0.04, 0.0, -0.02, 0.01, 0.03],
            "eligible": True,
        }
    )


def test_inverse_vol_book_prices_g3_by_weight() -> None:
    book, bu = cohort_book(_spec(top_n=2, weighting="inverse_vol"), _cross())
    assert list(book.index) == ["A", "B"]
    assert bu is not None
    book_ret, univ_ret = bu
    assert book_ret == pytest.approx(2 / 3 * 0.10 + 1 / 3 * 0.04)  # 0.08, not the EW 0.07
    assert univ_ret == pytest.approx(np.mean([0.10, 0.04, 0.0, -0.02, 0.01, 0.03]))


def test_us_large_tier_is_the_g3_universe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gates, "US_LARGE_N", 3)
    book, bu = cohort_book(_spec(top_n=2, universe="us_large"), _cross())
    # tier by cap = B, C, D (A is the smallest-but-one) → the book ranks inside it
    assert list(book.index) == ["B", "C"]
    assert bu is not None
    assert bu[1] == pytest.approx(np.mean([0.04, 0.0, -0.02]))  # EW of the tier, not all six


def test_filters_select_but_do_not_shrink_the_g3_universe() -> None:
    from heimdall.screener.model import Predicate

    spec = _spec(top_n=2, filters=[Predicate(field="vol_63d", op=">", value=0.15)])
    book, bu = cohort_book(spec, _cross())
    assert list(book.index) == ["B", "C"]  # A fails the filter
    assert bu is not None
    assert bu[1] == pytest.approx(np.mean([0.10, 0.04, 0.0, -0.02, 0.01, 0.03]))


# --- the referee over months ---------------------------------------------------


def _bench(n: int = 1200, crash_at: int | None = None) -> pd.Series:
    k = np.arange(n)
    daily = 0.0004 + 0.0002 * np.sin(k / 7.0)
    if crash_at is not None:
        daily = np.where((k >= crash_at) & (k < crash_at + 150), -0.004, daily)
    return pd.Series(100.0 * np.cumprod(1.0 + daily), index=pd.bdate_range("2022-01-03", periods=n))


def _churny_panel(bench: pd.Series, n_months: int = 30, seed: int = 11) -> pd.DataFrame:
    """15 'good' names shuffled at random each month above 25 weak ones.

    Plain top-5 churns ≈ 1 − 5/15 of the book monthly (> 60%: G6 rejects); a buffer with
    exit_rank = 15 keeps every member (all 15 good names always rank ≤ 15).
    """
    rng = np.random.default_rng(seed)
    months = list(pd.date_range("2023-01-31", periods=n_months, freq="BME"))
    rows: list[dict[str, object]] = []
    for m_idx, t in enumerate(months):
        nxt = months[m_idx + 1] if m_idx + 1 < len(months) else None
        i0, j0 = int(bench.index.searchsorted(t)), 0
        bench_m = 0.0
        if nxt is not None:
            j0 = int(bench.index.searchsorted(nxt))
            bench_m = float(bench.iloc[j0] / bench.iloc[i0] - 1.0)
        good = rng.permutation(15)
        complete6 = m_idx < n_months - 2
        for i in range(40):
            sig = 100.0 + float(good[i]) if i < 15 else float(i)
            rel1 = (0.01 if i < 15 else -0.002) + float(rng.normal(0, 0.003))
            rows.append(
                {
                    "date": t,
                    "symbol": f"S{i:02d}",
                    "eligible": True,
                    "sig": sig,
                    "vol_63d": 0.1 + 0.01 * i,
                    "fwd_1m": rel1 + bench_m,
                    "fwd_1m_rel": rel1,
                    "fwd_6m": 6 * rel1 + 0.05 if complete6 else float("nan"),
                    "fwd_6m_rel": 6 * rel1 if complete6 else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _gate(report: object, name: str) -> object:
    return next(g for g in report.gates if g.gate == name)  # type: ignore[attr-defined]


def test_rank_buffer_flips_g6() -> None:
    bench = _bench()
    panel = _churny_panel(bench)
    plain = certify(_spec(), panel, bench)
    buffered = certify(_spec(exit_rank=15), panel, bench)
    assert plain.mean_turnover > gates.G6_STRESS_TURNOVER
    assert not _gate(plain, "G6_turnover").passed  # type: ignore[attr-defined]
    assert buffered.mean_turnover == pytest.approx(0.0)
    assert _gate(buffered, "G6_turnover").passed  # type: ignore[attr-defined]
    assert buffered.construction == {"exit_rank": 15}
    assert plain.construction == {}


def test_overlay_moves_g4_but_never_the_selection_gates() -> None:
    bench = _bench(crash_at=330)  # falls below its 200d SMA through part of 2023
    panel = _churny_panel(bench)
    plain = certify(_spec(), panel, bench)
    timed = certify(_spec(overlay="spy_sma200_cash"), panel, bench)
    assert timed.selection_alpha_mean == pytest.approx(plain.selection_alpha_mean)
    assert timed.mean_turnover == pytest.approx(plain.mean_turnover)
    for g in ("G1_ic", "G2_mean", "G3_alpha"):
        assert _gate(timed, g).value == pytest.approx(_gate(plain, g).value)  # type: ignore[attr-defined]
    assert _gate(timed, "G4_cagr").value != pytest.approx(_gate(plain, "G4_cagr").value)  # type: ignore[attr-defined]


def test_monitor_replays_the_certified_buffered_book() -> None:
    bench = _bench()
    panel = _churny_panel(bench)
    spec = _spec(exit_rank=15)
    report = certify(spec, panel, bench)
    realized = realized_cohorts(spec, panel)
    assert [c.alpha for c in realized] == pytest.approx([c["alpha_6m"] for c in report.cohorts])


def test_evaluate_uses_weighted_turnover_for_weighted_books() -> None:
    panel = _churny_panel(_bench())
    panel["date"] = panel["date"] - pd.DateOffset(years=5)  # move into the dev window
    ew = evaluate(_spec(exit_rank=15), panel, ("2018-01-01", "2019-12-31"))
    iv = evaluate(_spec(exit_rank=15, weighting="inverse_vol"), panel, ("2018-01-01", "2019-12-31"))
    assert ew.mean_turnover == pytest.approx(0.0)  # same members every month
    assert iv.mean_turnover == pytest.approx(0.0)  # same members, same vols → same weights
    assert iv.selection_alpha_mean != pytest.approx(ew.selection_alpha_mean)


# --- today + ledger --------------------------------------------------------------


def _snapshot() -> pd.DataFrame:
    syms = ["A.US", "B.US", "C.US", "D.US", "E.US"]
    return pd.DataFrame(
        {
            "symbol": syms,
            "as_of": pd.Timestamp("2026-09-15"),
            "price": 100.0,
            "dollar_vol_21d": 1e8,
            "ret_12_1": 0.1,
            "sig": [5.0, 4.0, 3.0, 2.0, 1.0],
            "vol_63d": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
    )


def test_todays_picks_carries_weights_and_honours_the_buffer() -> None:
    picks = todays_picks(_spec(top_n=2, weighting="inverse_vol"), _snapshot())
    assert picks["symbol"].tolist() == ["A.US", "B.US"]
    assert picks["weight"].tolist() == pytest.approx([2 / 3, 1 / 3])
    buffered = todays_picks(_spec(top_n=2, exit_rank=3), _snapshot(), prev={"C.US", "Z.US"})
    assert buffered["symbol"].tolist() == ["A.US", "C.US"]  # C (rank 3) held, Z gone
    assert todays_picks(_spec(top_n=2), _snapshot())["weight"].tolist() == [0.5, 0.5]


def test_todays_picks_requires_construction_columns() -> None:
    with pytest.raises(ValueError, match="market_cap"):
        todays_picks(_spec(universe="us_large"), _snapshot())


def test_ledger_freeze_feeds_the_buffer_and_stores_weights(tmp_path: Path) -> None:
    spec = _spec(top_n=2, exit_rank=3, weighting="inverse_vol")
    prior = cohort_path(spec.name, spec.version, "2026-08", tmp_path)
    prior.parent.mkdir(parents=True)
    prior.write_text(json.dumps({"month": "2026-08", "picks": [{"symbol": "C.US"}]}))
    assert latest_members(spec.name, spec.version, tmp_path) == {"C.US"}

    path = freeze(spec, _snapshot(), "2026-08", root=tmp_path, today=date(2026, 9, 15))
    frozen = json.loads(path.read_text())
    assert [p["symbol"] for p in frozen["picks"]] == ["A.US", "C.US"]
    assert sum(p["weight"] for p in frozen["picks"]) == pytest.approx(1.0)
    assert latest_members("nobody", 1, tmp_path) is None
