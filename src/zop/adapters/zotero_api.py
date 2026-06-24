"""Async Zotero Web API client (batch-capable).

Differences from pyzotero-based tools (e.g. zot):
- Real batch POST for collection creation
- Bounded-concurrency PATCH for item moves (pyzotero's addto_collection is single-item per call)
- True reparent via PATCH /collections/{key} with parentCollection=false (pyzotero doesn't expose this)
- Per-item error isolation: one failure doesn't abort the batch
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import httpx

from zop.core.concurrency import chunked
from zop.core.errors import ApiError, AuthError, ConflictError, NotFoundError

_SENTINEL = object()


@dataclass
class ApiCreds:
    library_id: str
    api_key: str
    library_type: str = "user"  # "user" or "group"


class ZoteroApi:
    """Thin async wrapper over the Zotero Web API."""

    BASE_URL = "https://api.zotero.org"
    USER_AGENT = "zop/0.1 (+https://github.com/anomalyco/zop)"

    # API limits per Zotero docs
    BATCH_WRITE_LIMIT = 50  # max objects per POST/PATCH
    BATCH_READ_LIMIT = 100  # max items per GET

    def __init__(
        self,
        creds: ApiCreds,
        *,
        concurrency: int = 8,
        timeout: float = 30.0,
    ) -> None:
        if not creds.library_id or not creds.api_key:
            raise AuthError("library_id and api_key are required")
        self.creds = creds
        self.concurrency = concurrency
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Zotero-API-Key": creds.api_key,
                "Zotero-API-Version": "3",
                "User-Agent": self.USER_AGENT,
            },
            timeout=timeout,
        )

    async def __aenter__(self) -> ZoteroApi:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ---- URL helpers ----

    def _root(self) -> str:
        return f"/{self.creds.library_type}s/{self.creds.library_id}"

    def _coll_url(self, key: str | None = None) -> str:
        base = f"{self._root()}/collections"
        return f"{base}/{key}" if key else base

    def _items_url(self, key: str | None = None) -> str:
        base = f"{self._root()}/items"
        return f"{base}/{key}" if key else base

    # ---- Response handling ----

    def _check(self, resp: httpx.Response) -> Any:
        """Parse response or raise structured error."""
        if resp.status_code == 404:
            raise NotFoundError(f"Not found: {resp.url}")
        if resp.status_code in (409, 412):
            raise ConflictError(f"Conflict (HTTP {resp.status_code}): {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise AuthError(f"Auth failed (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text[:200])
        if not resp.content:
            return None
        return resp.json()

    # ---- Collections ----

    async def list_collections(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch all collections for the library (paginated)."""
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            resp = await self._client.get(
                self._coll_url(),
                params={"limit": min(limit, self.BATCH_READ_LIMIT), "start": start},
            )
            data = self._check(resp)
            if not data:
                break
            out.extend(data)
            if len(data) < self.BATCH_READ_LIMIT:
                break
            start += len(data)
        return out

    async def create_collections(
        self, payloads: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create up to BATCH_WRITE_LIMIT collections per request.

        Returns the created collection objects (each with `key`, `version`, etc.)
        in the same order as the input. The Zotero API returns:
        `{"successful": {...}, "unchanged": {...}, "failed": {...}, "success": {...}}`
        """
        if not payloads:
            return []
        results: list[dict[str, Any]] = []
        for batch in chunked(list(payloads), self.BATCH_WRITE_LIMIT):
            resp = await self._client.post(self._coll_url(), json=list(batch))
            data = self._check(resp)
            if isinstance(data, dict):
                # data has keys: successful (dict by index), unchanged, failed, success
                # Reconstruct ordered list of created collections.
                created = data.get("successful", {})
                if isinstance(created, dict):
                    results.extend(created.values())
                else:
                    results.extend(created)
            elif isinstance(data, list):
                results.extend(data)
        return results

    async def update_collection(
        self,
        key: str,
        *,
        name: str | None = None,
        parent_key: str | None | object = _SENTINEL,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Update a collection.

        Args:
            key: Collection key.
            name: New name (optional).
            parent_key: New parent key. Pass ``None`` or ``False`` to detach to
                top-level. Default (sentinel) leaves parent unchanged.
            version: If-Unmodified-Since-Version for optimistic locking.
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if parent_key is not _SENTINEL:
            payload["parentCollection"] = parent_key if parent_key else False
        headers: dict[str, str] = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        resp = await self._client.patch(self._coll_url(key), json=payload, headers=headers)
        return cast("dict[str, Any]", self._check(resp))

    async def delete_collection(self, key: str, *, version: int | None = None) -> None:
        """Delete a collection. CASCADE: deletes all subcollections."""
        headers: dict[str, str] = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        resp = await self._client.delete(self._coll_url(key), headers=headers)
        self._check(resp)

    # ---- Items ----

    async def get_item(self, key: str) -> dict[str, Any]:
        resp = await self._client.get(self._items_url(key))
        return cast("dict[str, Any]", self._check(resp))

    async def update_item_collections(
        self, key: str, collections: list[str], *, version: int | None = None
    ) -> dict[str, Any]:
        """Set an item's collection membership (replaces existing)."""
        headers: dict[str, str] = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        resp = await self._client.patch(
            self._items_url(key), json={"collections": collections}, headers=headers
        )
        return cast("dict[str, Any]", self._check(resp))

    async def batch_update_item_collections(
        self,
        updates: Sequence[tuple[str, list[str], int | None]],
        *,
        concurrency: int | None = None,
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """Move many items concurrently with bounded parallelism.

        Args:
            updates: Sequence of ``(item_key, target_collections, version)``.
            concurrency: Override default concurrency.

        Returns:
            ``(success_keys, failures)`` where ``failures`` is a list of
            ``(item_key, exception)`` pairs.
        """
        if not updates:
            return [], []
        sem = asyncio.Semaphore(concurrency or self.concurrency)

        async def _one(item_key: str, colls: list[str], ver: int | None) -> str:
            async with sem:
                await self.update_item_collections(item_key, colls, version=ver)
                return item_key

        results = await asyncio.gather(
            *(_one(k, c, v) for k, c, v in updates), return_exceptions=True
        )
        successes: list[str] = []
        failures: list[tuple[str, Exception]] = []
        for (k, _, _), r in zip(updates, results, strict=True):
            if isinstance(r, Exception):
                failures.append((k, r))
            else:
                successes.append(cast(str, r))
        return successes, failures


__all__ = ["ApiCreds", "ZoteroApi"]
