# tools/dump_schema_cards.py
import os, json
import pyodbc
from collections import defaultdict

# --- adjust these two ---
CONN = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=YOURSERVER\\YOURINSTANCE;"   # or just YOURSERVER
    "Database=YOURDB;"
    "Trusted_Connection=yes;"
)
OUT_DIR = r"C:\support-agent\docs\schema\SQLSERVER"
# -------------------------

SQL = {
"tables": """
SELECT s.name AS schema_name, t.name AS table_name, t.object_id
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
ORDER BY s.name, t.name;
""",
"cols": """
SELECT t.object_id, c.column_id, c.name AS column_name, ty.name AS data_type,
       c.max_length, c.precision, c.scale, c.is_nullable,
       dc.definition AS default_def
FROM sys.columns c
JOIN sys.tables t   ON c.object_id = t.object_id
JOIN sys.types ty   ON c.user_type_id = ty.user_type_id
LEFT JOIN sys.default_constraints dc
  ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id;
""",
"pks": """
SELECT k.parent_object_id AS object_id, ic.column_id
FROM sys.key_constraints k
JOIN sys.index_columns ic
  ON ic.object_id = k.parent_object_id AND ic.index_id = k.unique_index_id
WHERE k.type = 'PK';
""",
"fks": """
SELECT fk.parent_object_id parent_id, fkc.parent_column_id parent_col,
       fk.referenced_object_id ref_id, fkc.referenced_column_id ref_col
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id;
""",
"checks": """
SELECT cc.parent_object_id AS object_id, cc.definition
FROM sys.check_constraints cc;
"""
}

cn = pyodbc.connect(CONN)
cur = cn.cursor()

tables = {}
for r in cur.execute(SQL["tables"]):
    tables[r.object_id] = (r.schema_name, r.table_name)

cols = defaultdict(list); pks = defaultdict(set); fks = defaultdict(list); checks = defaultdict(list)

for r in cur.execute(SQL["cols"]):
    cols[r.object_id].append(dict(
        _id=r.column_id, name=r.column_name, type=r.data_type,
        max_length=r.max_length, precision=r.precision, scale=r.scale,
        nullable=bool(r.is_nullable), default=r.default_def
    ))

for r in cur.execute(SQL["pks"]):
    pks[r.object_id].add(r.column_id)

for r in cur.execute(SQL["fks"]):
    fks[r.parent_id].append((r.parent_col, r.ref_id, r.ref_col))

for r in cur.execute(SQL["checks"]):
    checks[r.object_id].append(r.definition)

os.makedirs(OUT_DIR, exist_ok=True)

for obj_id, (schema, table) in tables.items():
    # columns
    c = sorted(cols[obj_id], key=lambda x: x["_id"])
    for col in c:
        col["pk"] = (col["_id"] in pks[obj_id])
        del col["_id"]
    # fks
    fk_list = []
    for parent_col_id, ref_id, ref_col_id in fks[obj_id]:
        ref_schema, ref_table = tables[ref_id]
        parent_col = next(x["name"] for x in cols[obj_id] if x["_id"] == parent_col_id)
        ref_col    = next(x["name"] for x in cols[ref_id] if x["_id"] == ref_col_id)
        fk_list.append({"from": parent_col, "to": f"{ref_schema}.{ref_table}({ref_col})"})

    card = {
        "table": f"{schema}.{table}",
        "columns": c,
        "fks": fk_list,
        "checks": checks[obj_id],
        "source": {"type":"catalog", "server":"YOURSERVER", "database":"YOURDB"}
    }

    path = os.path.join(OUT_DIR, f"{schema}.{table}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(tables)} schema cards to {OUT_DIR}")
