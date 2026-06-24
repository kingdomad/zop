"""Tag service: batch tag operations."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from zop.adapters.sqlite_reader import SqliteReader
from zop.adapters.zotero_api import ApiCreds, ZoteroApi
from zop.core.errors import AuthError, ZopError


class TagsService:
    """Tag operations: list all tags, add/remove tags from items in batch."""

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

    def list_all(self) -> list[dict[str, int | str]]:
        return self._reader.list_all_tags()

    def _require_api(self) -> ZoteroApi:
        if not self._creds or not self._creds.api_key:
            raise AuthError("API credentials required for write operations")
        return ZoteroApi(self._creds)

    async def add(
        self, item_keys: Sequence[str], tags: Sequence[str]
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """Add tags to items. Preserves existing tags. Per-item failures isolated."""
        if not item_keys or not tags:
            return [], []
        api = self._require_api()
        new_tag_set = {t.strip() for t in tags if t.strip()}

        async with api:
            async def _one(k: str) -> str:
                item = await api.get_item(k)
                existing = {tg.get("tag", "") for tg in item["data"].get("tags", [])}
                merged = list(existing | new_tag_set)
                payload = {"tags": [{"tag": t} for t in sorted(merged)]}
                await api.update_item(k, payload, version=item["version"])
                return k

            results = await asyncio.gather(
                *[_one(k) for k in item_keys], return_exceptions=True
            )
        ok: list[str] = []
        fail: list[tuple[str, Exception]] = []
        for k, r in zip(item_keys, results, strict=True):
            if isinstance(r, Exception):
                fail.append((k, r))
            else:
                ok.append(cast(str, r))
        return ok, fail

    async def remove(
        self, item_keys: Sequence[str], tags: Sequence[str]
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """Remove tags from items. Per-item failures isolated."""
        if not item_keys or not tags:
            return [], []
        remove_set = {t.strip() for t in tags if t.strip()}
        api = self._require_api()

        async with api:
            async def _one(k: str) -> str:
                item = await api.get_item(k)
                existing = [tg.get("tag", "") for tg in item["data"].get("tags", [])]
                kept = [t for t in existing if t not in remove_set]
                payload = {"tags": [{"tag": t} for t in kept]}
                await api.update_item(k, payload, version=item["version"])
                return k

            results = await asyncio.gather(
                *[_one(k) for k in item_keys], return_exceptions=True
            )
        ok: list[str] = []
        fail: list[tuple[str, Exception]] = []
        for k, r in zip(item_keys, results, strict=True):
            if isinstance(r, Exception):
                fail.append((k, r))
            else:
                ok.append(cast(str, r))
        return ok, fail


__all__ = ["TagsService"]
