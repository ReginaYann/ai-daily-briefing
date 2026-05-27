"""arXiv collector — uses the `arxiv` Python client.

Pulls recent submissions per category within `lookback_hours`. We query each
category separately with small page sizes (instead of one big OR-query across
10 categories) because the latter pattern looks like crawling and gets 429'd.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import arxiv

from ..models import Item
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.arxiv")

# Per-category query tuning. arXiv asks for ≥3s between requests; we sleep more
# between *separate* queries so the overall pattern looks like a normal client.
ARXIV_PAGE_SIZE = 30
ARXIV_PER_CATEGORY_LIMIT = 30      # one page per category, no pagination needed
ARXIV_DELAY_SECONDS = 5            # within-query pagination delay (used by arxiv client)
ARXIV_NUM_RETRIES = 3
ARXIV_BETWEEN_QUERIES_SECONDS = 10 # sleep between distinct category queries
ARXIV_BACKOFF_SECONDS = 90         # longer wait after a 429 before retrying that one category


@register_collector
class ArxivCollector(BaseCollector):
    name = "arxiv"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.arxiv
        if not cfg.enabled:
            return []
        cats = cfg.categories or ["cs.AI"]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.lookback_hours)
        per_cat_cap = min(ARXIV_PER_CATEGORY_LIMIT, cfg.max_items)

        seen: set[str] = set()
        items: list[Item] = []

        for idx, cat in enumerate(cats):
            if idx > 0:
                await asyncio.sleep(ARXIV_BETWEEN_QUERIES_SECONDS)
            cat_items = await self._fetch_category_with_retry(cat, per_cat_cap, cutoff)
            for it in cat_items:
                if it.source_id in seen:
                    continue
                seen.add(it.source_id)
                items.append(it)

        # Sort newest-first then cap to max_items globally.
        items.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
        items = items[: cfg.max_items]
        log.info("arxiv_collected", count=len(items), categories=len(cats))
        return items

    async def _fetch_category_with_retry(
        self, category: str, max_results: int, cutoff: datetime
    ) -> list[Item]:
        try:
            return self._fetch_category(category, max_results, cutoff)
        except Exception as e:
            log.warning("arxiv_category_failed_will_retry",
                        category=category, error=str(e),
                        backoff=ARXIV_BACKOFF_SECONDS)
            await asyncio.sleep(ARXIV_BACKOFF_SECONDS)
            try:
                return self._fetch_category(category, max_results, cutoff)
            except Exception as e2:
                log.error("arxiv_category_failed", category=category, error=str(e2))
                return []

    def _fetch_category(
        self, category: str, max_results: int, cutoff: datetime
    ) -> list[Item]:
        client = arxiv.Client(
            page_size=ARXIV_PAGE_SIZE,
            delay_seconds=ARXIV_DELAY_SECONDS,
            num_retries=ARXIV_NUM_RETRIES,
        )
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        items: list[Item] = []
        for r in client.results(search):
            published = r.published.astimezone(timezone.utc) if r.published else None
            if published and published < cutoff:
                break
            arxiv_id = r.get_short_id()
            items.append(
                Item(
                    source=self.name,
                    source_id=arxiv_id,
                    url=r.entry_id,
                    title=r.title.strip(),
                    authors=[a.name for a in r.authors],
                    abstract=(r.summary or "").strip().replace("\n", " "),
                    published_at=published,
                    is_paper=True,
                    raw={
                        "primary_category": r.primary_category,
                        "categories": list(r.categories),
                        "pdf_url": r.pdf_url,
                        "comment": r.comment,
                    },
                )
            )
        log.info("arxiv_category_done", category=category, count=len(items))
        return items
