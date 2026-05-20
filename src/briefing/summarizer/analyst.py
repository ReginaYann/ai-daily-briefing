"""Two-stage research-analyst pipeline.

Stage 1 (single LLM call):
    Take top-N ranked items → return themes + key_paper_ids + mentions + noise.

Stage 2 (parallel LLM calls, only on key_paper_ids):
    Each picked paper gets a deep-read card.

Outputs:
    - One row in `analyst_reports` (full Stage 1 JSON, keyed by date)
    - One row in `summaries` per key paper (Stage 2 result, reuses paper_method/etc cols)
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from sqlite_utils import Database

from ..config import AppConfig, Secrets
from ..db import (
    find_cached_summary,
    get_items_by_status,
    upsert_analyst_report,
    upsert_summary,
)
from ..llm.base import LLMOutputError
from ..llm.factory import build_provider
from ..models import PaperSummary, Summary
from ..utils.logging import get_logger
from .prompts import (
    ANALYST_SYSTEM_PROMPT,
    PROMPT_VERSION,
    STAGE1_CLUSTER_TEMPLATE,
    STAGE2_DEEP_READ_TEMPLATE,
)

log = get_logger("analyst")


# --------------------------- helpers ---------------------------- #


def _truncate(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse_authors(s: str | None) -> list[str]:
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _parse_categories(s: str | None) -> list[str]:
    return _parse_authors(s)


def _format_items_block(items: list[dict[str, Any]]) -> str:
    """Compact representation fed to Stage 1 LLM. ~150-300 tokens per item."""
    lines: list[str] = []
    for it in items:
        sid = it["source_id"]
        title = (it.get("title") or "").strip()
        abstract = _truncate(it.get("abstract"), 600)
        authors = _parse_authors(it.get("authors"))
        author_str = ", ".join(authors[:3]) + (" 等" if len(authors) > 3 else "")
        cats = _parse_categories(it.get("categories"))
        cat_str = "/".join(cats) if cats else "-"
        score = it.get("score") or 0
        source = it.get("source") or "-"
        lines.append(
            f"<<ID={sid}>> (src={source}, score={score:.2f}, cats={cat_str})\n"
            f"  Title: {title}\n"
            f"  Authors: {author_str or '-'}\n"
            f"  Abstract: {abstract}\n"
        )
    return "\n".join(lines)


# --------------------------- Stage 1 ---------------------------- #


def _run_stage1(
    provider, items: list[dict[str, Any]], config: AppConfig, date_str: str
) -> dict[str, Any]:
    user_msg = STAGE1_CLUSTER_TEMPLATE.format(
        date=date_str,
        n_items=len(items),
        max_themes=config.output.max_themes,
        max_per_theme=config.output.max_key_papers_per_theme,
        max_total_key=config.output.max_total_key_papers,
        items_block=_format_items_block(items),
    )
    log.info("stage1_call", model=provider.model, items=len(items))
    data = provider.complete_json(ANALYST_SYSTEM_PROMPT, user_msg)
    return data


def _clean_sid(s: Any) -> str | None:
    if not isinstance(s, str):
        return None
    s = s.strip()
    # Tolerate hallucinated wrappers: "<<ID=xxx>>", "SID:xxx", "ID=xxx", "[xxx]"
    for prefix in ("<<ID=", "ID=", "SID:", "SID_", "[SID:", "["):
        if s.startswith(prefix):
            s = s[len(prefix):]
    for suffix in (">>", "]"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.strip() or None


def _normalize_stage1(raw: dict[str, Any], valid_sids: set[str]) -> dict[str, Any]:
    """Defensive normalization: clamp shape, drop unknown source_ids, dedup."""
    themes_in = raw.get("themes") or []
    seen: set[str] = set()
    unknown: list[str] = []

    def _take(s: Any) -> str | None:
        sid = _clean_sid(s)
        if not sid:
            return None
        if sid not in valid_sids:
            unknown.append(sid)
            return None
        if sid in seen:
            return None
        seen.add(sid)
        return sid

    themes_out: list[dict[str, Any]] = []
    for t in themes_in:
        if not isinstance(t, dict):
            continue
        kp = [s for s in (_take(x) for x in (t.get("key_paper_ids") or [])) if s]
        mentions = []
        for m in t.get("mentions") or []:
            if not isinstance(m, dict):
                continue
            sid = _take(m.get("source_id"))
            if not sid:
                continue
            mentions.append({"source_id": sid, "one_liner": (m.get("one_liner") or "").strip()})
        themes_out.append({
            "id": t.get("id") or "",
            "title_zh": t.get("title_zh") or "",
            "why_hot": t.get("why_hot") or "",
            "problem": t.get("problem") or "",
            "approach": t.get("approach") or "",
            "industry_impact": t.get("industry_impact") or "",
            "connections": t.get("connections") or "",
            "key_paper_ids": kp,
            "mentions": mentions,
        })
    noise = [s for s in (_take(x) for x in (raw.get("noise_dropped_ids") or [])) if s]
    if unknown:
        log.warning("stage1_unknown_sids", count=len(unknown), sample=unknown[:5])
    return {
        "executive_summary": (raw.get("executive_summary") or "").strip(),
        "themes": themes_out,
        "noise_dropped_ids": noise,
    }


# --------------------------- Stage 2 ---------------------------- #


def _run_stage2(
    provider,
    item: dict[str, Any],
    theme_title: str,
) -> Summary | None:
    authors = _parse_authors(item.get("authors"))
    user_msg = STAGE2_DEEP_READ_TEMPLATE.format(
        title=item.get("title") or "",
        source=item.get("source") or "",
        url=item.get("url") or "",
        authors=", ".join(authors[:8]),
        content=_truncate(item.get("abstract"), 1800) or "（无摘要）",
        theme_title=theme_title or "（未指定主题）",
    )
    try:
        data = provider.complete_json(ANALYST_SYSTEM_PROMPT, user_msg)
    except LLMOutputError as e:
        log.warning("stage2_parse_failed", source_id=item.get("source_id"), err=str(e))
        return None
    except Exception as e:
        log.warning("stage2_call_failed", source_id=item.get("source_id"), err=str(e))
        return None

    tldr = (data.get("tldr") or "").strip()
    method = (data.get("method") or "").strip()
    novelty = (data.get("novelty") or "").strip()
    if not tldr or not method:
        log.warning("stage2_empty", source_id=item.get("source_id"))
        return None
    return Summary(
        tldr=tldr,
        why_matters=novelty or "（未给出 novelty）",
        work_relevance=None,
        paper=PaperSummary(
            method=method,
            is_open_source=_to_bool(data.get("is_open_source")),
            has_benchmark_gain=_to_bool(data.get("has_benchmark_gain")),
            worth_deep_read=(data.get("read_priority") == "high"),
        ),
        model=provider.model,
        prompt_version=PROMPT_VERSION,
    )


def _to_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1", "yes"}
    return bool(v)


# --------------------------- entry ------------------------------ #


def run_analyst(db: Database, config: AppConfig, secrets: Secrets, date_str: str | None = None) -> dict[str, Any]:
    """Full two-stage analyst run. Returns {themes, key_paper_count}."""
    top_n = config.output.top_n_for_clustering
    candidates = get_items_by_status(db, "new", limit=top_n * 2)
    candidates = [r for r in candidates if (r.get("score") or 0) >= config.ranker.min_score][:top_n]
    if not candidates:
        log.warning("analyst_no_candidates")
        return {"themes": 0, "key_papers": 0}

    sid_to_item = {it["source_id"]: it for it in candidates}
    valid_sids = set(sid_to_item.keys())
    date_label = date_str or datetime.now().strftime(config.output.date_format)

    # Build separate providers for each stage (may be same model or different).
    stage1_model = config.llm.stage1_model or config.llm.model
    stage2_model = config.llm.stage2_model or config.llm.model
    stage1_max_tokens = config.llm.stage1_max_tokens or 8192
    stage2_max_tokens = config.llm.stage2_max_tokens or config.llm.max_tokens_per_summary

    provider_s1 = build_provider(config, secrets, model_override=stage1_model, max_tokens_override=stage1_max_tokens)
    provider_s2 = build_provider(config, secrets, model_override=stage2_model, max_tokens_override=stage2_max_tokens)

    log.info("analyst_start", date=date_label, candidates=len(candidates),
             stage1_model=provider_s1.model, stage2_model=provider_s2.model)

    # ---- Stage 1
    try:
        raw = _run_stage1(provider_s1, candidates, config, date_label)
    except Exception as e:
        log.error("stage1_failed", err=str(e))
        return {"themes": 0, "key_papers": 0, "error": str(e)}
    report = _normalize_stage1(raw, valid_sids)

    upsert_analyst_report(
        db, date=date_label,
        themes_json=json.dumps(report, ensure_ascii=False),
        model=provider_s1.model,
        prompt_version=PROMPT_VERSION,
    )
    log.info("stage1_done", themes=len(report["themes"]),
             noise=len(report["noise_dropped_ids"]))

    # ---- Stage 2: deep-read on key_paper_ids only
    key_papers: list[tuple[str, str]] = []  # (source_id, theme_title)
    for t in report["themes"]:
        for sid in t["key_paper_ids"]:
            key_papers.append((sid, t["title_zh"]))
    log.info("stage2_picks", count=len(key_papers))

    # Resolve cache hits on the main thread (SQLite is not thread-safe).
    main_thread_writes: list[tuple[int, Summary]] = []
    to_call: list[tuple[dict[str, Any], str]] = []
    for sid, theme_title in key_papers:
        item = sid_to_item.get(sid)
        if not item:
            continue
        ch = item.get("content_hash") or ""
        cached = None
        if config.cache.llm_cache and ch:
            cached = find_cached_summary(db, ch, provider_s2.model, PROMPT_VERSION)
        if cached:
            summ = Summary(
                tldr=cached["tldr"],
                why_matters=cached["why_matters"],
                work_relevance=cached.get("work_relevance"),
                paper=PaperSummary(
                    method=cached.get("paper_method") or "",
                    is_open_source=bool(cached["is_open_source"]) if cached.get("is_open_source") is not None else None,
                    has_benchmark_gain=bool(cached["has_benchmark_gain"]) if cached.get("has_benchmark_gain") is not None else None,
                    worth_deep_read=bool(cached["worth_deep_read"]) if cached.get("worth_deep_read") is not None else None,
                ) if cached.get("paper_method") else None,
                model=cached.get("model") or provider_s2.model,
                prompt_version=cached.get("prompt_version") or PROMPT_VERSION,
            )
            main_thread_writes.append((item["id"], summ))
        else:
            to_call.append((item, theme_title))

    # Parallel LLM calls (no DB inside).
    llm_results: list[tuple[int, Summary | None]] = []
    if to_call:
        with ThreadPoolExecutor(max_workers=max(1, config.llm.concurrency)) as ex:
            futures = {ex.submit(_run_stage2, provider_s2, item, theme_title): item
                       for item, theme_title in to_call}
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    summary = fut.result()
                except Exception as e:
                    log.error("stage2_unexpected", source_id=item.get("source_id"), err=str(e))
                    summary = None
                llm_results.append((item["id"], summary))

    written = 0
    for item_id, summary in main_thread_writes:
        upsert_summary(db, item_id, summary)
        written += 1
    for item_id, summary in llm_results:
        if summary is None:
            continue
        upsert_summary(db, item_id, summary)
        written += 1

    log.info("analyst_done", themes=len(report["themes"]),
             key_papers=len(key_papers), deep_reads_written=written,
             cache_hits=len(main_thread_writes), llm_calls=len(to_call))

    return {
        "themes": len(report["themes"]),
        "key_papers": len(key_papers),
        "deep_reads_written": written,
    }
