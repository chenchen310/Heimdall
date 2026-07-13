"""Forward performance ledger — the live track record (roadmap 16.1).

The strongest honest trust feature the app can have: **freeze** each month's
certified picks the moment they are shown, then later show their *realized*,
costed return — no backfill, no hindsight. A frozen cohort is immutable
(mirroring certification): a second freeze of the same month refuses, and only
months **on/after the certification month** may be frozen (pre-certification
history is the OOS report's job — backfilled rows would masquerade as live).

The realized view recomputes each frozen cohort's forward returns **from the
panel** on exactly the sanctioned post-2023 monitoring basis of
:mod:`heimdall.research.monitor` (12.2): the equal-weight book's 6-month
benchmark-relative return, the equal-weight eligible-universe's 6-month return,
and their difference — the G3 selection skill. The "followed every month" equity
curve chains each cohort's realized one-month book return net of G4's 20 bps per
side (:func:`heimdall.research.certify.apply_costs`), so costs and the cost model
match the certification exactly — one home for the math.

Nothing here reads registry *state* to decide what to freeze; the caller
(:func:`freeze_all`) passes the certified spec and its certification month, so the
certified-only rule stays enforced in one place (the registry).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from heimdall.research import gates
from heimdall.research.certify import apply_costs, cohort_turnover
from heimdall.research.spec import SignalSpec
from heimdall.research.today import todays_picks


def ledger_dir(name: str, version: int, root: Path | None = None) -> Path:
    base = root if root is not None else _repo_root()
    return base / "signals" / "ledger" / f"{name}_v{version}"


def cohort_path(name: str, version: int, month: str, root: Path | None = None) -> Path:
    return ledger_dir(name, version, root) / f"{month}.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _month_of(d: date) -> str:
    return d.strftime("%Y-%m")


# --- freeze (append-only, no backfill) ------------------------------------------


class BackfillRefused(ValueError):
    """Freezing a month before the certification month — pre-cert history is the OOS report's."""


