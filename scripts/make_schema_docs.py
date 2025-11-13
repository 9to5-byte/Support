import csv, re
from pathlib import Path

# ---- point to your CSV that has 4 columns per row: schema, table, column, datatype
COLUMNS_CSV = Path("docs/SSMS/schema_tables_two.csv")
OUT_DIR = Path("docs/SSMS/by_table")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def sniff_delim(path: Path) -> str:
    sample = path.read_text(encoding="utf-8", errors="ignore")[:4096]
    for d in [",", ";", "\t", "|"]:
        if d in sample:
            return d
    return ","  # default

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())

def has_headers(fieldnames):
    """Detects typical header names; returns True if column names look like headers."""
    if not fieldnames: return False
    expected = {"table_schema","schema","table_name","table","column_name","column","data_type","type"}
    low = {f.lower() for f in fieldnames}
    return bool(low & expected)

def main():
    if not COLUMNS_CSV.exists():
        raise SystemExit(f"CSV not found: {COLUMNS_CSV}")

    delim = sniff_delim(COLUMNS_CSV)
    by_table = {}
    by_column = {}

    with open(COLUMNS_CSV, "r", encoding="utf-8", errors="ignore", newline="") as f:
        peek = f.read(4096)
        f.seek(0)

        # Try DictReader first
        dict_reader = csv.DictReader(f, delimiter=delim)
        use_dict = has_headers(dict_reader.fieldnames)

        f.seek(0)
        if use_dict:
            reader = csv.DictReader(f, delimiter=delim)
            for row in reader:
                schema = norm(row.get("TABLE_SCHEMA", "") or row.get("Schema", "") or row.get("schema",""))
                table  = norm(row.get("TABLE_NAME", "")  or row.get("Table", "")  or row.get("table",""))
                col    = norm(row.get("COLUMN_NAME", "") or row.get("Column", "") or row.get("column",""))
                dtype  = norm(row.get("DATA_TYPE", "")   or row.get("Datatype","") or row.get("type",""))
                if not table or not col:
                    continue
                fq = f"{schema}.{table}" if schema else table
                by_table.setdefault(fq, []).append((col, dtype))
                by_column.setdefault(col.upper(), set()).add(fq)
        else:
            # No headers → plain reader with positional columns: schema, table, column, datatype
            f.seek(0)
            reader = csv.reader(f, delimiter=delim)
            for row in reader:
                if not row or all(not c.strip() for c in row):
                    continue
                # tolerate extra/short rows
                schema = norm(row[0]) if len(row) > 0 else ""
                table  = norm(row[1]) if len(row) > 1 else ""
                col    = norm(row[2]) if len(row) > 2 else ""
                dtype  = norm(row[3]) if len(row) > 3 else ""
                if not table or not col:
                    continue
                fq = f"{schema}.{table}" if schema else table
                by_table.setdefault(fq, []).append((col, dtype))
                by_column.setdefault(col.upper(), set()).add(fq)

    # Write one markdown per table
    count = 0
    for fq, cols in by_table.items():
        cols_sorted = sorted(cols, key=lambda x: x[0].upper())
        lines = [f"# TABLE: {fq}", "", "| column | data_type |", "|---|---|"]
        lines += [f"| {c} | {t or ''} |" for c, t in cols_sorted]
        (OUT_DIR / f"{fq.replace('.','_')}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        count += 1

    # Write inverted map
    inv = Path("docs/SSMS/column_to_tables.txt")
    lines = [f"{col}: " + ", ".join(sorted(tables)) for col, tables in sorted(by_column.items())]
    inv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {count} table files to {OUT_DIR}")
    print(f"Wrote column map: {inv}")

if __name__ == "__main__":
    main()
