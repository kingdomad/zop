"""Collection models."""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict, Field

from zop.models.common import ID_PATTERN


class CollectionSummary(BaseModel):
    """Minimal collection info (saves tokens for list views)."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=ID_PATTERN)
    name: str
    parent_key: str | None = Field(default=None, pattern=ID_PATTERN)


class Collection(CollectionSummary):
    """Full collection info."""

    version: int = 0
    item_count: int = 0
    synced: bool = True


class CollectionTree(BaseModel):
    """Collection as a node in a parent/child tree."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=ID_PATTERN)
    name: str
    parent_key: str | None = Field(default=None, pattern=ID_PATTERN)
    item_count: int = 0
    children: list[CollectionTree] = Field(default_factory=list)

    def walk(self) -> Iterator[CollectionTree]:
        """Pre-order traversal (self before descendants)."""
        yield self
        for child in self.children:
            yield from child.walk()
