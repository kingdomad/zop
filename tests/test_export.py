"""Tests for export service (no API/DB needed)."""

from __future__ import annotations

from zop.models.common import ItemType
from zop.models.item import Item
from zop.services.export import (
    ExportService,
    _extract_year,
    _make_bibtex_key,
)


def _item(key: str = "ABCDEFGH", title: str = "Test Paper", creators: list[str] | None = None,
          date: str = "2024") -> Item:
    return Item(
        key=key,
        item_type=ItemType.JOURNAL_ARTICLE,
        title=title,
        creators=creators or ["Smith, John", "Doe, Jane"],
        date=date,
        doi="10.1234/test",
        url="https://example.com",
        abstract="An abstract.",
    )


def test_extract_year():
    assert _extract_year("2024") == "2024"
    assert _extract_year("2024-05-01") == "2024"
    assert _extract_year("May 2024") == "2024"
    assert _extract_year("nope") == ""


def test_make_bibtex_key():
    it = _item(creators=["Smith, John"], date="2024", title="Hello World")
    assert _make_bibtex_key(it) == "smith2024hello"


def test_to_csl_json_minimal():
    svc = ExportService.__new__(ExportService)  # skip __init__ (no db)
    items = [_item()]
    data = svc.to_csl_json(items)
    assert len(data) == 1
    e = data[0]
    assert e["id"] == "ABCDEFGH"
    assert e["type"] == "article-journal"
    assert e["title"] == "Test Paper"
    assert e["DOI"] == "10.1234/test"
    assert e["author"][0]["family"] == "Smith"
    assert e["author"][0]["given"] == "John"


def test_to_bibtex():
    svc = ExportService.__new__(ExportService)
    out = svc.to_bibtex([_item()])
    assert "@article{" in out
    assert "title = {Test Paper}" in out
    assert "author = {Smith, John and Doe, Jane}" in out
    assert "year = {2024}" in out
    assert "doi = {10.1234/test}" in out


def test_to_ris():
    svc = ExportService.__new__(ExportService)
    out = svc.to_ris([_item()])
    assert out.startswith("TY  - JOUR")
    assert "TI  - Test Paper" in out
    assert "AU  - Smith, John" in out
    assert "PY  - 2024" in out
    assert "ER  -" in out


def test_bibtex_escapes_braces():
    svc = ExportService.__new__(ExportService)
    it = _item(title="Title with {curly} and } braces")
    out = svc.to_bibtex([it])
    assert r"Title with \{curly\} and \} braces" in out
