"""Thin Claude API wrapper for the optional persona-report layer.

Lazy-imports ``anthropic`` so the package loads (and the rest of the app runs)
without the optional ``personas`` extra installed. The client is injectable so
``render`` can be tested without a key or network. Model defaults to a current
Claude model — see the ``claude-api`` skill; do not hardcode a stale id.
"""

from __future__ import annotations

import os
from typing import Any

#: Current default model (see the claude-api skill / docs/ for guidance).
DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are a precise sell-side analyst. Write the requested report using ONLY the "
    "computed data provided. If a figure is missing, say so explicitly rather than "
    "inventing it. Respond with the report content only — no preamble or meta-commentary."
)


class PersonaError(RuntimeError):
    """Raised when the AI report layer is unavailable or fails."""


def _default_client() -> Any:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise PersonaError("AI reports require ANTHROPIC_API_KEY (set it in .env)")
    import anthropic  # imported lazily — optional dependency

    return anthropic.Anthropic()


def generate(
    prompt: str,
    *,
    system: str = _SYSTEM,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 12_000,
    client: Any | None = None,
) -> str:
    """Generate report text from ``prompt``. ``client`` is injectable for tests."""
    cli = client if client is not None else _default_client()
    resp = cli.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
