"""Pydantic models that flow through the pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Item(BaseModel):
    """A normalized piece of content from any source."""

    source: str                                # 'arxiv' | 'huggingface' | 'github_trending' | ...
    source_id: str                             # arxiv id / repo full_name / post id / ...
    url: str
    title: str
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = None
    published_at: datetime | None = None
    content_hash: str = ""                     # filled by db layer if blank
    score: float | None = None
    categories: list[str] = Field(default_factory=list)
    raw: dict[str, Any] | None = None          # source-specific extras (stars, upvotes, etc.)
    is_paper: bool = False                     # paper vs general (link, blog, repo, etc.)


class PaperSummary(BaseModel):
    method: str
    is_open_source: bool | None = None
    has_benchmark_gain: bool | None = None
    worth_deep_read: bool | None = None


class Summary(BaseModel):
    """LLM output for one item, in Chinese."""

    tldr: str
    why_matters: str
    work_relevance: str | None = None
    paper: PaperSummary | None = None
    model: str = ""
    prompt_version: str = ""


# --------------------------- analyst-mode models --------------------------- #

class MentionBrief(BaseModel):
    """One-line take on a non-key item, produced inline by Stage 1."""

    source_id: str
    one_liner: str


class Theme(BaseModel):
    """One thematic cluster identified by Stage 1."""

    id: str                                   # short slug, e.g. 'embodied_vla'
    title_zh: str
    why_hot: str                              # why this theme is heating up now
    problem: str                              # what problem it tackles
    approach: str                              # technical route
    industry_impact: str                       # potential industry impact
    connections: str                           # ties to agent/memory/retrieval/multimodal
    key_paper_ids: list[str] = Field(default_factory=list)        # source_ids picked for deep-read
    mentions: list[MentionBrief] = Field(default_factory=list)    # everything else in the theme


class AnalystReport(BaseModel):
    """Full Stage 1 output: themes + dropped noise."""

    executive_summary: str = ""
    themes: list[Theme] = Field(default_factory=list)
    noise_dropped_ids: list[str] = Field(default_factory=list)


class DeepReadSummary(BaseModel):
    """Stage 2 output for one key paper."""

    source_id: str
    tldr: str
    method: str
    novelty: str
    is_open_source: bool | None = None
    has_benchmark_gain: bool | None = None
    read_priority: str = "medium"            # high | medium
