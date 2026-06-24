"""Library service: stats, recent, duplicates."""

from __future__ import annotations

from pathlib import Path

from zop.adapters.sqlite_reader import SqliteReader
from zop.core.errors import ZopError
from zop.models.item import ItemSummary


class LibraryService:
    """Top-level library operations: stats, recent items, duplicate detection."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            raise ZopError("db_path required")
        self._reader = SqliteReader(db_path)

    def stats(self) -> dict[str, object]:
        return self._reader.get_library_stats()

    def recent(self, days: int = 7, limit: int = 50) -> list[ItemSummary]:
        return self._reader.list_recent(days=days, limit=limit)

    def duplicates(self, by: str = "doi") -> dict[str, list[str]]:
        return self._reader.find_duplicates(by=by)


__all__ = ["LibraryService"]
