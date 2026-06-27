"""Factor computation: technical indicators, multi-factor scoring, panels, validation."""

from __future__ import annotations

from heimdall.factors.indicators import atr, bollinger, macd, rsi, sma
from heimdall.factors.panel import PanelData, build_panel
from heimdall.factors.scoring import (
    DEFAULT_WEIGHTS,
    FACTOR_NAMES,
    FACTORS,
    factor_scores,
)
from heimdall.factors.validate import (
    FactorIC,
    information_coefficient,
    quantile_spread,
)

__all__ = [
    "sma",
    "rsi",
    "macd",
    "atr",
    "bollinger",
    "factor_scores",
    "FACTORS",
    "FACTOR_NAMES",
    "DEFAULT_WEIGHTS",
    "build_panel",
    "PanelData",
    "information_coefficient",
    "quantile_spread",
    "FactorIC",
]
