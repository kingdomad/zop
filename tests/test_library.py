"""Tests for library service (against in-memory SQLite)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from zop.services.library import LibraryService


@pytest.fixture
def fake_db(tmp_path: Path) -> Iterator[Path]:
    db = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INT,
            dateAdded TIMESTAMP,
            dateModified TIMESTAMP,
            libraryID INT,
            key TEXT
        );
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE itemAttachments (itemID INT, parentItemID INT, contentType TEXT, linkMode INT);
        CREATE TABLE itemTags (itemID INT, tagID INT);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, libraryID INT, key TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, orderIndex INT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);

        INSERT INTO itemTypes VALUES (17, 'journalArticle'), (14, 'note'), (1, 'attachment');
        INSERT INTO fields VALUES (1, 'title'), (22, 'DOI'), (12, 'date');

        INSERT INTO items VALUES
            (1, 17, '2024-01-01', '2024-01-01', 1, 'ITEM0001'),
            (2, 17, '2024-02-01', '2024-02-01', 1, 'ITEM0002'),
            (3, 14, '2024-03-01', '2024-03-01', 1, 'NOTE0001'),
            (4, 17, '2024-04-01', '2024-04-01', 1, 'DOI00001'),
            (5, 17, '2024-04-01', '2024-04-01', 1, 'DOI00002'),
            (100, 1, '2024-01-01', '2024-01-01', 1, 'ATTACH01');

        INSERT INTO itemAttachments VALUES (100, 1, 'application/pdf', 0);
        INSERT INTO itemTags VALUES (1, 1), (1, 2), (2, 1);
        INSERT INTO tags VALUES (1, 'cs.AI'), (2, 'to-read');
        INSERT INTO collections VALUES (1, 1, 'COLL0001');
    """)
    con.commit()
    con.close()
    return db


def test_stats(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    s = svc.stats()
    # Should exclude notes (type 14) and attachments (type 1)
    assert s["total_items"] == 4  # 5 items - 1 note
    assert s["pdf_attachments"] == 1
    assert s["top_tags"]["cs.AI"] == 2
    assert s["collections"] == 1


def test_recent(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    items = svc.recent(days=30, limit=10)
    # Should not include the note (type 14)
    assert all(it.key != "NOTE0001" for it in items)


def test_duplicates_by_doi(fake_db: Path) -> None:
    # Add DOI data (fieldID 22 already in fixture)
    con = sqlite3.connect(fake_db)
    con.executescript("""
        INSERT INTO itemDataValues VALUES (1, '10.1234/shared');
        INSERT INTO itemData VALUES (4, 22, 1);
        INSERT INTO itemDataValues VALUES (2, '10.1234/shared');
        INSERT INTO itemData VALUES (5, 22, 2);
    """)
    con.commit()
    con.close()
    svc = LibraryService(db_path=fake_db)
    dupes = svc.duplicates(by="doi")
    assert "10.1234/shared" in dupes
    assert set(dupes["10.1234/shared"]) == {"DOI00001", "DOI00002"}
