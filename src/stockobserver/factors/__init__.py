"""Factor computation: technical indicators, multi-factor scoring, panels, validation."""

from __future__ import annotations

from stockobserver.factors.indicators import atr, macd, rsi, sma
from stockobserver.factors.panel import PanelData, build_panel
from stockobserver.factors.scoring import (
    DEFAULT_WEIGHTS,
    FACTOR_NAMES,
    FACTORS,
    factor_scores,
)
from stockobserver.factors.validate import (
    FactorIC,
    information_coefficient,
    quantile_spread,
)

__all__ = [
    "sma",
    "rsi",
    "macd",
    "atr",
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
