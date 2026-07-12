"""The persisted research panel — one row per (rebalance month-end, symbol).

This is the dataset every experiment reads (``docs/ROADMAP_V2.md`` 7.3): all
``snapshot_row`` fields (point-in-time by construction), eligibility flags per
``docs/RESEARCH_PLAYBOOK.md`` §3, and forward labels ``fwd_1m/3m/6m`` plus their
benchmark-relative ``*_rel`` variants (§2). Signals never compute here — specs
score this panel later (8.x).

Honesty invariants baked in:

- **PIT**: rows are built by ``factors.metrics.snapshot_row`` with ``as_of`` =
  the rebalance date, so fundamentals are keyed on ``filed_at`` — the machinery
  is reused, not duplicated.
- **Labels**: both the stock and the benchmark leg go through the same
  ``research.benchmark`` primitives, so a ``*_rel`` subtraction covers one
  identical calendar window; incomplete windows are NaN, never partial.
- **Resume never rewrites history**: existing months are skipped (feature
  values are frozen at first write — later vendor restatements must not leak
  in, per ``data-discipline.md``), but still-NaN *labels* are refreshed, since
  they are pure future-price lookups that simply hadn't completed yet.
- **Thin months are dropped and reported** (``meta.dropped_months``), and every
  artifact carries the ``current_universe (optimistic)`` survivorship stamp.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from heimdall.data.base import DataProvider, NotSupported, ProviderError
from heimdall.data.providers.form4 import BUY_CODE, SELL_CODE
from heimdall.data.providers.tdcc import BIG_HOLDER_LEVELS
from heimdall.data.schema import FUNDAMENTALS_COLUMNS
from heimdall.data.store import data_root
from heimdall.factors.metrics import snapshot_row
from heimdall.factors.panel import _prices_wide, _rebalance_dates
from heimdall.research import gates
from heimdall.research.benchmark import BENCHMARK, forward_return, window_return

LABEL_COLS: list[str] = ["fwd_1m", "fwd_3m", "fwd_6m", "fwd_1m_rel", "fwd_3m_rel", "fwd_6m_rel"]
_MARKET_KEY: dict[str, str] = {"US": "us", "Taiwan": "tw"}


def panel_path(market: str, root: Path | None = None) -> Path:
    base = root if root is not None else data_root()
    return base / "research" / f"panel_{_MARKET_KEY[market]}.parquet"


def meta_path(market: str, root: Path | None = None) -> Path:
    p = panel_path(market, root)
    return p.with_name(f"{p.stem}.meta.json")


def load_panel(market: str, root: Path | None = None) -> pd.DataFrame:
    path = panel_path(market, root)
    if not path.exists():
        raise FileNotFoundError(f"no research panel at {path}; build one first")
    return pd.read_parquet(path)


def _save_atomic(df: pd.DataFrame, path: Path) -> None:
    """Temp + rename so a concurrent reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


@dataclass
class DatasetProgress:
    """Mutated and re-yielded per month — read live, don't collect."""

    total_months: int
    done_months: int = 0
    month: pd.Timestamp | None = None
    rows: int = 0
    eligible: int = 0
    dropped: list[str] = field(default_factory=list)  # thin months (ISO dates), this run
    relabeled: int = 0  # previously-NaN labels filled on resume
    failures: dict[str, int] = field(default_factory=dict)  # fetch errors, by exception name
    finished: bool = False


def _labels(
    adj: pd.Series, bench_adj: pd.Series, t: pd.Timestamp, next_t: pd.Timestamp | None
) -> dict[str, float]:
    nan = float("nan")
    f1 = window_return(adj, t, next_t) if next_t is not None else nan
    b1 = window_return(bench_adj, t, next_t) if next_t is not None else nan
    f3, b3 = forward_return(adj, t, 63), forward_return(bench_adj, t, 63)
    f6, b6 = forward_return(adj, t, 126), forward_return(bench_adj, t, 126)
    return {
        "fwd_1m": f1,
        "fwd_3m": f3,
        "fwd_6m": f6,
        "fwd_1m_rel": f1 - b1,
        "fwd_3m_rel": f3 - b3,
        "fwd_6m_rel": f6 - b6,
    }


_FLOW_KEYS = [
    "foreign_net_buy_21d",
    "foreign_net_buy_63d",
    "trust_net_buy_21d",
    "foreign_hold_delta_63d",
    "margin_delta_21d",
    "margin_short_delta_21d",
]


