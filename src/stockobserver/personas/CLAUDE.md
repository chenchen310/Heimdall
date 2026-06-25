# `personas/` — OPTIONAL AI narrative reports

The **only** module that calls an LLM, and **nothing in the core imports it**. The platform is fully
usable with this directory absent or `ANTHROPIC_API_KEY` unset. Building it is Phase 4+.

## Contract
A persona function receives a **fully-computed payload** (the dict of numbers its dashboard already
shows, produced by `analytics.reporting`) + the persona's prompt template, calls the Claude API, and
returns text. It computes nothing itself — if a number is missing, that is an `analytics` gap, not a
job for the model.

```
input:  payload (computed dict)  +  prompt template  +  user-supplied context
output: markdown report (rating box / trade plan / risk memo / …)
```

## Planned files
```
client.py          # thin Claude API wrapper (model id, retries) — see `claude-api` skill
templates/         # the 8 persona prompts (Goldman, Morgan Stanley, Bridgewater, JPM,
                   #   Citadel, RenTech, Vanguard, Two Sigma)
render.py          # payload + template -> report
```

## Rules
- **Decoupled:** core modules must not `import stockobserver.personas`. Wire it in at the `ui` edge,
  guarded by a feature flag + key presence.
- Use a **current** Claude model id (consult the `claude-api` skill; do not hardcode a stale id).
- The model writes prose over **given** numbers — it must not invent data. Persona prompts already
  instruct "if key data is missing, ask rather than guess"; preserve that.
