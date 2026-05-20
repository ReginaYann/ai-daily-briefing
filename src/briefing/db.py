"""SQLite storage layer using sqlite-utils.

Schema is created idempotently on first connection. Items use (source, source_id) as the
natural key. Summaries are 1:1 with items. Runs and source_state track scheduling/cursors.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from sqlite_utils import Database

from .models import Item, PaperSummary, Summary
from .utils.hashing import content_hash


DEFAULT_DB_PATH = Path("./data/briefing.db")


def open_db(path: str | Path = DEFAULT_DB_PATH) -> Database:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    db = Database(p)
    _ensure_schema(db)
    return db


def _ensure_schema(db: Database) -> None:
    if "items" not in db.table_names():
        db["items"].create(
            {
                "id": int,
                "source": str,
                "source_id": str,
                "url": str,
                "title": str,
                "authors": str,           # json array
                "abstract": str,
                "published_at": str,
                "fetched_at": str,
                "content_hash": str,
                "score": float,
                "categories": str,        # json array
                "raw": str,               # json blob
                "is_paper": int,
                "status": str,            # new | summarized | rendered | skipped
            },
            pk="id",
            not_null={"source", "source_id", "url", "title", "content_hash"},
        )
        db["items"].create_index(["source", "source_id"], unique=True)
        db["items"].create_index(["status"])
        db["items"].create_index(["published_at"])
        db["items"].create_index(["content_hash"])

    if "summaries" not in db.table_names():
        db["summaries"].create(
            {
                "item_id": int,
                "tldr": str,
                "why_matters": str,
                "work_relevance": str,
                "paper_method": str,
                "is_open_source": int,
                "has_benchmark_gain": int,
                "worth_deep_read": int,
                "model": str,
                "prompt_version": str,
                "created_at": str,
            },
            pk="item_id",
            foreign_keys=[("item_id", "items", "id")],
        )

    if "runs" not in db.table_names():
        db["runs"].create(
            {
                "id": int,
                "started_at": str,
                "finished_at": str,
                "items_collected": int,
                "items_summarized": int,
                "report_path": str,
                "status": str,
            },
            pk="id",
        )

    if "source_state" not in db.table_names():
        db["source_state"].create(
            {
                "source": str,
                "last_run_at": str,
                "last_seen_id": str,
            },
            pk="source",
        )

    if "analyst_reports" not in db.table_names():
        db["analyst_reports"].create(
            {
                "date": str,
                "themes_json": str,           # full Stage 1 output as JSON
                "model": str,
                "prompt_version": str,
                "created_at": str,
            },
            pk="date",
            not_null={"date", "themes_json"},
        )


# ----------------------------- helpers ------------------------------------ #

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _json_dumps(v: Any) -> str | None:
    return json.dumps(v, ensure_ascii=False) if v is not None else None


def _to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _from_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ----------------------------- items -------------------------------------- #

def upsert_items(db: Database, items: list[Item]) -> tuple[int, int]:
    """Insert items, ignoring duplicates by (source, source_id). Returns (inserted, updated)."""
    if not items:
        return (0, 0)
    inserted = 0
    updated = 0
    with db.conn:
        for it in items:
            if not it.content_hash:
                it.content_hash = content_hash(it.title, it.abstract or "", it.url)
            row = {
                "source": it.source,
                "source_id": it.source_id,
                "url": it.url,
                "title": it.title,
                "authors": _json_dumps(it.authors),
                "abstract": it.abstract,
                "published_at": _to_iso(it.published_at),
                "fetched_at": _now_iso(),
                "content_hash": it.content_hash,
                "score": it.score,
                "categories": _json_dumps(it.categories),
                "raw": _json_dumps(it.raw),
                "is_paper": int(it.is_paper),
                "status": "new",
            }
            cur = db.execute(
                "SELECT id, status FROM items WHERE source=? AND source_id=?",
                [it.source, it.source_id],
            ).fetchone()
            if cur is None:
                db["items"].insert(row)
                inserted += 1
            else:
                # Existing row: only refresh content fields. Never overwrite
                # categories/score/status — those are populated by classifier/ranker
                # AFTER collect, so the incoming Item from a collector always has them empty.
                db.execute(
                    """UPDATE items SET url=:url, title=:title, authors=:authors,
                       abstract=:abstract, published_at=:published_at, fetched_at=:fetched_at,
                       content_hash=:content_hash, raw=:raw, is_paper=:is_paper
                       WHERE id=:id""",
                    {
                        "url": row["url"],
                        "title": row["title"],
                        "authors": row["authors"],
                        "abstract": row["abstract"],
                        "published_at": row["published_at"],
                        "fetched_at": _now_iso(),
                        "content_hash": row["content_hash"],
                        "raw": row["raw"],
                        "is_paper": row["is_paper"],
                        "id": cur[0],
                    },
                )
                updated += 1
    return inserted, updated


def _rows_to_dicts(cur) -> list[dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_items_by_status(db: Database, status: str, limit: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM items WHERE status = ? ORDER BY COALESCE(score, 0) DESC, COALESCE(published_at, '') DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _rows_to_dicts(db.execute(sql, [status]))


def query_items(db: Database, where: str = "1=1", params: list[Any] | None = None) -> list[dict[str, Any]]:
    return _rows_to_dicts(db.execute(f"SELECT * FROM items WHERE {where}", params or []))


def set_item_status(db: Database, item_id: int, status: str) -> None:
    db.execute("UPDATE items SET status=? WHERE id=?", [status, item_id])
    db.conn.commit()


def update_item_categories_score(db: Database, item_id: int, categories: list[str], score: float) -> None:
    db.execute(
        "UPDATE items SET categories=?, score=? WHERE id=?",
        [json.dumps(categories, ensure_ascii=False), score, item_id],
    )
    db.conn.commit()


# ----------------------------- summaries --------------------------------- #

def upsert_summary(db: Database, item_id: int, summary: Summary) -> None:
    paper = summary.paper or PaperSummary(method="")
    row = {
        "item_id": item_id,
        "tldr": summary.tldr,
        "why_matters": summary.why_matters,
        "work_relevance": summary.work_relevance,
        "paper_method": paper.method or None,
        "is_open_source": _bool_to_int(paper.is_open_source),
        "has_benchmark_gain": _bool_to_int(paper.has_benchmark_gain),
        "worth_deep_read": _bool_to_int(paper.worth_deep_read),
        "model": summary.model,
        "prompt_version": summary.prompt_version,
        "created_at": _now_iso(),
    }
    db["summaries"].upsert(row, pk="item_id")
    db.execute("UPDATE items SET status='summarized' WHERE id=?", [item_id])
    db.conn.commit()


def get_summary(db: Database, item_id: int) -> dict[str, Any] | None:
    cur = db.execute("SELECT * FROM summaries WHERE item_id=?", [item_id])
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def find_cached_summary(db: Database, content_hash_value: str, model: str, prompt_version: str) -> dict[str, Any] | None:
    """Return existing summary for any item with matching content_hash+model+prompt_version."""
    cur = db.execute(
        """SELECT s.* FROM summaries s
           JOIN items i ON i.id = s.item_id
           WHERE i.content_hash=? AND s.model=? AND s.prompt_version=?
           LIMIT 1""",
        [content_hash_value, model, prompt_version],
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


# ----------------------------- runs --------------------------------------- #

@contextmanager
def record_run(db: Database) -> Iterator[dict[str, Any]]:
    info: dict[str, Any] = {"started_at": _now_iso(), "items_collected": 0, "items_summarized": 0,
                            "report_path": None, "status": "running"}
    rid = db["runs"].insert(info).last_pk
    try:
        yield info
        info["status"] = "ok"
    except Exception:
        info["status"] = "error"
        raise
    finally:
        info["finished_at"] = _now_iso()
        db.execute(
            """UPDATE runs SET finished_at=:finished_at, items_collected=:items_collected,
               items_summarized=:items_summarized, report_path=:report_path, status=:status
               WHERE id=:id""",
            {**info, "id": rid},
        )
        db.conn.commit()


def get_source_cursor(db: Database, source: str) -> dict[str, Any] | None:
    cur = db.execute("SELECT * FROM source_state WHERE source=?", [source])
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def set_source_cursor(db: Database, source: str, last_seen_id: str | None = None) -> None:
    db["source_state"].upsert(
        {"source": source, "last_run_at": _now_iso(), "last_seen_id": last_seen_id},
        pk="source",
    )


# ----------------------------- misc --------------------------------------- #

def _bool_to_int(v: bool | None) -> int | None:
    if v is None:
        return None
    return 1 if v else 0


def stats(db: Database) -> dict[str, Any]:
    def count_status(s: str) -> int:
        return db.execute("SELECT COUNT(*) FROM items WHERE status=?", [s]).fetchone()[0]

    return {
        "items_total": db["items"].count,
        "items_new": count_status("new"),
        "items_summarized": count_status("summarized"),
        "items_rendered": count_status("rendered"),
        "summaries_total": db["summaries"].count,
        "runs_total": db["runs"].count,
        "analyst_reports_total": db["analyst_reports"].count if "analyst_reports" in db.table_names() else 0,
    }


# ----------------------------- analyst reports --------------------------- #

def upsert_analyst_report(db: Database, date: str, themes_json: str, model: str, prompt_version: str) -> None:
    db["analyst_reports"].insert(
        {
            "date": date,
            "themes_json": themes_json,
            "model": model,
            "prompt_version": prompt_version,
            "created_at": _now_iso(),
        },
        pk="date",
        replace=True,
    )
    db.conn.commit()


def get_analyst_report(db: Database, date: str) -> dict[str, Any] | None:
    cur = db.execute("SELECT * FROM analyst_reports WHERE date=?", [date])
    row = cur.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def get_items_by_source_ids(db: Database, source_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map source_id -> item row. Used by analyst renderer to look up full item info."""
    if not source_ids:
        return {}
    placeholders = ",".join(["?"] * len(source_ids))
    cur = db.execute(f"SELECT * FROM items WHERE source_id IN ({placeholders})", source_ids)
    cols = [c[0] for c in cur.description]
    out: dict[str, dict[str, Any]] = {}
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        out[d["source_id"]] = d
    return out
