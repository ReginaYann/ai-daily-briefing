"""Configuration loading: config.yaml + .env (via pydantic-settings)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    provider: str = "claude"               # claude | openai | ollama | deepseek
    model: str = "claude-opus-4-5"
    max_tokens_per_summary: int = 800
    temperature: float = 0.2
    concurrency: int = 4
    ollama_base_url: str = "http://localhost:11434"
    deepseek_base_url: str = "https://api.deepseek.com"

    # Optional per-stage overrides (analyst mode).
    # If unset, both stages use `model` / `max_tokens_per_summary`.
    stage1_model: str | None = None        # used for thematic clustering
    stage2_model: str | None = None        # used for per-paper deep-read
    stage1_max_tokens: int | None = None   # reasoners need more headroom for CoT
    stage2_max_tokens: int | None = None


class InterestsConfig(BaseModel):
    topics: list[str] = Field(default_factory=list)
    keywords: dict[str, list[str]] = Field(default_factory=dict)


class ArxivCollectorConfig(BaseModel):
    enabled: bool = True
    categories: list[str] = Field(default_factory=lambda: ["cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO"])
    lookback_hours: int = 36
    max_items: int = 120


class HuggingFaceCollectorConfig(BaseModel):
    enabled: bool = True
    daily_papers: bool = True
    trending_models: int = 20


class GitHubTrendingCollectorConfig(BaseModel):
    enabled: bool = True
    languages: list[str] = Field(default_factory=lambda: ["", "python"])
    since: str = "daily"


class RedditCollectorConfig(BaseModel):
    enabled: bool = False
    subreddits: list[str] = Field(default_factory=lambda: ["MachineLearning", "LocalLLaMA"])
    min_upvotes: int = 50
    lookback_hours: int = 36


class HackerNewsCollectorConfig(BaseModel):
    enabled: bool = True
    min_score: int = 80
    max_items: int = 50


class RSSFeed(BaseModel):
    name: str
    url: str


class RSSCollectorConfig(BaseModel):
    enabled: bool = True
    feeds: list[RSSFeed] = Field(default_factory=list)


class CollectorsConfig(BaseModel):
    arxiv: ArxivCollectorConfig = Field(default_factory=ArxivCollectorConfig)
    huggingface: HuggingFaceCollectorConfig = Field(default_factory=HuggingFaceCollectorConfig)
    github_trending: GitHubTrendingCollectorConfig = Field(default_factory=GitHubTrendingCollectorConfig)
    reddit: RedditCollectorConfig = Field(default_factory=RedditCollectorConfig)
    hackernews: HackerNewsCollectorConfig = Field(default_factory=HackerNewsCollectorConfig)
    rss: RSSCollectorConfig = Field(default_factory=RSSCollectorConfig)


class RankerConfig(BaseModel):
    source_weights: dict[str, float] = Field(default_factory=dict)
    top_n_to_summarize: int = 30
    min_score: float = 0.4
    recency_half_life_hours: int = 36


class OutputConfig(BaseModel):
    reports_dir: str = "./reports"
    date_format: str = "%Y-%m-%d"
    group_by: str = "category"             # category | source (legacy mode only)
    mode: str = "analyst"                  # analyst | legacy
    max_themes: int = 5
    max_key_papers_per_theme: int = 3
    max_total_key_papers: int = 10
    top_n_for_clustering: int = 50         # how many ranked items to feed Stage 1


class CacheConfig(BaseModel):
    http_dir: str = "./data/http_cache"
    llm_cache: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    interests: InterestsConfig = Field(default_factory=InterestsConfig)
    collectors: CollectorsConfig = Field(default_factory=CollectorsConfig)
    ranker: RankerConfig = Field(default_factory=RankerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class Secrets(BaseSettings):
    """Loaded from .env / environment. Optional — only needed for the providers you enable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "ai-daily-briefing/0.1"


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"config not found at {p}. Run `briefing init` to create config.yaml."
        )
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)


def load_secrets() -> Secrets:
    return Secrets()
