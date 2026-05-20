"""Heuristic ranker.

Score formula:
    score = source_weight * (0.4 + 0.15 * num_categories_hit)
            * recency_factor
            * (1 + bonus_from_raw_signals)

Where:
- recency_factor = 0.5 ** (age_hours / half_life_hours), clipped to [0.1, 1.0]
- bonus_from_raw_signals reads stars / upvotes / votes from raw json (0..0.5).

This keeps the ranker simple and explainable. It runs on items with status='new'.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlite_utils import Database

from ..config import AppConfig


def _recency_factor(published_at_iso: str | None, half_life_hours: int) -> float:
    if not published_at_iso:
        return 0.6
    try:
        dt = datetime.fromisoformat(published_at_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.6
    age_h = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    f = 0.5 ** (age_h / max(1, half_life_hours))
    return max(0.1, min(1.0, f))


def _signal_bonus(source: str, raw_json: str | None) -> float:
    if not raw_json:
        return 0.0
    try:
        raw = json.loads(raw_json)
    except Exception:
        return 0.0

    if source == "github_trending":
        stars = raw.get("stars", 0) or 0
        return min(0.5, math.log10(stars + 1) / 5.0)
    if source == "huggingface":
        likes = raw.get("upvotes", raw.get("likes", 0)) or 0
        return min(0.4, likes / 100.0)
    if source == "hackernews":
        score = raw.get("score", 0) or 0
        return min(0.4, score / 500.0)
    if source == "reddit":
        ups = raw.get("ups", raw.get("score", 0)) or 0
        return min(0.4, ups / 1000.0)
    return 0.0


def rank_new_items(db: Database, config: AppConfig) -> int:
    weights = config.ranker.source_weights or {}
    half_life = config.ranker.recency_half_life_hours
    cur = db.execute(
        "SELECT id, source, categories, published_at, raw FROM items WHERE status='new'"
    )
    rows = cur.fetchall()
    n = 0
    for item_id, source, cats_json, published_at, raw in rows:
        try:
            cats = json.loads(cats_json) if cats_json else []
        except Exception:
            cats = []
        sw = weights.get(source, 0.5)
        topic_factor = 0.4 + 0.15 * min(4, len(cats))
        rf = _recency_factor(published_at, half_life)
        bonus = _signal_bonus(source, raw)
        score = sw * topic_factor * rf * (1.0 + bonus)
        db.execute("UPDATE items SET score=? WHERE id=?", [round(score, 4), item_id])
        n += 1
    db.conn.commit()
    return n
