"""Collection CLI subcommands."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from zop.adapters.zotero_api import ApiCreds
from zop.core.config import load_config
from zop.core.envelope import emit, emit_batch, emit_error
from zop.core.errors import ZopError
from zop.services.collections import CollectionsService, PlanNode


def _service(ctx: click.Context) -> CollectionsService:
    cfg = load_config()
    creds: ApiCreds | None = None
    if cfg.has_write_credentials:
        creds = ApiCreds(library_id=cfg.library_id, api_key=cfg.api_key)
    if not cfg.data_dir:
        raise click.UsageError(
            "data_dir not configured. Run 'zop config init' or set in "
            "~/.config/zop/config.toml"
        )
    return CollectionsService(db_path=Path(cfg.data_dir) / "zotero.sqlite", creds=creds)


def _human() -> bool:
    return sys.stdout.isatty()


@click.group(name="collection")
def collection() -> None:
    """Manage Zotero collections."""


@collection.command("list")
@click.option("--tree", is_flag=True, help="Show as parent/child tree.")
@click.option("--flat", is_flag=True, help="Show as flat list (default).")
@click.pass_context
def list_cmd(ctx: click.Context, tree: bool, flat: bool) -> None:
    """List all collections."""
    try:
        svc = _service(ctx)
        if tree:
            nodes = svc.list_tree()
            data = [n.model_dump() for n in nodes]
        else:
            data = [c.model_dump() for c in svc.list_all()]
        emit(data, human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("items")
@click.argument("key")
@click.pass_context
def items_cmd(ctx: click.Context, key: str) -> None:
    """List item keys in a collection (by KEY)."""
    try:
        svc = _service(ctx)
        data = svc.items(key)
        emit(data, human=_human(), count=len(data))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("create")
@click.argument("name")
@click.option("--parent", "parent_ref", default=None, help="Parent collection KEY or NAME.")
@click.pass_context
def create_cmd(ctx: click.Context, name: str, parent_ref: str | None) -> None:
    """Create a collection (NAME). Parent may be a KEY or NAME. Requires API key."""
    try:
        svc = _service(ctx)
        result = asyncio.run(svc.create(name, parent=parent_ref))
        emit([result.model_dump()], human=_human(), count=1)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("delete")
@click.argument("key")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.pass_context
def delete_cmd(ctx: click.Context, key: str, yes: bool) -> None:
    """Delete a collection (cascades to subcollections). Requires API key."""
    if not yes:
        click.confirm(f"Delete collection {key} (and all subcollections)?", abort=True)
    try:
        svc = _service(ctx)
        asyncio.run(svc.delete(key))
        emit({"deleted": key}, human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("reparent")
@click.argument("key")
@click.option("--parent", "parent_name", default=None, help="New parent NAME (omit for top-level).")
@click.pass_context
def reparent_cmd(ctx: click.Context, key: str, parent_name: str | None) -> None:
    """Move a collection under a new parent (or to top-level). Requires API key."""
    try:
        svc = _service(ctx)
        result = asyncio.run(svc.reparent(key, parent_name))
        emit([result.model_dump()], human=_human(), count=1)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("move")
@click.argument("item_keys", nargs=-1, required=True)
@click.option("--to", "to_collection_key", required=True, help="Target collection KEY.")
@click.pass_context
def move_cmd(
    ctx: click.Context,
    item_keys: tuple[str, ...],
    to_collection_key: str,
) -> None:
    """Move items into a collection. Bounded-concurrent PATCH."""
    try:
        svc = _service(ctx)
        ok, fail = asyncio.run(svc.move_items(list(item_keys), to_collection_key))
        emit_batch(
            [{"key": k} for k in ok],
            [(k, _wrapped(e)) for k, e in fail],
            human=_human(),
        )
        if fail:
            sys.exit(2)
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@collection.command("plan")
@click.argument("plan_file", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Validate without executing.")
@click.option("--execute", "do_execute", is_flag=True, help="Actually execute.")
@click.pass_context
def plan_cmd(
    ctx: click.Context,
    plan_file: Path,
    dry_run: bool,
    do_execute: bool,
) -> None:
    """Batch reorg from a plan JSON file.

    Plan format::

        {
          "collections": [
            {"name": "Topic A", "parent": "ExistingParent", "items": ["KEY1", "KEY2"]},
            {"name": "Topic B", "items": []}
          ]
        }
    """
    if dry_run == do_execute:
        raise click.UsageError("Specify exactly one of --dry-run or --execute")
    try:
        with plan_file.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        plan = [
            PlanNode(
                name=p["name"],
                parent=p.get("parent"),
                items=p.get("items", []),
            )
            for p in raw.get("collections", [])
        ]
        svc = _service(ctx)
        report = svc.validate_plan(plan)
        out = {
            "to_create": [
                {"name": n.name, "parent": n.parent, "items": n.items}
                for n in report.to_create
            ],
            "assignments": [{"item": k, "collection": c} for k, c in report.item_assignments],
            "conflicts": report.conflicts,
            "unresolved_parents": report.unresolved_parents,
            "ok": report.ok,
        }
        if dry_run:
            emit(out, human=_human())
            if not report.ok:
                sys.exit(2)
            return
        # execute
        if not report.ok:
            emit(out, human=_human())
            sys.exit(2)
        created = asyncio.run(svc.create_many(plan))
        emit(
            {
                "created": [c.model_dump() for c in created],
                "assignments_pending": report.item_assignments,
            },
            human=_human(),
            count=len(created),
        )
        # Note: item assignment to newly-created collections would go here
        # in a follow-up step (separate API call after collections exist).
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


def _wrapped(e: BaseException) -> ZopError:
    if isinstance(e, ZopError):
        return e
    return ZopError(str(e))
