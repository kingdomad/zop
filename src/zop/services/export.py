"""Export service: BibTeX, CSL-JSON, RIS formatters."""

from __future__ import annotations

import re
from pathlib import Path

from zop.adapters.sqlite_reader import SqliteReader
from zop.core.errors import ZopError
from zop.models.item import Item


class ExportService:
    """Format items into citation formats."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            raise ZopError("db_path required")
        self._reader = SqliteReader(db_path)

    def to_csl_json(self, items: list[Item]) -> list[dict[str, object]]:
        """Convert to CSL-JSON (Citation Style Language)."""
        out: list[dict[str, object]] = []
        for it in items:
            entry: dict[str, object] = {
                "id": it.key,
                "type": _map_type_to_csl(it.item_type.value),
                "title": it.title,
            }
            if it.creators:
                entry["author"] = [
                    {"family": _family(c), "given": _given(c)} for c in it.creators
                ]
            if it.date:
                entry["issued"] = {"date-parts": [[_extract_year(it.date)]]}
            if it.doi:
                entry["DOI"] = it.doi
            if it.url:
                entry["URL"] = it.url
            if it.abstract:
                entry["abstract"] = it.abstract
            out.append(entry)
        return out

    def to_bibtex(self, items: list[Item]) -> str:
        """Convert to BibTeX."""
        lines: list[str] = []
        for it in items:
            entry_type = _map_type_to_bibtex(it.item_type.value)
            key = _make_bibtex_key(it)
            lines.append(f"@{entry_type}{{{key},")
            lines.append(f"  title = {{{_escape_bibtex(it.title)}}},")
            if it.creators:
                authors = " and ".join(it.creators)
                lines.append(f"  author = {{{_escape_bibtex(authors)}}},")
            if it.date:
                year = _extract_year(it.date)
                lines.append(f"  year = {{{year}}},")
            if it.doi:
                lines.append(f"  doi = {{{it.doi}}},")
            if it.url:
                lines.append(f"  url = {{{it.url}}},")
            if it.abstract:
                lines.append(f"  abstract = {{{_escape_bibtex(it.abstract)}}},")
            lines.append("}")
            lines.append("")
        return "\n".join(lines)

    def to_ris(self, items: list[Item]) -> str:
        """Convert to RIS format."""
        out: list[str] = []
        for it in items:
            out.append(_map_type_to_ris(it.item_type.value))
            if it.title:
                out.append(f"TI  - {it.title}")
            for c in it.creators:
                out.append(f"AU  - {c}")
            if it.date:
                out.append(f"PY  - {_extract_year(it.date)}")
            if it.doi:
                out.append(f"DO  - {it.doi}")
            if it.url:
                out.append(f"UR  - {it.url}")
            if it.abstract:
                out.append(f"AB  - {it.abstract}")
            out.append("ER  - ")
            out.append("")
        return "\n".join(out)


# ---- Helpers ----

def _family(creator: str) -> str:
    return creator.split(",", 1)[0].strip() if "," in creator else creator.split()[-1]


def _given(creator: str) -> str:
    return creator.split(",", 1)[1].strip() if "," in creator else " ".join(creator.split()[:-1])


def _escape_bibtex(s: str) -> str:
    return s.replace("{", "\\{").replace("}", "\\}").replace("$", "\\$")


def _extract_year(date: str | None) -> str:
    if date is None:
        return ""
    m = re.search(r"\d{4}", date)
    return m.group(0) if m else ""


def _make_bibtex_key(item: Item) -> str:
    """Generate a citation key: firstAuthorLastName + Year + FirstTitleWord."""
    auth = "anon"
    if item.creators:
        first_author = item.creators[0]
        auth = _family(first_author).lower().replace(" ", "")
    year = _extract_year(item.date) or "nodate"
    title_word = ""
    for w in re.split(r"\W+", item.title.lower()):
        if w and w not in {"a", "an", "the", "on", "of", "in", "for", "to", "and", "or"}:
            title_word = w
            break
    return f"{auth}{year}{title_word}"[:40]


_TYPE_MAP_CSL = {
    "book": "book",
    "bookSection": "chapter",
    "journalArticle": "article-journal",
    "conferencePaper": "paper-conference",
    "preprint": "article",
    "report": "report",
    "document": "document",
    "dataset": "dataset",
    "webpage": "webpage",
    "computerProgram": "software",
    "thesis": "thesis",
    "manuscript": "manuscript",
}


def _map_type_to_csl(t: str) -> str:
    return _TYPE_MAP_CSL.get(t, "article")


_TYPE_MAP_BIBTEX = {
    "book": "book",
    "bookSection": "incollection",
    "journalArticle": "article",
    "conferencePaper": "inproceedings",
    "preprint": "article",
    "report": "techreport",
    "document": "misc",
    "dataset": "misc",
    "webpage": "misc",
    "computerProgram": "misc",
    "thesis": "phdthesis",
    "manuscript": "unpublished",
}


def _map_type_to_bibtex(t: str) -> str:
    return _TYPE_MAP_BIBTEX.get(t, "misc")


_TYPE_MAP_RIS = {
    "book": "TY  - BOOK",
    "bookSection": "TY  - CHAP",
    "journalArticle": "TY  - JOUR",
    "conferencePaper": "TY  - CONF",
    "preprint": "TY  - GEN",
    "report": "TY  - RPRT",
    "document": "TY  - GEN",
    "dataset": "TY  - DATA",
    "webpage": "TY  - ELEC",
    "computerProgram": "TY  - COMP",
    "thesis": "TY  - THES",
    "manuscript": "TY  - UNPB",
}


def _map_type_to_ris(t: str) -> str:
    return _TYPE_MAP_RIS.get(t, "TY  - GEN")


__all__ = ["ExportService"]
