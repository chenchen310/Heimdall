"""Descriptive TW chip/flow shaping (roadmap 11.5) — NOT a certified signal.

Turns the daily 籌碼 panel (``FinMindProvider.daily_chips``) into the cumulative
"who is accumulating" view the chips dashboard renders. Pure pandas — analytics
reads canonical data passed in, never a provider, and no LLM is involved. Today's
Picks never imports this: it is a descriptive lens only.
"""

from __future__ import annotations

import pandas as pd


def cumulative_flows(chips: pd.DataFrame) -> pd.DataFrame:
    """Add cumulative 外資/投信 net-buy-share columns over the window.

    ``foreign_cum_net`` / ``trust_cum_net`` are the running sum of daily net-buy
    **shares** (a missing trading day counts as zero net flow, so the running
    total is flat across gaps rather than broken). The input is a ``daily_chips``
    frame; a copy sorted ascending by ``date`` is returned. Empty in ⇒ empty out.
    """
    if chips.empty:
        return chips.copy()
    out = chips.sort_values("date").reset_index(drop=True).copy()
    out["foreign_cum_net"] = out["foreign_net_shares"].fillna(0.0).cumsum()
    out["trust_cum_net"] = out["trust_net_shares"].fillna(0.0).cumsum()
    return out
