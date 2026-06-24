import shutil
import sqlite3
import tempfile
from pathlib import Path

src = Path(r'D:\Program Data\zotero\zotero.sqlite')
# Copy to temp (avoid lock contention)
tmp = Path(tempfile.gettempdir()) / 'zop_zotero_snapshot.sqlite'
print(f"Copying {src} -> {tmp} ...")
shutil.copy2(src, tmp)
print("done")

con = sqlite3.connect(f'file:{tmp}?mode=ro', uri=True)

def q(sql, *args):
    return con.execute(sql, args).fetchall()

print("\n--- collections schema ---")
for r in q('PRAGMA table_info(collections)'):
    print(r)

print("\n--- items schema ---")
for r in q('PRAGMA table_info(items)'):
    print(r)

print("\n--- collectionItems schema ---")
for r in q('PRAGMA table_info(collectionItems)'):
    print(r)

print("\n--- sample collections ---")
for r in q('SELECT collectionID, collectionName, parentCollectionID, libraryID FROM collections LIMIT 5'):
    print(r)

print("\n--- collections count by libraryID ---")
for r in q('SELECT libraryID, COUNT(*) FROM collections GROUP BY libraryID'):
    print(r)

print("\n--- sample items ---")
for r in q('SELECT itemID, itemKey, itemTypeID, libraryID FROM items LIMIT 3'):
    print(r)

print("\n--- items with non-null key count ---")
for r in q('SELECT COUNT(*) FROM items WHERE itemKey IS NOT NULL'):
    print(r)

print("\n--- collectionItems count ---")
for r in q('SELECT COUNT(*) FROM collectionItems'):
    print(r)
