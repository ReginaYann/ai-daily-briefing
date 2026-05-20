"""DeepSeek provider.

DeepSeek exposes an OpenAI-compatible Chat Completions endpoint, so we reuse the
``openai`` SDK and just point ``base_url`` at https://api.deepseek.com.

Common models:
- ``deepseek-chat``      — general (DeepSeek-V3.x). Supports JSON response_format.
- ``deepseek-reasoner``  — reasoning (R1). Does NOT support response_format;
                           returns plain text we parse with the same JSON extractor.
"""
from __future__ import annotations

from typing import Any

from openai import OpenAI

from .base import BaseLLMProvider
from .claude import _extract_json


DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(BaseLLMProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 800,
        temperature: float = 0.2,
        base_url: str = DEFAULT_BASE_URL,
    ):
        super().__init__(model=model, max_tokens=max_tokens, temperature=temperature)
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        # deepseek-reasoner ignores / rejects response_format; only enable for chat.
        if "reasoner" not in self.model.lower():
            kwargs["response_format"] = {"type": "json_object"}

        resp = self.client.chat.completions.create(**kwargs)
        text = (resp.choices[0].message.content or "").strip()
        return _extract_json(text)
