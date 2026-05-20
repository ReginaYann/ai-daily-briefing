"""Pick an LLM provider implementation based on AppConfig."""
from __future__ import annotations

from ..config import AppConfig, Secrets
from .base import BaseLLMProvider


def build_provider(
    config: AppConfig,
    secrets: Secrets,
    model_override: str | None = None,
    max_tokens_override: int | None = None,
) -> BaseLLMProvider:
    """Build the provider, optionally overriding model and/or max_tokens.

    Used by analyst mode to pick different models for Stage 1 vs Stage 2 (e.g.
    a reasoner for clustering and a chat model for fast extraction).
    """
    p = config.llm.provider.lower()
    model = model_override or config.llm.model
    max_tokens = max_tokens_override or config.llm.max_tokens_per_summary

    if p == "claude":
        from .claude import ClaudeProvider

        if not secrets.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set — needed for claude provider")
        return ClaudeProvider(
            api_key=secrets.anthropic_api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=config.llm.temperature,
        )
    if p == "openai":
        from .openai import OpenAIProvider

        if not secrets.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set — needed for openai provider")
        return OpenAIProvider(
            api_key=secrets.openai_api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=config.llm.temperature,
        )
    if p == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(
            base_url=config.llm.ollama_base_url,
            model=model,
            max_tokens=max_tokens,
            temperature=config.llm.temperature,
        )
    if p == "deepseek":
        from .deepseek import DeepSeekProvider

        if not secrets.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set — needed for deepseek provider")
        return DeepSeekProvider(
            api_key=secrets.deepseek_api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=config.llm.temperature,
            base_url=config.llm.deepseek_base_url,
        )
    raise ValueError(f"unknown llm provider: {p}")
