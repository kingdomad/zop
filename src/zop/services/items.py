"""Item service: business logic for item operations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from zop.adapters.sqlite_reader import SqliteReader
from zop.adapters.zotero_api import ApiCreds, ZoteroApi, zotero_failure_to_error
from zop.core.errors import AuthError, NotFoundError, ZopError
from zop.models.common import ItemType
from zop.models.item import Item, ItemSummary, parse_year


class ItemsService:
    """High-level item operations."""

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

    # ---- Read (local SQLite) ----

    def get(self, key: str) -> Item:
        return self._reader.get_item(key)

    def search(self, query: str, *, limit: int = 50) -> list[ItemSummary]:
        return self._reader.search_items(query, limit=limit)

    # ---- Write (API) ----

    def _require_api(self) -> ZoteroApi:
        if not self._creds or not self._creds.api_key:
            raise AuthError("API credentials required for write operations")
        return ZoteroApi(self._creds)

    async def update(
        self,
        key: str,
        *,
        title: str | None = None,
        date: str | None = None,
        abstract: str | None = None,
        doi: str | None = None,
        url: str | None = None,
        extra: dict[str, str] | None = None,
        collections: Sequence[str] | None = None,
    ) -> Item:
        """Patch an item's metadata. Pass only fields you want to change.

        Use ``extra`` to set arbitrary fields (becomes Zotero's `extra` blob).
        Use ``collections`` to set collection membership (replaces existing).
        """
        api = self._require_api()
        # Get current state for the If-Unmodified-Since-Version header.
        async with api:
            current = await api.get_item(key)
            version = current["version"]
            payload: dict[str, object] = dict(current["data"])
            if title is not None:
                payload["title"] = title
            if date is not None:
                payload["date"] = date
            if abstract is not None:
                payload["abstractNote"] = abstract
            if doi is not None:
                payload["DOI"] = doi
            if url is not None:
                payload["url"] = url
            if collections is not None:
                payload["collections"] = list(collections)
            if extra:
                # Merge into existing extra blob (newline-separated key: value).
                existing_extra = str(payload.get("extra", ""))
                lines = [ln for ln in existing_extra.splitlines() if ln.strip()]
                seen_keys = set()
                for ln in lines:
                    if ":" in ln:
                        seen_keys.add(ln.split(":", 1)[0].strip())
                for k, v in extra.items():
                    line = f"{k}: {v}"
                    if k in seen_keys:
                        lines = [ln for ln in lines if not ln.startswith(f"{k}:")]
                    lines.append(line)
                payload["extra"] = "\n".join(lines)
            # Strip fields the API doesn't accept in PATCH
            payload.pop("key", None)
            payload.pop("version", None)
            payload.pop("dateAdded", None)
            payload.pop("dateModified", None)

            await api.update_item(key, payload, version=version)
        # Re-fetch from local DB (will pick up after sync)
        try:
            return self._reader.get_item(key)
        except NotFoundError:
            return Item(
                key=key,
                item_type=self.get(key).item_type,
                title=title or "",
            )

    async def delete(self, key: str) -> None:
        api = self._require_api()
        async with api:
            current = await api.get_item(key)
            await api.delete_item(key, version=current["version"])

    async def add_by_doi(self, doi: str, *, collection_keys: Sequence[str] | None = None) -> Item:
        """Create an item from a DOI via batch POST /items."""
        api = self._require_api()
        payload: dict[str, object] = {
            "itemType": "journalArticle",  # default; server may override
            "DOI": doi,
            "collections": list(collection_keys or []),
        }
        async with api:
            successful, failed_entries = await api.create_items([payload])
        if not successful:
            # Surface Zotero's real rejection reason instead of a generic message (BUG-15).
            if failed_entries:
                raise zotero_failure_to_error(failed_entries[0]) from None
            raise ZopError(f"DOI '{doi}' rejected by server")
        return await self._item_after_create(successful[0])

    async def add_many(
        self, dois: Sequence[str]
    ) -> tuple[list[Item], list[tuple[str, ZopError]]]:
        """Add multiple items by DOI in a single batched POST.

        Returns ``(created, failed)``. ``failed`` is ``(doi, ZopError)`` per
        rejected DOI — never silently dropped (BUG-15). Each failure is mapped
        from Zotero's ``failed`` envelope via :func:`zotero_failure_to_error`.
        """
        api = self._require_api()
        dois_list = list(dois)
        payload = [{"itemType": "journalArticle", "DOI": doi} for doi in dois_list]
        async with api:
            successful, failed_entries = await api.create_items(payload)
        created = [await self._item_after_create(c) for c in successful if c.get("key")]
        failures: list[tuple[str, ZopError]] = []
        for entry in failed_entries:
            idx = entry.get("index")
            doi = (
                dois_list[idx]
                if isinstance(idx, int) and 0 <= idx < len(dois_list)
                else "?"
            )
            failures.append((doi, zotero_failure_to_error(entry)))
        return created, failures

    async def _item_after_create(self, created: dict[str, Any]) -> Item:
        """Return the created item: local DB if synced, else from API response.

        A just-created item is not in local SQLite until Zotero syncs it
        (BUG-9), so a strict local read would falsely report failure while
        the item already exists server-side. Prefer local; fall back to the
        API response so the caller gets the new key without a false error.
        """
        key = created.get("key")
        if not key:
            raise ZopError("Server created item but returned no key")
        try:
            return self._reader.get_item(str(key))
        except NotFoundError:
            return self._item_from_api_response(created)

    def _item_from_api_response(self, created: dict[str, Any]) -> Item:
        """Build a best-effort Item from a create_items API response.

        Fields absent from the response (creators, etc.) are left empty;
        they populate after Zotero syncs the new item to local SQLite.
        """
        data = created.get("data")
        if not isinstance(data, dict):
            data = {}
        date_str = str(data["date"]) if data.get("date") else None
        return Item(
            key=str(created["key"]),
            item_type=ItemType(str(data.get("itemType", ""))),
            title=str(data.get("title", "")),
            doi=str(data["DOI"]) if data.get("DOI") else None,
            url=str(data["url"]) if data.get("url") else None,
            date=date_str,
            year=parse_year(date_str),
        )


__all__ = ["ItemsService"]
