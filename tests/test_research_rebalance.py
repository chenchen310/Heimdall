"""Monthly rebalance helper (roadmap 16.3) — known-answer lot & cost math.

The two things that are easy to get wrong and costly if so: Taiwan **board-lot
rounding** (with the odd-lot escape) and the **sell-tax asymmetry** (a TW sell
carries the 0.3% transaction tax a buy does not).
"""

from __future__ import annotations

import pytest

from heimdall.research.rebalance import (
    TW_FEE_RATE,
    TW_SELL_TAX_RATE,
    Order,
    diff_picks,
    orders_to_csv,
    rebalance_plan,
    target_shares,
    trade_cost,
)


def test_diff_picks_added_dropped_kept() -> None:
    d = diff_picks(["A.US", "B.US", "C.US"], ["B.US", "C.US", "D.US"])
    assert d.added == ["A.US"]
    assert d.dropped == ["D.US"]
    assert d.kept == ["B.US", "C.US"]


def test_target_shares_tw_board_lot_and_odd_lot_and_us_whole() -> None:
    # TW: 100,000 / 30 = 3,333 affordable → floor to whole 1,000-lots = 3,000.
    assert target_shares(100_000, 30.0, "Taiwan") == 3_000
    # TW odd-lot: keep the whole-share count.
    assert target_shares(100_000, 30.0, "Taiwan", odd_lot=True) == 3_333
    # US: whole shares, no lot.
    assert target_shares(100_000, 30.0, "US") == 3_333
    # Degenerate inputs never overspend.
    assert target_shares(100_000, 0.0, "US") == 0
    assert target_shares(0.0, 30.0, "Taiwan") == 0


def test_trade_cost_tw_sell_tax_asymmetry_and_us_symmetric() -> None:
    buy = trade_cost(30_000, "buy", "Taiwan")
    sell = trade_cost(30_000, "sell", "Taiwan")
    assert buy == pytest.approx(30_000 * TW_FEE_RATE)  # 42.75
    assert sell == pytest.approx(30_000 * (TW_FEE_RATE + TW_SELL_TAX_RATE))  # 132.75
    assert sell - buy == pytest.approx(30_000 * TW_SELL_TAX_RATE)  # exactly the 0.3% tax

    # US is symmetric at the flat bps.
    assert trade_cost(30_000, "buy", "US", us_bps=5.0) == pytest.approx(15.0)
    assert trade_cost(30_000, "sell", "US", us_bps=5.0) == pytest.approx(15.0)


def test_rebalance_plan_buys_added_sells_dropped_holds_kept() -> None:
    orders = rebalance_plan(
        current=["A.US", "B.US"],
        previous=["B.US", "C.US"],
        ref_closes={"A.US": 100.0, "B.US": 50.0, "C.US": 200.0},
        budget=200_000.0,
        market="US",
        us_bps=5.0,
    )
    # Added A: EW target 100,000 / $100 = 1,000 sh; value 100,000; cost 100,000·5bps = 50.
    # Dropped C: prior EW 100,000 / $200 = 500 sh; value 100,000; cost 50. B (kept): no order.
    assert orders == [
        Order("A.US", "buy", 1000, 100.0, 50.0),
        Order("C.US", "sell", 500, 200.0, 50.0),
    ]


def test_rebalance_plan_tw_sell_carries_more_cost_than_a_same_value_buy() -> None:
    orders = rebalance_plan(
        current=["1101.TW"],
        previous=["2330.TW"],
        ref_closes={"1101.TW": 40.0, "2330.TW": 40.0},
        budget=40_000.0,
        market="Taiwan",
    )
    buy = next(o for o in orders if o.side == "buy")
    sell = next(o for o in orders if o.side == "sell")
    assert buy.shares == 1000 and sell.shares == 1000  # both floor to one board lot
    assert sell.est_cost > buy.est_cost  # the sell tax makes exiting cost more
    assert sell.est_cost - buy.est_cost == pytest.approx(40_000 * TW_SELL_TAX_RATE)


def test_orders_to_csv_shape() -> None:
    csv_text = orders_to_csv([Order("A.US", "buy", 10, 100.0, 5.0)])
    lines = csv_text.strip().splitlines()
    assert lines[0] == "symbol,side,shares,reference_close,est_cost"
    assert lines[1] == "A.US,buy,10,100.0000,5.00"
