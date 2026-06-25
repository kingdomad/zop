"""Tests for collection service (using in-memory SQLite with real schema)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from zop.adapters.zotero_api import _SENTINEL, ApiCreds
from zop.core.errors import AuthError
from zop.services.collections import CollectionsService, PlanNode

# ---- Test fixture: minimal Zotero SQLite schema in memory ----

@pytest.fixture
def fake_db(tmp_path: Path) -> Iterator[Path]:
    """Build an in-memory-like Zotero SQLite for testing.

    Copies the real schema (read-only) from the user's Zotero install if
    available; otherwise builds a minimal schema.
    """
    db = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(db)
    # Minimal schema covering what CollectionsService needs.
    con.executescript("""
        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT NOT NULL,
            parentCollectionID INT,
            clientDateModified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            libraryID INT NOT NULL,
            key TEXT NOT NULL,
            version INT DEFAULT 0,
            synced INT DEFAULT 0
        );
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INT NOT NULL,
            dateAdded TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dateModified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            clientDateModified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            libraryID INT NOT NULL,
            key TEXT NOT NULL,
            version INT DEFAULT 0,
            synced INT DEFAULT 0
        );
        CREATE TABLE collectionItems (
            collectionID INT NOT NULL,
            itemID INT NOT NULL,
            orderIndex INT DEFAULT 0,
            PRIMARY KEY (collectionID, itemID)
        );
        CREATE TABLE itemTypes (
            itemTypeID INTEGER PRIMARY KEY,
            typeName TEXT NOT NULL
        );
        CREATE TABLE fields (
            fieldID INTEGER PRIMARY KEY,
            fieldName TEXT NOT NULL
        );
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, orderIndex INT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);

        INSERT INTO itemTypes(itemTypeID, typeName) VALUES
            (1,'book'), (14,'note'), (17,'journalArticle'), (24,'preprint');

        INSERT INTO fields(fieldID, fieldName) VALUES
            (1,'title'), (12,'date'), (110,'abstract');

        INSERT INTO collections(collectionID, collectionName, parentCollectionID, libraryID, key) VALUES
            (1,'ExistingParent', NULL, 1, 'PARENT01'),
            (2,'AnotherExisting', 1, 1, 'ANOTHER1'),
            (3,'SingleItem',    NULL, 1, 'SINGLTM1');

        INSERT INTO items(itemID, itemTypeID, libraryID, key) VALUES
            (100, 17, 1, 'ITM00001'),
            (101, 17, 1, 'ITM00002'),
            (102, 24, 1, 'ITM00003');

        INSERT INTO collectionItems(collectionID, itemID) VALUES
            (3, 100), (3, 101);
    """)
    con.commit()
    con.close()
    return db


@pytest.fixture
def svc(fake_db: Path) -> CollectionsService:
    creds = ApiCreds(library_id="12345", api_key="dummy")
    return CollectionsService(db_path=fake_db, creds=creds)


# ---- validate_plan tests ----

def test_validate_plan_clean(svc: CollectionsService) -> None:
    plan = [
        PlanNode(name="NewTopic", parent="ExistingParent", items=["ITM00001"]),
        PlanNode(name="TopLevelNew", items=[]),
    ]
    report = svc.validate_plan(plan)
    assert report.ok
    assert len(report.to_create) == 2
    assert report.conflicts == []
    assert report.unresolved_parents == []
    # Parent key should be resolved
    assert plan[0].parent_key == "PARENT01"
    assert plan[1].parent_key is None


def test_validate_plan_duplicate_name(svc: CollectionsService) -> None:
    plan = [PlanNode(name="ExistingParent", items=[])]
    report = svc.validate_plan(plan)
    assert not report.ok
    assert any("already exists" in c for c in report.conflicts)


def test_validate_plan_unresolved_parent(svc: CollectionsService) -> None:
    plan = [PlanNode(name="NewTopic", parent="DoesNotExist", items=[])]
    report = svc.validate_plan(plan)
    assert not report.ok
    assert "DoesNotExist" in report.unresolved_parents


def test_validate_plan_missing_item(svc: CollectionsService) -> None:
    plan = [PlanNode(name="NewTopic", items=["NOTEXIST"])]
    report = svc.validate_plan(plan)
    assert not report.ok
    assert any("NOTEXIST" in c for c in report.conflicts)


def test_validate_plan_empty_name(svc: CollectionsService) -> None:
    plan = [PlanNode(name="   ")]
    report = svc.validate_plan(plan)
    assert not report.ok
    assert any("Empty" in c for c in report.conflicts)


# ---- list / get tests ----

def test_list_all(svc: CollectionsService) -> None:
    cols = svc.list_all()
    names = {c.name for c in cols}
    assert "ExistingParent" in names
    assert "AnotherExisting" in names
    assert "SingleItem" in names


def test_list_tree(svc: CollectionsService) -> None:
    roots = svc.list_tree()
    # 2 top-level: ExistingParent (parent of AnotherExisting), SingleItem
    assert len(roots) == 2
    by_name = {r.name: r for r in roots}
    assert "ExistingParent" in by_name
    # ExistingParent has AnotherExisting as child
    children = by_name["ExistingParent"].children
    assert any(c.name == "AnotherExisting" for c in children)


def test_get_collection(svc: CollectionsService) -> None:
    c = svc.get("PARENT01")
    assert c.name == "ExistingParent"
    assert c.parent_key is None


def test_resolve_by_name(svc: CollectionsService) -> None:
    c = svc.resolve("SingleItem")
    assert c.key == "SINGLTM1"


def test_items_in_collection(svc: CollectionsService) -> None:
    keys = svc.items("SINGLTM1")
    assert set(keys) == {"ITM00001", "ITM00002"}


# ---- API adapter unit tests (no real network) ----

def test_zotero_api_requires_creds() -> None:
    from zop.adapters.zotero_api import ZoteroApi

    with pytest.raises(AuthError, match="library_id and api_key"):
        ZoteroApi(ApiCreds(library_id="", api_key=""))


def test_sentinel_distinguishes_no_change() -> None:
    """Ensure sentinel is not None/False, so 'no change' is distinct from 'set to None'."""
    assert _SENTINEL is not None
    assert _SENTINEL is not False


# ---- write paths: version handling (BUG-8) ----


async def test_delete_fetches_version_before_delete(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_collection.return_value = {"key": "K", "version": 5, "data": {"name": "n"}}
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    await svc.delete("K")

    # Collection PATCH/DELETE need If-Unmodified-Since-Version; the service
    # must fetch the current version first (mirroring ItemsService.delete).
    fake_api.get_collection.assert_awaited_once_with("K")
    fake_api.delete_collection.assert_awaited_once_with("K", version=5)


async def test_reparent_fetches_version_when_not_provided(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.get_collection.return_value = {
        "key": "KEY00001",
        "version": 5,
        "data": {"name": "n", "parentCollection": False},
    }
    fake_api.update_collection.return_value = {}  # 204 No Content
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    await svc.reparent("KEY00001", None)  # detach to top-level

    # get_collection called twice: once to read the version, once to re-read
    # the updated state (PATCH /collections/{key} returns no body — BUG-11).
    assert fake_api.get_collection.await_count == 2
    assert all(c.args == ("KEY00001",) for c in fake_api.get_collection.call_args_list)
    assert fake_api.update_collection.await_count == 1
    assert fake_api.update_collection.call_args.kwargs["version"] == 5


async def test_reparent_returns_updated_state_after_empty_patch(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-11: PATCH /collections/{key} returns 204 No Content → update_collection
    yields {}. reparent must NOT subscript the patch response; it re-reads the
    collection to build the result, so it returns a Collection instead of
    raising ``TypeError: 'NoneType' object is not subscriptable``.
    """
    fake_api.update_collection.return_value = {}  # real 204 behavior
    fake_api.get_collection.return_value = {
        "key": "KEY00001",
        "version": 6,
        "data": {"name": "ExistingParent", "parentCollection": "PARENT01"},
    }
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    # "ExistingParent" resolves locally to PARENT01; reparent KEY00001 under it.
    result = await svc.reparent("KEY00001", "ExistingParent")

    assert result.key == "KEY00001"
    assert result.parent_key == "PARENT01"
    assert result.version == 6


