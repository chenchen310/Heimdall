"""Universe-hygiene constants — the referee's numbers.

Mirrors the table in ``docs/RESEARCH_PLAYBOOK.md`` §3; a change here is a
process event (playbook §4 rule 4: its own PR, playbook updated in the same
commit, existing certifications voided). Only hygiene lives here for now —
the certification gates G1–G6 arrive with the certify harness (roadmap 8.2).
"""

from __future__ import annotations

# Min raw close, in the market's local currency (US$2 / NT$10).
MIN_PRICE: dict[str, float] = {"US": 2.0, "Taiwan": 10.0}

# Min liquidity: 21-day median of close×volume (US$5M / NT$50M).
MIN_DOLLAR_VOL_21D: dict[str, float] = {"US": 5_000_000.0, "Taiwan": 50_000_000.0}

# One trading year of history before a name is rankable.
MIN_HISTORY_BARS: int = 252

# Months with fewer eligible names are dropped and reported, never silently kept.
MIN_CROSS_SECTION: int = 100
