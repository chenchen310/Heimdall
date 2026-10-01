"""SignalSpec — a signal as data, not code.

A spec is a frozen recipe: panel features with fixed weights (direction via
sign), ranked cross-sectionally within one market, taking the top ``top_n``.
Optional **construction** fields (roadmap 18.1 — universe tier, filters,
weighting, sector cap, rank buffer, regime overlay) turn the ranking into a
weighted book; :mod:`heimdall.research.construct` is their single home.
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

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from heimdall.data.symbols import MARKET_REGION
from heimdall.factors.scoring import _zscore
from heimdall.screener.model import Predicate

#: Construction menus (roadmap 18.1). ``""`` is always today's behaviour.
UNIVERSES: tuple[str, ...] = ("", "us_large")  # us_large = PIT top gates.US_LARGE_N by market cap
WEIGHTINGS: tuple[str, ...] = ("", "inverse_vol", "rank_linear")  # "" = equal weight
#: Score neutralizations: raw, within-sector (17.5), or sector + size residual (18.18).
NEUTRALIZATIONS: tuple[str, ...] = ("", "sector", "sector_size")
OVERLAYS: tuple[str, ...] = ("", "spy_sma200_cash")  # cash while the benchmark < its 200d SMA

#: Construction fields and their defaults. A field holding its default is popped from the
#: canonical hash, so every spec written before the field existed keeps its committed hash.
CONSTRUCTION_DEFAULTS: dict[str, object] = {
    "neutralize": "",
    "universe": "",
    "filters": [],
    "weighting": "",
    "max_sector_weight": None,
    "exit_rank": None,
    "overlay": "",
}


class SignalSpec(BaseModel):
    """One versioned signal recipe. ``features`` maps panel column → weight."""

    name: str
    family: str  # the OOS budget (3 attempts, ever) is spent per family
    market: str  # "US" | "Taiwan" — one market per spec, one currency per book
    version: int = Field(default=1, ge=1)
    features: dict[str, float]
    top_n: int = Field(default=20, ge=1)
    description: str = ""  # free text; excluded from the canonical hash
    neutralize: str = ""  # "" raw | "sector" within-sector (17.5) | "sector_size" (18.18)
    # --- construction (18.1); every default reproduces the pre-18.1 book exactly ---
    universe: str = ""  # "" = every eligible row | "us_large" = PIT top-N eligible by market cap
    filters: list[Predicate] = []  # screener predicates; missing data fails, never passes
    weighting: str = ""  # "" = equal weight | "inverse_vol" = ∝ 1/vol_63d
    max_sector_weight: float | None = None  # per-sector cap; excess goes pro-rata to the rest
    exit_rank: int | None = None  # rank buffer: hold a member until its rank exceeds this
    overlay: str = ""  # book-level regime switch, applied by consumers (never inside the book)

    @field_validator("neutralize")
    @classmethod
    def _known_neutralize(cls, v: str) -> str:
        if v not in NEUTRALIZATIONS:
            raise ValueError(f"neutralize must be one of {NEUTRALIZATIONS}, got {v!r}")
        return v

    @field_validator("universe")
    @classmethod
    def _known_universe(cls, v: str) -> str:
        if v not in UNIVERSES:
            raise ValueError(f"universe must be one of {UNIVERSES}, got {v!r}")
        return v

    @field_validator("weighting")
    @classmethod
    def _known_weighting(cls, v: str) -> str:
        if v not in WEIGHTINGS:
            raise ValueError(f"weighting must be one of {WEIGHTINGS}, got {v!r}")
        return v

    @field_validator("overlay")
    @classmethod
    def _known_overlay(cls, v: str) -> str:
        if v not in OVERLAYS:
            raise ValueError(f"overlay must be one of {OVERLAYS}, got {v!r}")
        return v

    @field_validator("max_sector_weight")
    @classmethod
    def _sane_sector_cap(cls, v: float | None) -> float | None:
        if v is not None and not (math.isfinite(v) and 0.0 < v <= 1.0):
            raise ValueError(f"max_sector_weight must be in (0, 1], got {v!r}")
        return v

    @field_validator("filters")
    @classmethod
    def _sane_filters(cls, v: list[Predicate]) -> list[Predicate]:
        for pred in v:
            if pred.field.startswith("fwd_"):  # a filter on a label is label leakage too
                raise ValueError(f"label leakage: filter on forward label {pred.field!r}")
            if not pred.enabled:  # a disabled predicate would change the hash but not the book
                raise ValueError(f"filter on {pred.field!r} is disabled; drop it from the spec")
        return v

    @model_validator(mode="after")
    def _coherent_construction(self) -> SignalSpec:
        if self.exit_rank is not None and self.exit_rank <= self.top_n:
            raise ValueError(f"exit_rank ({self.exit_rank}) must exceed top_n ({self.top_n})")
        if self.universe == "us_large" and self.market != "US":
            raise ValueError("universe 'us_large' is a US tier; market must be 'US'")
        return self

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
        unchanged. A registry-wide test pins this. The 18.1 construction fields follow the
        same rule (``CONSTRUCTION_DEFAULTS``).
        """
        payload = self.model_dump(exclude={"description"})
        for fld, default in CONSTRUCTION_DEFAULTS.items():  # 17.5/18.1: defaults don't hash
            if payload.get(fld, default) == default:
                payload.pop(fld, None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def recipe_hash(self) -> str:
        """SHA-256 of the **recipe** only — the canonical payload without the identity fields
        (``name``, ``family``, ``version``). Two specs that would build the same book share it
        whatever they are called: the §12.3 no-respin check compares this, never the
        canonical hash (which a rename alone would change)."""
        payload = self.model_dump(exclude={"description", "name", "family", "version"})
        for fld, default in CONSTRUCTION_DEFAULTS.items():
            if payload.get(fld, default) == default:
                payload.pop(fld, None)
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


def count_free_params(spec: SignalSpec) -> tuple[int, dict[str, object]]:
    """G5/F5 counting: each nonzero feature weight is one free parameter (``certify``'s G5).

    Returns ``(count, structural)`` — ``structural`` lists every non-default construction
    field so a log entry or the Lab can disclose it (playbook §12.1 F5: structural menu
    picks don't count, but are always shown).
    """
    dumped = spec.model_dump()
    structural = {
        fld: dumped[fld]
        for fld, default in CONSTRUCTION_DEFAULTS.items()
        if dumped.get(fld, default) != default
    }
    return len(spec.features), structural


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


def _sector_size_zscore(values: pd.Series, sectors: pd.Series, market_cap: pd.Series) -> pd.Series:
    """Z-score with sector and size removed (18.18): the pool's winsorized z, residualized by
    one cross-sectional OLS on sector dummies (``Unknown`` is its own level) plus
    log(market cap), then z-scored again.

    Rows with no usable market cap (NaN or ≤ 0) or no feature value score NaN, and so do rows in
    a sector with fewer than ``_MIN_SECTOR_MEMBERS`` usable rows (the 17.5 small-group rule: a
    dummy would fit them exactly). The sector map is the static current map, not point-in-time
    (the 17.5 caveat).
    """
    out = pd.Series(float("nan"), index=values.index)
    z = _zscore(values)
    cap = pd.to_numeric(market_cap, errors="coerce").astype(float)
    sec = sectors.astype(object).where(sectors.notna(), "Unknown").astype(str)
    usable = z.notna() & (cap > 0)
    counts = sec[usable].value_counts()
    usable &= sec.map(counts).fillna(0) >= _MIN_SECTOR_MEMBERS
    if int(usable.sum()) < 2:
        return out
    dummies = pd.get_dummies(sec[usable], dtype=float)
    x = np.column_stack([dummies.to_numpy(), np.log(cap[usable].to_numpy())])
    y = z[usable].to_numpy(dtype=float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = pd.Series(y - x @ beta, index=z.index[usable.to_numpy()])
    out.loc[resid.index] = _zscore(resid)
    return out


def feature_z(values: pd.Series, pool: pd.DataFrame, neutralize: str) -> pd.Series:
    """One feature's z-scores over ``pool`` under a spec's neutralization: the single home used by
    :func:`score`, ``research.today`` and the factory, so the three can never disagree. A missing
    ``sector`` or ``market_cap`` column raises ``KeyError`` (never a guessed neutralization)."""
    if neutralize == "":
        return _zscore(values)
    if "sector" not in pool.columns:
        raise KeyError("sector")
    if neutralize == "sector":
        return _sector_zscore(values, pool["sector"])
    if neutralize == "sector_size":
        if "market_cap" not in pool.columns:
            raise KeyError("market_cap")
        return _sector_size_zscore(values, pool["sector"], pool["market_cap"])
    raise ValueError(f"unknown neutralize {neutralize!r}")  # pragma: no cover - validated


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
    mega-cap theme — roadmap 17.5); ``"sector_size"`` also removes log market cap
    (18.18, :func:`_sector_size_zscore`). A missing ``sector`` / ``market_cap`` column
    then raises ``KeyError``, the same posture as a missing feature.
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
        total = total + weight * feature_z(pool[feat], pool, spec.neutralize)
    out.loc[pool.index] = total
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "hash":
        print(load_spec(Path(sys.argv[2])).canonical_hash())
    else:
        print("usage: python -m heimdall.research.spec hash <spec.json>", file=sys.stderr)
        raise SystemExit(2)
