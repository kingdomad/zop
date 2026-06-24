"""Note CLI subcommands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from zop.adapters.zotero_api import ApiCreds
from zop.core.config import load_config
from zop.core.envelope import emit, emit_error
from zop.core.errors import ZopError
from zop.services.notes import NotesService


def _service() -> NotesService:
    cfg = load_config()
    creds = (
        ApiCreds(library_id=cfg.library_id, api_key=cfg.api_key)
        if cfg.has_write_credentials
        else None
    )
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return NotesService(db_path=Path(cfg.data_dir) / "zotero.sqlite", creds=creds)


def _human() -> bool:
    return sys.stdout.isatty()


@click.group(name="note")
def note() -> None:
    """Manage notes."""


@note.command("list")
@click.argument("item_key")
def list_cmd(item_key: str) -> None:
    """List notes attached to an item (by KEY)."""
    try:
        svc = _service()
        data = svc.list_for_item(item_key)
        emit(data, human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@note.command("add")
@click.argument("item_key")
@click.option("--text", "-t", required=True, help="Note text (Markdown/HTML allowed).")
@click.option("--file", "file", type=click.Path(exists=True), help="Read note text from file.")
def add_cmd(item_key: str, text: str | None, file: str | None) -> None:
    """Add a note to an item (parent KEY)."""
    if file:
        text = Path(file).read_text(encoding="utf-8")
    if not text:
        raise click.UsageError("Provide --text or --file")
    try:
        svc = _service()
        new_key = asyncio.run(svc.add(item_key, text))
        emit({"created": new_key}, human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)
