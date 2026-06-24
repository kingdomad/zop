import shutil
import sqlite3
from pathlib import Path
import tempfile

src = Path(r'D:\Program Data\zotero\zotero.sqlite')
tmp = Path(tempfile.gettempdir()) / 'zop_zotero_snapshot.sqlite'
shutil.copy2(src, tmp)

con = sqlite3.connect(f'file:{tmp}?mode=ro', uri=True)

def q(sql, *args):
    return con.execute(sql, args).fetchall()

print("--- All tables ---")
for r in q("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(r[0])