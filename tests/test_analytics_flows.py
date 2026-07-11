"""TW market-wide flow aggregation (roadmap 15.2) — known-answer tests, no network."""

from __future__ import annotations

import pandas as pd
import pytest

from heimdall.analytics import (
    holding_ratio_delta,
    market_totals,
    sector_rollup,
    top_net_buy_sell,
    trust_streak,
)


def _row(
    symbol: str,
    sector: str,
    day: str,
    foreign: float,
    trust: float,
    dealer: float,
    close: float,
    hold: float = float("nan"),
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "sector": sector,
        "date": pd.Timestamp(day),
        "foreign_net_shares": foreign,
        "trust_net_shares": trust,
        "dealer_net_shares": dealer,
        "foreign_hold_ratio": hold,
        "close": close,
    }


# --- market_totals -----------------------------------------------------------


def test_market_totals_ntd_sum_across_symbols_and_days() -> None:
    days = pd.DataFrame(
        [
            _row("A", "Tech", "2024-01-02", 100, 50, -20, 10.0),
            _row("A", "Tech", "2024-01-03", 200, -10, 5, 11.0),
            _row("B", "Energy", "2024-01-02", -50, 30, 0, 20.0),
        ]
    )
    out = market_totals(days)
    # foreign: 100*10 + 200*11 + (-50)*20 = 1000 + 2200 - 1000 = 2200
    assert out["foreign"] == pytest.approx(2200.0)
    assert out["trust"] == pytest.approx(50 * 10 + -10 * 11 + 30 * 20)
    assert out["dealer"] == pytest.approx(-20 * 10 + 5 * 11 + 0 * 20)


def test_market_totals_empty() -> None:
    out = market_totals(pd.DataFrame())
    assert all(pd.isna(v) for v in out.values())


# --- sector_rollup -------------------------------------------------------------


def test_sector_rollup_sums_per_sector_sorted_by_foreign() -> None:
    days = pd.DataFrame(
        [
            _row("A", "Tech", "2024-01-02", 100, 10, 0, 10.0),
            _row("B", "Tech", "2024-01-02", 50, 0, 0, 10.0),
            _row("C", "Energy", "2024-01-02", 200, 0, 0, 10.0),
        ]
    )
    out = sector_rollup(days).set_index("sector")
    assert out.loc["Tech", "foreign_ntd"] == pytest.approx(1500.0)  # (100+50)*10
    assert out.loc["Energy", "foreign_ntd"] == pytest.approx(2000.0)
    # sorted foreign descending: Energy (2000) before Tech (1500).
    assert list(sector_rollup(days)["sector"]) == ["Energy", "Tech"]


def test_sector_rollup_missing_sector_column_is_empty() -> None:
    from heimdall.analytics.flows import sector_rollup as _sr

    out = _sr(pd.DataFrame({"symbol": ["A"]}))
    assert out.empty


# --- top_net_buy_sell ----------------------------------------------------------


def test_top_net_buy_sell_ranks_buyers_and_sellers() -> None:
    days = pd.DataFrame(
        [
            _row("A", "Tech", "2024-01-02", 100, 0, 0, 10.0),  # +1000
            _row("B", "Tech", "2024-01-02", -50, 0, 0, 10.0),  # -500
            _row("C", "Tech", "2024-01-02", 10, 0, 0, 10.0),  # +100
        ]
    )
    out = top_net_buy_sell(days, "foreign", n=2)
    buyers = out[out["side"] == "buy"]
    sellers = out[out["side"] == "sell"]
    assert buyers["symbol"].tolist() == ["A", "C"]  # +1000 then +100
    assert buyers["ntd"].tolist() == pytest.approx([1000.0, 100.0])
    assert sellers["symbol"].tolist() == ["B", "C"]  # -500 then +100 (least negative)


def test_top_net_buy_sell_unknown_type_is_empty() -> None:
    days = pd.DataFrame([_row("A", "Tech", "2024-01-02", 100, 0, 0, 10.0)])
    assert top_net_buy_sell(days, "nonsense").empty


def test_top_net_buy_sell_empty_frame() -> None:
    assert top_net_buy_sell(pd.DataFrame(), "foreign").empty


# --- trust_streak ----------------------------------------------------------------


def test_trust_streak_counts_consecutive_days_ending_today() -> None:
    days = pd.DataFrame(
        [
            _row("A", "Tech", "2024-01-02", 0, 5, 0, 10.0),
            _row("A", "Tech", "2024-01-03", 0, 3, 0, 10.0),
            _row("A", "Tech", "2024-01-04", 0, -1, 0, 10.0),  # breaks the buy streak
            _row("A", "Tech", "2024-01-05", 0, 4, 0, 10.0),  # a fresh 1-day buy streak
        ]
    )
    out = trust_streak(days).set_index("symbol")
    assert out.loc["A", "streak_days"] == 1
    assert out.loc["A", "direction"] == "buy"


def test_trust_streak_full_run() -> None:
    days = pd.DataFrame(
        [_row("A", "Tech", f"2024-01-0{i}", 0, v, 0, 10.0) for i, v in enumerate([5, 3, 2, 1], 2)]
    )
    out = trust_streak(days).set_index("symbol")
    assert out.loc["A", "streak_days"] == 4
    assert out.loc["A", "direction"] == "buy"


def test_trust_streak_sell_streak_and_flat() -> None:
    days = pd.DataFrame(
        [
            _row("SELLER", "Tech", "2024-01-02", 0, -5, 0, 10.0),
            _row("SELLER", "Tech", "2024-01-03", 0, -3, 0, 10.0),
            _row("FLAT", "Tech", "2024-01-02", 0, 5, 0, 10.0),
            _row("FLAT", "Tech", "2024-01-03", 0, 0, 0, 10.0),
        ]
    )
    out = trust_streak(days).set_index("symbol")
    assert out.loc["SELLER", "streak_days"] == 2
    assert out.loc["SELLER", "direction"] == "sell"
    assert out.loc["FLAT", "streak_days"] == 0
    assert out.loc["FLAT", "direction"] == "flat"
    # sorted longest streak first.
    assert trust_streak(days)["symbol"].tolist()[0] == "SELLER"


def test_trust_streak_empty() -> None:
    assert trust_streak(pd.DataFrame()).empty


# --- holding_ratio_delta ---------------------------------------------------------


def test_holding_ratio_delta_first_vs_last_available() -> None:
    days = pd.DataFrame(
        [
            _row("A", "Tech", "2024-01-02", 0, 0, 0, 10.0, hold=70.0),
            _row("A", "Tech", "2024-01-03", 0, 0, 0, 10.0, hold=float("nan")),  # a gap, skipped
            _row("A", "Tech", "2024-01-04", 0, 0, 0, 10.0, hold=72.5),
        ]
    )
    out = holding_ratio_delta(days).set_index("symbol")
    assert out.loc["A", "delta_pp"] == pytest.approx(2.5)


def test_holding_ratio_delta_needs_two_observations() -> None:
    days = pd.DataFrame([_row("A", "Tech", "2024-01-02", 0, 0, 0, 10.0, hold=70.0)])
    assert holding_ratio_delta(days).empty


def test_holding_ratio_delta_empty() -> None:
    assert holding_ratio_delta(pd.DataFrame()).empty
