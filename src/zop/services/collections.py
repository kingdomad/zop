"""Collection service: business logic for collection operations.

This layer:
- Validates inputs
- Resolves collection names <-> keys
- Coordinates SQLite reads and Web API writes
- Aggregates per-item failures in batch ops
- Implements a real dry-run that checks existence + would-create conflicts
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from zop.adapters.sqlite_reader import SqliteReader
from zop.adapters.zotero_api import ApiCreds, ZoteroApi
from zop.core.errors import (
    AuthError,
    NotFoundError,
    ValidationError,
    ZopError,
)
from zop.models.collection import Collection, CollectionTree


@dataclass
class PlanNode:
    """One entry in a reorg plan.

    `parent` is a NAME (resolved against current library state during validate).
    `items` are item keys to assign to the new collection.
    """

    name: str
    parent: str | None = None
    items: list[str] = field(default_factory=list)
    parent_key: str | None = None  # set during validate()


@dataclass
class PlanReport:
    """Result of validating a plan against current library state."""

    to_create: list[PlanNode] = field(default_factory=list)
    item_assignments: list[tuple[str, str]] = field(default_factory=list)  # (item_key, coll_name)
    conflicts: list[str] = field(default_factory=list)
    unresolved_parents: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts and not self.unresolved_parents


class CollectionsService:
    """High-level collection operations."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        creds: ApiCreds | None = None,
    ) -> None:
        if db_path is None:
            raise ValidationError(
                "db_path required (set data_dir in config or pass explicitly)"
            )
        self._db_path = Path(db_path)
        self._creds = creds
        self._reader = SqliteReader(self._db_path)

    # ---- Read ----

    def list_all(self) -> list[Collection]:
        return self._reader.list_collections()

    def list_tree(self) -> list[CollectionTree]:
        return self._reader.build_tree()

    def get(self, key: str) -> Collection:
        return self._reader.get_collection(key)

    def items(self, key: str) -> list[str]:
        return [it.key for it in self._reader.list_collection_items(key)]

    def resolve(self, name: str) -> Collection:
        for c in self.list_all():
            if c.name == name:
                return c
        raise NotFoundError(f"No collection named '{name}'")

    # ---- Plan validation (real dry-run) ----

    def validate_plan(self, plan: list[PlanNode]) -> PlanReport:
        """Check a plan against current state.

        Validates:
        - No duplicate names (vs current library)
        - All parent references resolve to existing collections OR to other
          nodes in the plan (which will be created first; creation is
          topologically ordered so parents are created before children)
        - All item keys exist locally (best-effort; the API will catch missed ones)
        """
        existing = {c.name: c for c in self.list_all()}
        report = PlanReport()
        plan_by_name: dict[str, PlanNode] = {n.name: n for n in plan}

        # First pass: name uniqueness + item existence
        for node in plan:
            if not node.name.strip():
                report.conflicts.append("Empty collection name in plan")
                continue
            if node.name in existing:
                report.conflicts.append(
                    f"Collection '{node.name}' already exists (key={existing[node.name].key})"
                )
                continue
            # Defer to second pass for parent resolution

        # Second pass: parent resolution + item checks (only on nodes that
        # passed the uniqueness check)
        for node in plan:
            if any(node.name in c for c in report.conflicts if "already exists" in c):
                continue  # skip nodes that failed uniqueness
            if not node.name.strip():
                continue
            if node.parent:
                if node.parent in existing:
                    node.parent_key = existing[node.parent].key
                elif node.parent in plan_by_name:
                    # Parent will be created in the same plan; mark deferred.
                    node.parent_key = "__PLAN_PARENT__"  # resolved at exec time
                else:
                    if node.parent not in report.unresolved_parents:
                        report.unresolved_parents.append(node.parent)
                    continue
            report.to_create.append(node)

            for item_key in node.items:
                if not self._item_exists_locally(item_key):
                    report.conflicts.append(
                        f"Item '{item_key}' (for collection '{node.name}') not found locally"
                    )
                else:
                    report.item_assignments.append((item_key, node.name))

        return report

    def _item_exists_locally(self, key: str) -> bool:
        try:
            with self._reader._connect() as con:
                row = con.execute(
                    "SELECT 1 FROM items WHERE key = ? LIMIT 1", (key,)
                ).fetchone()
            return row is not None
        except Exception:
            return False

    # ---- Write (requires API credentials) ----

    def _require_api(self) -> ZoteroApi:
        if not self._creds or not self._creds.api_key:
            raise AuthError("API credentials required for write operations")
        return ZoteroApi(self._creds)

    async def create(
        self,
        name: str,
        *,
        parent: str | None = None,
    ) -> Collection:
        """Create one collection. `parent` is the parent NAME."""
        api = self._require_api()
        payload: dict[str, object] = {"name": name}
        if parent:
            p = self.resolve(parent)
            payload["parentCollection"] = p.key
        async with api:
            result = await api.create_collections([payload])
        if not result:
            raise ZopError(f"Failed to create '{name}' (empty response)")
        r = result[0]
        return Collection(
            key=r["key"],
            name=r["data"]["name"],
            parent_key=r["data"].get("parentCollection") or None,
            version=r["version"],
        )

    async def create_many(self, plan: list[PlanNode]) -> list[Collection]:
        """Create all collections in a validated plan (batched POST, topologically ordered).

        Handles intra-plan parent references: a node whose parent is another
        node in the plan is created after its parent. We process in waves
        (Kahn-style topological order), POSTing each wave as a batch.
        """
        report = self.validate_plan(plan)
        if not report.ok:
            raise ValidationError(
                f"Plan invalid. conflicts={report.conflicts} unresolved={report.unresolved_parents}"
            )

        plan_by_name = {n.name: n for n in report.to_create}
        # Build dependency: who depends on whom
        # remaining[node] = set of node-names this node still waits on
        remaining: dict[str, set[str]] = {}
        for n in report.to_create:
            if n.parent_key == "__PLAN_PARENT__" and n.parent in plan_by_name:
                remaining[n.name] = {n.parent}
            else:
                remaining[n.name] = set()

        api = self._require_api()
        created: dict[str, Collection] = {}  # name -> Collection
        async with api:
            while remaining:
                # Find nodes with no remaining dependencies
                ready = [n for n in report.to_create if n.name in remaining and not remaining[n.name]]
                if not ready:
                    raise ValidationError("Plan has a cycle in parent references")
                payloads: list[dict[str, object]] = []
                for n in ready:
                    parent_key: str | None = None
                    if n.parent:
                        if n.parent in created:
                            parent_key = created[n.parent].key
                        elif n.parent in plan_by_name and n.parent_key == "__PLAN_PARENT__":
                            # Should have been picked up already by topo sort
                            raise ValidationError(
                                f"Parent '{n.parent}' not yet created for '{n.name}'"
                            )
                        else:
                            # Use the resolved key from validate_plan (existing parent)
                            parent_key = n.parent_key
                    payloads.append(
                        {"name": n.name, "parentCollection": parent_key}
                    )
                results = await api.create_collections(payloads)
                if len(results) != len(ready):
                    raise ZopError(
                        f"API returned {len(results)} collections, expected {len(ready)}"
                    )
                for n, r in zip(ready, results, strict=True):
                    c = Collection(
                        key=r["key"],
                        name=r["data"]["name"],
                        parent_key=r["data"].get("parentCollection") or None,
                        version=r["version"],
                    )
                    created[n.name] = c
                # Remove processed nodes from remaining, decrement dependents
                for n in ready:
                    del remaining[n.name]
                for deps in remaining.values():
                    deps.difference_update({n.name for n in ready})

        return list(created.values())

    async def delete(self, key: str) -> None:
        api = self._require_api()
        async with api:
            await api.delete_collection(key)

    async def reparent(
        self, key: str, new_parent: str | None, *, version: int | None = None
    ) -> Collection:
        """Move collection under new parent (NAME), or detach if new_parent is None."""

        api = self._require_api()
        if new_parent is None:
            parent_key: str | None | object = False  # detach
        else:
            parent_key = self.resolve(new_parent).key
        async with api:
            r = await api.update_collection(key, parent_key=parent_key, version=version)
        return Collection(
            key=r["key"],
            name=r["data"]["name"],
            parent_key=r["data"].get("parentCollection") or None,
            version=r["version"],
        )

    async def move_items(
        self,
        item_keys: Sequence[str],
        to_collection_key: str,
    ) -> tuple[list[str], list[tuple[str, Exception]]]:
        """Add items to a collection (preserves existing memberships).

        Fetches each item's current collections, adds the target, then
        bounded-concurrent PATCH. Per-item failures are isolated.
        """
        api = self._require_api()
        async with api:
            # Fetch current state + version per item.
            async def _fetch(k: str) -> tuple[str, list[str], int] | tuple[str, Exception]:
                try:
                    item = await api.get_item(k)
                    colls = list(item["data"].get("collections", []))
                    if to_collection_key not in colls:
                        colls = [*colls, to_collection_key]
                    return (k, colls, item["version"])
                except Exception as e:
                    return (k, e)

            fetched = await asyncio.gather(
                *[_fetch(k) for k in item_keys], return_exceptions=False
            )

            updates: list[tuple[str, list[str], int | None]] = []
            fetch_failures: list[tuple[str, Exception]] = []
            for r in fetched:
                if len(r) == 3 and isinstance(r[1], list):
                    _, colls, ver = r  # type: ignore[misc]
                    updates.append((r[0], colls, ver))
                else:
                    fetch_failures.append((r[0], r[1]))  # type: ignore[arg-type]

            ok, move_failures = await api.batch_update_item_collections(updates)

        return ok, fetch_failures + move_failures


__all__ = ["CollectionsService", "PlanNode", "PlanReport"]
