"""Integration tests for ``zop collection plan`` using a bundled plan JSON.

Loads ``tests/fixtures/test_plan.json`` and drives the full dry-run path end
to end: file parse -> PlanNode construction -> validate_plan against a real
SQLite schema -> JSON envelope -> exit code. The fixture deliberately mixes
valid entries with one unresolved parent so both branches are covered.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from zop.adapters.zotero_api import ApiCreds
from zop.services.collections import CollectionsService

# commands/__init__.py re-exports the `collection` group, which shadows the
# submodule, so fetch the real module object via importlib (same trick as
# test_cli_collection.py).
coll_mod = importlib.import_module("zop.commands.collection")

FIXTURE = Path(__file__).parent / "fixtures" / "test_plan.json"


@pytest.fixture
def schema_db(tmp_path: Path) -> Path:
    """Minimal Zotero schema: only what validate_plan's list_all() reads."""
    db = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript(
        """
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
        -- list_collections() runs a COUNT(*) sub-query against collectionItems,
        -- so the table must exist even when the plan references no items.
        CREATE TABLE collectionItems (
            collectionID INT NOT NULL,
            itemID INT NOT NULL,
            orderIndex INT DEFAULT 0,
            PRIMARY KEY (collectionID, itemID)
        );
        -- list_collections()'s item_count subquery JOINs itemTypes; the table
        -- must exist even though this fixture inserts no items.
        CREATE TABLE itemTypes (
            itemTypeID INTEGER PRIMARY KEY,
            typeName TEXT
        );
        INSERT INTO collections(collectionID, collectionName, parentCollectionID, libraryID, key)
        VALUES
            (1, 'ExistingParent', NULL, 1, 'PARENT01'),
            (2, 'AnotherExisting', 1, 1, 'ANOTHER1');
        """
    )
    con.commit()
    con.close()
    return db


def _real_service(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> CollectionsService:
    """Inject a real CollectionsService wired to the schema db (not a mock)."""
    svc = CollectionsService(
        db_path=db_path,
        creds=ApiCreds(library_id="12345", api_key="dummy"),
    )
    monkeypatch.setattr(coll_mod, "_service", lambda ctx: svc)
    monkeypatch.setattr(coll_mod, "_human", lambda: False)
    return svc


def test_plan_dry_run_reports_unresolved_parent(
    monkeypatch: pytest.MonkeyPatch,
    schema_db: Path,
) -> None:
    """The bundled fixture: 3 valid collections + 1 bad parent -> exit 2."""
    _real_service(monkeypatch, schema_db)

    result = CliRunner().invoke(coll_mod.plan_cmd, [str(FIXTURE), "--dry-run"])

    # BadTopic's parent "DoesNotExist" makes ok=False -> exit 2.
    assert result.exit_code == 2
    out = json.loads(result.output)
    # Two `ok`s: envelope.ok (emit-level, always True without an error) vs the
    # plan report's own ok nested in data. Report invalid -> data["ok"] False.
    assert out["data"]["ok"] is False
    created = {n["name"] for n in out["data"]["to_create"]}
    assert created == {"TestTopic1", "TestTopic2", "推荐系统"}
    assert "DoesNotExist" in out["data"]["unresolved_parents"]
    assert out["data"]["conflicts"] == []


def test_plan_requires_exactly_one_flag(
    monkeypatch: pytest.MonkeyPatch,
    schema_db: Path,
) -> None:
    """Passing neither --dry-run nor --execute is a usage error."""
    _real_service(monkeypatch, schema_db)

    result = CliRunner().invoke(coll_mod.plan_cmd, [str(FIXTURE)])

    assert result.exit_code == 2
    assert "exactly one" in result.output.lower()


def test_plan_dry_run_valid_plan_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    schema_db: Path,
    tmp_path: Path,
) -> None:
    """A conflict-free, fully-resolvable plan exits 0 on dry-run."""
    plan = tmp_path / "ok.json"
    plan.write_text(
        json.dumps(
            {"collections": [{"name": "BrandNew", "parent": "ExistingParent", "items": []}]}
        ),
        encoding="utf-8",
    )
    _real_service(monkeypatch, schema_db)

    result = CliRunner().invoke(coll_mod.plan_cmd, [str(plan), "--dry-run"])

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["data"]["ok"] is True
    assert out["data"]["to_create"][0]["name"] == "BrandNew"