def _flow_features(
    chips: pd.DataFrame, price: pd.DataFrame, as_of: pd.Timestamp
) -> dict[str, float]:
    """TW chip/flow features — 法人籌碼 (roadmap 11.3), all keyed to *t−1* data.

    ``chips`` is ``FinMindProvider.daily_chips`` output. The **+1 trading-day
    shift** is the point-in-time guard: these streams are published after day
    *d*'s close, so a rebalance at ``as_of`` may read only rows dated *strictly
    before* it (``date < as_of``). Features (window = trading days):

    - ``foreign_net_buy_21d`` / ``_63d`` — Σ(net foreign shares × close) over the
      window ÷ its median daily dollar volume (a signed "days of turnover" of net
      foreign accumulation; higher = stronger buying);
    - ``trust_net_buy_21d`` — the same for投信 (trust) flow;
    - ``foreign_hold_delta_63d`` — percentage-point change in the foreign holding
      ratio over 63 trading days;
    - ``margin_delta_21d`` — %-change in the margin **buy** balance (融資) over 21
      trading days (prior direction **negative**: rising retail leverage is
      crowding);
    - ``margin_short_delta_21d`` — %-change in the margin **short** balance (融券)
      over 21 trading days (roadmap 17.1); prior direction **negative**, but
      weaker/ambiguous than the buy side — retail short covering is partly
      squeeze fuel (record this ambiguity in the 17.2 log entry).

    Each feature reads the last N *available* observations within the ``< as_of``
    window (daily gaps are rare data noise, unlike a missing revenue month — the
    look-ahead guard is the shift, not window-completeness); a feature is NaN only
    when fewer than N observations exist or its liquidity denominator is ≤ 0.
    """
    out = {k: float("nan") for k in _FLOW_KEYS}
    if chips.empty:
        return out
    usable = chips[chips["date"] < as_of]  # +1 trading-day guard: row t sees ≤ t−1 only
    if usable.empty:
        return out
    m = usable.merge(price[["date", "close", "volume"]], on="date", how="inner").sort_values("date")
    if m.empty:
        return out

    def _net_buy(col: str, n: int) -> float:
        sub = m.dropna(subset=[col, "close", "volume"])
        if len(sub) < n:
            return float("nan")
        sub = sub.tail(n)
        num = float((sub[col].to_numpy(float) * sub["close"].to_numpy(float)).sum())
        med = float(np.median((sub["close"] * sub["volume"]).to_numpy(float)))
        return num / med if med > 0 else float("nan")

    out["foreign_net_buy_21d"] = _net_buy("foreign_net_shares", 21)
    out["foreign_net_buy_63d"] = _net_buy("foreign_net_shares", 63)
    out["trust_net_buy_21d"] = _net_buy("trust_net_shares", 21)

    hold = m["foreign_hold_ratio"].dropna().to_numpy(float)
    if len(hold) >= 64:  # need a value 63 trading days back
        out["foreign_hold_delta_63d"] = float(hold[-1] - hold[-64])

    margin = m["margin_balance"].dropna().to_numpy(float)
    if len(margin) >= 22 and margin[-22] > 0:
        out["margin_delta_21d"] = float(margin[-1] / margin[-22] - 1.0)

    margin_short = m["margin_short_balance"].dropna().to_numpy(float)
    if len(margin_short) >= 22 and margin_short[-22] > 0:
        out["margin_short_delta_21d"] = float(margin_short[-1] / margin_short[-22] - 1.0)
    return out


_LENDING_KEYS = ["sbl_short_delta_21d", "sbl_short_delta_63d"]


