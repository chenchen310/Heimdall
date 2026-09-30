# Operations — weekly self-refresh + notifications

The app keeps itself current with a single scheduled job (roadmap 16.2, completing
12.1). It runs the **existing resumable CLIs**, freezes the month's certified
cohorts, and sends **one digest per run**. Nothing here needs the Streamlit app to
be running.

## What the weekly job does

`heimdall.ops.notify run-weekly` chains, in order:

1. **Snapshot refresh** — `python -m heimdall.screener.build`
2. **Form 4 bulk refresh** — `python -m heimdall.data.providers.form4 --download` (a no-op
   until SEC posts a new quarter; see "Quarterly: SEC Form 4 insider data" below)
3. **Panel extension** — `python -m heimdall.research.build_dataset --market us` then `--market tw`
4. **Drift monitor** — `python -m heimdall.research.monitor --apply` (auto-flips a
   drifted signal to `under_review`; playbook §9)
5. **TDCC big-holder cache** — `python -m heimdall.research.tdcc_cache` fetches this
   week's 集保 shareholding-dispersion file (roadmap 13.9/16.4). **Missed weeks are
   unrecoverable**: the open-data endpoint serves only the current week with no
   backfill, so every skipped run is `tw-bigholder`/15.3 history lost forever, and
   `big_holder_ratio_delta_4w` stays NaN until four real weeks sit on disk. Note that
   `--rebuild` only re-fetches the *current* week's file — it cannot recover a past
   one.
6. **Cohort freeze** — the certified picks for the current month are frozen in place
   (roadmap 16.1). This is **idempotent**: on a weekly cadence only the first run of
   each month actually writes a cohort; later runs are no-ops.

Every step is resumable and safe to re-run, so a failed or interrupted week simply
picks up where it left off on the next run.

Steps 1–5 run as subprocesses on **the job's own interpreter** (`sys.executable -m …`,
i.e. the venv that the plist's `uv run` resolved) — never via a `PATH` lookup. launchd
starts jobs with a minimal `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`, no `~/.local/bin`
or `/opt/homebrew/bin`); from 2026-07-20 to 2026-09-28 the steps shelled out to a bare
`uv`, which launchd could not find, and every run died before the freeze and digest. A
step that cannot even launch is now reported like any other failed step, and the run
carries on.

## Notifications

Delivery channels are read from `.env`. **With none configured the job is a
print-only dry run** — a safe default. (LINE Notify is discontinued and is not
supported.)

| Channel  | `.env` keys |
| -------- | ----------- |
| Email    | `HEIMDALL_SMTP_HOST`, `HEIMDALL_SMTP_TO` (and optionally `HEIMDALL_SMTP_PORT`, `HEIMDALL_SMTP_USER`, `HEIMDALL_SMTP_PASSWORD`, `HEIMDALL_SMTP_FROM`) |
| Telegram | `HEIMDALL_TELEGRAM_TOKEN`, `HEIMDALL_TELEGRAM_CHAT_ID` |

The digest reports only what needs you:

- **Job step failed** — a refresh/monitor step exited non-zero or could not be launched (the tail
  of its output, or the launch error, is included).
- **Weekly chain is dead: all N steps failed** — every step failed in the same run. That is almost
  always the job environment (interpreter, `PATH`, working directory), not the data — check
  `data/logs/weekly.err.log` and the plist paths first.
- **… flipped to under_review (drift)** — a certified signal's trailing-12 selection skill went
  significantly negative; Today's Picks now withholds its ranking until it re-certifies or retires.
- **Froze cohort …** — this month's picks were recorded to the live track record.
- **Snapshot is N business days stale** — the refresh did not advance the snapshot; investigate.
- **TDCC big-holder cache is N days stale** — the newest cached 集保 week is ≥ 9 calendar days old
  (a fresh Monday run is ~3 days). Either a weekly run was missed — that week is now lost forever —
  or the endpoint is silently re-serving an old file (the exact 13.9 probe incident). An outright
  fetch failure shows up as **Job step failed** above instead.

If nothing needs attention the digest says so in one line.

**Errors are loud even in a dry run.** Any `error` event makes the job exit **1** (shown as
the last-exit column of `launchctl list`) and prints a short error list to stderr
(`data/logs/weekly.err.log`), marked `DRY RUN — nobody was notified` when no channel is
configured. The full digest always goes to stdout (`data/logs/weekly.out.log`). A clean run
exits 0 and writes nothing to stderr.

## Install (macOS, launchd)

1. Copy the template and fill in your absolute paths (repo and `uv`):

   ```bash
   mkdir -p ~/Library/LaunchAgents data/logs
   sed -e "s#__REPLACE_WITH_ABSOLUTE_REPO_PATH__#$(pwd)#g" \
       -e "s#/opt/homebrew/bin/uv#$(command -v uv)#" \
     src/heimdall/ops/com.heimdall.weekly.plist \
     > ~/Library/LaunchAgents/com.heimdall.weekly.plist
   ```

   Check that the first `ProgramArguments` entry is an **absolute** path to `uv`
   (e.g. `~/.local/bin/uv` expanded, or `/opt/homebrew/bin/uv`). It is the only
   executable launchd has to find; the chained steps reuse its interpreter.

2. Load it (runs Mondays 08:00 local):

   ```bash
   launchctl load ~/Library/LaunchAgents/com.heimdall.weekly.plist
   ```

3. Seed the TDCC big-holder cache **once, right now** — don't wait for Monday, or this
   week's file (which no backfill can recover) is lost:

   ```bash
   uv run python -m heimdall.research.tdcc_cache
   ```

## Verify

```bash
# Run the whole flow once, right now (dry run unless a channel is configured):
uv run python -m heimdall.ops.notify run-weekly

# Confirm launchd registered the job; the middle column is the last exit status
# (0 = clean, 1 = the run had error events or crashed, "-" = never run yet):
launchctl list | grep com.heimdall.weekly

# Watch the logs after a scheduled run:
tail -f data/logs/weekly.err.log data/logs/weekly.out.log
```

To rehearse under launchd's own environment without waiting for Monday, prefix the
run-weekly command with `env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin` and
call `uv` by the absolute path from your plist. This runs the real chain, and it freezes
this month's cohort if that has not happened yet.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.heimdall.weekly.plist
rm ~/Library/LaunchAgents/com.heimdall.weekly.plist
```

## Quarterly: SEC Form 4 insider data (roadmap 18.13)

The insider features (`insider_net_buy_90d`, `insider_cluster_buy`) read SEC's quarterly
**Insider Transactions Data Sets**, not a per-filing crawl. SEC publishes each quarter's zip a few
weeks after the quarter ends. Once it is out, fetch the new zip(s) and re-ingest:

```bash
uv run python -m heimdall.data.providers.form4 --download
```

- Only zips not already under `data/form4/raw/` are downloaded (~10 MB each).
- The per-symbol caches in `data/form4/` and the `data/form4/_bulk.json` marker are rebuilt from
  the raw zips, which takes about 1–2 minutes.
- Panel months after the marker's `coverage_end` get **NaN** insider features, never a false "no
  trades" 0, until the next quarter is ingested.

**Automatic since 2026-09-30 (user decision):** the weekly chain runs
`python -m heimdall.data.providers.form4 --download` right after the snapshot and before the US
panel extension. Each run makes one request to SEC's index page. A zip is downloaded only when a new
quarter has been published, and the caches are re-ingested only when something new arrived, so
most weeks it is a no-op printing "up to date". Panel months that the resumable build already
computed before their quarter arrived keep NaN insider values (features are frozen at first write)
until the next full rebuild.
