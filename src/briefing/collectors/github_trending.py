"""GitHub Trending scraper.

There is no official trending API. We parse https://github.com/trending HTML and
read the per-repo `<article.Box-row>` elements. Best-effort: if DOM changes the
collector logs a warning and returns empty (does not block the pipeline).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import Item
from ..utils.http import get_with_retry, make_async_client
from ..utils.logging import get_logger
from .base import BaseCollector
from .registry import register_collector

log = get_logger("collector.gh_trending")

BASE = "https://github.com/trending"


def _parse_stars(s: str) -> int:
    s = s.strip().replace(",", "")
    m = re.search(r"\d+", s)
    return int(m.group()) if m else 0


@register_collector
class GitHubTrendingCollector(BaseCollector):
    name = "github_trending"

    async def collect(self) -> list[Item]:
        cfg = self.config.collectors.github_trending
        if not cfg.enabled:
            return []
        results: list[Item] = []
        async with make_async_client() as client:
            for lang in cfg.languages or [""]:
                url = BASE
                params = {"since": cfg.since}
                if lang:
                    url = f"{BASE}/{lang}"
                try:
                    r = await get_with_retry(client, url, params=params)
                    results.extend(self._parse(r.text, lang))
                except Exception as e:
                    log.error("gh_trending_failed", lang=lang, error=str(e))
        # dedup within this collector (same repo can appear under multiple languages)
        seen: set[str] = set()
        dedup: list[Item] = []
        for it in results:
            if it.source_id in seen:
                continue
            seen.add(it.source_id)
            dedup.append(it)
        log.info("gh_trending_collected", count=len(dedup))
        return dedup

    def _parse(self, html: str, lang: str) -> list[Item]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("article.Box-row")
        if not rows:
            log.warning("gh_trending_no_rows", lang=lang)
            return []
        items: list[Item] = []
        for row in rows:
            a = row.select_one("h2 a")
            if not a or not a.get("href"):
                continue
            href = a["href"].strip().lstrip("/")
            if "/" not in href:
                continue
            owner, repo = href.split("/", 1)
            full_name = f"{owner}/{repo}"
            desc_el = row.select_one("p")
            description = desc_el.get_text(strip=True) if desc_el else ""
            star_el = row.select_one('a[href$="/stargazers"]')
            stars = _parse_stars(star_el.get_text()) if star_el else 0
            language_el = row.select_one('[itemprop="programmingLanguage"]')
            language = language_el.get_text(strip=True) if language_el else lang or ""
            items.append(
                Item(
                    source=self.name,
                    source_id=full_name,
                    url=f"https://github.com/{full_name}",
                    title=full_name,
                    abstract=description,
                    raw={"stars": stars, "language": language, "filter_language": lang},
                )
            )
        return items
