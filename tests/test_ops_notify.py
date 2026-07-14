"""Weekly notifier (roadmap 16.2) — formatting, channel selection, dry-run, and the
chained run — all with an injected runner and no network."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from heimdall.ops.notify import (
    WEEKLY_CHAIN,
    Event,
    _tdcc_staleness_event,
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


def test_weekly_chain_appends_tdcc_cache_last() -> None:
    # 16.4: the TDCC weekly cache runs last; the 16.2 chain stays an intact prefix.
    assert WEEKLY_CHAIN[-1] == ["heimdall.research.tdcc_cache"]
    assert WEEKLY_CHAIN[:4] == [
        ["heimdall.screener.build"],
        ["heimdall.research.build_dataset", "--market", "us"],
        ["heimdall.research.build_dataset", "--market", "tw"],
        ["heimdall.research.monitor", "--apply"],
    ]


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


def test_run_weekly_reports_failed_tdcc_step_but_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failing tdcc_cache fetch (its own exit-1) is reported as an error but must
    # not abort the run — the in-process cohort freeze still executes afterward.
    monkeypatch.setenv("HEIMDALL_DATA_DIR", str(tmp_path))
    frozen = [tmp_path / "signals" / "ledger" / "tw-rev_v1" / "2024-03.json"]
    monkeypatch.setattr("heimdall.research.ledger.freeze_all", lambda **k: frozen)
    seen: list[list[str]] = []
    events = run_weekly(
        today=date(2024, 3, 4),
        root=tmp_path,
        env={},
        run=_fixed_run(seen, failures={"heimdall.research.tdcc_cache"}),
    )
    assert seen == WEEKLY_CHAIN  # tdcc ran (and failed) as the final step
    errs = [e for e in events if e.level == "error"]
    assert len(errs) == 1 and "tdcc_cache" in errs[0].title
    assert any("Froze cohort" in e.title for e in events)  # post-chain work still ran


def _tdcc_history(dates: list[date]) -> pd.DataFrame:
    """A fake ``load_cached_weeks`` frame — only ``data_date`` matters to staleness."""
    return pd.DataFrame({"data_date": [pd.Timestamp(d) for d in dates]})


def test_tdcc_staleness_fresh_run_no_event(monkeypatch: pytest.MonkeyPatch) -> None:
    # Newest file 3 days old (a normal Monday run); an older file is also present,
    # proving the check keys off the max data_date, not the min.
    monkeypatch.setattr(
        "heimdall.data.providers.tdcc.load_cached_weeks",
        lambda *a, **k: _tdcc_history([date(2024, 2, 2), date(2024, 3, 8)]),
    )
    assert _tdcc_staleness_event(date(2024, 3, 11)) is None


def test_tdcc_staleness_nine_days_warns_naming_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "heimdall.data.providers.tdcc.load_cached_weeks",
        lambda *a, **k: _tdcc_history([date(2024, 3, 2)]),  # exactly 9 calendar days
    )
    ev = _tdcc_staleness_event(date(2024, 3, 11))
    assert ev is not None and ev.level == "warn" and "2024-03-02" in ev.title


def test_tdcc_staleness_no_history_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "heimdall.data.providers.tdcc.load_cached_weeks",
        lambda *a, **k: _tdcc_history([]),  # nothing accumulated yet
    )
    assert _tdcc_staleness_event(date(2024, 3, 11)) is None


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
