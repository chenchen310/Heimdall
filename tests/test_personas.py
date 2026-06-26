"""Optional persona layer: render wiring with a fake client; key gating (no network)."""

from __future__ import annotations

from typing import Any

import pytest

from stockobserver.personas.client import PersonaError, generate
from stockobserver.personas.render import render_report


class _Block:
    def __init__(self, text: str) -> None:
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, blocks: list[_Block]) -> None:
        self.content = blocks


class _Messages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        return _Resp([_Block("REPORT BODY")])


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _Messages()


def test_render_embeds_payload_and_uses_template() -> None:
    fake = _FakeClient()
    out = render_report("goldman", {"symbol": "AAPL.US", "pe": 36}, client=fake)
    assert out == "REPORT BODY"

    call = fake.messages.calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert "Goldman" in call["system"]  # role from the template
    assert "AAPL.US" in call["messages"][0]["content"]  # computed payload embedded


def test_unknown_persona_raises() -> None:
    with pytest.raises(PersonaError, match="unknown persona"):
        render_report("nope", {}, client=_FakeClient())


def test_generate_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(PersonaError, match="ANTHROPIC_API_KEY"):
        generate("hello")  # no client injected → resolves default → no key
