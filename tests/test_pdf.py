"""Tests for PDF outline page-number resolution (BUG-6).

The resolution logic is exercised with a fake reader, since the real
pypdf path needs an actual PDF (verified separately by the user).
"""

from __future__ import annotations

from typing import Any

from zop.services.pdf import _resolve_page_number


class _FakeReader:
    """Minimal stand-in for pypdf.PdfReader for page-resolution logic."""

    def __init__(
        self, page_of: dict[Any, int], named: dict[str, Any] | None = None
    ) -> None:
        self._page_of = page_of
        self.named_destinations = named or {}

    def get_destination_page_number(self, dest: Any) -> int | None:
        return self._page_of.get(dest)


def test_resolve_explicit_destination() -> None:
    # get_destination_page_number returns the 0-indexed page directly.
    reader = _FakeReader(page_of={"D1": 4})
    assert _resolve_page_number(reader, "D1") == 5  # 1-indexed


def test_resolve_named_destination_fallback() -> None:
    # /Dest is a name string; the direct method misses, named_destinations
    # resolves it to an explicit destination.
    resolved = "RESOLVED"
    reader = _FakeReader(page_of={resolved: 3}, named={"byname": resolved})
    dest = {"/Dest": "byname"}
    assert _resolve_page_number(reader, dest) == 4  # 1-indexed


def test_resolve_unresolvable_returns_none() -> None:
    reader = _FakeReader(page_of={}, named={})
    assert _resolve_page_number(reader, {"/Dest": "missing"}) is None
