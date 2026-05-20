"""Hacker News collector via the Firebase API (no auth)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from ..models import Item
from ..utils.http import get_with_retry, make_async_client
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.hn")

TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


@register_collector
class HackerNewsCollector(BaseCollector):
    name = "hackernews"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.hackernews
        if not cfg.enabled:
            return []
        async with make_async_client() as client:
            try:
                r = await get_with_retry(client, TOP_URL)
                ids = r.json()[: cfg.max_items * 2]
            except Exception as e:
                log.error("hn_top_failed", error=str(e))
                return []

            async def fetch(item_id: int):
                try:
                    rr = await get_with_retry(client, ITEM_URL.format(id=item_id))
                    return rr.json()
                except Exception:
                    return None

            raw_items = await asyncio.gather(*(fetch(i) for i in ids))

        items: list[Item] = []
        for raw in raw_items:
            if not raw or raw.get("type") != "story":
                continue
            score = raw.get("score", 0) or 0
            if score < cfg.min_score:
                continue
            url = raw.get("url") or f"https://news.ycombinator.com/item?id={raw['id']}"
            ts = raw.get("time")
            published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
            items.append(
                Item(
                    source=self.name,
                    source_id=str(raw["id"]),
                    url=url,
                    title=raw.get("title") or "",
                    abstract=raw.get("text"),
                    published_at=published,
                    raw={
                        "score": score,
                        "by": raw.get("by"),
                        "descendants": raw.get("descendants"),
                        "hn_url": f"https://news.ycombinator.com/item?id={raw['id']}",
                    },
                )
            )
            if len(items) >= cfg.max_items:
                break

        log.info("hn_collected", count=len(items))
        return items
