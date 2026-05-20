"""HuggingFace collector.

- Daily papers via https://huggingface.co/api/daily_papers (undocumented but stable).
- Trending models via https://huggingface.co/api/models?sort=likes7d (best-effort).
"""
from __future__ import annotations

from datetime import datetime

from ..models import Item
from ..utils.http import get_with_retry, make_async_client
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.hf")

DAILY_PAPERS_URL = "https://huggingface.co/api/daily_papers"
MODELS_URL = "https://huggingface.co/api/models"


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@register_collector
class HuggingFaceCollector(BaseCollector):
    name = "huggingface"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.huggingface
        if not cfg.enabled:
            return []
        items: list[Item] = []
        async with make_async_client() as client:
            if cfg.daily_papers:
                items.extend(await self._daily_papers(client))
            if cfg.trending_models > 0:
                items.extend(await self._trending_models(client, cfg.trending_models))
        log.info("hf_collected", count=len(items))
        return items

    async def _daily_papers(self, client) -> list[Item]:
        try:
            r = await get_with_retry(client, DAILY_PAPERS_URL)
            data = r.json()
        except Exception as e:
            log.error("hf_daily_papers_failed", error=str(e))
            return []
        out: list[Item] = []
        for entry in data or []:
            p = entry.get("paper") or entry
            pid = p.get("id") or entry.get("id")
            if not pid:
                continue
            arxiv_url = f"https://arxiv.org/abs/{pid}"
            title = p.get("title") or entry.get("title") or ""
            summary = p.get("summary") or ""
            authors = [a.get("name") for a in p.get("authors", []) if a.get("name")]
            published = _parse_dt(entry.get("publishedAt") or p.get("publishedAt"))
            upvotes = p.get("upvotes") or entry.get("upvotes") or 0
            out.append(
                Item(
                    source=self.name,
                    source_id=f"paper:{pid}",
                    url=arxiv_url,
                    title=title.strip(),
                    abstract=summary.strip().replace("\n", " "),
                    authors=authors,
                    published_at=published,
                    is_paper=True,
                    raw={"upvotes": upvotes, "hf_url": f"https://huggingface.co/papers/{pid}"},
                )
            )
        return out

    async def _trending_models(self, client, n: int) -> list[Item]:
        try:
            r = await get_with_retry(
                client,
                MODELS_URL,
                params={"sort": "likes7d", "direction": -1, "limit": n},
            )
            data = r.json()
        except Exception as e:
            log.error("hf_models_failed", error=str(e))
            return []
        out: list[Item] = []
        for m in data or []:
            mid = m.get("id") or m.get("modelId")
            if not mid:
                continue
            tags = ", ".join(m.get("tags") or [])
            out.append(
                Item(
                    source=self.name,
                    source_id=f"model:{mid}",
                    url=f"https://huggingface.co/{mid}",
                    title=mid,
                    abstract=f"{m.get('pipeline_tag') or ''} · {tags[:200]}",
                    published_at=_parse_dt(m.get("createdAt") or m.get("lastModified")),
                    raw={"likes": m.get("likes"), "downloads": m.get("downloads")},
                )
            )
        return out