def freeze(
    spec: SignalSpec,
    snapshot: pd.DataFrame,
    cert_month: str,
    *,
    root: Path | None = None,
    today: date | None = None,
) -> Path:
    """Freeze this month's picks for a certified spec; return the written path.

    ``cert_month`` (``YYYY-MM``) is the signal's certification month — the caller
    reads it from the immutable certification report. The freeze month is
    ``today``'s month. Refuses to **backfill** (month < ``cert_month``) and to
    overwrite an existing cohort (immutability, mirroring certification). The
    picks are exactly what Today's Picks shows (``research.today.todays_picks``),
    stored with the snapshot's ``as_of`` for provenance.
    """
    freeze_day = today if today is not None else date.today()
    month = _month_of(freeze_day)
    if month < cert_month:
        raise BackfillRefused(
            f"refusing to freeze {month} for {spec.name} v{spec.version}: before its "
            f"certification month {cert_month} (no backfill — the OOS report covers pre-cert)"
        )
    path = cohort_path(spec.name, spec.version, month, root)
    if path.exists():
        raise FileExistsError(
            f"{path} already exists — a frozen cohort is immutable (16.1); one freeze per month"
        )

    picks = todays_picks(spec, snapshot)
    as_of = ""
    if "as_of" in snapshot.columns and snapshot["as_of"].notna().any():
        as_of = pd.to_datetime(snapshot["as_of"]).max().date().isoformat()
    payload = {
        "name": spec.name,
        "version": spec.version,
        "market": spec.market,
        "month": month,
        "as_of": as_of,
        "frozen_at": datetime.now(UTC).isoformat(),
        "spec_hash": spec.canonical_hash(),
        "picks": [
            {"symbol": str(s), "signal_score": float(v)}
            for s, v in zip(picks["symbol"], picks["signal_score"], strict=True)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)
    return path


def load_cohorts(name: str, version: int, root: Path | None = None) -> list[dict[str, object]]:
    """Every frozen cohort for a signal, oldest month first."""
    d = ledger_dir(name, version, root)
    if not d.exists():
        return []
    out = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
    return sorted(out, key=lambda c: str(c["month"]))


# --- realized track record (recomputed from the panel) --------------------------


@dataclass
class RealizedCohort:
    month: str
    as_of: str
    n_frozen: int  # total picks in the frozen cohort — always known, panel-independent
    n_realized: int  # of those, how many the panel currently carries a complete 6m label for
    book_rel_6m: float  # EW book 6m return, benchmark-relative
    univ_rel_6m: float  # EW eligible-universe 6m return, benchmark-relative
    alpha_6m: float  # book − universe: the G3 selection skill (the certified edge)
    realized: bool  # the 6m forward window has completed
    symbols: list[str] = field(default_factory=list)  # the frozen picks (for a live price mark)


@dataclass
class CurvePoint:
    month: str
    gross: float  # EW book one-month return (from the panel's fwd_1m)
    net: float  # after G4 costs on the traded fraction
    equity: float  # cumulative "followed every month" wealth, starting at 1.0


@dataclass
class TrackRecord:
    name: str
    version: int
    market: str
    cert_month: str
    survivorship: str
    cohorts: list[RealizedCohort] = field(default_factory=list)
    curve: list[CurvePoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _panel_date_for_month(month: str, panel_dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    y, m = (int(x) for x in month.split("-"))
    same = [d for d in panel_dates if d.year == y and d.month == m]
    return same[-1] if same else None  # the month-end rebalance date


def realized_track_record(
    spec: SignalSpec,
    panel: pd.DataFrame,
    cert_month: str,
    *,
    survivorship: str = "current_universe (optimistic)",
    root: Path | None = None,
) -> TrackRecord:
    """Recompute every frozen cohort's realized return from the current panel.

    For each frozen month, its panel month-end cross-section supplies the frozen
    picks' forward labels: the EW book's 6m benchmark-relative return, the EW
    eligible-universe's 6m return, and the selection alpha between them (the
    monitor/certify basis). The equity curve chains each cohort's realized 1-month
    book return net of :data:`gates.G4_COST_BPS` per side on the traded fraction,
    stopping at the first month whose forward window has not completed.
    """
    tr = TrackRecord(spec.name, spec.version, spec.market, cert_month, survivorship)
    cohorts = load_cohorts(spec.name, spec.version, root)
    panel_dates = sorted(pd.Timestamp(x) for x in panel["date"].unique()) if not panel.empty else []

    ordered_sets: list[set[str]] = []
    monthly_gross: list[float] = []
    curve_months: list[str] = []
    for c in cohorts:
        month = str(c["month"])
        picks = cast("list[dict[str, object]]", c["picks"])
        symbols = {str(p["symbol"]) for p in picks}
        t = _panel_date_for_month(month, panel_dates)
        cross = panel[panel["date"] == t] if t is not None else panel.iloc[0:0]
        book_rows = cross[cross["symbol"].isin(symbols)]

        book6 = book_rows["fwd_6m_rel"].dropna()
        elig = cross[cross["eligible"].astype(bool)] if "eligible" in cross.columns else cross
        univ6 = elig["fwd_6m_rel"].dropna()
        book_rel = float(book6.mean()) if len(book6) else float("nan")
        univ_rel = float(univ6.mean()) if len(univ6) else float("nan")
        tr.cohorts.append(
            RealizedCohort(
                month=month,
                as_of=str(c.get("as_of", "")),
                n_frozen=len(picks),
                n_realized=int(book_rows["fwd_6m"].notna().sum()) if not book_rows.empty else 0,
                book_rel_6m=book_rel,
                univ_rel_6m=univ_rel,
                alpha_6m=book_rel - univ_rel,
                realized=bool(book_rows["fwd_6m"].notna().any()) if not book_rows.empty else False,
                symbols=sorted(symbols),
            )
        )
        # Curve leg: this cohort's realized one-month book return.
        gross_1m = book_rows["fwd_1m"].dropna()
        ordered_sets.append(symbols)
        monthly_gross.append(float(gross_1m.mean()) if len(gross_1m) else float("nan"))
        curve_months.append(month)

    tr.curve = _equity_curve(curve_months, monthly_gross, ordered_sets)
    return tr


def _equity_curve(months: list[str], gross: list[float], sets: list[set[str]]) -> list[CurvePoint]:
    """Chain the realized monthly book returns net of G4 costs into a wealth curve.

    Only the realized prefix is drawn: the curve stops at the first month whose
    one-month window has not completed (a NaN gross — the most recent cohorts)."""
    realized_n = 0
    for g in gross:
        if np.isnan(g):
            break
        realized_n += 1
    if realized_n == 0:
        return []
    g_prefix = gross[:realized_n]
    turnovers = cohort_turnover(sets[:realized_n])
    net = apply_costs(g_prefix, turnovers, gates.G4_COST_BPS)
    equity = 1.0
    points: list[CurvePoint] = []
    for i in range(realized_n):
        equity *= 1.0 + net[i]
        points.append(CurvePoint(months[i], g_prefix[i], net[i], equity))
    return points


# --- unrealized mark (live, price-only — orthogonal to the certified panel math) ---


@dataclass
class UnrealizedMark:
    """A live "how is this doing so far" read for a cohort still inside its
    6-month window — the panel has no verdict yet (``realized_track_record``
    correctly shows NaN there), but raw prices already exist."""

    n_frozen: int
    n_priced: int  # of those, how many had a price on/after as_of AND today
    return_pct: float  # EW mean raw price return since as_of
    bench_return_pct: float
    alpha_pct: (
        float  # return_pct − bench_return_pct — same _rel convention as every other number here
    )
    as_of: str
    marked_at: str  # the latest price date actually used


def unrealized_mark(
    picks: list[str], as_of: str, prices: dict[str, pd.DataFrame], bench: pd.DataFrame
) -> UnrealizedMark:
    """Benchmark-relative mark-to-market from **today's cached prices** — never net
    of costs (nothing has been sold), never a bare price return (playbook §2: every
    return in this app is benchmark-relative, so this one is too). Deliberately
    **separate** from :func:`realized_track_record`: it reads raw OHLCV, not the
    monthly research panel, so it has an answer even for a cohort frozen mid-month,
    before the panel has a cross-section for it — the actual gap this closes.

    ``prices``/``bench`` are canonical OHLCV frames (``date``, ``adj_close``) —
    the caller fetches them (e.g. ``ui._data.get_ohlcv``); each is filtered here to
    ``>= as_of`` so a wider-window frame is fine to pass in. A symbol with no row
    on/after ``as_of`` (not yet cached, delisted, …) is skipped, not zero-filled.
    """
    as_of_ts = pd.Timestamp(as_of)

    def _leg_return(frame: pd.DataFrame) -> tuple[float, str] | None:
        if frame.empty or "date" not in frame.columns:
            return None
        f = frame[frame["date"] >= as_of_ts].sort_values("date")
        if f.empty:
            return None
        entry, current = float(f["adj_close"].iloc[0]), float(f["adj_close"].iloc[-1])
        if entry <= 0:
            return None
        return current / entry - 1.0, cast("pd.Timestamp", f["date"].iloc[-1]).date().isoformat()

    bench_leg = _leg_return(bench)
    rets: list[float] = []
    marked_at = as_of
    for sym in picks:
        leg = _leg_return(prices.get(sym, pd.DataFrame()))
        if leg is not None:
            ret, dt = leg
            rets.append(ret)
            marked_at = max(marked_at, dt)

    ew_ret = float(np.mean(rets)) if rets else float("nan")
    bench_ret = bench_leg[0] if bench_leg is not None else float("nan")
    return UnrealizedMark(
        n_frozen=len(picks),
        n_priced=len(rets),
        return_pct=ew_ret,
        bench_return_pct=bench_ret,
        alpha_pct=ew_ret - bench_ret,
        as_of=as_of,
        marked_at=marked_at,
    )


# --- CLI (freeze every certified signal — the monthly ledger step) ---------------


def freeze_all(*, root: Path | None = None, today: date | None = None) -> list[Path]:
    """Freeze the current month for every ``certified`` signal. The monthly ledger
    step 16.2 schedules. Reads the registry (the one certified-only gate), loads each
    spec + its certification month, and freezes the live snapshot's picks. Already-
    frozen months and backfill attempts are skipped, not fatal — the chore is
    idempotent and safe to re-run."""
    from heimdall.research import registry
    from heimdall.research.spec import load_spec
    from heimdall.screener.snapshot import load_snapshot

    base = root if root is not None else registry.registry_path().parent.parent
    reg = registry.load_registry(root)
    snap = load_snapshot()
    written: list[Path] = []
    for entry in cast("list[dict[str, object]]", reg["signals"]):
        if entry.get("status") != "certified":
            continue
        p = Path(str(entry["spec_path"]))
        spec = load_spec(p if p.is_absolute() else base / p)
        report = json.loads(Path(str(entry["cert_report"])).read_text())
        cert_month = str(report.get("generated_at", ""))[:7]
        try:
            written.append(freeze(spec, snap, cert_month, root=root, today=today))
        except (FileExistsError, BackfillRefused):
            continue  # already frozen this month, or pre-cert — both are no-ops
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Freeze this month's certified picks (roadmap 16.1)")
    p.add_argument("command", choices=["freeze"], help="freeze every certified signal's picks")
    p.parse_args(argv)
    written = freeze_all()
    if not written:
        print("Nothing frozen (no certified signal, or already frozen this month).")
        return 0
    for path in written:
        print(f"Froze {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
