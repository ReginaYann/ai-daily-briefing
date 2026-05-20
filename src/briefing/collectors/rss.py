"""Generic RSS / Atom collector. Reads feeds listed in config.collectors.rss.feeds."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import feedparser

from ..models import Item
from ..utils.http import get_with_retry, make_async_client
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.rss")

# RSS feeds publish months of backlog. Keep only recent entries to avoid spamming
# the LLM with old news.
RSS_LOOKBACK_DAYS = 14
MAX_ENTRIES_PER_FEED = 30


def _struct_time_to_dt(t) -> datetime | None:
    if not t:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    except Exception:
        return None


@register_collector
class RSSCollector(BaseCollector):
    name = "rss"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.rss
        if not cfg.enabled:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=RSS_LOOKBACK_DAYS)
        items: list[Item] = []
        async with make_async_client() as client:
            for feed_cfg in cfg.feeds:
                try:
                    r = await get_with_retry(client, feed_cfg.url)
                    parsed = feedparser.parse(r.text)
                except Exception as e:
                    log.warning("rss_fetch_failed", feed=feed_cfg.name, error=str(e))
                    continue
                if parsed.bozo and not parsed.entries:
                    log.warning("rss_parse_empty", feed=feed_cfg.name)
                    continue
                per_feed = 0
                for e in parsed.entries:
                    link = (e.get("link") or "").strip()
                    if not link:
                        continue
                    eid = e.get("id") or link
                    published = (
                        _struct_time_to_dt(e.get("published_parsed"))
                        or _struct_time_to_dt(e.get("updated_parsed"))
                    )
                    if published and published < cutoff:
                        continue
                    summary = e.get("summary") or e.get("description") or ""
                    summary_text = _strip_html(summary)
                    items.append(
                        Item(
                            source=self.name,
                            source_id=f"{feed_cfg.name}|{eid}",
                            url=link,
                            title=(e.get("title") or "").strip(),
                            abstract=summary_text,
                            published_at=published,
                            authors=[a.get("name") for a in e.get("authors") or [] if a.get("name")],
                            raw={"feed": feed_cfg.name},
                        )
                    )
                    per_feed += 1
                    if per_feed >= MAX_ENTRIES_PER_FEED:
                        break
        log.info("rss_collected", count=len(items))
        return items


def _strip_html(html: str) -> str:
    """Quick & dirty HTML → text for RSS summaries."""
    from bs4 import BeautifulSoup

    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
