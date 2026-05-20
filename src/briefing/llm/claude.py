"""Anthropic Claude provider."""
from __future__ import annotations

import json
from typing import Any

from anthropic import Anthropic

from .base import BaseLLMProvider, LLMOutputError


class ClaudeProvider(BaseLLMProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str, max_tokens: int = 800, temperature: float = 0.2):
        super().__init__(model=model, max_tokens=max_tokens, temperature=temperature)
        self.client = Anthropic(api_key=api_key)

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        return _extract_json(text)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first top-level JSON object out of a model response."""
    if not text:
        raise LLMOutputError("empty response")
    # Strip code fences if present.
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    # Try direct parse first.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Fallback: locate the outermost braces.
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMOutputError(f"no JSON object in response: {text[:200]!r}")
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"invalid JSON: {e}") from e
