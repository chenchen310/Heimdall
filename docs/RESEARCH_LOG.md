# Research Log — append-only

> Every experiment that touches the OOS vault is registered **here, before it runs** (see
> `docs/RESEARCH_PLAYBOOK.md` §4 and §8 for the rules and the entry template). Entries are
> append-only: never edit or delete a past entry; corrections are new entries that reference the
> old id. The certify CLI refuses to run without a committed entry whose spec hash matches.

---

## 000 — institution established (2026-07-03, model: Fable 5)

- Decisions frozen with the user: success = 6-month benchmark-relative (3m secondary); monthly
  top-10–20 rebalance; US first, Taiwan second; free data first.
- Splits frozen: Development 2010–2019 · Validation 2020–2022 · OOS vault 2023→(complete-label
  frontier). OOS budget: 3 attempts per family.
- Gates v1 frozen as `docs/RESEARCH_PLAYBOOK.md` §5 (to be mirrored in `research/gates.py`,
  Phase 8.2, with a sync test).
- Known accepted limitations recorded in `docs/NORTH_STAR.md` (survivorship: current universe;
  TW synthetic filed_at until Phase 11.1; free-data ceiling).
- No signals exist yet. Next research entries begin at 001 with Phase 10 pre-registrations.
