"""Tag CLI subcommands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from zop.adapters.zotero_api import ApiCreds
from zop.core.config import load_config
from zop.core.envelope import emit, emit_batch, emit_error
from zop.core.errors import ZopError
from zop.services.tags import TagsService


def _service() -> TagsService:
    cfg = load_config()
    creds = (
        ApiCreds(library_id=cfg.library_id, api_key=cfg.api_key)
        if cfg.has_write_credentials
        else None
    )
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return TagsService(db_path=Path(cfg.data_dir) / "zotero.sqlite", creds=creds)


def _human() -> bool:
    return sys.stdout.isatty()


@click.group(name="tag")
def tag() -> None:
    """Manage tags."""


@tag.command("list")
def list_cmd() -> None:
    """List all tags with usage counts."""
    try:
        svc = _service()
        data = svc.list_all()
        emit(data, human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@tag.command("add")
@click.argument("item_keys", nargs=-1, required=True)
@click.option("--tags", "tags", required=True, help="Comma-separated tags to add.")
def add_cmd(item_keys: tuple[str, ...], tags: str) -> None:
    """Add tags to items (preserves existing)."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        svc = _service()
        ok, fail = asyncio.run(svc.add(list(item_keys), tag_list))
        emit_batch(
            [{"key": k} for k in ok],
            [(k, _wrap(e)) for k, e in fail],
            human=_human(),
        )
        if fail:
            sys.exit(2)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@tag.command("remove")
@click.argument("item_keys", nargs=-1, required=True)
@click.option("--tags", "tags", required=True, help="Comma-separated tags to remove.")
def remove_cmd(item_keys: tuple[str, ...], tags: str) -> None:
    """Remove tags from items."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        svc = _service()
        ok, fail = asyncio.run(svc.remove(list(item_keys), tag_list))
        emit_batch(
            [{"key": k} for k in ok],
            [(k, _wrap(e)) for k, e in fail],
            human=_human(),
        )
        if fail:
            sys.exit(2)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


def _wrap(e: BaseException) -> ZopError:
    return e if isinstance(e, ZopError) else ZopError(str(e))
