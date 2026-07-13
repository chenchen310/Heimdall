"""Weekly notifier (roadmap 16.2) — formatting, channel selection, dry-run, and the
chained run — all with an injected runner and no network."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from heimdall.ops.notify import (
    WEEKLY_CHAIN,
    Event,
    channels_from_env,
    dispatch,
    format_digest,
    run_weekly,
)


def test_format_digest_orders_worst_first_and_flags_attention() -> None:
    body = format_digest(
        [
            Event("info", "all quiet"),
            Event("error", "boom", "stack detail"),
            Event("warn", "careful"),
        ]
    )
    lines = body.splitlines()
    assert lines.index("❌ boom") < lines.index("⚠️ careful") < lines.index("• all quiet")
    assert "    stack detail" in body  # the detail is indented under its title
    assert body.strip().endswith("Needs attention.")


def test_format_digest_all_clear_when_only_info() -> None:
    assert (
        format_digest([Event("info", "refresh ok")])
        .strip()
        .endswith("All clear — nothing needs you.")
    )


def test_channels_from_env_selects_configured_only() -> None:
    assert channels_from_env({}) == []  # nothing configured ⇒ dry run
    assert channels_from_env({"HEIMDALL_SMTP_HOST": "h", "HEIMDALL_SMTP_TO": "me@x"}) == ["email"]
    both = channels_from_env(
        {
            "HEIMDALL_SMTP_HOST": "h",
            "HEIMDALL_SMTP_TO": "me@x",
            "HEIMDALL_TELEGRAM_TOKEN": "t",
            "HEIMDALL_TELEGRAM_CHAT_ID": "1",
        }
    )
    assert both == ["email", "telegram"]
    # A half-configured channel is not selected (no accidental broken sends).
    assert channels_from_env({"HEIMDALL_TELEGRAM_TOKEN": "t"}) == []


def test_dispatch_dry_run_prints_and_sends_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    result = dispatch([Event("info", "hello")], env={})
    assert result.dry_run and result.channels == []
    assert "Heimdall weekly digest" in capsys.readouterr().out


def _fixed_run(seen: list[list[str]], failures: set[str] = frozenset()):  # type: ignore[no-untyped-def]
    def run(step: list[str]) -> tuple[int, str]:
        seen.append(step)
        label = " ".join(step)
        return (1, "traceback…") if label in failures else (0, "ok")

    return run


def test_run_weekly_chains_every_step_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))  # isolate snapshot lookup
    monkeypatch.setattr("heimdall.research.ledger.freeze_all", lambda **k: [])
    seen: list[list[str]] = []
    events = run_weekly(today=date(2024, 3, 4), root=tmp_path, env={}, run=_fixed_run(seen))
    assert seen == WEEKLY_CHAIN
    assert all(e.level == "info" for e in events)  # clean run
    assert any("completed cleanly" in e.title for e in events)


def test_run_weekly_reports_a_failed_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("heimdall.research.ledger.freeze_all", lambda **k: [])
    seen: list[list[str]] = []
    events = run_weekly(
        today=date(2024, 3, 4),
        root=tmp_path,
        env={},
        run=_fixed_run(seen, failures={"heimdall.research.build_dataset --market tw"}),
    )
    assert seen == WEEKLY_CHAIN  # a failure does not abort the chain
    errs = [e for e in events if e.level == "error"]
    assert len(errs) == 1 and "build_dataset --market tw" in errs[0].title


def test_run_weekly_reports_frozen_cohorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    frozen = [tmp_path / "signals" / "ledger" / "tw-rev_v1" / "2024-03.json"]
    monkeypatch.setattr("heimdall.research.ledger.freeze_all", lambda **k: frozen)
    events = run_weekly(today=date(2024, 3, 4), root=tmp_path, env={}, run=lambda s: (0, "ok"))
    assert any("Froze cohort" in e.title and "2024-03" in e.title for e in events)


def test_launchd_plist_is_valid_and_present() -> None:
    plist = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "heimdall"
        / "ops"
        / "com.heimdall.weekly.plist"
    )
    assert plist.exists()
    if shutil.which("plutil"):  # macOS only — skip elsewhere
        proc = subprocess.run(
            ["plutil", "-lint", str(plist)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
