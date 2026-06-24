"""Item service: business logic for item operations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from zop.adapters.sqlite_reader import SqliteReader
from zop.adapters.zotero_api import ApiCreds, ZoteroApi
from zop.core.errors import AuthError, NotFoundError, ZopError
from zop.models.item import Item, ItemSummary


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

            resp = await api._client.patch(
                api._items_url(key),
                json=payload,
                headers={"If-Unmodified-Since-Version": str(version)},
            )
            api._check(resp)
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
            resp = await api._client.delete(
                api._items_url(key),
                headers={"If-Unmodified-Since-Version": str(current["version"])},
            )
            api._check(resp)

    async def add_by_doi(self, doi: str, *, collection_keys: Sequence[str] | None = None) -> Item:
        """Create an item from a DOI. Uses Zotero's translation API endpoint."""
        api = self._require_api()
        payload: dict[str, object] = {
            "itemType": "journalArticle",  # default; server may override
            "DOI": doi,
            "collections": list(collection_keys or []),
        }
        async with api:
            resp = await api._client.post(
                f"{api._root()}/items",
                json=[payload],
            )
            data = api._check(resp)
        if not data:
            raise ZopError(f"Failed to add item with DOI '{doi}'")
        successful = data.get("successful", {}) if isinstance(data, dict) else {}
        if not successful:
            raise ZopError(f"DOI '{doi}' not found or rejected by server")
        first = next(iter(successful.values()))
        return self.get(first["key"])

    async def add_many(self, dois: Sequence[str]) -> list[Item]:
        """Add multiple items by DOI in a single batched POST."""
        api = self._require_api()
        payload = [
            {"itemType": "journalArticle", "DOI": doi}
            for doi in dois
        ]
        async with api:
            resp = await api._client.post(
                f"{api._root()}/items",
                json=payload,
            )
            data = api._check(resp)
        successful = data.get("successful", {}) if isinstance(data, dict) else {}
        keys = [v["key"] for v in successful.values()]
        return [self.get(k) for k in keys if k]


__all__ = ["ItemsService"]
