"""Tag items with topic categories based on configured keywords (case-insensitive)."""
from __future__ import annotations

import json
import re

from sqlite_utils import Database

from ..config import AppConfig


def _compile_keyword_patterns(keywords: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    out: dict[str, list[re.Pattern]] = {}
    for topic, words in keywords.items():
        patterns: list[re.Pattern] = []
        for w in words:
            w = w.strip()
            if not w:
                continue
            # word-boundary match for alphanumeric tokens; substring for hyphenated/special.
            if re.fullmatch(r"[A-Za-z0-9]+", w):
                patterns.append(re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE))
            else:
                patterns.append(re.compile(re.escape(w), re.IGNORECASE))
        if patterns:
            out[topic] = patterns
    return out


def classify_text(text: str, patterns: dict[str, list[re.Pattern]]) -> list[str]:
    hits: list[str] = []
    for topic, pats in patterns.items():
        if any(p.search(text) for p in pats):
            hits.append(topic)
    return hits


def classify_new_items(db: Database, config: AppConfig, all_items: bool = False) -> int:
    """Update categories for items.

    By default only touches status='new' rows with empty categories. Pass
    ``all_items=True`` to (re-)classify every row in the DB — useful after a
    keyword/config change or to repair items whose categories were wiped.
    """
    patterns = _compile_keyword_patterns(config.interests.keywords)
    if not patterns:
        return 0
    if all_items:
        cur = db.execute("SELECT id, title, abstract FROM items")
    else:
        cur = db.execute(
            "SELECT id, title, abstract FROM items "
            "WHERE status='new' AND (categories IS NULL OR categories='' OR categories='[]')"
        )
    rows = cur.fetchall()
    n = 0
    for item_id, title, abstract in rows:
        text = f"{title or ''}\n{abstract or ''}"
        cats = classify_text(text, patterns)
        db.execute(
            "UPDATE items SET categories=? WHERE id=?",
            [json.dumps(cats, ensure_ascii=False), item_id],
        )
        n += 1
    db.conn.commit()
    return n
