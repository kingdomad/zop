"""CLI entry point."""

from __future__ import annotations

import sys
from typing import NoReturn

import click

from zop import __version__
from zop.commands.collection import collection as collection_cmd
from zop.commands.export import export_cmd
from zop.commands.item import item as item_cmd
from zop.commands.library import duplicates_cmd, recent_cmd, stats_cmd
from zop.commands.note import note as note_cmd
from zop.commands.pdf import pdf as pdf_cmd
from zop.commands.tag import tag as tag_cmd


@click.group(
    name="zop",
    help="High-throughput Zotero CLI. Reads from local SQLite; writes via Web API.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, "-V", "--version")
@click.option(
    "--json",
    "force_json",
    is_flag=True,
    default=False,
    help="Force JSON envelope output.",
)
@click.option(
    "--human",
    "force_human",
    is_flag=True,
    default=False,
    help="Force human-readable output.",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress non-essential output (errors only).",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (-v, -vv).",
)
@click.pass_context
def main(
    ctx: click.Context,
    force_json: bool,
    force_human: bool,
    quiet: bool,
    verbose: int,
) -> None:
    """Entry point."""
    if force_json and force_human:
        raise click.UsageError("--json and --human are mutually exclusive")
    if force_json:
        human = False
    elif force_human:
        human = True
    else:
        human = sys.stdout.isatty()
    ctx.ensure_object(dict)
    ctx.obj["human"] = human
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose


main.add_command(collection_cmd, name="collection")
main.add_command(item_cmd, name="item")
main.add_command(tag_cmd, name="tag")
main.add_command(note_cmd, name="note")
main.add_command(pdf_cmd, name="pdf")
main.add_command(export_cmd, name="export")
main.add_command(stats_cmd, name="stats")
main.add_command(recent_cmd, name="recent")
main.add_command(duplicates_cmd, name="duplicates")


def run() -> NoReturn:
    """Entry point for setuptools/uv script wrapper."""
    try:
        main(standalone_mode=True)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except click.exceptions.Abort:
        sys.exit(1)
    sys.exit(0)
