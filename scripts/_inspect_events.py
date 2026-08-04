import sqlite3
import json

con = sqlite3.connect(r"data/events.db")
cur = con.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("tables:", tables)
for t in tables:
    print(f"=== {t} ===")
    try:
        rows = cur.execute(f"SELECT * FROM {t}").fetchall()
    except Exception as e:
        print("err", e)
        continue
    for r in rows:
        print(r)
