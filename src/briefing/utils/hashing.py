"""Hashing helpers — used for content de-duplication and cache keys."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "src", "fbclid", "gclid",
}


def normalize_url(url: str) -> str:
    """Lowercase host, strip trailing slash, drop fragments and tracking params."""
    try:
        u = urlparse(url.strip())
    except Exception:
        return url
    netloc = u.netloc.lower()
    path = re.sub(r"/+$", "", u.path) or "/"
    if u.query:
        kept = [
            kv for kv in u.query.split("&")
            if "=" in kv and kv.split("=", 1)[0] not in _TRACKING_PARAMS
        ]
        query = "&".join(kept)
    else:
        query = ""
    return urlunparse((u.scheme.lower(), netloc, path, "", query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def content_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        if p:
            h.update(p.strip().lower().encode("utf-8"))
            h.update(b"\x00")
    return h.hexdigest()