async def test_reparent_accepts_parent_key_directly(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1: reparent --parent must accept an 8-char KEY (like create), not just a NAME.
    Passing a KEY short-circuits name lookup — no list_collections scan. Regression
    for ``reparent <KEY> --parent <父KEY>`` failing with ``No collection named '<KEY>'``.
    """
    fake_api.update_collection.return_value = {}  # 204 No Content
    fake_api.get_collection.return_value = {
        "key": "KEY00001",
        "version": 6,
        "data": {"name": "child", "parentCollection": "PARENT01"},
    }
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    await svc.reparent("KEY00001", "PARENT01")  # an 8-char KEY, not a NAME

    # KEY path must not scan collection names via the API
    fake_api.list_collections.assert_not_awaited()
    # update_collection must receive the raw KEY as parent_key
    assert fake_api.update_collection.call_args.kwargs["parent_key"] == "PARENT01"


# ---- create: --parent accepts KEY + API fallback (BUG-7) ----


async def test_create_accepts_parent_key_directly(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.create_collections.return_value = [
        {
            "key": "CHILD001",
            "version": 1,
            "data": {"name": "child", "parentCollection": "PARENT01"},
        }
    ]
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    await svc.create("child", parent="PARENT01")  # an 8-char KEY

    payload = fake_api.create_collections.call_args.args[0][0]
    assert payload["parentCollection"] == "PARENT01"
    # KEY path must not scan local names or hit the API list endpoint.
    fake_api.list_collections.assert_not_awaited()


async def test_create_falls_back_to_api_for_unknown_name(
    fake_db: Path,
    creds: ApiCreds,
    fake_api: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_api.list_collections.return_value = [
        {"key": "APIKEY01", "data": {"name": "RemoteParent"}}
    ]
    fake_api.create_collections.return_value = [
        {
            "key": "CHILD001",
            "version": 1,
            "data": {"name": "child", "parentCollection": "APIKEY01"},
        }
    ]
    monkeypatch.setattr(CollectionsService, "_require_api", lambda self: fake_api)
    svc = CollectionsService(db_path=fake_db, creds=creds)

    await svc.create("child", parent="RemoteParent")  # not in local DB

    fake_api.list_collections.assert_awaited_once()
    payload = fake_api.create_collections.call_args.args[0][0]
    assert payload["parentCollection"] == "APIKEY01"
