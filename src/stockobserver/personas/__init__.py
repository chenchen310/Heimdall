"""OPTIONAL AI narrative reports. The quant core never imports this package.

Usable only when the ``personas`` extra is installed and ``ANTHROPIC_API_KEY`` is
set; absence degrades gracefully to the computed dashboard.
"""

from __future__ import annotations

from stockobserver.personas.client import DEFAULT_MODEL, PersonaError, generate
from stockobserver.personas.render import render_report
from stockobserver.personas.templates import PERSONAS, PersonaTemplate

__all__ = [
    "render_report",
    "generate",
    "PERSONAS",
    "PersonaTemplate",
    "PersonaError",
    "DEFAULT_MODEL",
]
