"""Notes service."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from zop.adapters.sqlite_reader import SqliteReader
from zop.adapters.zotero_api import ApiCreds, ZoteroApi, zotero_failure_to_error
from zop.core.errors import AuthError, ZopError


class NotesService:
    """Notes operations: list notes on an item, add a new note."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        creds: ApiCreds | None = None,
    ) -> None:
        if db_path is None:
            raise ZopError("db_path required")
        self._db_path = Path(db_path)
        self._creds = creds
        self._reader = SqliteReader(self._db_path)

    def list_for_item(self, item_key: str) -> list[dict[str, str]]:
        return self._reader.get_item_notes(item_key)

    def _require_api(self) -> ZoteroApi:
        if not self._creds or not self._creds.api_key:
            raise AuthError("API credentials required for write operations")
        return ZoteroApi(self._creds)

    async def add(self, item_key: str, text: str) -> str:
        """Create a note attached to an item. Returns the new note key."""
        api = self._require_api()
        payload = [{"itemType": "note", "note": text, "parentItem": item_key}]
        async with api:
            successful, failed_entries = await api.create_items(payload)
        if not successful:
            # Surface Zotero's real rejection reason (e.g. invalid parentItem)
            # instead of a generic "rejected" (BUG-15).
            if failed_entries:
                raise zotero_failure_to_error(failed_entries[0]) from None
            raise ZopError("Note creation rejected by server")
        return cast(str, successful[0]["key"])


__all__ = ["NotesService"]
