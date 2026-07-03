# Rule: Signal certification

The referee layer. `.claude/rules/backtest-honesty.md` and `data-discipline.md` keep computations
honest; this rule keeps **claims** honest. Full process: `docs/RESEARCH_PLAYBOOK.md`.

- **Today's Picks shows certified signals only.** The page reads `signals/registry.json` entries
  with status `certified` and renders an honest empty state otherwise. No exceptions, no previews,
  no "temporary" rankings.
- **Pre-register, then test.** The OOS window (2023+) may only be evaluated by
  `heimdall.research.certify` against a spec whose hash appears in a committed
  `docs/RESEARCH_LOG.md` entry. Development/tuning code must never read OOS rows.
- **3 OOS attempts per family, ever.** A rejected spec is logged and closed — re-tuning and
  silently retrying against the vault is the cardinal sin of this codebase.
- **Gates are law, not knobs.** Thresholds live in `research/gates.py` and must equal
  `docs/RESEARCH_PLAYBOOK.md` §5 (a test enforces the mirror). Changing them = its own PR + every
  existing certification voided and re-run.
- **Certification reports are immutable** (`signals/certifications/`, committed). New evidence =
  new version, never an edit.
- **Registry transitions happen only through code** (`heimdall.research`), never hand-edits.
- **Every certified number carries its caveats**: benchmark-relative, `current_universe
  (optimistic)` survivorship stamp, CI + cohort count alongside any probability.
- **No LLM output feeds any certified computation.** Identical results with `personas/` absent.
