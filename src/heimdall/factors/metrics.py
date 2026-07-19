"""Per-symbol metric assembly — one row of technicals + point-in-time fundamentals.

Lives in ``factors`` (not ``screener``) because it computes indicators via
``factors.indicators``; placing it here keeps the dependency one-directional
(``screener`` → ``factors``) and lets both the snapshot builder and the factor
panel reuse the *same* computation. See ``docs/ARCHITECTURE.md`` §5–6.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from heimdall.data.symbols import parse_symbol
from heimdall.factors.indicators import rsi, sma


def _safe_div(a: float, b: float) -> float:
    return a / b if b not in (0, 0.0) and pd.notna(a) and pd.notna(b) else float("nan")


def _latest_annual(fund: pd.DataFrame, as_of: date) -> dict[str, float]:
    """Most-recently-ended annual value per metric known on/before ``as_of``."""
    known = fund[fund["filed_at"] <= pd.Timestamp(as_of)]
    if known.empty:
        return {}
    latest = known.sort_values(["fiscal_end", "filed_at"]).groupby("metric").tail(1)
    return {str(m): float(v) for m, v in zip(latest["metric"], latest["value"], strict=True)}


def _growth_yoy(fund: pd.DataFrame, metric: str, as_of: date) -> float:
    """YoY growth of an annual ``metric`` (latest vs prior fiscal year), point-in-time.

    NaN when fewer than two years are known or the prior value is <= 0 — a percent
    change off a non-positive base (e.g. a prior-year loss) is meaningless.
    """
    s = fund[(fund["metric"] == metric) & (fund["filed_at"] <= pd.Timestamp(as_of))]
    if s.empty:
        return float("nan")
    per_year = s.sort_values(["fiscal_end", "filed_at"]).groupby("fiscal_end").tail(1)
    per_year = per_year.sort_values("fiscal_end")
    if len(per_year) < 2:
        return float("nan")
    prev, last = float(per_year["value"].iloc[-2]), float(per_year["value"].iloc[-1])
    return last / prev - 1.0 if prev > 0 else float("nan")


def _revenue_growth_yoy(fund: pd.DataFrame, as_of: date) -> float:
    return _growth_yoy(fund, "revenue", as_of)


def _or0(x: float) -> float:
    """Treat a missing line item as zero (e.g. a debt-free firm reports no debt tag)."""
    return float(x) if pd.notna(x) else 0.0


def _technicals(ohlcv: pd.DataFrame) -> dict[str, float]:
    nan = float("nan")
    close = ohlcv["adj_close"].reset_index(drop=True)
    price = float(close.iloc[-1])

    def ret(n: int) -> float:
        return _safe_div(price, float(close.iloc[-1 - n])) - 1.0 if len(close) > n else nan

    # Liquidity: median daily dollar volume over the last 21 bars, on RAW close (adjusted
    # prices rescale history and would distort past traded value). Hygiene filters use this.
    traded = (ohlcv["close"] * ohlcv["volume"]).reset_index(drop=True)
    dollar_vol_21d = float(traded.tail(21).median()) if len(traded) >= 21 else nan

    # Skip-month momentum (t−12m → t−1m): the most recent month tends to reverse, so classic
    # momentum (UMD) excludes it — unlike ret_12m, which is the plain trailing-year return.
    ret_12_1 = (
        _safe_div(float(close.iloc[-21]), float(close.iloc[-252])) - 1.0
        if len(close) >= 252
        else nan
    )

    # Proximity to the 52-week high (George–Hwang 2004 anchoring): today's price ÷ the
    # highest adjusted close over the last 252 bars (current bar included, so it sits in
    # (0, 1]; 1.0 = at a new high). Underreaction near this salient reference level
    # predicts continued outperformance — this is anchoring, NOT return continuation.
    pct_of_52w_high = _safe_div(price, float(close.tail(252).max())) if len(close) >= 252 else nan

    # Realized volatility: std of the last 63 daily returns, annualized.
    rets = close.pct_change().dropna()
    vol_63d = float(rets.tail(63).std() * (252.0**0.5)) if len(rets) >= 63 else nan

    s200 = sma(close, 200).iloc[-1]
    return {
        "price": price,
        "sma_20": float(sma(close, 20).iloc[-1]),
        "sma_50": float(sma(close, 50).iloc[-1]),
        "sma_200": float(s200),
        "rsi_14": float(rsi(close, 14).iloc[-1]),
        "ret_3m": ret(63),
        "ret_6m": ret(126),
        "ret_12m": ret(252),
        "ret_12_1": ret_12_1,
        "pct_of_52w_high": pct_of_52w_high,
        "vol_63d": vol_63d,
        "dollar_vol_21d": dollar_vol_21d,
        "pct_above_sma_200": _safe_div(price, float(s200)) - 1.0,
    }


def revenue_momentum_features(monthly: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """TW monthly-revenue momentum — the signature free Taiwan signal (roadmap 11.2).

    Point-in-time on ``filed_at`` (§36: the 10th of the following month, see 11.1):
    only months filed on/before ``as_of`` exist. Features (both higher-is-better):

    - ``rev_mom_yoy`` — the latest known month's revenue YoY;
    - ``rev_mom_accel`` — mean YoY of the last 3 known months minus the prior 3,
      the second derivative that leads inflections.

    Computed on a contiguous monthly calendar (a gap month poisons its windows to
    NaN rather than silently spanning it); YoY on a non-positive year-ago base is
    NaN, mirroring ``_growth_yoy``. Shared by the research panel
    (``research.dataset``) and the live snapshot (``snapshot_row`` below) so a
    certified TW signal ranks identically whether it's being backtested or shown
    on Today's Picks.
    """
    nan = float("nan")
    out = {"rev_mom_yoy": nan, "rev_mom_accel": nan}
    if monthly.empty:
        return out
    known = monthly[monthly["filed_at"] <= as_of]
    if known.empty:
        return out
    s = known.sort_values(["month", "filed_at"]).groupby("month")["revenue"].last()
    s.index = pd.PeriodIndex(s.index, freq="M")
    full = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M"))
    prev = full.shift(12)
    yoy = pd.Series(np.where(prev > 0, full / prev - 1.0, np.nan), index=full.index, dtype=float)
    if pd.notna(yoy.iloc[-1]):
        out["rev_mom_yoy"] = float(yoy.iloc[-1])
    if len(yoy) >= 6:
        last3, prior3 = yoy.iloc[-3:], yoy.iloc[-6:-3]
        if not (bool(last3.isna().any()) or bool(prior3.isna().any())):
            out["rev_mom_accel"] = float(last3.mean() - prior3.mean())
    return out


def snapshot_row(
    symbol: str,
    ohlcv: pd.DataFrame,
    fund: pd.DataFrame,
    as_of: date,
    *,
    monthly: pd.DataFrame | None = None,
) -> dict[str, object]:
    """One snapshot row: technicals (from ``ohlcv``) + point-in-time fundamentals.

    Reused by both the cross-section builder (``screener.snapshot``) and the
    historical factor panel (``factors.panel``/``research.dataset``) so the
    metrics are identical. ``monthly`` is TW monthly-revenue rows (optional,
    market-neutral — omit for US or when unavailable): when provided,
    ``revenue_momentum_features`` is merged in; when ``None`` the
    ``rev_mom_*`` keys are absent entirely, not NaN-filled, so a US-only
    snapshot never carries a TW-only column.
    """
    nan = float("nan")
    f = _latest_annual(fund, as_of)
    tech = _technicals(ohlcv)
    g = f.get

    revenue, net_income = g("revenue", nan), g("net_income", nan)
    operating_income = g("operating_income", nan)
    pretax_income = g("pretax_income", nan)
    equity, shares = g("equity", nan), g("shares_outstanding", nan)
    cash, long_term_debt = g("cash", nan), g("long_term_debt", nan)
    dep_amort, interest_expense = g("dep_amort", nan), g("interest_expense", nan)
    fcf = g("cfo", nan) - g("capex", nan)
    market_cap = tech["price"] * shares if pd.notna(shares) else nan

    # Enterprise value & leverage. Missing debt/cash tags are treated as zero
    # (a debt-free filer simply reports no debt concept) — see `_or0`.
    net_debt = _or0(long_term_debt) - _or0(cash)
    ev = market_cap + net_debt
    ebitda = operating_income + dep_amort  # NaN unless both are reported
    invested_capital = equity + _or0(long_term_debt) - _or0(cash)
    # NOPAT = EBIT × (1 − effective tax), tax rate implied by net/pre-tax income.
    nopat = operating_income * _safe_div(net_income, pretax_income) if pretax_income > 0 else nan

    pe = _safe_div(market_cap, net_income) if net_income > 0 else nan
    eps_growth = _growth_yoy(fund, "eps_diluted", as_of)
    share_change = _growth_yoy(fund, "shares_outstanding", as_of)

    row: dict[str, object] = {
        "symbol": symbol,
        "as_of": pd.Timestamp(as_of),
        # Currency follows the market (US→USD, TW/TWO→TWD) — never assume USD, or a
        # Taiwan row's TWD figures get mislabeled and compared against US dollars.
        "currency": parse_symbol(symbol).currency,
        **tech,
        "market_cap": market_cap,
        "revenue": revenue,
        "net_income": net_income,
        "eps_diluted": g("eps_diluted", nan),
        "ebitda": ebitda,
        "equity": equity,
        "shares_outstanding": shares,
        "net_debt": net_debt,
        "ev": ev,
        "fcf": fcf,
        "pe": pe,
        "ps": _safe_div(market_cap, revenue),
        "peg": _safe_div(pe, eps_growth * 100.0)
        if pd.notna(eps_growth) and eps_growth > 0
        else nan,
        "ev_ebitda": _safe_div(ev, ebitda) if ebitda > 0 else nan,
        "ev_fcf": _safe_div(ev, fcf) if fcf > 0 else nan,
        "fcf_yield": _safe_div(fcf, market_cap),
        "net_margin": _safe_div(net_income, revenue),
        "gross_margin": _safe_div(g("gross_profit", nan), revenue),
        "operating_margin": _safe_div(operating_income, revenue),
        "fcf_margin": _safe_div(fcf, revenue),
        "roe": _safe_div(net_income, equity),
        "roic": _safe_div(nopat, invested_capital) if invested_capital > 0 else nan,
        "debt_to_equity": _safe_div(g("liabilities", nan), equity),
        "net_debt_to_ebitda": _safe_div(net_debt, ebitda) if ebitda > 0 else nan,
        "interest_coverage": _safe_div(operating_income, interest_expense)
        if interest_expense > 0
        else nan,
        "revenue_growth_yoy": _revenue_growth_yoy(fund, as_of),
        "eps_growth_yoy": eps_growth,
        "share_dilution_yoy": share_change,  # +ve = dilution, −ve = net buybacks
        "buyback_yield": -share_change if pd.notna(share_change) else nan,
        "fundamentals_asof": fund.loc[fund["filed_at"] <= pd.Timestamp(as_of), "filed_at"].max()
        if not fund.empty
        else pd.NaT,
    }
    if monthly is not None:
        row.update(revenue_momentum_features(monthly, pd.Timestamp(as_of)))
    return row
