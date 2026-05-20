"""Cross-source dedup.

Strategy:
1. URL hash match (after URL normalization).
2. Same content_hash (title + abstract) match.

When duplicates collide across sources, prefer the higher source_weight; mark losers
status='skipped' so they are not summarized but still kept for traceability.
"""
from __future__ import annotations

from sqlite_utils import Database

from ..config import AppConfig
from ..utils.hashing import normalize_url


def dedup_new_items(db: Database, config: AppConfig) -> int:
    weights = config.ranker.source_weights or {}
    rows = list(db.execute(
        "SELECT id, source, url, content_hash FROM items WHERE status='new'"
    ).fetchall())

    by_url: dict[str, list[tuple[int, str]]] = {}
    by_hash: dict[str, list[tuple[int, str]]] = {}

    for item_id, source, url, ch in rows:
        u = normalize_url(url)
        by_url.setdefault(u, []).append((item_id, source))
        by_hash.setdefault(ch, []).append((item_id, source))

    skipped = 0

    def _resolve(group: list[tuple[int, str]]):
        nonlocal skipped
        if len(group) <= 1:
            return
        group_sorted = sorted(
            group, key=lambda x: weights.get(x[1], 0.5), reverse=True
        )
        for item_id, _src in group_sorted[1:]:
            db.execute("UPDATE items SET status='skipped' WHERE id=? AND status='new'", [item_id])
            skipped += 1

    for g in by_url.values():
        _resolve(g)
    for g in by_hash.values():
        _resolve(g)

    db.conn.commit()
    return skipped
