"""OpenAI provider (Chat Completions, JSON response format)."""
from __future__ import annotations

from typing import Any

from openai import OpenAI

from .base import BaseLLMProvider
from .claude import _extract_json


class OpenAIProvider(BaseLLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, max_tokens: int = 800, temperature: float = 0.2):
        super().__init__(model=model, max_tokens=max_tokens, temperature=temperature)
        self.client = OpenAI(api_key=api_key)

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return _extract_json(text)
