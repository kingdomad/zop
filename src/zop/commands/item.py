"""Item CLI subcommands."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from zop.adapters.zotero_api import ApiCreds
from zop.core.config import load_config
from zop.core.envelope import emit, emit_batch, emit_error
from zop.core.errors import ZopError
from zop.services.items import ItemsService


def _service() -> ItemsService:
    cfg = load_config()
    creds = (
        ApiCreds(library_id=cfg.library_id, api_key=cfg.api_key)
        if cfg.has_write_credentials
        else None
    )
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return ItemsService(db_path=Path(cfg.data_dir) / "zotero.sqlite", creds=creds)


def _human() -> bool:
    return sys.stdout.isatty()


@click.group(name="item")
def item() -> None:
    """Manage Zotero items."""


@item.command("search")
@click.argument("query")
@click.option("--limit", default=50, type=int, help="Max results (default 50).")
def search_cmd(query: str, limit: int) -> None:
    """Search items by title, abstract, or author (LIKE substring)."""
    try:
        svc = _service()
        results = svc.search(query, limit=limit)
        emit(
            [it.model_dump() for it in results],
            human=_human(),
            count=len(results),
        )
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@item.command("read")
@click.argument("key")
def read_cmd(key: str) -> None:
    """Get full metadata for an item (by KEY)."""
    try:
        svc = _service()
        data = svc.get(key)
        emit(data.model_dump(), human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@item.command("update")
@click.argument("key")
@click.option("--title", default=None)
@click.option("--date", default=None)
@click.option("--abstract", default=None)
@click.option("--doi", default=None)
@click.option("--url", default=None)
@click.option("--set", "extras", multiple=True, help="Set extra field KEY=VALUE (repeatable).")
def update_cmd(
    key: str,
    title: str | None,
    date: str | None,
    abstract: str | None,
    doi: str | None,
    url: str | None,
    extras: tuple[str, ...],
) -> None:
    """Update an item's metadata. Only provided fields are changed."""
    extra_dict: dict[str, str] = {}
    for e in extras:
        if "=" in e:
            k, v = e.split("=", 1)
            extra_dict[k.strip()] = v.strip()
    try:
        svc = _service()
        result = asyncio.run(
            svc.update(
                key,
                title=title,
                date=date,
                abstract=abstract,
                doi=doi,
                url=url,
                extra=extra_dict or None,
            )
        )
        emit(result.model_dump(), human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@item.command("delete")
@click.argument("keys", nargs=-1, required=True)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def delete_cmd(keys: tuple[str, ...], yes: bool) -> None:
    """Delete one or more items."""
    if not yes:
        click.confirm(f"Delete {len(keys)} item(s)?", abort=True)
    try:
        svc = _service()

        async def _all() -> list[tuple[str, Exception | None]]:
            results = await asyncio.gather(
                *[svc.delete(k) for k in keys], return_exceptions=True
            )
            out: list[tuple[str, Exception | None]] = []
            for k, r in zip(keys, results, strict=True):
                if isinstance(r, Exception):
                    out.append((k, r))
                else:
                    out.append((k, None))
            return out

        outcomes = asyncio.run(_all())
        ok = [k for k, e in outcomes if e is None]
        fail = [(k, e) for k, e in outcomes if e is not None]
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


@item.command("add")
@click.option("--doi", "dois", multiple=True, help="DOI(s) to add (repeatable).")
@click.option("--from-file", "dois_file", type=click.Path(exists=True), help="File with one DOI per line.")
def add_cmd(dois: tuple[str, ...], dois_file: str | None) -> None:
    """Add item(s) by DOI."""
    items: list[str] = list(dois)
    if dois_file:
        items.extend(Path(dois_file).read_text(encoding="utf-8").splitlines())
    items = [d.strip() for d in items if d.strip() and not d.startswith("#")]
    if not items:
        raise click.UsageError("Provide --doi or --from-file")
    try:
        svc = _service()
        created, failures = asyncio.run(svc.add_many(items))
        emit_batch(
            [it.model_dump() for it in created],
            [(doi, err) for doi, err in failures],
            human=_human(),
        )
        if failures:
            sys.exit(2)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


def _wrap(e: BaseException) -> ZopError:
    if isinstance(e, ZopError):
        return e
    return ZopError(str(e))