def _lending_features(
    lending: pd.DataFrame, price: pd.DataFrame, as_of: pd.Timestamp
) -> dict[str, float]:
    """TW securities-lending short-balance features — 借券賣出 (roadmap 17.1), the
    informed sell-side counterpart to ``_flow_features``'s buy-side flows. Same
    **+1 trading-day** point-in-time shift (test the shift): a rebalance at
    ``as_of`` may read only ``lending`` rows dated strictly before it.

    ``lending`` is ``FinMindProvider.daily_lending`` output.

    - ``sbl_short_delta_21d`` / ``_63d`` — Δ(``sbl_short_balance``) over the
      window (last minus first of the ``n + 1``-observation span) × the window's
      last close ÷ the window's median daily dollar volume — the ``_net_buy``
      scaling pattern, applied to a level-delta instead of a windowed sum (the
      ``foreign_hold_delta_63d`` precedent). A signed "days of turnover" of the
      *change* in securities-lending short interest. Direction **−** (rising
      informed short pressure).

    A feature is NaN when fewer than ``n + 1`` observations exist or its
    liquidity denominator is ≤ 0.
    """
    out = {k: float("nan") for k in _LENDING_KEYS}
    if lending.empty:
        return out
    usable = lending[lending["date"] < as_of]  # +1 trading-day guard, same as _flow_features
    if usable.empty:
        return out
    m = usable.merge(price[["date", "close", "volume"]], on="date", how="inner").sort_values("date")
    if m.empty:
        return out

    def _delta(n: int) -> float:
        sub = m.dropna(subset=["sbl_short_balance", "close", "volume"])
        if len(sub) < n + 1:  # n+1 points span an n-trading-day change
            return float("nan")
        window = sub.tail(n + 1)
        delta_shares = float(
            window["sbl_short_balance"].iloc[-1] - window["sbl_short_balance"].iloc[0]
        )
        recent = window.tail(n)  # the _net_buy-style n-day window for the volume denominator
        med = float(np.median((recent["close"] * recent["volume"]).to_numpy(float)))
        close_now = float(window["close"].iloc[-1])
        return (delta_shares * close_now) / med if med > 0 else float("nan")

    out["sbl_short_delta_21d"] = _delta(21)
    out["sbl_short_delta_63d"] = _delta(63)
    return out


_INSIDER_KEYS = ["insider_net_buy_90d", "insider_cluster_buy"]
_INSIDER_WINDOW_DAYS = 90
_CLUSTER_MIN_BUYERS = 3  # ≥3 distinct officer/director buyers in the window = a cluster buy


def _insider_features(
    insider: pd.DataFrame, as_of: pd.Timestamp, market_cap: float
) -> dict[str, float]:
    """US insider-transaction features — SEC Form 4 (roadmap 12.4/13.3), the honest
    "smart money" axis. Keyed on ``filed_at`` (never ``txn_date``): a rebalance at
    ``as_of`` may read only Form 4s **filed** on/before it — the same point-in-time
    convention as EDGAR fundamentals (both are SEC filings). The trade itself
    happened up to two business days earlier, but was not *knowable* until filed
    (the **PIT leak test is mandatory** — a filing after ``as_of`` must not move
    this row).

    ``insider`` is one symbol's ``Form4Provider.get_insider_transactions`` output.
    Officer/director rows only (a 10%-owner-only filer is excluded). Over the
    trailing ``_INSIDER_WINDOW_DAYS`` (90 calendar days, ``lo < filed_at ≤ as_of``):

    - ``insider_net_buy_90d`` — (Σ open-market **buys** ``P`` − Σ open-market
      **sells** ``S``, each ``shares × price``) ÷ ``market_cap``. Direction **+**
      (net insider buying is bullish). NaN only when the market-cap denominator is
      unusable; a populated stream with no in-window open-market trade is a
      genuine **0** (no net buying), not missing data.
    - ``insider_cluster_buy`` — 1.0 when ≥ ``_CLUSTER_MIN_BUYERS`` *distinct*
      officers/directors made an open-market purchase in the window, else 0.0 (the
      cluster-buy literature's higher-conviction subset). Independent of
      market cap.

    Both keys are absent from a symbol with **no** insider data at all (empty
    frame → NaN), so US rows built without the Form 4 stream simply do not carry
    these columns (mirroring the other optional-stream features).
    """
    out = {k: float("nan") for k in _INSIDER_KEYS}
    if insider.empty:
        return out
    lo = as_of - pd.Timedelta(days=_INSIDER_WINDOW_DAYS)
    role = insider["is_officer"].to_numpy(bool) | insider["is_director"].to_numpy(bool)
    win = insider[(insider["filed_at"] <= as_of) & (insider["filed_at"] > lo) & role]
    buys = win[win["txn_code"] == BUY_CODE]
    sells = win[win["txn_code"] == SELL_CODE]
    out["insider_cluster_buy"] = float(buys["owner_cik"].nunique() >= _CLUSTER_MIN_BUYERS)
    if pd.notna(market_cap) and market_cap > 0:
        buy_usd = float((buys["shares"] * buys["price_per_share"]).sum())
        sell_usd = float((sells["shares"] * sells["price_per_share"]).sum())
        out["insider_net_buy_90d"] = (buy_usd - sell_usd) / market_cap
    return out


