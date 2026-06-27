"""Transaction-cost model. Frictionless backtests lie — costs are mandatory.

See ``.claude/rules/backtest-honesty.md``. Values are fractions of traded
notional, applied per side by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Costs:
    """Per-side trading frictions, as fractions of notional."""

    fees: float = 0.001  # 10 bps commission/spread
    slippage: float = 0.0005  # 5 bps slippage

    def __post_init__(self) -> None:
        if self.fees < 0 or self.slippage < 0:
            raise ValueError("costs must be non-negative")


#: Sensible retail default; override per backtest.
DEFAULT_COSTS = Costs()

#: For zero-cost comparison in tests/sanity checks only — never for reporting.
ZERO_COSTS = Costs(fees=0.0, slippage=0.0)
