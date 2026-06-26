"""Render a persona report from a computed payload (the only LLM entry point).

A persona receives a fully-computed payload (the numbers its dashboard already
shows) and turns it into prose via the Claude API. It computes nothing itself.
The quant core does NOT import this module — wire it in at the UI edge, guarded
by key presence. See ``src/stockobserver/personas/CLAUDE.md``.
"""

from __future__ import annotations

import json
from typing import Any

from stockobserver.personas.client import PersonaError, generate
from stockobserver.personas.templates import PERSONAS


def render_report(persona_key: str, payload: dict[str, Any], *, client: Any | None = None) -> str:
    """Generate the ``persona_key`` report for ``payload`` (a computed-metrics dict)."""
    if persona_key not in PERSONAS:
        raise PersonaError(f"unknown persona {persona_key!r}; have {sorted(PERSONAS)}")
    template = PERSONAS[persona_key]
    prompt = (
        f"{template.instructions}\n\n"
        "Computed data (use only this; state explicitly if something is missing):\n"
        f"{json.dumps(payload, indent=2, default=str)}\n\n"
        "Write the report now."
    )
    return generate(prompt, system=template.system, client=client)
