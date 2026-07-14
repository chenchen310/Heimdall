# Operations — weekly self-refresh + notifications

The app keeps itself current with a single scheduled job (roadmap 16.2, completing
12.1). It runs the **existing resumable CLIs**, freezes the month's certified
cohorts, and sends **one digest per run**. Nothing here needs the Streamlit app to
be running.

## What the weekly job does

`heimdall.ops.notify run-weekly` chains, in order:

1. **Snapshot refresh** — `python -m heimdall.screener.build`
2. **Panel extension** — `python -m heimdall.research.build_dataset --market us` then `--market tw`
3. **Drift monitor** — `python -m heimdall.research.monitor --apply` (auto-flips a
   drifted signal to `under_review`; playbook §9)
4. **TDCC big-holder cache** — `python -m heimdall.research.tdcc_cache` fetches this
   week's 集保 shareholding-dispersion file (roadmap 13.9/16.4). **Missed weeks are
   unrecoverable**: the open-data endpoint serves only the current week with no
   backfill, so every skipped run is `tw-bigholder`/15.3 history lost forever, and
   `big_holder_ratio_delta_4w` stays NaN until four real weeks sit on disk. Note that
   `--rebuild` only re-fetches the *current* week's file — it cannot recover a past
   one.
5. **Cohort freeze** — the certified picks for the current month are frozen in place
   (roadmap 16.1). This is **idempotent**: on a weekly cadence only the first run of
   each month actually writes a cohort; later runs are no-ops.

Every step is resumable and safe to re-run, so a failed or interrupted week simply
picks up where it left off on the next run.

## Notifications

Delivery channels are read from `.env`. **With none configured the job is a
print-only dry run** — a safe default. (LINE Notify is discontinued and is not
supported.)

| Channel  | `.env` keys |
| -------- | ----------- |
| Email    | `HEIMDALL_SMTP_HOST`, `HEIMDALL_SMTP_TO` (and optionally `HEIMDALL_SMTP_PORT`, `HEIMDALL_SMTP_USER`, `HEIMDALL_SMTP_PASSWORD`, `HEIMDALL_SMTP_FROM`) |
| Telegram | `HEIMDALL_TELEGRAM_TOKEN`, `HEIMDALL_TELEGRAM_CHAT_ID` |

The digest reports only what needs you:

- **Job step failed** — a refresh/monitor step exited non-zero (the tail of its output is included).
- **… flipped to under_review (drift)** — a certified signal's trailing-12 selection skill went
  significantly negative; Today's Picks now withholds its ranking until it re-certifies or retires.
- **Froze cohort …** — this month's picks were recorded to the live track record.
- **Snapshot is N business days stale** — the refresh did not advance the snapshot; investigate.
- **TDCC big-holder cache is N days stale** — the newest cached 集保 week is ≥ 9 calendar days old
  (a fresh Monday run is ~3 days). Either a weekly run was missed — that week is now lost forever —
  or the endpoint is silently re-serving an old file (the exact 13.9 probe incident). An outright
  fetch failure shows up as **Job step failed** above instead.

If nothing needs attention the digest says so in one line.

## Install (macOS, launchd)

1. Copy the template and fill in your absolute paths:

   ```bash
   mkdir -p ~/Library/LaunchAgents data/logs
   sed "s#__REPLACE_WITH_ABSOLUTE_REPO_PATH__#$(pwd)#g" \
     src/heimdall/ops/com.heimdall.weekly.plist \
     > ~/Library/LaunchAgents/com.heimdall.weekly.plist
   ```

   If `which uv` is not `/opt/homebrew/bin/uv`, edit that path in the copied plist too.

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

# Confirm launchd registered the job:
launchctl list | grep com.heimdall.weekly

# Watch the logs after a scheduled run:
tail -f data/logs/weekly.err.log data/logs/weekly.out.log
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.heimdall.weekly.plist
rm ~/Library/LaunchAgents/com.heimdall.weekly.plist
```
