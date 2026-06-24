"""PDF service: read local PDF attachments."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pypdf import PdfReader

from zop.adapters.sqlite_reader import SqliteReader
from zop.core.errors import NotFoundError, ZopError


class OutlineEntry(TypedDict):
    """A flat PDF outline entry: one bookmark, indexed by depth."""

    section: int
    title: str
    page: int | None
    depth: int


class PdfService:
    """PDF operations: read text, extract outline."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            raise ZopError("db_path required")
        self._reader = SqliteReader(db_path)

    def get_attachment_path(self, item_key: str) -> Path:
        """Find the local PDF path for an item."""
        path = self._reader.get_attachment_path(item_key)
        if path is None or not path.exists():
            raise NotFoundError(f"No local PDF attachment for item '{item_key}'")
        return path

    def read_text(self, item_key: str, *, max_chars: int = 200_000) -> str:
        """Extract full text from the PDF (truncated to max_chars)."""
        path = self.get_attachment_path(item_key)
        reader = PdfReader(str(path))
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if total + len(txt) > max_chars:
                remaining = max_chars - total
                chunks.append(txt[:remaining])
                chunks.append("\n\n[...truncated at max_chars]")
                break
            chunks.append(txt)
            total += len(txt)
        return "\n\n".join(chunks)

    def get_outline(self, item_key: str) -> list[OutlineEntry]:
        """Return the PDF outline (bookmarks) as a flat list."""
        path = self.get_attachment_path(item_key)
        reader = PdfReader(str(path))
        out: list[OutlineEntry] = []

        def _walk(items: object, depth: int) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, list):
                    continue
                # item[0] is a dict like {'/Title': '...', '/Page': IndirectObject(...)}
                raw_title = item[0] if len(item) > 0 else None
                title = ""
                if isinstance(raw_title, dict):
                    title = str(raw_title.get("/Title", ""))
                elif raw_title is not None:
                    title = str(raw_title)
                try:
                    raw_page = reader.get_destination_page_number(item)  # type: ignore[arg-type]
                    page_num: int | None = raw_page + 1 if raw_page is not None else None
                except Exception:
                    page_num = None
                out.append(
                    {"section": len(out) + 1, "title": title, "page": page_num, "depth": depth}
                )
                # Recurse into sub-items (last element is list of sub-outlines)
                if len(item) > 1 and isinstance(item[-1], list):
                    _walk(item[-1], depth + 1)

        outline = reader.outline
        _walk(outline, 0)
        return out

    def read_section(
        self, item_key: str, section_number: int, *, max_chars: int = 100_000
    ) -> str:
        """Read text from a specific outline section (1-indexed)."""
        outline = self.get_outline(item_key)
        if section_number < 1 or section_number > len(outline):
            raise NotFoundError(
                f"Section {section_number} not in outline (1-{len(outline)})"
            )
        # Find the next sibling/depth-0 section to know where to stop
        start_page: int | None = outline[section_number - 1]["page"]
        end_page: int | None = None
        for next_sec in outline[section_number:]:
            if next_sec["depth"] <= outline[section_number - 1]["depth"]:
                end_page = next_sec["page"]
                break
        path = self.get_attachment_path(item_key)
        reader = PdfReader(str(path))
        start_idx = 0 if start_page is None else start_page - 1
        end_idx = len(reader.pages) if end_page is None else end_page - 1
        chunks: list[str] = []
        total = 0
        for i in range(start_idx, min(end_idx, len(reader.pages))):
            try:
                txt = reader.pages[i].extract_text() or ""
            except Exception:
                txt = ""
            if total + len(txt) > max_chars:
                remaining = max_chars - total
                chunks.append(txt[:remaining])
                chunks.append("\n[...truncated]")
                break
            chunks.append(txt)
            total += len(txt)
        return f"# {outline[section_number - 1]['title']}\n\n" + "\n\n".join(chunks)


__all__ = ["OutlineEntry", "PdfService"]
