"""Monthly rebalance helper — from "here are the picks" to "here is what to change".

Pure math (roadmap 16.3): diff the current certified picks against the last frozen
cohort (16.1), size an **equal-weight** target book to a budget, and cost each
order with the market's real, **asymmetric** frictions. An execution *aid* — it
never places orders, never advises, and offers no sizing scheme beyond equal
weight (a different scheme would be a spec change requiring re-certification).

Taiwan frictions are asymmetric: a 0.1425% brokerage fee on **each** side plus a
0.3% securities-transaction **tax on sells only** — so a sell costs materially
more than a buy, which the cost function encodes. Taiwan trades in 1,000-share
board lots (an odd-lot toggle relaxes that); US trades whole shares.

:func:`weighted_plan` (roadmap 18.10) is the general form: it sizes every name to the
spec's **own target weights** (``research.construct`` — never assumed equal), estimates
the previous book from the last frozen cohort's weights (equal weight when a cohort
predates weights), and trades the difference — including a kept name whose weight
changed. US: whole shares by default, an optional fractional mode (4 dp), no sell tax.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

# Editable cost/lot constants (the card's "editable constants").
TW_FEE_RATE: float = 0.001425  # brokerage fee, charged per side
TW_SELL_TAX_RATE: float = 0.003  # securities transaction tax, sells only
US_DEFAULT_BPS: float = 5.0  # flat per-side cost in basis points (editable)
TW_BOARD_LOT: int = 1000


@dataclass
class PickDiff:
    added: list[str]  # in current, not in the last frozen cohort → new buys
    dropped: list[str]  # in the last frozen cohort, not in current → exits
    kept: list[str]  # in both → held, no order


#: Fractional-share precision for brokers that support it (US).
FRACTIONAL_DP: int = 4


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    shares: float  # whole shares, or fractional (US) when requested
    ref_close: float
    est_cost: float


def diff_picks(current: list[str], previous: list[str]) -> PickDiff:
    """Classify the move from the previous (frozen) book to the current picks."""
    cur, prev = set(current), set(previous)
    return PickDiff(
        added=sorted(cur - prev),
        dropped=sorted(prev - cur),
        kept=sorted(cur & prev),
    )


def target_shares(
    target_value: float, ref_close: float, market: str, *, odd_lot: bool = False
) -> int:
    """Whole-share count for a target position value, floored to the market's lot.

    Taiwan floors to whole 1,000-share board lots (unless ``odd_lot``); US (and
    Taiwan odd-lot) floors to whole shares. Floor, never round up — an execution
    aid must not overspend the budget. Non-positive price/target → 0.
    """
    if ref_close <= 0 or target_value <= 0:
        return 0
    raw = int(target_value // ref_close)  # whole shares affordable
    if market == "Taiwan" and not odd_lot:
        return (raw // TW_BOARD_LOT) * TW_BOARD_LOT
    return raw


def trade_cost(value: float, side: str, market: str, *, us_bps: float = US_DEFAULT_BPS) -> float:
    """Estimated one-side trading cost for a trade of gross ``value``.

    Taiwan: 0.1425% fee both sides + 0.3% tax on sells (the asymmetry). US: a flat
    ``us_bps`` per side (symmetric). ``value`` is ``shares × ref_close``.
    """
    if market == "Taiwan":
        rate = TW_FEE_RATE + (TW_SELL_TAX_RATE if side == "sell" else 0.0)
        return value * rate
    return value * us_bps / 1e4


def rebalance_plan(
    current: list[str],
    previous: list[str],
    ref_closes: dict[str, float],
    budget: float,
    market: str,
    *,
    odd_lot: bool = False,
    us_bps: float = US_DEFAULT_BPS,
) -> list[Order]:
    """The minimal set of trades to move the book toward the equal-weight current picks.

    Buys the **added** names to their equal-weight target (``budget / N_current``);
    sells the **dropped** names, sized at the previous book's equal-weight target
    (this assumes the prior frozen book was held equal-weight at the same budget —
    an honest simplification the caption states). **Kept** names are held, not
    re-traded (no churn, no scheme beyond equal weight). ``ref_closes`` must cover
    every added and dropped symbol; a missing/zero close skips that order rather
    than guessing.
    """
    diff = diff_picks(current, previous)
    orders: list[Order] = []
    if current:
        ew = budget / len(current)
        for sym in diff.added:
            close = ref_closes.get(sym, float("nan"))
            shares = target_shares(ew, close, market, odd_lot=odd_lot)
            if shares > 0:
                value = shares * close
                orders.append(
                    Order(
                        sym, "buy", shares, close, trade_cost(value, "buy", market, us_bps=us_bps)
                    )
                )
    if previous:
        ew_prev = budget / len(previous)
        for sym in diff.dropped:
            close = ref_closes.get(sym, float("nan"))
            shares = target_shares(ew_prev, close, market, odd_lot=odd_lot)
            if shares > 0:
                value = shares * close
                orders.append(
                    Order(
                        sym, "sell", shares, close, trade_cost(value, "sell", market, us_bps=us_bps)
                    )
                )
    return orders


def frozen_weights(picks: list[dict[str, object]]) -> dict[str, float]:
    """A frozen cohort's book as weights: its stored ``weight`` per pick (weighted specs
    freeze them, 18.2), else equal weight."""
    if not picks:
        return {}
    if all("weight" in p for p in picks):
        return {str(p["symbol"]): float(str(p["weight"])) for p in picks}
    return {str(p["symbol"]): 1.0 / len(picks) for p in picks}


def shares_for(
    target_value: float,
    ref_close: float,
    market: str,
    *,
    odd_lot: bool = False,
    fractional: bool = False,
) -> float:
    """Shares for a target value: :func:`target_shares`, or floored to ``FRACTIONAL_DP``
    decimals when ``fractional`` (US only — Taiwan has no fractional shares)."""
    if fractional and market != "Taiwan":
        if ref_close <= 0 or target_value <= 0:
            return 0.0
        scale = 10**FRACTIONAL_DP
        return float(int(target_value / ref_close * scale) / scale)
    return float(target_shares(target_value, ref_close, market, odd_lot=odd_lot))


def weighted_plan(
    targets: dict[str, float],
    previous: dict[str, float],
    ref_closes: dict[str, float],
    budget: float,
    market: str,
    *,
    fractional: bool = False,
    odd_lot: bool = False,
    us_bps: float = US_DEFAULT_BPS,
) -> list[Order]:
    """Orders moving the book from ``previous`` weights to ``targets`` at ``budget``.

    Every name in either book is sized ``weight × budget`` at its reference close (floored,
    never overspending) and the share difference becomes one order; a kept name whose weight
    changed is re-traded, an unchanged one is not. A name without a positive close is skipped
    rather than guessed. The previous book is an *estimate* (its frozen weights at today's
    budget and closes) — the UI states that assumption.
    """
    orders: list[Order] = []
    for sym in sorted(set(targets) | set(previous)):
        close = ref_closes.get(sym, float("nan"))
        if not close > 0:
            continue
        kw = {"odd_lot": odd_lot, "fractional": fractional}
        want = shares_for(targets.get(sym, 0.0) * budget, close, market, **kw)
        have = shares_for(previous.get(sym, 0.0) * budget, close, market, **kw)
        delta = round(want - have, FRACTIONAL_DP)
        if delta == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        value = abs(delta) * close
        orders.append(
            Order(sym, side, abs(delta), close, trade_cost(value, side, market, us_bps=us_bps))
        )
    return orders


def orders_to_csv(orders: list[Order]) -> str:
    """CSV export: ``symbol, side, shares, reference_close, est_cost``."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["symbol", "side", "shares", "reference_close", "est_cost"])
    for o in orders:
        writer.writerow(
            [o.symbol, o.side, f"{o.shares:g}", f"{o.ref_close:.4f}", f"{o.est_cost:.2f}"]
        )
    return buf.getvalue()
