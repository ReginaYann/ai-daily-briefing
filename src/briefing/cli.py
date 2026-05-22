"""Typer-based CLI: `briefing init | collect | summarize | render | run | db ...`."""
from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

# Force UTF-8 on Windows consoles (default is GBK on zh-CN, which breaks bullets / CJK).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config, load_secrets
from .db import open_db, stats as db_stats
from .utils.logging import setup_logging

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="AI Daily Briefing — collect, filter, summarize, render.",
)
db_app = typer.Typer(no_args_is_help=True, help="Database utilities.")
app.add_typer(db_app, name="db")
console = Console()

ROOT = Path.cwd()


def _setup(config_path: str = "config.yaml"):
    cfg = load_config(config_path)
    setup_logging(cfg.logging.level)
    return cfg


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
):
    """Create config.yaml, .env, data/, reports/."""
    pkg_dir = Path(__file__).parent
    project_root = ROOT

    examples = {
        project_root / "config.yaml": project_root / "config.example.yaml",
        project_root / ".env": project_root / ".env.example",
    }
    for dest, src in examples.items():
        if not src.exists():
            console.print(f"[yellow]missing template: {src}[/yellow]")
            continue
        if dest.exists() and not force:
            console.print(f"[dim]skip {dest.name} (exists)[/dim]")
            continue
        shutil.copy(src, dest)
        console.print(f"[green]created[/green] {dest}")

    for d in [project_root / "data", project_root / "reports"]:
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]ensured[/green] {d}/")

    open_db()  # creates SQLite + schema
    console.print("[green]db ready at[/green] data/briefing.db")
    console.print("\nNext: edit [bold]config.yaml[/bold] and [bold].env[/bold], then run "
                  "[bold]briefing run[/bold].")


@app.command()
def run(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    skip_summarize: bool = typer.Option(False, "--no-summarize"),
    skip_render: bool = typer.Option(False, "--no-render"),
    lookback_hours: int = typer.Option(
        None,
        "--lookback-hours",
        "-L",
        help="Override collector lookback window in hours (e.g. 84 for Monday catch-up after a 2-day skip). Defaults to per-collector config.",
    ),
):
    """End-to-end: collect → classify+rank → summarize → render."""
    _setup(config)
    from .pipeline import run as pipeline_run

    result = pipeline_run(
        config,
        skip_summarize=skip_summarize,
        skip_render=skip_render,
        lookback_hours=lookback_hours,
    )
    console.print(result)


@app.command()
def collect(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    lookback_hours: int = typer.Option(
        None,
        "--lookback-hours",
        "-L",
        help="Override collector lookback window in hours.",
    ),
):
    """Run collectors only."""
    cfg = _setup(config)
    if lookback_hours is not None:
        if lookback_hours <= 0:
            raise typer.BadParameter("--lookback-hours must be positive")
        cfg.collectors.arxiv.lookback_hours = lookback_hours
        cfg.collectors.reddit.lookback_hours = lookback_hours
    secrets = load_secrets()
    db = open_db()
    from .pipeline import collect_all

    inserted = asyncio.run(collect_all(cfg, secrets, db))
    console.print(f"[green]inserted {inserted} new items[/green]")


@app.command()
def summarize(config: str = typer.Option("config.yaml", "--config", "-c")):
    """Run LLM summaries on top-N ranked items (or run analyst mode)."""
    cfg = _setup(config)
    secrets = load_secrets()
    db = open_db()
    mode = (cfg.output.mode or "analyst").lower()
    if mode == "analyst":
        from .summarizer import analyst as analyst_mod

        result = analyst_mod.run_analyst(db, cfg, secrets)
        console.print(f"[green]analyst: {result}[/green]")
    else:
        from .summarizer import service as summarizer_mod

        n = summarizer_mod.summarize_top(db, cfg, secrets)
        console.print(f"[green]summarized {n} items[/green]")


