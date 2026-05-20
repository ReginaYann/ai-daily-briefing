"""Ollama (local model) provider."""
from __future__ import annotations

from typing import Any

import ollama

from .base import BaseLLMProvider
from .claude import _extract_json


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, max_tokens: int = 800, temperature: float = 0.2):
        super().__init__(model=model, max_tokens=max_tokens, temperature=temperature)
        self.client = ollama.Client(host=base_url)

    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            options={"temperature": self.temperature, "num_predict": self.max_tokens},
            format="json",
        )
        text = (resp.get("message", {}).get("content") or "").strip()
        return _extract_json(text)
