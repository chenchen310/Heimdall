"""US research features shared by the research panel and the live snapshot (roadmap 18.16).

Moved verbatim from ``research/dataset.py`` so there is **one home**: the panel builder
(``research.dataset``) and the live snapshot builder (``screener.snapshot``) call the same
functions, so a certified or incubating strategy that uses these columns ranks identically
whether it is being backtested or scored on today's data. ``screener`` may not import
``research`` (the one-way layer rule), which is why they live in ``factors``.

Every function is point-in-time on ``filed_at`` (SEC filing dates), never on fiscal-period end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from heimdall.data.providers.form4 import BUY_CODE, SELL_CODE

_INSIDER_KEYS = ["insider_net_buy_90d", "insider_cluster_buy"]
_INSIDER_WINDOW_DAYS = 90
_CLUSTER_MIN_BUYERS = 3  # ≥3 distinct officer/director buyers in the window = a cluster buy


def _insider_features(
    insider: pd.DataFrame,
    as_of: pd.Timestamp,
    market_cap: float,
    coverage_end: pd.Timestamp | None = None,
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

    ``coverage_end`` (18.13) is the last filing date the bulk Form 4 data sets cover: a
    month after it would read "no trades" as a genuine 0, so it is NaN instead — an
    uncovered window is missing data, not an absence of insider activity.
    """
    out = {k: float("nan") for k in _INSIDER_KEYS}
    if insider.empty or (coverage_end is not None and as_of > coverage_end):
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


_ACCEL_KEYS = ["rev_accel_q", "gross_margin_delta_q"]
_ACCEL_MIN_QUARTERS = 9  # ≥9 usable quarterly revenue obs before an acceleration is meaningful
_ACCEL_MIN_YOY = 5  # latest rev_yoy_q + the prior 4 it is compared against
_SEASON_LO_DAYS = 320  # ~365 − 45: same-quarter-a-year-ago match tolerance (roadmap 17.4 step 1)
_SEASON_HI_DAYS = 410  # ~365 + 45
_FY_SPAN_DAYS = 330  # a fiscal year's three prior discrete quarters all end within this window


def _seasonal_prior(fiscal_ends: list[pd.Timestamp], i: int) -> int | None:
    """Position of the discrete quarter ~one year before ``fiscal_ends[i]`` (span in
    ``[320, 410]`` days, nearest to 365), or ``None``. US files 3 discrete quarters a
    year (Q4 lives in the 10-K), so a *positional* q−4 would misalign seasons; matching
    by fiscal-end **date** is robust to the 3/year cadence and to fiscal-year day drift."""
    best_j, best_gap = None, None
    for j in range(i):
        span = (fiscal_ends[i] - fiscal_ends[j]).days
        if _SEASON_LO_DAYS <= span <= _SEASON_HI_DAYS:
            gap = abs(span - 365)
            if best_gap is None or gap < best_gap:
                best_gap, best_j = gap, j
    return best_j


def _discrete_quarters(
    fund_annual: pd.DataFrame, fund_quarter: pd.DataFrame, metric: str, as_of: pd.Timestamp
) -> pd.DataFrame:
    """Discrete-quarter ``metric`` rows (columns ``fiscal_end``/``value``/``filed_at``),
    point-in-time (``filed_at ≤ as_of``), deduped per fiscal_end (latest filing wins).

    Fiscal **Q4 is derived** as ``FY − (Q1+Q2+Q3)`` wherever a discrete Q4 is absent but
    the FY row and exactly the three prior discrete quarters of that fiscal year all
    exist (roadmap 17.4 step 4 — the derivation lives here, in the feature builder, so
    providers stay as-reported). The derived Q4's ``filed_at`` is the FY row's: the
    residual is knowable only once the 10-K is filed, so it inherits the 10-K's date and
    the ``filed_at ≤ as_of`` filter above already makes it point-in-time.
    """
    q = fund_quarter[(fund_quarter["metric"] == metric) & (fund_quarter["filed_at"] <= as_of)]
    disc = (
        q.sort_values(["fiscal_end", "filed_at"])
        .groupby("fiscal_end")
        .tail(1)
        .loc[:, ["fiscal_end", "value", "filed_at"]]
    )
    a = fund_annual[(fund_annual["metric"] == metric) & (fund_annual["filed_at"] <= as_of)]
    a = a.sort_values(["fiscal_end", "filed_at"]).groupby("fiscal_end").tail(1)
    have = set(disc["fiscal_end"])
    q_by_fe = disc.set_index("fiscal_end")["value"]
    derived: list[dict[str, object]] = []
    for _, fy in a.iterrows():
        fe = pd.Timestamp(fy["fiscal_end"])
        if fe in have:  # a real discrete Q4 is already present — never synthesize over it
            continue
        lo = fe - pd.Timedelta(days=_FY_SPAN_DAYS)
        prior = q_by_fe[(q_by_fe.index < fe) & (q_by_fe.index > lo)]
        if len(prior) == 3:  # exactly the fiscal year's Q1–Q3
            derived.append(
                {
                    "fiscal_end": fe,
                    "value": float(fy["value"]) - float(prior.sum()),
                    "filed_at": pd.Timestamp(fy["filed_at"]),
                }
            )
    if derived:
        disc = pd.concat([disc, pd.DataFrame(derived)], ignore_index=True)
    return disc.sort_values("fiscal_end").reset_index(drop=True)


