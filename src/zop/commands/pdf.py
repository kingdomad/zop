"""PDF CLI subcommands."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from zop.core.config import load_config
from zop.core.envelope import emit, emit_error
from zop.core.errors import ZopError
from zop.services.pdf import PdfService


def _service() -> PdfService:
    cfg = load_config()
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return PdfService(db_path=Path(cfg.data_dir) / "zotero.sqlite")


def _human() -> bool:
    return sys.stdout.isatty()


@click.group(name="pdf")
def pdf() -> None:
    """Read local PDF attachments."""


@pdf.command("read")
@click.argument("item_key")
@click.option("--max-chars", default=200_000, type=int)
def read_cmd(item_key: str, max_chars: int) -> None:
    """Extract full text from the PDF attached to an item."""
    try:
        svc = _service()
        text = svc.read_text(item_key, max_chars=max_chars)
        emit({"text": text, "length": len(text)}, human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@pdf.command("outline")
@click.argument("item_key")
def outline_cmd(item_key: str) -> None:
    """Show PDF outline (bookmarks)."""
    try:
        svc = _service()
        outline = svc.get_outline(item_key)
        emit(outline, human=_human(), count=len(outline))
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)


@pdf.command("section")
@click.argument("item_key")
@click.argument("section_number", type=int)
@click.option("--max-chars", default=100_000, type=int)
def section_cmd(item_key: str, section_number: int, max_chars: int) -> None:
    """Read a specific outline section (1-indexed)."""
    try:
        svc = _service()
        text = svc.read_section(item_key, section_number, max_chars=max_chars)
        emit({"text": text, "length": len(text)}, human=_human())
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)
