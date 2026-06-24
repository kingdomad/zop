"""Item models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from zop.models.common import ID_PATTERN, ItemType


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
