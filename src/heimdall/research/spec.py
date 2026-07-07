"""SignalSpec — a signal as data, not code.

A spec is a frozen recipe: panel features with fixed weights (direction via
sign), ranked cross-sectionally within one market, taking the top ``top_n``.
Specs serialize to JSON under ``signals/specs/`` and are identified by their
**canonical hash**, which is what pre-registration commits to
(``docs/RESEARCH_PLAYBOOK.md`` §4/§8) — the certify CLI refuses a spec whose
hash is not in a committed ``docs/RESEARCH_LOG.md`` entry.

Hash a spec file:  ``uv run python -m heimdall.research.spec hash <spec.json>``
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from heimdall.data.symbols import MARKET_REGION
from heimdall.factors.scoring import _zscore


class SignalSpec(BaseModel):
    """One versioned signal recipe. ``features`` maps panel column → weight."""

    name: str
    family: str  # the OOS budget (3 attempts, ever) is spent per family
    market: str  # "US" | "Taiwan" — one market per spec, one currency per book
    version: int = Field(default=1, ge=1)
    features: dict[str, float]
    top_n: int = Field(default=20, ge=1)
    description: str = ""  # free text; excluded from the canonical hash

    @field_validator("market")
    @classmethod
    def _known_market(cls, v: str) -> str:
        regions = sorted(set(MARKET_REGION.values()))
        if v not in regions:
            raise ValueError(f"unknown market {v!r}; expected one of {regions}")
        return v

    @field_validator("features")
    @classmethod
    def _sane_features(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            raise ValueError("a spec needs at least one feature")
        for feat, weight in v.items():
            if feat.startswith("fwd_"):  # belt-and-braces label-leakage guard (roadmap 8.3)
                raise ValueError(f"label leakage: {feat!r} is a forward label, not a feature")
            if not math.isfinite(weight) or weight == 0:
                raise ValueError(f"feature {feat!r} weight must be finite and nonzero")
        return v

    def canonical_hash(self) -> str:
        """SHA-256 of the spec's meaning: sorted keys, ``description`` excluded.

        Feature insertion order and prose must not change the hash — the log
        entry pins *what is tested*, not how the JSON happened to be written.
        """
        payload = self.model_dump(exclude={"description"})
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def load_spec(path: Path) -> SignalSpec:
    return SignalSpec.model_validate(json.loads(Path(path).read_text()))


def score(spec: SignalSpec, cross_section: pd.DataFrame) -> pd.Series:
    """Spec score for one cross-section: weighted sum of winsorized (±3σ) z-scores.

    Z-scores are computed within the **eligible** rows (an ``eligible`` column,
    when present, restricts the pool; ineligible rows get NaN and never rank).
    A row missing any feature value gets NaN — missing data excludes, never
    silently re-weights (same philosophy as the screener). Reuses
    ``factors.scoring._zscore`` so the math has exactly one home.
    """
    out = pd.Series(float("nan"), index=cross_section.index)
    if "eligible" in cross_section.columns:
        pool = cross_section[cross_section["eligible"].astype(bool)]
    else:
        pool = cross_section
    if pool.empty:
        return out
    total = pd.Series(0.0, index=pool.index)
    for feat, weight in spec.features.items():
        if feat not in cross_section.columns:
            raise KeyError(f"feature {feat!r} not in the cross-section")
        total = total + weight * _zscore(pool[feat])
    out.loc[pool.index] = total
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(load_spec(Path(sys.argv[2])).canonical_hash())
    else:
        print("usage: python -m heimdall.research.spec hash <spec.json>", file=sys.stderr)
        raise SystemExit(2)
