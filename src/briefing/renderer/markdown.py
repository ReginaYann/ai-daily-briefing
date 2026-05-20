"""Render the daily Markdown report from items + summaries in SQLite."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlite_utils import Database

from ..config import AppConfig
from ..db import get_analyst_report, get_items_by_source_ids, get_summary
from ..utils.logging import get_logger

log = get_logger("renderer")

TOPIC_LABELS = {
    "embodied_ai": "具身智能",
    "multimodal": "多模态",
    "rag": "RAG / 检索",
    "agent": "Agent",
    "memory": "Memory",
    "grounding": "Grounding",
    "vlm": "VLM",
    "reasoning": "推理模型",
    "rl_for_llm": "RL for LLM",
    "long_context": "长上下文",
    "open_source": "开源模型/框架",
}


def _label(topic: str) -> str:
    return TOPIC_LABELS.get(topic, topic)


def _env() -> Environment:
    tpl_dir = Path(__file__).parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(disabled_extensions=("md", "j2", "txt"), default=False),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def _fetch_for_report(db: Database) -> list[dict[str, Any]]:
    """Items that have a summary and are not yet rendered."""
    cur = db.execute(
        """SELECT i.*, s.tldr, s.why_matters, s.work_relevance,
                  s.paper_method, s.is_open_source, s.has_benchmark_gain, s.worth_deep_read,
                  s.model AS summary_model
           FROM items i
           JOIN summaries s ON s.item_id = i.id
           WHERE i.status IN ('summarized', 'rendered')
           ORDER BY COALESCE(i.score, 0) DESC"""
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _group(rows: list[dict[str, Any]], by: str) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if by == "source":
        for r in rows:
            groups[r["source"]].append(r)
    else:                                           # category
        for r in rows:
            try:
                cats = json.loads(r.get("categories") or "[]")
            except Exception:
                cats = []
            if not cats:
                groups["其它"].append(r)
            else:
                # primary category = first hit; also list others
                groups[_label(cats[0])].append(r)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _decorate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        try:
            authors = json.loads(r.get("authors") or "[]")
        except Exception:
            authors = []
        try:
            cats = json.loads(r.get("categories") or "[]")
        except Exception:
            cats = []
        out.append({
            **r,
            "authors_list": authors,
            "categories_list": [_label(c) for c in cats],
        })
    return out


def render_today(db: Database, config: AppConfig, date_str: str | None = None) -> Path | None:
    rows = _fetch_for_report(db)
    if not rows:
        log.warning("nothing_to_render")
        return None

    rows = _decorate(rows)
    groups = _group(rows, by=config.output.group_by)

    dt = datetime.now()
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            log.warning("bad_date_format", date=date_str)
    date_label = dt.strftime(config.output.date_format)

    env = _env()
    tpl = env.get_template("daily.md.j2")
    md = tpl.render(
        date=date_label,
        groups=groups,
        total=len(rows),
        group_by=config.output.group_by,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    out_dir = Path(config.output.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_label}.md"
    out_path.write_text(md, encoding="utf-8")

    # mark rendered
    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ",".join(["?"] * len(ids))
        db.execute(f"UPDATE items SET status='rendered' WHERE id IN ({placeholders})", ids)
        db.conn.commit()

    log.info("rendered", path=str(out_path), items=len(rows))
    return out_path


# ============================================================================
# Analyst-mode rendering
# ============================================================================

def _resolve_authors_str(item: dict[str, Any]) -> str:
    try:
        authors = json.loads(item.get("authors") or "[]")
    except Exception:
        authors = []
    if not authors:
        return ""
    return ", ".join(authors[:5]) + (" 等" if len(authors) > 5 else "")


def render_analyst_report(db: Database, config: AppConfig, date_str: str | None = None) -> Path | None:
    """Render the analyst-mode Markdown from analyst_reports + summaries tables."""
    dt = datetime.now()
    if date_str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            log.warning("bad_date_format", date=date_str)
    date_label = dt.strftime(config.output.date_format)

    report_row = get_analyst_report(db, date_label)
    if not report_row:
        log.warning("analyst_report_missing", date=date_label)
        return None

    try:
        report = json.loads(report_row["themes_json"])
    except Exception as e:
        log.error("analyst_report_parse_failed", err=str(e))
        return None

    # Collect every source_id referenced anywhere → batch lookup
    all_sids: list[str] = []
    for t in report.get("themes", []):
        all_sids.extend(t.get("key_paper_ids", []))
        for m in t.get("mentions", []):
            all_sids.append(m["source_id"])
    all_sids.extend(report.get("noise_dropped_ids", []))
    items_by_sid = get_items_by_source_ids(db, all_sids)

    # Decorate themes with full paper data + Stage 2 summaries
    themes_decorated = []
    key_paper_count = 0
    for t in report.get("themes", []):
        kps = []
        for sid in t.get("key_paper_ids", []):
            it = items_by_sid.get(sid)
            if not it:
                continue
            summ = get_summary(db, it["id"])
            kps.append({
                "title": it["title"],
                "url": it["url"],
                "authors_str": _resolve_authors_str(it),
                "tldr": (summ or {}).get("tldr"),
                "method": (summ or {}).get("paper_method"),
                "novelty": (summ or {}).get("why_matters"),
                "is_open_source": (summ or {}).get("is_open_source"),
                "has_benchmark_gain": (summ or {}).get("has_benchmark_gain"),
                "read_priority_high": bool((summ or {}).get("worth_deep_read")),
            })
            key_paper_count += 1

        mentions = []
        for m in t.get("mentions", []):
            it = items_by_sid.get(m["source_id"])
            if not it:
                continue
            mentions.append({
                "title": it["title"],
                "url": it["url"],
                "one_liner": m.get("one_liner") or "",
            })

        themes_decorated.append({
            "title_zh": t.get("title_zh") or "",
            "why_hot": t.get("why_hot") or "",
            "problem": t.get("problem") or "",
            "approach": t.get("approach") or "",
            "industry_impact": t.get("industry_impact") or "",
            "connections": t.get("connections") or "",
            "key_papers": kps,
            "mentions": mentions,
        })

    noise = []
    for sid in report.get("noise_dropped_ids", []):
        it = items_by_sid.get(sid)
        if not it:
            continue
        noise.append({"title": it["title"], "url": it["url"], "source": it["source"]})

    candidate_count = (
        sum(len(t.get("key_paper_ids", [])) for t in report.get("themes", []))
        + sum(len(t.get("mentions", [])) for t in report.get("themes", []))
        + len(report.get("noise_dropped_ids", []))
    )

    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(disabled_extensions=("md", "j2", "txt"), default=False),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    tpl = env.get_template("analyst.md.j2")
    md = tpl.render(
        date=date_label,
        executive_summary=report.get("executive_summary") or "",
        themes=themes_decorated,
        noise=noise,
        key_paper_count=key_paper_count,
        candidate_count=candidate_count,
        model=report_row.get("model") or "",
        prompt_version=report_row.get("prompt_version") or "",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    out_dir = Path(config.output.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_label}.md"
    out_path.write_text(md, encoding="utf-8")

    # Mark every referenced item as 'rendered' so it doesn't keep coming up.
    referenced_ids = [items_by_sid[sid]["id"] for sid in all_sids if sid in items_by_sid]
    if referenced_ids:
        placeholders = ",".join(["?"] * len(referenced_ids))
        db.execute(f"UPDATE items SET status='rendered' WHERE id IN ({placeholders})", referenced_ids)
        db.conn.commit()

    log.info("analyst_rendered", path=str(out_path),
             themes=len(themes_decorated), key_papers=key_paper_count,
             noise=len(noise))
    return out_path