_PEAD_KEYS = ["sue", "earn_gap"]
_SUE_MIN_OBS = 8  # need 8 YoY surprises before a standardized value is meaningful
_EARN_GAP_LOOKBACK_BARS = 65  # ~one quarter; PEAD drift is spent past this


def _annual_yoy_pct(fund: pd.DataFrame, metric: str, as_of: pd.Timestamp) -> float:
    """YoY % change of an annual ``metric`` (latest vs prior fiscal year),
    point-in-time on ``filed_at``. Mirrors ``factors.metrics._growth_yoy`` exactly
    (dedup per fiscal year, base must be > 0) so ``net_issuance_12m`` is identical
    to the snapshot's ``share_dilution_yoy``."""
    s = fund[(fund["metric"] == metric) & (fund["filed_at"] <= as_of)]
    if s.empty:
        return float("nan")
    per_year = (
        s.sort_values(["fiscal_end", "filed_at"]).groupby("fiscal_end").tail(1)
    ).sort_values("fiscal_end")
    if len(per_year) < 2:
        return float("nan")
    prev, last = float(per_year["value"].iloc[-2]), float(per_year["value"].iloc[-1])
    return last / prev - 1.0 if prev > 0 else float("nan")


def _seasonal_yoy_changes(per_q: pd.Series) -> list[float]:
    """Per-quarter YoY EPS changes (EPS_q − EPS_same-quarter-last-year), in
    fiscal-end order. US 10-Ks file **no discrete Q4** (verified 2026-07-12: EDGAR
    carries only 3 discrete quarterly ``eps_diluted`` rows/year — Q4 lives in the
    annual FY figure), so a *positional* "4 rows back" would pair mismatched
    quarters. Each quarter is instead matched to the row ~365 days earlier (span in
    ``[300, 430]`` days, nearest to a year), which is robust to both the 3/year
    cadence and the day-level fiscal-end drift (e.g. Apple's Dec-30 → Dec-28)."""
    idx = list(per_q.index)
    vals = [float(v) for v in per_q.to_numpy()]
    changes: list[float] = []
    for i in range(len(idx)):
        best_j, best_gap = None, None
        for j in range(i):
            span = (idx[i] - idx[j]).days
            if 300 <= span <= 430:
                gap = abs(span - 365)
                if best_gap is None or gap < best_gap:
                    best_gap, best_j = gap, j
        if best_j is not None:
            changes.append(vals[i] - vals[best_j])
    return changes


