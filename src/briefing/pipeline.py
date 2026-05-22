"""Pipeline orchestrator.

Wires Collectors → DB → (Filter) → (Summarizer) → Renderer. Each phase is
exposed as a public function so the CLI can run them independently.
"""
from __future__ import annotations

import asyncio
import importlib
import pkgutil
from datetime import datetime
from pathlib import Path

from .config import AppConfig, Secrets, load_config, load_secrets
from .db import (
    open_db,
    record_run,
    upsert_items,
)
from .models import Item
from .utils.logging import get_logger

log = get_logger("pipeline")


def _load_all_collector_modules() -> None:
    """Import every module under briefing.collectors so @register_collector runs."""
    from . import collectors as pkg

    for mod in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        if mod.name.endswith((".base", ".registry")):
            continue
        try:
            importlib.import_module(mod.name)
        except Exception as e:
            log.warning("collector_import_failed", module=mod.name, error=str(e))


def _instantiate_enabled(config: AppConfig, secrets: Secrets):
    from .collectors.registry import get_registry

    _load_all_collector_modules()
    instances = []
    for name, cls in get_registry().items():
        try:
            inst = cls(config, secrets)
        except Exception as e:
            log.warning("collector_init_failed", name=name, error=str(e))
            continue
        if inst.is_enabled():
            instances.append(inst)
    return instances


async def _run_collector(collector) -> list[Item]:
    try:
        items = await collector.collect()
        log.info("collector_done", source=collector.name, count=len(items))
        return items
    except Exception as e:
        log.error("collector_failed", source=collector.name, error=str(e))
        return []


async def collect_all(config: AppConfig, secrets: Secrets, db) -> int:
    collectors = _instantiate_enabled(config, secrets)
    if not collectors:
        log.warning("no_enabled_collectors")
        return 0
    results = await asyncio.gather(*[_run_collector(c) for c in collectors])
    items = [it for batch in results for it in batch]
    inserted, updated = upsert_items(db, items)
    log.info("collect_done", total=len(items), inserted=inserted, updated=updated)
    return inserted


def run(
    config_path: str | Path = "config.yaml",
    skip_summarize: bool = False,
    skip_render: bool = False,
    lookback_hours: int | None = None,
) -> dict:
    """End-to-end run. Returns a small summary dict.

    `lookback_hours`, if given, overrides the per-collector `lookback_hours`
    setting at runtime (e.g. for Monday catch-up after a weekend skip).
    """
    config = load_config(config_path)
    secrets = load_secrets()
    if lookback_hours is not None:
        if lookback_hours <= 0:
            raise ValueError("lookback_hours must be positive")
        config.collectors.arxiv.lookback_hours = lookback_hours
        config.collectors.reddit.lookback_hours = lookback_hours
        log.info("lookback_override", hours=lookback_hours)
    db = open_db()

    # Lazy imports so Step 1 boots even before later modules exist
    from .filters import classifier as classifier_mod
    from .filters import ranker as ranker_mod

    with record_run(db) as run_info:
        # 1. Collect
        inserted = asyncio.run(collect_all(config, secrets, db))
        run_info["items_collected"] = inserted

        # 2. Classify + rank (cheap, deterministic)
        classifier_mod.classify_new_items(db, config)
        ranker_mod.rank_new_items(db, config)

        report_path: Path | None = None
        mode = (config.output.mode or "analyst").lower()

        if mode == "analyst":
            if not skip_summarize:
                from .summarizer import analyst as analyst_mod

                result = analyst_mod.run_analyst(db, config, secrets)
                run_info["items_summarized"] = result.get("deep_reads_written", 0)

            if not skip_render:
                from .renderer import markdown as renderer_mod

                report_path = renderer_mod.render_analyst_report(db, config)
                run_info["report_path"] = str(report_path) if report_path else None
        else:
            # legacy per-item mode
            if not skip_summarize:
                from .summarizer import service as summarizer_mod

                n = summarizer_mod.summarize_top(db, config, secrets)
                run_info["items_summarized"] = n

            if not skip_render:
                from .renderer import markdown as renderer_mod

                report_path = renderer_mod.render_today(db, config)
                run_info["report_path"] = str(report_path) if report_path else None

    return {
        "items_collected": run_info["items_collected"],
        "items_summarized": run_info.get("items_summarized", 0),
        "report_path": run_info.get("report_path"),
    }
