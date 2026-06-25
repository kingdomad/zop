"""Item models."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from zop.models.common import ID_PATTERN, ItemType


def parse_year(date: str | None) -> int | None:
    """Extract a 4-digit year from a Zotero date string, else None.

    Zotero stores dates as free-form strings ("2024-05-01", "May 2024",
    "2024-11-07 2024-11-07", ...). Single source of truth for year parsing —
    both the read path (Item.year) and the export path go through it.
    """
    if date is None:
        return None
    match = re.search(r"\d{4}", date)
    return int(match.group(0)) if match else None


class ItemSummary(BaseModel):
    """Minimal item info (used for list views)."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=ID_PATTERN)
    item_type: ItemType
    title: str
    creators: list[str] = Field(default_factory=list)  # "Last, First" strings
    year: int | None = None
    date: str | None = None  # raw Zotero date string


class Item(ItemSummary):
    """Full item metadata."""

    abstract: str | None = None
    doi: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)  # keys
    version: int = 0
    date_added: str | None = None
    date_modified: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)
