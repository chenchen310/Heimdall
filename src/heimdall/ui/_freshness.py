"""Shared 'how stale is the snapshot' signal, reused by any page that shows an
``as_of`` date. Business-day thresholds mirror Today's Picks' own stale check
(over 5 business days triggers its refresh warning); this just gives the pages
that only *mention* the date a lightweight, consistent, colour-coded word for
it instead of a bare date.
"""

from __future__ import annotations

import pandas as pd

from heimdall.research.today import freshness
from heimdall.ui.i18n import t

_WARN_BDAYS = 2
_STALE_BDAYS = 5


def freshness_word(snap: pd.DataFrame) -> str | None:
    """``"🟢 fresh · today"`` / ``"🟡 aging · 3 bdays old"`` / ``"🔴 stale · …"``.

    ``None`` when the snapshot carries no usable ``as_of`` column (caller should
    just omit the badge rather than show a confusing one).
    """
    try:
        bdays = freshness(snap)
    except ValueError:
        return None
    if bdays <= _WARN_BDAYS:
        icon, word = "🟢", t("fresh")
    elif bdays <= _STALE_BDAYS:
        icon, word = "🟡", t("aging")
    else:
        icon, word = "🔴", t("stale")
    age = t("updated today") if bdays <= 0 else f"{bdays} {t('bdays old')}"
    return f"{icon} {word} · {age}"