def _pead_features(
    fund_annual: pd.DataFrame,
    fund_quarter: pd.DataFrame,
    price: pd.DataFrame,
    bench_adj: pd.Series,
    as_of: pd.Timestamp,
) -> dict[str, float]:
    """US post-earnings-drift features — estimate-free PEAD (roadmap 13.4), keyed
    on ``filed_at`` (never fiscal-period end): a rebalance at ``as_of`` reads only
    filings knowable by then (the **PIT leak test is mandatory**).

    - ``sue`` — standardized unexpected earnings: the latest quarterly
      seasonal EPS surprise (EPS_q − EPS_same-quarter-prior-year) ÷ the standard
      deviation of the last ``_SUE_MIN_OBS`` such surprises. NaN with fewer than
      8 surprises or a zero-variance denominator. Direction **+** (positive
      surprises drift up). The ``ddof`` of the std is immaterial — with a fixed
      8-observation window it is a uniform scale on every stock's denominator, so
      cross-sectional ranking is unchanged; ``np.std`` (population) is used.
    - ``earn_gap`` — the announcement reaction: the (stock − benchmark) one-bar
      return on the first trading bar on/after the latest EPS filing (annual **or**
      quarterly — the 10-K carries Q4's earnings), provided that reaction bar falls
      within the past ``_EARN_GAP_LOOKBACK_BARS`` trading days of ``as_of``. NaN
      when there is no recent filing or no prior bar to measure the jump against.
      Direction **+** (the initial reaction continues as drift). The filing date is
      a conservative, PIT-safe proxy for the earlier press-release date, which
      EDGAR does not expose.
    """
    out = {k: float("nan") for k in _PEAD_KEYS}

    # -- sue --------------------------------------------------------------------
    q = fund_quarter[
        (fund_quarter["metric"] == "eps_diluted") & (fund_quarter["filed_at"] <= as_of)
    ]
    if not q.empty:
        per_q = (
            q.sort_values(["fiscal_end", "filed_at"]).groupby("fiscal_end")["value"].last()
        ).sort_index()
        changes = _seasonal_yoy_changes(per_q)
        if len(changes) >= _SUE_MIN_OBS:
            last8 = np.asarray(changes[-_SUE_MIN_OBS:], dtype=float)
            sd = float(np.std(last8))
            if sd > 0:
                out["sue"] = float(last8[-1]) / sd

    # -- earn_gap ---------------------------------------------------------------
    def _eps_filings(fund: pd.DataFrame) -> pd.Series:
        m = fund[(fund["metric"] == "eps_diluted") & (fund["filed_at"] <= as_of)]
        return m["filed_at"]

    parts = [s for s in (_eps_filings(fund_annual), _eps_filings(fund_quarter)) if not s.empty]
    filings = pd.concat(parts) if parts else pd.Series(dtype="datetime64[ns]")
    if not filings.empty and not price.empty:
        latest_filed = pd.Timestamp(filings.max())
        px = price[price["date"] <= as_of].sort_values("date").reset_index(drop=True)
        after = px.index[px["date"] >= latest_filed]
        if len(after) and after[0] >= 1 and (len(px) - 1 - after[0]) <= _EARN_GAP_LOOKBACK_BARS:
            b = int(after[0])
            d0, d1 = px["date"].iloc[b - 1], px["date"].iloc[b]
            p0, p1 = float(px["adj_close"].iloc[b - 1]), float(px["adj_close"].iloc[b])
            bench0 = float(bench_adj.asof(d0))  # type: ignore[arg-type]
            bench1 = float(bench_adj.asof(d1))  # type: ignore[arg-type]
            if p0 > 0 and bench0 > 0:
                out["earn_gap"] = (p1 / p0 - 1.0) - (bench1 / bench0 - 1.0)
    return out


_ISSUANCE_KEYS = ["net_issuance_12m", "asset_growth", "gross_profitability"]


