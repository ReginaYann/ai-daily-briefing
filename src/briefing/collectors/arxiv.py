"""arXiv collector — uses the `arxiv` Python client.

Pulls recent submissions in the configured categories within `lookback_hours`. The
arxiv client wraps the arXiv API and handles pagination/rate-limits.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import arxiv

from ..models import Item
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.arxiv")


@register_collector
class ArxivCollector(BaseCollector):
    name = "arxiv"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.arxiv
        if not cfg.enabled:
            return []
        cats = cfg.categories or ["cs.AI"]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg.lookback_hours)

        # arXiv query: OR over categories, sorted by submitted date desc.
        query = " OR ".join(f"cat:{c}" for c in cats)
        client = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)
        search = arxiv.Search(
            query=query,
            max_results=cfg.max_items,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        items: list[Item] = []
        try:
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
        except Exception as e:
            log.error("arxiv_query_failed", error=str(e))
            return items

        log.info("arxiv_collected", count=len(items), query=query)
        return items
