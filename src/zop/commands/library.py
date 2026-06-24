"""Top-level library commands: stats, recent, duplicates."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from zop.core.config import load_config
from zop.core.envelope import emit, emit_error
from zop.core.errors import ZopError
from zop.services.library import LibraryService


def _service() -> LibraryService:
    cfg = load_config()
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return LibraryService(db_path=Path(cfg.data_dir) / "zotero.sqlite")


def _human() -> bool:
    return sys.stdout.isatty()


@click.command(name="stats")
def stats_cmd() -> None:
    """Show library statistics (items, types, top tags, collections)."""
    try:
        svc = _service()
        data = svc.stats()
        emit(data, human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@click.command(name="recent")
@click.option("--days", default=7, type=int, help="Look back N days (default 7).")
@click.option("--limit", default=50, type=int)
def recent_cmd(days: int, limit: int) -> None:
    """List recently added items."""
    try:
        svc = _service()
        data = svc.recent(days=days, limit=limit)
        emit([it.model_dump() for it in data], human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@click.command(name="duplicates")
@click.option("--by", type=click.Choice(["doi", "title"]), default="doi")
def duplicates_cmd(by: str) -> None:
    """Find potential duplicate items grouped by DOI (or title)."""
    try:
        svc = _service()
        data = svc.duplicates(by=by)
        emit(data, human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)
