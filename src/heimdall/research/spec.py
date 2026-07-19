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
    neutralize: str = ""  # "" = raw cross-section | "sector" = within-sector ranking (17.5)

    @field_validator("neutralize")
    @classmethod
    def _known_neutralize(cls, v: str) -> str:
        if v not in ("", "sector"):
            raise ValueError(f"neutralize must be '' or 'sector', got {v!r}")
        return v

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

        Hash stability across the 17.5 ``neutralize`` addition is load-bearing: a
        spec that does not neutralize hashes exactly as it did before the field
        existed (the field is popped from the payload when it holds its default),
        so every pre-17.5 committed hash — including the certified TW signal — is
        unchanged. A registry-wide test pins this.
        """
        payload = self.model_dump(exclude={"description"})
        if payload.get("neutralize", "") == "":
            payload.pop("neutralize", None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def load_spec(path: Path) -> SignalSpec:
    return SignalSpec.model_validate(json.loads(Path(path).read_text()))


_MIN_SECTOR_MEMBERS = 5  # a sector group smaller than this can't yield a meaningful z (17.5)


def _sector_zscore(values: pd.Series, sectors: pd.Series) -> pd.Series:
    """Winsorized z-score computed *within* each sector group (17.5). Groups with
    fewer than ``_MIN_SECTOR_MEMBERS`` members score NaN — a 1–2 name z-score is
    degenerate — so those rows are excluded, never forced to a spurious rank."""
    out = pd.Series(float("nan"), index=values.index)
    for _, idx in values.groupby(sectors).groups.items():
        if len(idx) >= _MIN_SECTOR_MEMBERS:
            out.loc[idx] = _zscore(values.loc[idx])
    return out


def score(spec: SignalSpec, cross_section: pd.DataFrame) -> pd.Series:
    """Spec score for one cross-section: weighted sum of winsorized (±3σ) z-scores.

    Z-scores are computed within the **eligible** rows (an ``eligible`` column,
    when present, restricts the pool; ineligible rows get NaN and never rank).
    A row missing any feature value gets NaN — missing data excludes, never
    silently re-weights (same philosophy as the screener). Reuses
    ``factors.scoring._zscore`` so the math has exactly one home.

    When ``spec.neutralize == "sector"`` each feature is z-scored **within its
    ``sector`` group** instead of across the whole eligible pool (the practitioner
    fix for a value book that is otherwise a structural short on the leading
    mega-cap theme — roadmap 17.5). A missing ``sector`` column then raises
    ``KeyError``, the same posture as a missing feature.
    """
    out = pd.Series(float("nan"), index=cross_section.index)
    if "eligible" in cross_section.columns:
        pool = cross_section[cross_section["eligible"].astype(bool)]
    else:
        pool = cross_section
    if pool.empty:
        return out
    neutral = spec.neutralize == "sector"
    if neutral and "sector" not in cross_section.columns:
        raise KeyError("sector")
    total = pd.Series(0.0, index=pool.index)
    for feat, weight in spec.features.items():
        if feat not in cross_section.columns:
            raise KeyError(f"feature {feat!r} not in the cross-section")
        z = _sector_zscore(pool[feat], pool["sector"]) if neutral else _zscore(pool[feat])
        total = total + weight * z
    out.loc[pool.index] = total
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(load_spec(Path(sys.argv[2])).canonical_hash())
    else:
        print("usage: python -m heimdall.research.spec hash <spec.json>", file=sys.stderr)
        raise SystemExit(2)
