"""Tests for library service (against in-file SQLite)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from zop.adapters.sqlite_reader import SqliteReader
from zop.services.library import LibraryService


@pytest.fixture
def fake_db(tmp_path: Path) -> Iterator[Path]:
    """A SQLite file whose itemTypeID mapping deliberately differs from zop's
    old hardcoded assumption (``NOT IN (1, 14)`` assumes 1=attachment, 14=note).

    Here the mapping is ``1=annotation, 3=attachment, 14=document, 28=note`` —
    mirroring a real user library. This exposes BUG-1: ``NOT IN (1, 14)`` would
    wrongly drop the *document* (14, a legitimate type) while letting *note*
    (28) and *attachment* (3) through. Filtering must be by ``typeName``.
    """
    db = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INT,
            dateAdded TIMESTAMP,
            dateModified TIMESTAMP,
            libraryID INT,
            key TEXT,
            version INT DEFAULT 0
        );
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE itemAttachments (itemID INT, parentItemID INT, contentType TEXT, linkMode INT);
        CREATE TABLE itemTags (itemID INT, tagID INT);
        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, libraryID INT, key TEXT);
        CREATE TABLE collectionItems (collectionID INT, itemID INT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, orderIndex INT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);

        -- Deliberately non-standard itemTypeID mapping (exposes BUG-1).
        INSERT INTO itemTypes VALUES
            (1, 'annotation'),
            (3, 'attachment'),
            (14, 'document'),
            (17, 'journalArticle'),
            (28, 'note');
        INSERT INTO fields VALUES (1, 'title'), (22, 'DOI'), (12, 'date');

        INSERT INTO items (itemID, itemTypeID, dateAdded, dateModified, libraryID, key) VALUES
            (1, 17, datetime('now','-5 days'), datetime('now'), 1, 'JOURN001'),
            (2, 17, datetime('now','-4 days'), datetime('now'), 1, 'JOURN002'),
            (3, 14, datetime('now','-3 days'), datetime('now'), 1, 'DOCUM001'),
            (4, 28, datetime('now','-3 days'), datetime('now'), 1, 'NOTE0001'),
            (5, 3,  datetime('now','-3 days'), datetime('now'), 1, 'ATTAC001'),
            (6, 1,  datetime('now','-3 days'), datetime('now'), 1, 'ANNO0001'),
            (7, 17, datetime('now','-2 days'), datetime('now'), 1, 'DUPJK001'),
            (8, 17, datetime('now','-2 days'), datetime('now'), 1, 'DUPJK002'),
            (9, 3,  datetime('now','-2 days'), datetime('now'), 1, 'ATTAC002');

        INSERT INTO itemAttachments VALUES
            (5, 1, 'application/pdf', 0),
            (9, 2, 'application/pdf', 0);
        INSERT INTO itemTags VALUES (1, 1), (1, 2), (2, 1);
        INSERT INTO tags VALUES (1, 'cs.AI'), (2, 'to-read');
        INSERT INTO collections VALUES (1, 1, 'COLL0001');

        -- Titles (for duplicates by title + recent display).
        INSERT INTO itemDataValues VALUES (10, 'Paper One');
        INSERT INTO itemData VALUES (1, 1, 10);
        INSERT INTO itemDataValues VALUES (11, 'Paper Two');
        INSERT INTO itemData VALUES (2, 1, 11);
        INSERT INTO itemDataValues VALUES (12, 'Some Document');
        INSERT INTO itemData VALUES (3, 1, 12);
        INSERT INTO itemDataValues VALUES (13, 'Real Paper');
        INSERT INTO itemData VALUES (7, 1, 13), (8, 1, 13);
        INSERT INTO itemDataValues VALUES (14, 'Full Text PDF');
        INSERT INTO itemData VALUES (5, 1, 14), (9, 1, 14);

        -- DOIs (for duplicates by DOI).
        INSERT INTO itemDataValues VALUES (20, '10.1234/shared');
        INSERT INTO itemData VALUES (7, 22, 20), (8, 22, 20);

        -- Dates (for year parsing — BUG-3).
        INSERT INTO itemDataValues VALUES (30, '2024-05-01');
        INSERT INTO itemData VALUES (1, 12, 30);
        INSERT INTO itemDataValues VALUES (31, '2024-01-01 2024-01-01');
        INSERT INTO itemData VALUES (7, 12, 31);
    """)
    con.commit()
    con.close()
    return db


def test_stats_excludes_non_bibliographic_types(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    s = svc.stats()
    # 4 journalArticle + 1 document; note/attachment/annotation excluded.
    assert s["total_items"] == 5
    assert s["pdf_attachments"] == 2
    assert s["collections"] == 1
    assert s["top_tags"]["cs.AI"] == 2
    by_type = s["by_type"]
    assert "journalArticle" in by_type
    assert "document" in by_type  # must NOT be dropped (BUG-1)
    assert "note" not in by_type
    assert "attachment" not in by_type
    assert "annotation" not in by_type


def test_recent_keeps_document_drops_others(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    items = svc.recent(days=30, limit=50)
    keys = {it.key for it in items}
    assert "DOCUM001" in keys  # document survives (BUG-1)
    assert "JOURN001" in keys
    assert "NOTE0001" not in keys
    assert "ATTAC001" not in keys
    assert "ATTAC002" not in keys
    assert "ANNO0001" not in keys
    leaked = {it.item_type.value for it in items} & {"note", "attachment", "annotation"}
    assert not leaked
    # year must be parsed from the raw date string (BUG-3).
    journ = next(it for it in items if it.key == "JOURN001")
    assert journ.year == 2024


def test_duplicates_by_doi(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    dupes = svc.duplicates(by="doi")
    assert "10.1234/shared" in dupes
    assert set(dupes["10.1234/shared"]) == {"DUPJK001", "DUPJK002"}


def test_duplicates_by_title_excludes_attachment_placeholders(fake_db: Path) -> None:
    svc = LibraryService(db_path=fake_db)
    dupes = svc.duplicates(by="title")
    assert "Real Paper" in dupes
    assert set(dupes["Real Paper"]) == {"DUPJK001", "DUPJK002"}
    # Attachment placeholder titles shared by multiple PDFs must NOT be flagged (BUG-4).
    assert "Full Text PDF" not in dupes


def test_get_item_populates_year(fake_db: Path) -> None:
    # year must be populated on the full Item, not just summaries (BUG-3).
    reader = SqliteReader(fake_db)
    item = reader.get_item("JOURN001")
    assert item.year == 2024
