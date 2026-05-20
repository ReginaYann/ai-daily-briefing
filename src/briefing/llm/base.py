"""Provider-agnostic LLM interface used by the summarizer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMProvider(ABC):
    """Each provider exposes a single text→JSON method.

    Implementations should return a parsed dict; on parse failure they may raise
    ``LLMOutputError`` to let the summarizer downgrade to a plain-text result.
    """

    name: str = ""

    def __init__(self, model: str, max_tokens: int = 800, temperature: float = 0.2):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return JSON parsed from the model's output."""
        ...


class LLMOutputError(RuntimeError):
    pass
