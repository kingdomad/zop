"""Read-only SQLite reader for the local Zotero database.

Zotero holds an exclusive write lock on its DB while running. To avoid
contention, we copy the DB to a temp file at most once per process and read
from the snapshot. This avoids 'database is locked' errors when Zotero is
running in the background.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from zop.core.errors import NotFoundError, ValidationError
from zop.models.collection import Collection, CollectionTree
from zop.models.common import ItemType
from zop.models.item import Item, ItemSummary


class SqliteReader:
    """Read access to a Zotero SQLite database."""

    def __init__(self, db_path: Path | str, *, snapshot: bool = True) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise NotFoundError(f"Zotero database not found: {self.db_path}")
        self._snapshot_path: Path | None = None
        self._snapshot: bool = snapshot

    def _connect(self) -> sqlite3.Connection:
        target = self.db_path
        if self._snapshot:
            if self._snapshot_path is None:
                tmp = Path(tempfile.gettempdir()) / "zop_zotero_snapshot.sqlite"
                shutil.copy2(self.db_path, tmp)
                self._snapshot_path = tmp
            target = self._snapshot_path
        # Read-only URI mode
        return sqlite3.connect(f"file:{target}?mode=ro", uri=True)

    # ---- Collections ----

    def list_collections(self, library_id: int = 1) -> list[Collection]:
        """Return all collections as flat list (with item counts)."""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT c.key, c.collectionName, c.parentCollectionID,
                       c.version, c.synced, p.key AS parent_key,
                       (SELECT COUNT(*) FROM collectionItems ci
                          JOIN items i ON i.itemID = ci.itemID
                          WHERE ci.collectionID = c.collectionID
                            AND i.itemTypeID NOT IN (1, 14)) AS item_count
                FROM collections c
                LEFT JOIN collections p ON p.collectionID = c.parentCollectionID
                WHERE c.libraryID = ?
                ORDER BY c.collectionName
                """,
                (library_id,),
            ).fetchall()
        result: list[Collection] = []
        for key, name, _parent_id, version, synced, parent_key, count in rows:
            if not key:
                continue  # skip unsynced collections (no API key yet)
            result.append(
                Collection(
                    key=key,
                    name=name,
                    parent_key=parent_key,
                    version=version,
                    synced=bool(synced),
                    item_count=count,
                )
            )
        return result

    def build_tree(self, library_id: int = 1) -> list[CollectionTree]:
        """Return top-level collections with their children populated."""
        all_coll = self.list_collections(library_id)
        by_key: dict[str, CollectionTree] = {}
        for c in all_coll:
            by_key[c.key] = CollectionTree(
                key=c.key,
                name=c.name,
                parent_key=c.parent_key,
                item_count=c.item_count,
            )
        roots: list[CollectionTree] = []
        for c in all_coll:
            node = by_key[c.key]
            if c.parent_key and c.parent_key in by_key:
                by_key[c.parent_key].children.append(node)
            else:
                roots.append(node)
        return roots

    def get_collection(self, key: str, library_id: int = 1) -> Collection:
        """Fetch a single collection by key."""
        for c in self.list_collections(library_id):
            if c.key == key:
                return c
        raise NotFoundError(f"Collection '{key}' not found in local database")

    def list_collection_items(
        self, collection_key: str, library_id: int = 1
    ) -> list[ItemSummary]:
        """Return ItemSummary list for a collection.

        Title and date are joined via the `fields` / `itemData` tables.
        """
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT i.key, it.typeName, i.dateAdded, i.dateModified,
                       (SELECT GROUP_CONCAT(c.lastName || ', ' || c.firstName, '; ')
                          FROM itemCreators ic
                          JOIN creators c ON c.creatorID = ic.creatorID
                          WHERE ic.itemID = i.itemID
                          ORDER BY ic.orderIndex) AS creators,
                       (SELECT iv.value FROM itemData id
                          JOIN fields f ON f.fieldID = id.fieldID
                          JOIN itemDataValues iv ON iv.valueID = id.valueID
                          WHERE id.itemID = i.itemID AND f.fieldName = 'title' LIMIT 1) AS title,
                       (SELECT iv.value FROM itemData id
                          JOIN fields f ON f.fieldID = id.fieldID
                          JOIN itemDataValues iv ON iv.valueID = id.valueID
                          WHERE id.itemID = i.itemID AND f.fieldName = 'date' LIMIT 1) AS date
                FROM collections c
                JOIN collectionItems ci ON ci.collectionID = c.collectionID
                JOIN items i ON i.itemID = ci.itemID
                JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
                WHERE c.key = ? AND c.libraryID = ?
                ORDER BY i.dateAdded DESC
                """,
                (collection_key, library_id),
            ).fetchall()
        result: list[ItemSummary] = []
        for key, type_name, _date_added, _date_modified, creators, title, date in rows:
            if not key:
                continue
            result.append(
                ItemSummary(
                    key=key,
                    item_type=ItemType(type_name) if type_name else ItemType.UNKNOWN,
                    title=title or "",
                    creators=[c.strip() for c in (creators or "").split(";") if c.strip()],
                    date=date,
                )
            )
        return result

    # ---- Items ----

    def get_item(self, key: str, library_id: int = 1) -> Item:
        """Fetch a single item with full metadata."""
        with self._connect() as con:
            row = con.execute(
                """
                SELECT i.key, it.typeName, i.dateAdded, i.dateModified, i.version,
                       (SELECT GROUP_CONCAT(c.lastName || ', ' || c.firstName, '; ')
                          FROM itemCreators ic JOIN creators c ON c.creatorID = ic.creatorID
                          WHERE ic.itemID = i.itemID ORDER BY ic.orderIndex) AS creators,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='title' LIMIT 1) AS title,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='abstractNote' LIMIT 1) AS abstract,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='date' LIMIT 1) AS date,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='DOI' LIMIT 1) AS doi,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='url' LIMIT 1) AS url
                FROM items i
                JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
                WHERE i.key = ? AND i.libraryID = ?
                """,
                (key, library_id),
            ).fetchone()
            if not row:
                raise NotFoundError(f"Item '{key}' not found in local DB")
            (key_, type_name, date_added, date_modified, version,
             creators, title, abstract, date, doi, url) = row
            tags = self._item_tags(con, key_)
            colls = self._item_collections(con, key_)
        return Item(
            key=key_,
            item_type=ItemType(type_name) if type_name else ItemType.UNKNOWN,
            title=title or "",
            creators=[c.strip() for c in (creators or "").split(";") if c.strip()],
            abstract=abstract,
            doi=doi,
            url=url,
            tags=tags,
            collections=colls,
            version=version,
            date=date,
            date_added=str(date_added) if date_added else None,
            date_modified=str(date_modified) if date_modified else None,
        )

    def _item_tags(self, con: sqlite3.Connection, key: str) -> list[str]:
        rows = con.execute(
            """
            SELECT t.name FROM itemTags it
            JOIN tags t ON t.tagID = it.tagID
            JOIN items i ON i.itemID = it.itemID
            WHERE i.key = ?
            ORDER BY t.name
            """,
            (key,),
        ).fetchall()
        return [r[0] for r in rows]

    def _item_collections(self, con: sqlite3.Connection, key: str) -> list[str]:
        rows = con.execute(
            """
            SELECT c.key FROM collections c
            JOIN collectionItems ci ON ci.collectionID = c.collectionID
            JOIN items i ON i.itemID = ci.itemID
            WHERE i.key = ?
            """,
            (key,),
        ).fetchall()
        return [r[0] for r in rows]

    def search_items(
        self,
        query: str,
        *,
        limit: int = 50,
        library_id: int = 1,
    ) -> list[ItemSummary]:
        """LIKE-search across title, creators, abstract.

        SQLite FTS would be better but a single LIKE query is portable and
        fast enough for libraries < 100k items.
        """
        like = f"%{query}%"
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT i.key, it.typeName, i.dateAdded,
                       (SELECT GROUP_CONCAT(c.lastName || ', ' || c.firstName, '; ')
                          FROM itemCreators ic JOIN creators c ON c.creatorID=ic.creatorID
                          WHERE ic.itemID=i.itemID ORDER BY ic.orderIndex) AS creators,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='title' LIMIT 1) AS title,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='date' LIMIT 1) AS date
                FROM items i
                JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
                WHERE i.libraryID = ?
                  AND i.itemTypeID NOT IN (1, 14)  -- exclude attachments & notes
                  AND (
                    EXISTS (SELECT 1 FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                              JOIN itemDataValues iv ON iv.valueID=id.valueID
                              WHERE id.itemID=i.itemID AND f.fieldName='title' AND iv.value LIKE ?)
                    OR EXISTS (SELECT 1 FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                                 JOIN itemDataValues iv ON iv.valueID=id.valueID
                                 WHERE id.itemID=i.itemID AND f.fieldName='abstractNote' AND iv.value LIKE ?)
                    OR EXISTS (SELECT 1 FROM itemCreators ic JOIN creators c ON c.creatorID=ic.creatorID
                                 WHERE ic.itemID=i.itemID AND (c.lastName LIKE ? OR c.firstName LIKE ?))
                  )
                ORDER BY i.dateAdded DESC
                LIMIT ?
                """,
                (library_id, like, like, like, like, limit),
            ).fetchall()
        return [
            ItemSummary(
                key=r[0],
                item_type=ItemType(r[1]) if r[1] else ItemType.UNKNOWN,
                title=r[4] or "",
                creators=[c.strip() for c in (r[3] or "").split(";") if c.strip()],
                date=r[5],
            )
            for r in rows
            if r[0]
        ]

    def list_recent(self, days: int = 7, limit: int = 50, library_id: int = 1) -> list[ItemSummary]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT i.key, it.typeName, i.dateAdded,
                       (SELECT GROUP_CONCAT(c.lastName || ', ' || c.firstName, '; ')
                          FROM itemCreators ic JOIN creators c ON c.creatorID=ic.creatorID
                          WHERE ic.itemID=i.itemID ORDER BY ic.orderIndex) AS creators,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='title' LIMIT 1) AS title,
                       (SELECT iv.value FROM itemData id JOIN fields f ON f.fieldID=id.fieldID
                          JOIN itemDataValues iv ON iv.valueID=id.valueID
                          WHERE id.itemID=i.itemID AND f.fieldName='date' LIMIT 1) AS date
                FROM items i
                JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
                WHERE i.libraryID = ?
                  AND i.itemTypeID NOT IN (1, 14)
                  AND i.dateAdded >= datetime('now', ?)
                ORDER BY i.dateAdded DESC
                LIMIT ?
                """,
                (library_id, f"-{days} days", limit),
            ).fetchall()
        return [
            ItemSummary(
                key=r[0],
                item_type=ItemType(r[1]) if r[1] else ItemType.UNKNOWN,
                title=r[4] or "",
                creators=[c.strip() for c in (r[3] or "").split(";") if c.strip()],
                date=r[5],
            )
            for r in rows
            if r[0]
        ]

    def get_attachment_path(self, item_key: str, library_id: int = 1) -> Path | None:
        """Find the local file path of an item's primary PDF attachment.

        Returns None if no local PDF exists. Zotero stores files as
        ``<data_dir>/storage/<attachment_key>/<filename>``, where the
        attachment_key is the attachment item's own 8-char key.
        """
        with self._connect() as con:
            row = con.execute(
                """
                SELECT ia.path, att.key
                FROM itemAttachments ia
                JOIN items att ON att.itemID = ia.itemID
                JOIN items parent ON parent.itemID = ia.parentItemID
                WHERE parent.key = ?
                  AND att.libraryID = ?
                  AND ia.contentType = 'application/pdf'
                  AND ia.linkMode IN (0, 1)  -- imported file (with or without copy)
                ORDER BY ia.itemID LIMIT 1
                """,
                (item_key, library_id),
            ).fetchone()
        if not row or not row[0]:
            return None
        rel_path, att_key = row
        # Path is "storage:<filename>" — the actual location is
        # <data_dir>/storage/<attachment_key>/<filename>
        if rel_path.startswith("storage:"):
            filename = rel_path[len("storage:"):]
            return self.db_path.parent / "storage" / att_key / filename
        if rel_path.startswith("files/"):
            return self.db_path.parent / rel_path
        return None

    def get_library_stats(self, library_id: int = 1) -> dict[str, object]:
        """Return counts: total items, by type, top tags, collection count, etc."""
        with self._connect() as con:
            total = con.execute(
                "SELECT COUNT(*) FROM items WHERE libraryID=? AND itemTypeID NOT IN (1,14)",
                (library_id,),
            ).fetchone()[0]
            by_type_rows = con.execute(
                """
                SELECT it.typeName, COUNT(*) FROM items i
                JOIN itemTypes it ON it.itemTypeID = i.itemTypeID
                WHERE i.libraryID=? AND i.itemTypeID NOT IN (1,14)
                GROUP BY it.typeName ORDER BY 2 DESC
                """,
                (library_id,),
            ).fetchall()
            coll_count = con.execute(
                "SELECT COUNT(*) FROM collections WHERE libraryID=?", (library_id,)
            ).fetchone()[0]
            top_tags = con.execute(
                """
                SELECT t.name, COUNT(*) as cnt FROM itemTags it
                JOIN tags t ON t.tagID=it.tagID
                JOIN items i ON i.itemID=it.itemID
                WHERE i.libraryID=? GROUP BY t.name ORDER BY cnt DESC LIMIT 15
                """,
                (library_id,),
            ).fetchall()
            pdf_count = con.execute(
                """
                SELECT COUNT(*) FROM itemAttachments ia
                JOIN items i ON i.itemID = ia.itemID
                WHERE i.libraryID=? AND ia.contentType='application/pdf'
                """,
                (library_id,),
            ).fetchone()[0]
        return {
            "total_items": total,
            "by_type": dict(by_type_rows),
            "top_tags": dict(top_tags),
            "collections": coll_count,
            "pdf_attachments": pdf_count,
        }

    def get_item_notes(self, item_key: str, library_id: int = 1) -> list[dict[str, str]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT i.key, n.note, i.dateAdded, i.dateModified
                FROM itemNotes n
                JOIN items i ON i.itemID = n.itemID
                JOIN items parent ON parent.itemID = n.parentItemID
                WHERE parent.key = ? AND i.libraryID = ?
                ORDER BY i.dateAdded DESC
                """,
                (item_key, library_id),
            ).fetchall()
        return [{"key": r[0], "note": r[1] or "", "date_added": str(r[2]) if r[2] else "",
                 "date_modified": str(r[3]) if r[3] else ""} for r in rows if r[0]]

    def list_all_tags(self, library_id: int = 1) -> list[dict[str, int | str]]:
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT t.name, COUNT(*) AS cnt FROM itemTags it
                JOIN tags t ON t.tagID = it.tagID
                JOIN items i ON i.itemID = it.itemID
                WHERE i.libraryID = ?
                GROUP BY t.name ORDER BY cnt DESC, t.name ASC
                """,
                (library_id,),
            ).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows]

    def find_duplicates(
        self, *, by: str = "doi", library_id: int = 1
    ) -> dict[str, list[str]]:
        """Find potential duplicate items grouped by DOI (or title).

        Returns a dict of duplicate_key -> [item_keys].
        """
        if by == "doi":
            with self._connect() as con:
                rows = con.execute(
                    """
                    SELECT iv.value, GROUP_CONCAT(i.key)
                    FROM itemData id
                    JOIN fields f ON f.fieldID = id.fieldID
                    JOIN itemDataValues iv ON iv.valueID = id.valueID
                    JOIN items i ON i.itemID = id.itemID
                    WHERE f.fieldName = 'DOI' AND i.libraryID = ?
                      AND iv.value IS NOT NULL AND iv.value != ''
                    GROUP BY iv.value
                    HAVING COUNT(*) > 1
                    """,
                    (library_id,),
                ).fetchall()
            return {doi: keys.split(",") for doi, keys in rows if keys}
        if by == "title":
            with self._connect() as con:
                rows = con.execute(
                    """
                    SELECT iv.value, GROUP_CONCAT(i.key)
                    FROM itemData id
                    JOIN fields f ON f.fieldID = id.fieldID
                    JOIN itemDataValues iv ON iv.valueID = id.valueID
                    JOIN items i ON i.itemID = id.itemID
                    WHERE f.fieldName = 'title' AND i.libraryID = ?
                      AND iv.value IS NOT NULL AND iv.value != ''
                    GROUP BY iv.value
                    HAVING COUNT(*) > 1
                    """,
                    (library_id,),
                ).fetchall()
            return {title: keys.split(",") for title, keys in rows if keys}
        raise ValidationError(f"Unknown duplicate-by: {by}")