def _issuance_quality_features(fund_annual: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """US issuance / asset-growth / quality features (roadmap 13.5) — three free
    annual-EDGAR axes, all ``filed_at``-keyed (**PIT leak test mandatory**),
    orthogonal to the already-tested roic/margin set.

    - ``net_issuance_12m`` — YoY % change in ``shares_outstanding``. Direction
      **−** (issuance dilutes; buybacks reward). *Numerically identical to the
      snapshot's ``share_dilution_yoy``* (same ``_annual_yoy_pct`` math); kept as an
      explicitly named member of the ``us-issuance-quality`` family (roadmap 13.6).
    - ``asset_growth`` — YoY % change in ``assets``. Direction **−** (the
      asset-growth anomaly: aggressive expanders underperform).
    - ``gross_profitability`` — ``gross_profit ÷ assets`` (Novy-Marx). Direction
      **+**. NaN when the ``GrossProfit`` tag is absent (coverage honesty over
      completeness — never derived from revenue − COGS, which isn't normalized).
    """
    out = {k: float("nan") for k in _ISSUANCE_KEYS}
    out["net_issuance_12m"] = _annual_yoy_pct(fund_annual, "shares_outstanding", as_of)
    out["asset_growth"] = _annual_yoy_pct(fund_annual, "assets", as_of)

    known = fund_annual[fund_annual["filed_at"] <= as_of]
    if not known.empty:
        latest = known.sort_values(["fiscal_end", "filed_at"]).groupby("metric").tail(1)
        vals = {str(m): float(v) for m, v in zip(latest["metric"], latest["value"], strict=True)}
        gp, assets = vals.get("gross_profit", float("nan")), vals.get("assets", float("nan"))
        if pd.notna(gp) and pd.notna(assets) and assets > 0:
            out["gross_profitability"] = gp / assets
    return out


_BIG_HOLDER_KEY = "big_holder_ratio_delta_4w"


def _big_holder_features(
    tdcc_weeks: pd.DataFrame, symbol: str, as_of: pd.Timestamp
) -> dict[str, float]:
    """TW big-holder concentration feature — 集保大戶 (roadmap 13.9), keyed to
    ``available_at`` (never ``data_date``) for point-in-time correctness: a
    rebalance at ``as_of`` may only read weekly TDCC files already available
    by then (the **PIT leak test is mandatory** — a week published after
    ``as_of`` must not move this feature).

    ``tdcc_weeks`` is ``data.providers.tdcc.load_cached_weeks()`` output — every
    accumulated weekly file, all symbols, concatenated (there is no per-symbol
    fetch for TDCC; the caller loads the whole cache once).

    - ``big_holder_ratio_delta_4w`` — percentage-point change in the ≥400-lot
      (大戶, ``BIG_HOLDER_LEVELS``) share of TDCC custody, from the oldest to
      the newest of the last **4** *available* weekly files for this symbol
      (not a fixed calendar window — "4 weekly files", per the card). Direction
      prior **+**: rising concentration is read as large-holder accumulation.
      NaN with fewer than 4 available weeks.
    """
    out = {_BIG_HOLDER_KEY: float("nan")}
    if tdcc_weeks.empty:
        return out
    mine = tdcc_weeks[(tdcc_weeks["symbol"] == symbol) & (tdcc_weeks["available_at"] <= as_of)]
    if mine.empty:
        return out
    big = (
        mine[mine["level"].isin(BIG_HOLDER_LEVELS)]
        .groupby("data_date")["pct_of_custody"]
        .sum()
        .sort_index()
    )
    if len(big) < 4:
        return out
    last4 = big.tail(4)
    out[_BIG_HOLDER_KEY] = float(last4.iloc[-1] - last4.iloc[0])
    return out


def _eligibility(market: str, n_bars: int, raw_close: float, dollar_vol: float) -> tuple[bool, str]:
    """Playbook §3 hygiene; first failing reason wins. NaN inputs fail their check."""
    if n_bars < gates.MIN_HISTORY_BARS:
        return False, "history"
    if not raw_close >= gates.MIN_PRICE[market]:  # NaN-safe: not (NaN >= x) → ineligible
        return False, "price"
    if not dollar_vol >= gates.MIN_DOLLAR_VOL_21D[market]:
        return False, "liquidity"
    return True, ""


def build_dataset_iter(
    symbols: list[str],
    prices: DataProvider,
    fundamentals: DataProvider,
    market: str,
    start: date,
    end: date,
    *,
    root: Path | None = None,
    resume: bool = True,
    min_cross_section: int = gates.MIN_CROSS_SECTION,
    checkpoint_every: int = 6,
    monthly_revenue: Callable[[str, date, date], pd.DataFrame] | None = None,
    daily_chips: Callable[[str, date, date], pd.DataFrame] | None = None,
    daily_lending: Callable[[str, date, date], pd.DataFrame] | None = None,
    tdcc_weeks: pd.DataFrame | None = None,
    insider: Callable[[str, date, date], pd.DataFrame] | None = None,
    quarterly_fundamentals: Callable[[str, date, date], pd.DataFrame] | None = None,
) -> Iterator[DatasetProgress]:
    """Build (or extend) the panel month by month, yielding progress per month.

    Fetches each symbol's full price/fundamental history once (delta-cached by
    the providers), then computes only the rebalance months not already in the
    parquet. Yields an initial plan row, one row per month, and a final
    ``finished=True`` row after the label-refresh pass and meta write.
    """
    bench_adj = prices.get_ohlcv(BENCHMARK[market], start - timedelta(days=500), end).set_index(
        "date"
    )["adj_close"]

    price_hist: dict[str, pd.DataFrame] = {}
    adj_by_sym: dict[str, pd.Series] = {}
    fund_data: dict[str, pd.DataFrame] = {}
    failures: dict[str, int] = {}
    for sym in symbols:
        try:
            ohlcv = prices.get_ohlcv(sym, start - timedelta(days=500), end)
        except Exception as exc:  # a broken symbol must not kill a long crawl
            failures[type(exc).__name__] = failures.get(type(exc).__name__, 0) + 1
            continue
        if ohlcv.empty:
            continue
        price_hist[sym] = ohlcv
        adj_by_sym[sym] = ohlcv.set_index("date")["adj_close"]
        try:
            fund_data[sym] = fundamentals.get_fundamentals(sym, "all", "annual")
        except (ProviderError, NotSupported):
            fund_data[sym] = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)

    # Optional third stream (TW): monthly revenue for the 11.2 momentum features.
    # Injected as a callable so the core stays market-neutral — the CLI routes it.
    rev_hist: dict[str, pd.DataFrame] = {}
    if monthly_revenue is not None:
        for sym in price_hist:
            try:  # ~19 months of warm-up needed for rev_mom_accel's YoY windows
                rev_hist[sym] = monthly_revenue(sym, start - timedelta(days=650), end)
            except (ProviderError, NotSupported):
                rev_hist[sym] = pd.DataFrame()

    # Optional fourth stream (TW): daily chip/flow data for the 11.3 features.
    # ~250 days of warm-up covers the 63-trading-day windows before the first month.
    chips_hist: dict[str, pd.DataFrame] = {}
    if daily_chips is not None:
        for sym in price_hist:
            try:
                chips_hist[sym] = daily_chips(sym, start - timedelta(days=250), end)
            except (ProviderError, NotSupported):
                chips_hist[sym] = pd.DataFrame()

    # Optional fifth stream (TW): daily securities-lending short balance for the
    # 17.1 sell-side features. Same 250-day warm-up as the chips stream (same
    # daily cadence, same 63-trading-day max window).
    lending_hist: dict[str, pd.DataFrame] = {}
    if daily_lending is not None:
        for sym in price_hist:
            try:
                lending_hist[sym] = daily_lending(sym, start - timedelta(days=250), end)
            except (ProviderError, NotSupported):
                lending_hist[sym] = pd.DataFrame()

    # Optional US stream: SEC Form 4 insider transactions for the 12.4/13.3
    # features. ~180-day warm-up safely covers the 90-day trailing window before
    # the first rebalance; the provider caches per issuer, so this is one crawl
    # per symbol, not per month.
    insider_hist: dict[str, pd.DataFrame] = {}
    if insider is not None:
        for sym in price_hist:
            try:
                insider_hist[sym] = insider(sym, start - timedelta(days=180), end)
            except (ProviderError, NotSupported):
                insider_hist[sym] = pd.DataFrame()

    # Optional US stream: quarterly fundamentals — the extra data the 13.4 PEAD
    # ``sue`` feature needs (annual rows, already fetched above, cover 13.5's
    # issuance/quality set and PEAD's Q4/10-K earnings dates). Its presence is the
    # US-fundamentals-feature switch: absent ⇒ neither the PEAD nor the
    # issuance/quality columns exist (mirroring the other optional streams).
    fund_q: dict[str, pd.DataFrame] = {}
    if quarterly_fundamentals is not None:
        for sym in price_hist:
            try:
                fund_q[sym] = quarterly_fundamentals(sym, start, end)
            except (ProviderError, NotSupported):
                fund_q[sym] = pd.DataFrame(columns=FUNDAMENTALS_COLUMNS)

    # Existing panel + meta: resume skips computed months AND previously-dropped ones.
    existing = pd.DataFrame()
    old_meta: dict[str, object] = {}
    if resume:
        with contextlib.suppress(FileNotFoundError):
            existing = load_panel(market, root)
        if meta_path(market, root).exists():
            old_meta = json.loads(meta_path(market, root).read_text())
    prior_dropped = set(cast("list[str]", old_meta.get("dropped_months", [])))
    have = set(existing["date"]) if not existing.empty else set()

    # Rebalance calendar over the union of trading days; extend back to the earliest
    # existing month so the label-refresh pass can find every month's successor.
    wide = _prices_wide(price_hist) if price_hist else pd.DataFrame()
    cal_start = min([start, *[d.date() for d in have]]) if have else start
    rebal = (
        _rebalance_dates(wide.index, cal_start, end, "ME")  # type: ignore[arg-type]
        if not wide.empty
        else []
    )
    next_of: dict[pd.Timestamp, pd.Timestamp | None] = {
        t: (rebal[i + 1] if i + 1 < len(rebal) else None) for i, t in enumerate(rebal)
    }
    todo = [
        t
        for t in rebal
        if pd.Timestamp(t) >= pd.Timestamp(start)
        and t not in have
        and t.date().isoformat() not in prior_dropped
    ]

    prog = DatasetProgress(total_months=len(todo), failures=failures)
    yield prog

    frames: list[pd.DataFrame] = [existing] if not existing.empty else []
    for i, t in enumerate(todo, start=1):
        rows: list[dict[str, object]] = []
        for sym, ohlcv in price_hist.items():
            hist = ohlcv[ohlcv["date"] <= t]
            if hist.empty:
                continue
            monthly = rev_hist.get(sym, pd.DataFrame()) if monthly_revenue is not None else None
            row = snapshot_row(sym, hist, fund_data[sym], t.date(), monthly=monthly)
            row.update(_labels(adj_by_sym[sym], bench_adj, t, next_of[t]))
            if daily_chips is not None:
                row.update(_flow_features(chips_hist.get(sym, pd.DataFrame()), ohlcv, t))
            if daily_lending is not None:
                row.update(_lending_features(lending_hist.get(sym, pd.DataFrame()), ohlcv, t))
            if insider is not None:
                row.update(
                    _insider_features(
                        insider_hist.get(sym, pd.DataFrame()),
                        t,
                        float(row["market_cap"]),  # type: ignore[arg-type]
                    )
                )
            if quarterly_fundamentals is not None:
                fq = fund_q.get(sym, pd.DataFrame(columns=FUNDAMENTALS_COLUMNS))
                row.update(_pead_features(fund_data[sym], fq, ohlcv, bench_adj, t))
                row.update(_issuance_quality_features(fund_data[sym], t))
            if tdcc_weeks is not None:
                row.update(_big_holder_features(tdcc_weeks, sym, t))
            ok, why = _eligibility(
                market,
                len(hist),
                float(hist["close"].iloc[-1]),
                float(row["dollar_vol_21d"]),  # type: ignore[arg-type]
            )
            row["date"] = t
            row["eligible"] = ok
            row["inelig_reason"] = why
            rows.append(row)

        n_eligible = sum(1 for r in rows if r["eligible"])
        prog.done_months, prog.month, prog.rows, prog.eligible = i, t, len(rows), n_eligible
        if n_eligible < min_cross_section:
            prog.dropped.append(t.date().isoformat())  # dropped and reported, never kept
            yield prog
            continue
        frames.append(pd.DataFrame(rows))
        if i % checkpoint_every == 0 and frames:
            _save_atomic(pd.concat(frames, ignore_index=True), panel_path(market, root))
        yield prog

    panel = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # Label refresh: fill labels that were NaN because their forward window hadn't
    # completed. Labels only — feature columns stay frozen at first write (PIT).
    if not panel.empty:
        stale = panel["fwd_6m"].isna() | panel["fwd_1m"].isna()
        for idx in panel.index[stale]:
            sym = str(panel.loc[idx, "symbol"])
            if sym not in adj_by_sym:
                continue  # symbol gone from the provider — keep what we have
            t = pd.Timestamp(panel.loc[idx, "date"])
            fresh = _labels(adj_by_sym[sym], bench_adj, t, next_of.get(t))
            for col in LABEL_COLS:
                if pd.isna(panel.loc[idx, col]) and pd.notna(fresh[col]):
                    panel.loc[idx, col] = fresh[col]
                    prog.relabeled += 1
        panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
        _save_atomic(panel, panel_path(market, root))
    if not panel.empty or prog.dropped or prior_dropped:
        # Meta is written even when every month was dropped — the dropped record is
        # what lets a resume skip those months instead of rebuilding them forever.
        _write_meta(panel, market, root, symbols, prior_dropped | set(prog.dropped), prog)

    prog.finished = True
    yield prog


def _write_meta(
    panel: pd.DataFrame,
    market: str,
    root: Path | None,
    symbols: list[str],
    dropped: set[str],
    prog: DatasetProgress,
) -> None:
    if panel.empty:
        months: list[str] = []
        per_month: dict[str, int] = {}
    else:
        counts = panel.groupby("date")["eligible"].sum()
        months = [cast("pd.Timestamp", d).date().isoformat() for d in counts.index]
        per_month = {cast("pd.Timestamp", d).date().isoformat(): int(n) for d, n in counts.items()}
    meta = {
        "built_at": datetime.now(UTC).isoformat(),
        "market": market,
        "months": months,
        "eligible_per_month": per_month,
        "dropped_months": sorted(dropped),
        "universe_size": len(symbols),
        "labels_refreshed": prog.relabeled,
        # Today's constituents only — certified numbers built on this are optimistic
        # upper bounds and must carry this stamp (docs/NORTH_STAR.md).
        "survivorship": "current_universe (optimistic)",
    }
    path = meta_path(market, root)
    path.parent.mkdir(parents=True, exist_ok=True)  # no parquet is written when all months drop
    path.write_text(json.dumps(meta, indent=2))
