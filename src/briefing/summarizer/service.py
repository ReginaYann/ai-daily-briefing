"""Summarization service: pick top-N items, call LLM, persist."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlite_utils import Database

from ..config import AppConfig, Secrets
from ..db import find_cached_summary, get_items_by_status, upsert_summary
from ..llm.base import LLMOutputError
from ..llm.factory import build_provider
from ..models import PaperSummary, Summary
from ..utils.logging import get_logger
from .prompts import (
    GENERIC_USER_TEMPLATE,
    PAPER_USER_TEMPLATE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
)

log = get_logger("summarizer")


def _truncate(text: str | None, n: int = 1800) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _build_prompt(item_row: dict[str, Any]) -> tuple[str, bool]:
    is_paper = bool(item_row.get("is_paper")) or item_row.get("source") in {"arxiv", "huggingface"}
    authors_json = item_row.get("authors") or "[]"
    try:
        authors = json.loads(authors_json) if authors_json else []
    except Exception:
        authors = []
    cats_json = item_row.get("categories") or "[]"
    try:
        cats = json.loads(cats_json) if cats_json else []
    except Exception:
        cats = []

    fmt_args = dict(
        title=item_row.get("title", ""),
        source=item_row.get("source", ""),
        url=item_row.get("url", ""),
        authors=", ".join(authors[:8]),
        categories=", ".join(cats) or "（未分类）",
        content=_truncate(item_row.get("abstract") or "（无摘要）"),
    )
    tpl = PAPER_USER_TEMPLATE if is_paper else GENERIC_USER_TEMPLATE
    return tpl.format(**fmt_args), is_paper


def _parse_summary(data: dict[str, Any], is_paper: bool, model: str) -> Summary:
    tldr = (data.get("tldr") or "").strip()
    why = (data.get("why_matters") or "").strip()
    rel = (data.get("work_relevance") or "").strip() or None
    paper = None
    if is_paper and isinstance(data.get("paper"), dict):
        p = data["paper"]
        paper = PaperSummary(
            method=(p.get("method") or "").strip(),
            is_open_source=_to_bool(p.get("is_open_source")),
            has_benchmark_gain=_to_bool(p.get("has_benchmark_gain")),
            worth_deep_read=_to_bool(p.get("worth_deep_read")),
        )
    if not tldr or not why:
        raise LLMOutputError("missing tldr/why_matters")
    return Summary(
        tldr=tldr,
        why_matters=why,
        work_relevance=rel,
        paper=paper,
        model=model,
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


def summarize_top(db: Database, config: AppConfig, secrets: Secrets) -> int:
    top_n = config.ranker.top_n_to_summarize
    min_score = config.ranker.min_score

    candidates = get_items_by_status(db, "new", limit=top_n * 3)
    candidates = [r for r in candidates if (r.get("score") or 0) >= min_score][:top_n]
    if not candidates:
        log.info("nothing_to_summarize")
        return 0

    provider = build_provider(config, secrets)
    log.info("summarize_start", count=len(candidates), provider=provider.name, model=provider.model)

    # --- Pass 1: resolve cache hits on the main thread (SQLite isn't thread-safe). ---
    cache_hits: list[tuple[int, Summary]] = []
    to_call: list[dict[str, Any]] = []
    for row in candidates:
        ch = row.get("content_hash") or ""
        cached = None
        if config.cache.llm_cache and ch:
            cached = find_cached_summary(db, ch, provider.model, PROMPT_VERSION)
        if cached:
            cache_hits.append((row["id"], _cached_to_summary(cached, provider.model)))
        else:
            to_call.append(row)

    # --- Pass 2: parallelize LLM calls only. Workers touch zero SQLite state. ---
    def _call_llm(row: dict[str, Any]) -> tuple[int, Summary | None, str]:
        item_id = row["id"]
        user_msg, is_paper = _build_prompt(row)
        try:
            data = provider.complete_json(SYSTEM_PROMPT, user_msg)
            summary = _parse_summary(data, is_paper, provider.model)
            return item_id, summary, "ok"
        except LLMOutputError as e:
            return item_id, None, f"parse:{e}"
        except Exception as e:  # network / quota / etc.
            return item_id, None, f"err:{e}"

    llm_results: list[tuple[int, Summary | None, str, dict[str, Any]]] = []
    if to_call:
        with ThreadPoolExecutor(max_workers=max(1, config.llm.concurrency)) as ex:
            futures = {ex.submit(_call_llm, row): row for row in to_call}
            for fut in as_completed(futures):
                row = futures[fut]
                try:
                    item_id, summary, status = fut.result()
                except Exception as e:
                    log.error("summary_unexpected", item_id=row["id"], error=str(e))
                    continue
                llm_results.append((item_id, summary, status, row))

    # --- Pass 3: write everything from the main thread. ---
    written = 0
    for item_id, summary in cache_hits:
        upsert_summary(db, item_id, summary)
        written += 1
    for item_id, summary, status, row in llm_results:
        if summary is None:
            log.warning("summary_failed", item_id=item_id, status=status, title=row.get("title"))
            continue
        upsert_summary(db, item_id, summary)
        log.info("summary_ok", item_id=item_id, status=status, title=(row.get("title") or "")[:60])
        written += 1

    log.info(
        "summarize_done",
        written=written,
        attempted=len(candidates),
        cache_hits=len(cache_hits),
        llm_calls=len(to_call),
    )
    return written


def _cached_to_summary(cached: dict[str, Any], fallback_model: str) -> Summary:
    return Summary(
        tldr=cached["tldr"],
        why_matters=cached["why_matters"],
        work_relevance=cached.get("work_relevance"),
        paper=(
            PaperSummary(
                method=cached.get("paper_method") or "",
                is_open_source=_int_to_bool(cached.get("is_open_source")),
                has_benchmark_gain=_int_to_bool(cached.get("has_benchmark_gain")),
                worth_deep_read=_int_to_bool(cached.get("worth_deep_read")),
            )
            if cached.get("paper_method")
            else None
        ),
        model=cached.get("model") or fallback_model,
        prompt_version=cached.get("prompt_version") or PROMPT_VERSION,
    )


def _int_to_bool(v: Any) -> bool | None:
    if v is None:
        return None
    return bool(v)
