"""Weekly self-refresh + notifications (roadmap 16.2, completes 12.1).

A ``launchd`` job runs :func:`run_weekly`, which chains the existing **resumable**
CLIs — snapshot refresh → panel extension (US + TW) → drift monitor → TDCC weekly
cache — then freezes this month's certified cohorts in-process (idempotent, so a
weekly cadence yields one freeze per month). It emits **one digest per run** (never
spam): job failures, newly drift-flipped signals, cohorts frozen, and snapshot or
TDCC-cache staleness. With no channel configured it is a **print-only dry run**;
configure SMTP and/or a Telegram bot in ``.env`` to actually deliver. (LINE Notify
is discontinued — not supported.)

Nothing here needs the Streamlit app running. The heavy steps are subprocesses of
the same resumable CLIs a human would run; the runner is injectable so the whole
flow is testable with no network and no real subprocess.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

# Each step is the ``python -m`` target + args; the runner prepends the interpreter.
# ``tdcc_cache`` is appended **last** (roadmap 16.4) — its own exit-1 on an empty
# fetch surfaces as an ``error`` digest event via the shared failure path below.
# The SEC Form 4 bulk refresh (roadmap 18.13) runs before the US panel extension so new
# months read the newest quarter; the user asked for it to run automatically (2026-09-30).
# It only downloads a quarter not yet on disk and re-ingests only when something is new.
# The Form 4 daily delta (roadmap 18.19) runs **first**: the snapshot reads insider features
# live, so the filings since the bulk coverage end must be stored before it is built. The FINRA
# short-interest refresh (17.11) follows for the same reason: a stale table makes the live
# days-to-cover features NaN after 35 days.
WEEKLY_CHAIN: list[list[str]] = [
    ["heimdall.data.providers.form4", "--delta"],
    ["heimdall.data.providers.finra"],
    ["heimdall.screener.build"],
    ["heimdall.data.providers.form4", "--download"],
    ["heimdall.research.build_dataset", "--market", "us"],
    ["heimdall.research.build_dataset", "--market", "tw"],
    ["heimdall.research.monitor", "--apply"],
    ["heimdall.research.tdcc_cache"],
]
_STALE_BDAYS = 5
# The 集保 endpoint serves only the current week with no backfill (roadmap 13.9): a
# fresh Monday run leaves the newest file ~3 days old, so 9+ calendar days means a
# missed weekly run or the endpoint silently re-serving a stale file (the 13.9 incident).
_TDCC_STALE_DAYS = 9
Runner = Callable[[list[str]], tuple[int, str]]


@dataclass(frozen=True)
class Event:
    level: str  # "info" | "warn" | "error"
    title: str
    detail: str = ""


_ORDER = {"error": 0, "warn": 1, "info": 2}


def format_digest(events: list[Event], *, now: datetime | None = None) -> str:
    """One human-readable digest, worst level first. Pure — the unit of the formatting test."""
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    ranked = sorted(events, key=lambda e: (_ORDER.get(e.level, 9), e.title))
    icon = {"error": "❌", "warn": "⚠️", "info": "•"}
    lines = [f"Heimdall weekly digest — {stamp}", ""]
    for e in ranked:
        lines.append(f"{icon.get(e.level, '•')} {e.title}")
        if e.detail:
            lines.append(f"    {e.detail}")
    worst = min((_ORDER.get(e.level, 9) for e in events), default=2)
    lines += ["", "Needs attention." if worst < 2 else "All clear — nothing needs you."]
    return "\n".join(lines)


def channels_from_env(env: Mapping[str, str]) -> list[str]:
    """Which delivery channels are fully configured. Empty ⇒ print-only dry run."""
    channels: list[str] = []
    if env.get("HEIMDALL_SMTP_HOST") and env.get("HEIMDALL_SMTP_TO"):
        channels.append("email")
    if env.get("HEIMDALL_TELEGRAM_TOKEN") and env.get("HEIMDALL_TELEGRAM_CHAT_ID"):
        channels.append("telegram")
    return channels


@dataclass
class DispatchResult:
    dry_run: bool
    channels: list[str]
    body: str


def dispatch(events: list[Event], *, env: Mapping[str, str] | None = None) -> DispatchResult:
    """Format one digest and deliver it on every configured channel; dry-run prints it.

    Delivery (SMTP/Telegram) is real network and never exercised by tests — the
    tests assert the dry-run path and the formatting. A send failure on one channel
    must not suppress the others."""
    env = env if env is not None else os.environ
    body = format_digest(events)
    channels = channels_from_env(env)
    if not channels:
        print(body)
        return DispatchResult(dry_run=True, channels=[], body=body)
    for channel in channels:
        try:
            if channel == "email":
                _send_email(body, env)
            elif channel == "telegram":
                _send_telegram(body, env)
        except Exception as exc:  # noqa: BLE001 — one channel's failure is not fatal
            print(f"notify: {channel} delivery failed: {exc}")
    return DispatchResult(dry_run=False, channels=channels, body=body)


def _send_email(body: str, env: Mapping[str, str]) -> None:  # pragma: no cover - network
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Heimdall weekly digest"
    msg["From"] = env.get("HEIMDALL_SMTP_FROM", env["HEIMDALL_SMTP_TO"])
    msg["To"] = env["HEIMDALL_SMTP_TO"]
    msg.set_content(body)
    host, port = env["HEIMDALL_SMTP_HOST"], int(env.get("HEIMDALL_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        if env.get("HEIMDALL_SMTP_USER"):
            s.login(env["HEIMDALL_SMTP_USER"], env.get("HEIMDALL_SMTP_PASSWORD", ""))
        s.send_message(msg)


def _send_telegram(body: str, env: Mapping[str, str]) -> None:  # pragma: no cover - network
    import requests

    token, chat = env["HEIMDALL_TELEGRAM_TOKEN"], env["HEIMDALL_TELEGRAM_CHAT_ID"]
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": body},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"telegram {resp.status_code}: {resp.text[:200]}")


def _default_run(step: list[str]) -> tuple[int, str]:
    """Run one resumable CLI as ``<this interpreter> -m <step>``; return (code, combined output).

    Never a PATH lookup: launchd starts jobs with a minimal PATH (no ``~/.local/bin``),
    so a bare ``uv`` child failed every scheduled run from 2026-07-20 to 2026-09-28.
    The job already runs inside the uv-managed venv (the plist invokes ``uv run``), so
    ``sys.executable`` is that venv's interpreter and each step sees the same packages
    — the same pattern as ``ui/build_page.py``'s background build."""
    proc = subprocess.run(
        [sys.executable, "-m", *step],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def _label(step: list[str]) -> str:
    return " ".join(step)


def _tail(text: str, n: int = 400) -> str:
    return text.strip()[-n:]


def _staleness_event(today: date) -> Event | None:
    """Best-effort: warn if the snapshot is more than a work-week stale."""
    try:
        from heimdall.research.today import freshness
        from heimdall.screener.snapshot import load_snapshot

        stale = freshness(load_snapshot(), today)
    except (FileNotFoundError, ValueError):
        return None
    if stale > _STALE_BDAYS:
        return Event("warn", f"Snapshot is {stale} business days stale", "Refresh may have failed.")
    return None


def _tdcc_staleness_event(today: date) -> Event | None:
    """Best-effort: warn if the newest cached TDCC big-holder week is 9+ days old.

    Since the endpoint has no backfill (roadmap 13.9), every missed week is
    ``tw-bigholder``/15.3 history lost forever, and ``big_holder_ratio_delta_4w``
    stays NaN until four real weeks sit on disk. Both a skipped run and the endpoint
    silently re-serving an old file show up as a stale newest ``data_date``.
    Empty/missing history ⇒ ``None``: a broken fetch is already an ``error`` event
    from the chain step above, so this must not double-report it."""
    import pandas as pd

    try:
        from heimdall.data.providers import tdcc

        history = tdcc.load_cached_weeks()
    except Exception:  # noqa: BLE001 — a monitoring read must never break the digest
        return None
    if history.empty:
        return None
    latest = pd.Timestamp(history["data_date"].max()).date()
    age = (today - latest).days
    if age >= _TDCC_STALE_DAYS:
        return Event(
            "warn",
            f"TDCC big-holder cache is {age} days stale (latest {latest.isoformat()})",
            "A weekly run was missed or the endpoint re-served an old file — history is lost.",
        )
    return None


def _certified_status(root: Path | None) -> dict[tuple[str, int], str]:
    from heimdall.research import registry

    reg = registry.load_registry(root)
    out: dict[tuple[str, int], str] = {}
    for e in cast("list[dict[str, object]]", reg["signals"]):
        out[(str(e["name"]), int(cast("int", e["version"])))] = str(e["status"])
    return out


def run_weekly(
    *,
    today: date | None = None,
    env: Mapping[str, str] | None = None,
    run: Runner | None = None,
    root: Path | None = None,
) -> list[Event]:
    """Chain the resumable CLIs, freeze this month's cohorts, and return the events.

    The heavy steps run via ``run`` (injectable — a subprocess by default); a
    non-zero exit **or a runner that raises** (the step could not even launch)
    becomes an ``error`` event but never aborts the run (later steps, the freeze
    and the digest still happen). If *every* step fails, one extra ``error`` calls
    the chain dead — that pattern is the job environment, not the data. Drift flips
    are detected by comparing certified status before/after the monitor step;
    freezes come from the in-process idempotent
    :func:`heimdall.research.ledger.freeze_all`.
    """
    run = run or _default_run
    env = env if env is not None else os.environ
    today = today or date.today()
    events: list[Event] = []

    before = _certified_status(root)
    failed = 0
    for step in WEEKLY_CHAIN:
        try:
            code, out = run(step)
        except Exception as exc:  # noqa: BLE001 — a step that cannot launch is a failed step
            code, out = -1, f"{type(exc).__name__}: {exc}"
        if code != 0:
            failed += 1
            events.append(Event("error", f"Job step failed: {_label(step)}", _tail(out)))
    if failed == len(WEEKLY_CHAIN):
        events.append(
            Event(
                "error",
                f"Weekly chain is dead: all {failed} steps failed",
                "Every step failing at once points at the job environment "
                "(interpreter, PATH, working directory), not the data.",
            )
        )

    # Drift: a signal that was certified and is now under_review flipped this run.
    after = _certified_status(root)
    for key, status in after.items():
        if status == "under_review" and before.get(key) == "certified":
            events.append(Event("warn", f"{key[0]} v{key[1]} flipped to under_review (drift)"))

    # Freeze this month's certified cohorts (idempotent — a no-op after the first run/month).
    try:
        from heimdall.research.ledger import freeze_all

        for path in freeze_all(root=root, today=today):
            events.append(Event("info", f"Froze cohort {path.parent.name}/{path.stem}"))
    except Exception as exc:  # noqa: BLE001 — a freeze problem is reportable, not fatal
        events.append(Event("error", "Cohort freeze failed", str(exc)[:200]))
    # Incubating factory strategies (playbook §12.3) freeze into their own ledger. The digest
    # names them as uncertified and never lists their holdings (no tier leakage).
    try:
        from heimdall.research.ledger import freeze_incubating

        for path in freeze_incubating(root=root, today=today):
            events.append(
                Event(
                    "info", f"Froze incubating (uncertified) cohort {path.parent.name}/{path.stem}"
                )
            )
    except Exception as exc:  # noqa: BLE001
        events.append(Event("error", "Incubating cohort freeze failed", str(exc)[:200]))
    for key, status in after.items():
        if status == "incubation_retired" and before.get(key) == "incubating":
            events.append(Event("info", f"{key[0]} v{key[1]} retired from incubation (drift)"))

    ev = _staleness_event(today)
    if ev is not None:
        events.append(ev)

    tdcc_ev = _tdcc_staleness_event(today)
    if tdcc_ev is not None:
        events.append(tdcc_ev)

    if not any(e.level in ("warn", "error") for e in events):
        events.insert(0, Event("info", "Weekly refresh completed cleanly."))
    return events


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description="Heimdall weekly refresh + notifications (16.2)")
    p.add_argument(
        "command",
        nargs="?",
        default="run-weekly",
        choices=["run-weekly"],
        help="chain the resumable CLIs, freeze cohorts, and send one digest",
    )
    p.parse_args(argv)
    events = run_weekly()
    result = dispatch(events)
    if not result.dry_run:
        print(f"notify: delivered on {', '.join(result.channels)}")
    errors = [e for e in events if e.level == "error"]
    if not errors:
        return 0
    # Loud even as a dry run: stderr lands in data/logs/weekly.err.log and the exit
    # code is the job's last status in `launchctl list` — a dead chain cannot hide.
    where = "DRY RUN — nobody was notified" if result.dry_run else "digest delivered"
    print(f"notify: {len(errors)} error(s) this run ({where}):", file=sys.stderr)
    for e in errors:
        print(f"  ❌ {e.title}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
