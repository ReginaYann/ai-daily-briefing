"""Shared async HTTP client with retry."""
from __future__ import annotations

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DEFAULT_HEADERS = {
    "User-Agent": "ai-daily-briefing/0.1 (+https://github.com/anthropics/claude-code)",
    "Accept": "*/*",
}


def make_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
    )


async def get_with_retry(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    """GET with exponential backoff on transient network errors / 5xx."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        reraise=True,
    ):
        with attempt:
            r = await client.get(url, **kw)
            if r.status_code >= 500:
                r.raise_for_status()
            return r
    raise RuntimeError("unreachable")
