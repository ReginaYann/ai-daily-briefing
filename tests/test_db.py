"""Test the DB schema + upsert + summary cache."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from briefing.db import (
    find_cached_summary,
    get_items_by_status,
    open_db,
    upsert_items,
    upsert_summary,
)
from briefing.models import Item, PaperSummary, Summary


@pytest.fixture
def db(tmp_path: Path):
    db = open_db(tmp_path / "test.db")
    yield db
    db.conn.close()


def _make_item(source="arxiv", sid="2401.00001", title="Test paper"):
    return Item(
        source=source,
        source_id=sid,
        url=f"https://arxiv.org/abs/{sid}",
        title=title,
        abstract="An abstract about multimodal agents.",
        authors=["A. Author"],
        published_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        is_paper=True,
    )


def test_upsert_inserts_and_updates(db):
    inserted, updated = upsert_items(db, [_make_item()])
    assert (inserted, updated) == (1, 0)
    inserted, updated = upsert_items(db, [_make_item(title="Updated title")])
    assert (inserted, updated) == (0, 1)
    rows = get_items_by_status(db, "new")
    assert len(rows) == 1
    assert rows[0]["title"] == "Updated title"


def test_summary_cache_hits_on_same_content_hash(db):
    upsert_items(db, [_make_item()])
    items = get_items_by_status(db, "new")
    item = items[0]
    summ = Summary(
        tldr="TL;DR", why_matters="重要",
        paper=PaperSummary(method="m", is_open_source=True),
        model="claude-test", prompt_version="v1",
    )
    upsert_summary(db, item["id"], summ)

    # Insert a *different* item with the same content_hash (e.g., re-fetched).
    same = _make_item(sid="2401.00002")        # different source_id
    same.content_hash = item["content_hash"]   # but same content
    upsert_items(db, [same])
    cached = find_cached_summary(db, item["content_hash"], "claude-test", "v1")
    assert cached is not None
    assert cached["tldr"] == "TL;DR"
