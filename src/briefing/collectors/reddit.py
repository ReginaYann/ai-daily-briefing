"""Reddit collector using PRAW."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import praw

from ..models import Item
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.reddit")


@register_collector
class RedditCollector(BaseCollector):
    name = "reddit"

    def is_enabled(self) -> bool:
        cfg = self.config.collectors.reddit
        if not cfg.enabled:
            return False
        if not (self.secrets.reddit_client_id and self.secrets.reddit_client_secret):
            log.warning("reddit_disabled_no_creds")
            return False
        return True

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.reddit
        # PRAW is sync — run in a thread so we don't block the event loop.
        return await asyncio.to_thread(self._collect_sync, cfg)

    def _collect_sync(self, cfg) -> list[Item]:
        reddit = praw.Reddit(
            client_id=self.secrets.reddit_client_id,
            client_secret=self.secrets.reddit_client_secret,
            user_agent=self.secrets.reddit_user_agent,
            check_for_async=False,
        )
        items: list[Item] = []
        cutoff_ts = (datetime.now(timezone.utc).timestamp() - cfg.lookback_hours * 3600)
        for name in cfg.subreddits or []:
            try:
                sub = reddit.subreddit(name)
                for post in sub.hot(limit=60):
                    if post.stickied:
                        continue
                    if post.score < cfg.min_upvotes:
                        continue
                    if post.created_utc < cutoff_ts:
                        continue
                    title = (post.title or "").strip()
                    link = post.url
                    if not link:
                        link = f"https://reddit.com{post.permalink}"
                    items.append(
                        Item(
                            source=self.name,
                            source_id=post.id,
                            url=link,
                            title=title,
                            abstract=(post.selftext or "")[:1500],
                            published_at=datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
                            raw={
                                "subreddit": name,
                                "ups": post.score,
                                "num_comments": post.num_comments,
                                "permalink": f"https://reddit.com{post.permalink}",
                                "flair": post.link_flair_text,
                            },
                        )
                    )
            except Exception as e:
                log.error("reddit_subreddit_failed", subreddit=name, error=str(e))
                continue
        log.info("reddit_collected", count=len(items))
        return items
