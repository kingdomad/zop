"""Common model types."""

from __future__ import annotations

from enum import StrEnum

# Zotero item keys / collection keys are 8-char alphanumeric
ID_PATTERN = r"^[A-Z0-9]{8}$"


class ItemType(StrEnum):
    """Subset of Zotero item types (extend as needed)."""

    BOOK = "book"
    BOOK_SECTION = "bookSection"
    JOURNAL_ARTICLE = "journalArticle"
    CONFERENCE_PAPER = "conferencePaper"
    PREPRINT = "preprint"
    REPORT = "report"
    DOCUMENT = "document"
    DATASET = "dataset"
    WEBPAGE = "webpage"
    COMPUTER_PROGRAM = "computerProgram"
    THESIS = "thesis"
    MANUSCRIPT = "manuscript"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> ItemType:  # type: ignore[override]
        return cls.UNKNOWN