def _accel_features(
    fund_annual: pd.DataFrame, fund_quarter: pd.DataFrame, as_of: pd.Timestamp
) -> dict[str, float]:
    """US fundamental-acceleration features (roadmap 17.4) — the economics of the
    program's one certified signal (TW monthly-revenue **acceleration**, entry 009)
    ported to the US on free EDGAR 10-Q data: fundamentals improving *faster than
    before*. Keyed on ``filed_at`` (never fiscal-period end): a rebalance at ``as_of``
    reads only filings knowable by then (the **PIT leak test is mandatory**).

    - ``rev_accel_q`` — the latest quarterly YoY revenue growth minus the mean of the
      prior 4 such growths, where each YoY growth pairs a quarter with the discrete
      quarter ~one year earlier (``_seasonal_prior``). NaN with fewer than
      ``_ACCEL_MIN_QUARTERS`` usable quarterly revenue observations (or fewer than
      ``_ACCEL_MIN_YOY`` computable YoY growths). Direction **+** (accelerating growth).
    - ``gross_margin_delta_q`` — (gross_profit ÷ revenue) of the latest discrete quarter
      minus the same ratio a year earlier, in **percentage points**. NaN when the
      ``GrossProfit`` tag is absent (coverage honesty — never derived from
      revenue − COGS, the 13.5 precedent) or no seasonal match exists. Direction **+**.

    Both use ``_discrete_quarters`` (which derives a missing fiscal Q4 from the 10-K),
    so a full four-quarter-a-year series is available where the FY figure permits.
    """
    out = {k: float("nan") for k in _ACCEL_KEYS}

    rev = _discrete_quarters(fund_annual, fund_quarter, "revenue", as_of)
    if len(rev) >= _ACCEL_MIN_QUARTERS:
        fes = list(rev["fiscal_end"])
        vals = rev["value"].to_numpy(float)
        yoy: list[float] = []
        for i in range(len(fes)):
            j = _seasonal_prior(fes, i)
            if j is not None and vals[j] > 0:
                yoy.append(float(vals[i] / vals[j] - 1.0))
        if len(yoy) >= _ACCEL_MIN_YOY:
            out["rev_accel_q"] = yoy[-1] - float(np.mean(yoy[-_ACCEL_MIN_YOY:-1]))

    gp = _discrete_quarters(fund_annual, fund_quarter, "gross_profit", as_of)
    if not gp.empty and not rev.empty:
        merged = rev.merge(gp, on="fiscal_end", suffixes=("_rev", "_gp"))
        merged = merged[merged["value_rev"] > 0].sort_values("fiscal_end")
        if len(merged) >= 2:
            fes = list(merged["fiscal_end"])
            margin = (merged["value_gp"] / merged["value_rev"]).to_numpy(float)
            j = _seasonal_prior(fes, len(fes) - 1)
            if j is not None:
                out["gross_margin_delta_q"] = float(margin[-1] - margin[j]) * 100.0
    return out


_ACCRUALS_KEY = "accruals"