@app.command()
def render(
    config: str = typer.Option("config.yaml", "--config", "-c"),
    date: str = typer.Option(None, "--date", help="YYYY-MM-DD; default = today"),
):
    """Render a Markdown report from already-summarized data."""
    cfg = _setup(config)
    db = open_db()
    from .renderer import markdown as renderer_mod

    mode = (cfg.output.mode or "analyst").lower()
    if mode == "analyst":
        path = renderer_mod.render_analyst_report(db, cfg, date_str=date)
    else:
        path = renderer_mod.render_today(db, cfg, date_str=date)
    if path:
        console.print(f"[green]wrote[/green] {path}")
    else:
        console.print("[yellow]nothing to render[/yellow]")


@app.command("list-sources")
def list_sources():
    """List registered collectors."""
    from .pipeline import _load_all_collector_modules
    from .collectors.registry import get_registry

    _load_all_collector_modules()
    table = Table("name", "class", "module")
    for name, cls in sorted(get_registry().items()):
        table.add_row(name, cls.__name__, cls.__module__)
    console.print(table)


@app.command("test-source")
def test_source(
    name: str = typer.Argument(..., help="Collector name, e.g. 'arxiv'."),
    config: str = typer.Option("config.yaml", "--config", "-c"),
    limit: int = typer.Option(5, "--limit"),
):
    """Run one collector and print the first N items, without writing to DB."""
    cfg = _setup(config)
    secrets = load_secrets()
    from .pipeline import _load_all_collector_modules
    from .collectors.registry import get_registry

    _load_all_collector_modules()
    cls = get_registry().get(name)
    if not cls:
        raise typer.BadParameter(f"unknown collector '{name}'. try `briefing list-sources`.")

    inst = cls(cfg, secrets)
    items = asyncio.run(inst.collect())
    console.print(f"[green]{name}: {len(items)} items[/green]")
    for it in items[:limit]:
        console.print(f"  - [{it.source_id}] {it.title}")
        console.print(f"    {it.url}")


@db_app.command("stats")
def db_stats_cmd():
    db = open_db()
    s = db_stats(db)
    table = Table("metric", "value")
    for k, v in s.items():
        table.add_row(k, str(v))
    console.print(table)


@db_app.command("migrate")
def db_migrate():
    """Re-create / reconcile schema (idempotent)."""
    open_db()
    console.print("[green]schema ok[/green]")


@db_app.command("reclassify")
def db_reclassify(config: str = typer.Option("config.yaml", "--config", "-c")):
    """Re-run the keyword classifier across ALL items (not just status='new')."""
    cfg = _setup(config)
    db = open_db()
    from .filters import classifier as classifier_mod

    n = classifier_mod.classify_new_items(db, cfg, all_items=True)
    console.print(f"[green]reclassified {n} items[/green]")


@db_app.command("drop-summaries")
def db_drop_summaries(
    where: str = typer.Option(..., "--where", help="SQL WHERE on summaries table, e.g. \"model='dummy'\""),
    yes: bool = typer.Option(False, "--yes"),
):
    """Delete summaries matching --where, and reset their items back to status='new'.

    Example: briefing db drop-summaries --where "model='dummy'" --yes
    """
    db = open_db()
    rows = list(db.execute(f"SELECT item_id FROM summaries WHERE {where}").fetchall())
    ids = [r[0] for r in rows]
    console.print(f"[yellow]matched {len(ids)} summaries[/yellow]")
    if not ids:
        return
    if not yes:
        console.print("[red]pass --yes to actually delete[/red]")
        return
    placeholders = ",".join(["?"] * len(ids))
    db.execute(f"DELETE FROM summaries WHERE item_id IN ({placeholders})", ids)
    db.execute(f"UPDATE items SET status='new' WHERE id IN ({placeholders})", ids)
    db.conn.commit()
    console.print(f"[green]deleted {len(ids)} summaries; items reset to status='new'[/green]")


if __name__ == "__main__":
    app()
