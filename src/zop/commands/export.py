"""Export CLI: export items in BibTeX, CSL-JSON, RIS."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from zop.core.config import load_config
from zop.core.envelope import emit, emit_error
from zop.core.errors import ZopError
from zop.services.export import ExportService


def _service() -> ExportService:
    cfg = load_config()
    if not cfg.data_dir:
        raise click.UsageError("data_dir not configured")
    return ExportService(db_path=Path(cfg.data_dir) / "zotero.sqlite")


def _human() -> bool:
    return sys.stdout.isatty()


@click.command(name="export")
@click.argument("item_keys", nargs=-1, required=True)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csl-json", "bibtex", "ris"]),
    default="bibtex",
)
@click.option("--out", "-o", type=click.Path(), help="Write to file instead of stdout.")
def export_cmd(
    item_keys: tuple[str, ...], fmt: str, out: str | None
) -> None:
    """Export items by KEY in the chosen format."""
    try:
        svc = _service()
        items = [svc._reader.get_item(k) for k in item_keys]
        if fmt == "csl-json":
            payload: object = svc.to_csl_json(items)
        elif fmt == "bibtex":
            payload = svc.to_bibtex(items)
        elif fmt == "ris":
            payload = svc.to_ris(items)
        else:
            raise ZopError(f"Unknown format: {fmt}")
        if out:
            if fmt == "csl-json":
                import json
                Path(out).write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            else:
                Path(out).write_text(str(payload), encoding="utf-8")
            emit({"written": out, "count": len(items)}, human=_human())
        else:
            if _human():
                # Human/tty: raw output (pipe-friendly, e.g. zop export K > refs.bib).
                if fmt == "csl-json":
                    import json
                    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
                    sys.stdout.write("\n")
                else:
                    sys.stdout.write(str(payload))
                sys.stdout.flush()
            else:
                # JSON/agent: wrap in the standard envelope.
                emit(
                    {"format": fmt, "content": payload, "count": len(items)},
                    human=False,
                )
    except ZopError as e:
        emit_error(e, human=_human())
        sys.exit(1)