def _accruals_features(fund_annual: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """US earnings-quality feature — the Sloan (1996) accruals anomaly (roadmap 17.6):
    earnings not backed by operating cash flow revert. Keyed on ``filed_at`` (**PIT leak
    test mandatory**); the one documented free US quality axis untouched by Phases 10/13
    (13.5 is issuance/asset-growth/profitability; this is earnings *quality*).

    - ``accruals`` = ``(net_income − cfo) ÷ assets``, all three from the latest annual
      rows with ``filed_at ≤ as_of`` and **sharing one ``fiscal_end``** (mismatched
      fiscal years ⇒ NaN — never cross a fresh income figure with a stale balance sheet).
      Direction **−** (high accruals = low-quality earnings that mean-revert). The
      parameter-free NI−CFO form; finer working-capital decompositions need thin-coverage
      tags, so they are deliberately out of scope.
    """
    out = {_ACCRUALS_KEY: float("nan")}
    known = fund_annual[fund_annual["filed_at"] <= as_of]
    if known.empty:
        return out
    latest = known.sort_values(["fiscal_end", "filed_at"]).groupby("metric").tail(1)
    by_metric = {str(r["metric"]): r for _, r in latest.iterrows()}
    need = ("net_income", "cfo", "assets")
    if not all(m in by_metric for m in need):
        return out
    if len({pd.Timestamp(by_metric[m]["fiscal_end"]) for m in need}) != 1:
        return out  # the three legs must be the same fiscal year
    assets = float(by_metric["assets"]["value"])
    if assets <= 0:
        return out
    ni, cfo = float(by_metric["net_income"]["value"]), float(by_metric["cfo"]["value"])
    out[_ACCRUALS_KEY] = (ni - cfo) / assets
    return out


US_FEATURE_KEYS: list[str] = [*_PEAD_KEYS, *_ISSUANCE_KEYS, *_ACCEL_KEYS, _ACCRUALS_KEY]


def us_fundamental_features(
    fund_annual: pd.DataFrame,
    fund_quarter: pd.DataFrame,
    price: pd.DataFrame,
    bench_adj: pd.Series,
    as_of: pd.Timestamp,
) -> dict[str, float]:
    """PEAD + issuance/quality + acceleration + accruals — exactly the set the panel builder
    computes when its quarterly-fundamentals stream is on (one call, one home)."""
    out: dict[str, float] = {}
    out.update(_pead_features(fund_annual, fund_quarter, price, bench_adj, as_of))
    out.update(_issuance_quality_features(fund_annual, as_of))
    out.update(_accel_features(fund_annual, fund_quarter, as_of))
    out.update(_accruals_features(fund_annual, as_of))
    return out


# --- FINRA short interest (roadmap 17.11) ---------------------------------------------------

SHORT_INTEREST_KEYS: list[str] = ["short_ratio", "short_ratio_delta_63d"]
#: The newest usable cycle must have settled within this many days of the row date. Cycles are
#: twice a month and become available 10 weekdays after settlement, so a healthy feed is at most
#: ~30 days old; anything older means a gap in the data and scores NaN, never a stale value.
_SI_MAX_AGE_DAYS = 35
_SI_DELTA_BARS = 63


def _days_to_cover(si: pd.DataFrame, d: pd.Timestamp) -> float:
    """Short shares ÷ FINRA's average daily volume of the newest cycle available on ``d``."""
    usable = si[si["available_at"] <= d]
    if usable.empty:
        return float("nan")
    i = int(usable["settlement_date"].to_numpy().argmax())
    if (d - pd.Timestamp(usable["settlement_date"].to_numpy()[i])).days > _SI_MAX_AGE_DAYS:
        return float("nan")
    volume = float(usable["avg_daily_volume"].to_numpy(dtype=float)[i])
    if bool(usable["split_flag"].to_numpy(dtype=bool)[i]) or not volume > 0:
        return float("nan")  # a split inside the cycle may mix share bases
    return float(usable["short_shares"].to_numpy(dtype=float)[i]) / volume


def short_interest_features(
    si: pd.DataFrame, price: pd.DataFrame, as_of: pd.Timestamp
) -> dict[str, float]:
    """US short-interest features from FINRA's twice-monthly cycles (roadmap 17.11).

    Point-in-time on ``available_at`` (settlement + 10 weekdays; the settlement date itself is
    never knowable). Both directions are **−**: a heavily shorted stock tends to underperform
    (days to cover: Hong, Li, Ni, Scheinkman & Yan 2016).

    - ``short_ratio``: days to cover, the newest available cycle's short shares ÷ FINRA's
      average daily volume **of the same cycle**. The card asked for our own 21-day median
      volume, but the price cache's volume is adjusted backwards for later splits while a short
      position is in the shares of its own date, so the ratio would be off by the split factor
      before every split. FINRA's volume is on the same share basis. A cycle with a split inside
      it, or a zero volume, scores NaN.
    - ``short_ratio_delta_63d``: ``short_ratio`` now minus its value 63 trading bars earlier,
      each read point-in-time on its own date.

    NaN with no usable cycle, or when the newest one settled more than 35 days before the date.
    """
    out = {k: float("nan") for k in SHORT_INTEREST_KEYS}
    if si.empty:
        return out
    now = _days_to_cover(si, as_of)
    out["short_ratio"] = now
    dates = pd.to_datetime(price["date"])
    dates = dates[dates <= as_of].sort_values()
    if len(dates) > _SI_DELTA_BARS:
        then = _days_to_cover(si, pd.Timestamp(dates.iloc[-1 - _SI_DELTA_BARS]))
        out["short_ratio_delta_63d"] = now - then
    return out
