"""Copy the local v1 SQLite database and managed Price Master files into central PostgreSQL.

    python scripts/migrate_sqlite_to_postgres.py --dry-run
    python scripts/migrate_sqlite_to_postgres.py --apply

SQLite is opened read-only and never modified. Existing PostgreSQL rows are never overwritten
(INSERT ... ON CONFLICT DO NOTHING), so the script is safe to re-run. DATABASE_URL comes only
from the environment and is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = ROOT / "runtime" / "deep_trekker.sqlite3"
SCHEMA_FILE = ROOT / "deploy" / "postgres_schema.sql"

# Order keeps parents before children for readability; there are no foreign keys.
TABLES = (
    "customers",
    "technical_cases",
    "technical_case_response_revisions",
    "quote_drafts",
    "approved_quote_snapshots",
    "activity_events",
    "price_master_imports",
)


def open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def sqlite_rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    if table not in sqlite_tables(connection):
        return []
    return connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def resolve_master_file(storage_root: Path, stored_path: str) -> Path:
    relative = PurePosixPath(stored_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Invalid stored price master path: {stored_path}")
    return storage_root.joinpath(*relative.parts)


def load_master_bytes(storage_root: Path, row: sqlite3.Row) -> bytes:
    path = resolve_master_file(storage_root, row["stored_path"])
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != row["sha256"]:
        raise SystemExit(f"SHA-256 mismatch for {row['import_id']}: refusing to migrate")
    return data


def postgres_columns(pg, table: str) -> list[str]:
    rows = pg.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return [row[0] for row in rows]


def postgres_count(pg, table: str):
    try:
        return pg.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return None


def copy_table(pg, table: str, rows: list[sqlite3.Row], storage_root: Path) -> int:
    if not rows:
        return 0
    target = set(postgres_columns(pg, table))
    source = [name for name in rows[0].keys() if name in target]
    columns = list(source)
    if table == "price_master_imports":
        columns.append("file_bytes")
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    inserted = 0
    for row in rows:
        values = [row[name] for name in source]
        if table == "price_master_imports":
            values.append(load_master_bytes(storage_root, row))
        inserted += pg.execute(sql, values).rowcount
    # Keep BIGSERIAL ahead of the preserved SQLite ids.
    pg.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), GREATEST((SELECT COALESCE(MAX(id), 1) FROM {table}), 1))"
    )
    return inserted


def verify_central_masters(pg) -> list[str]:
    problems = []
    for import_id, sha256, data in pg.execute(
        "SELECT import_id, sha256, file_bytes FROM price_master_imports ORDER BY id"
    ).fetchall():
        if data is None or hashlib.sha256(bytes(data)).hexdigest() != sha256:
            problems.append(import_id)
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    args = parser.parse_args(argv)

    if not args.sqlite.is_file():
        print(f"SQLite not found: {args.sqlite}")
        return 1
    storage_root = args.sqlite.parent / "price_masters"
    source = open_sqlite_readonly(args.sqlite)
    rows = {table: sqlite_rows(source, table) for table in TABLES}

    for row in rows["price_master_imports"]:
        load_master_bytes(storage_root, row)
    print(f"Price Master files: {len(rows['price_master_imports'])} found, SHA-256 OK")

    url = os.environ.get("DATABASE_URL")
    pg = None
    if url:
        import psycopg

        pg = psycopg.connect(url, autocommit=False, prepare_threshold=None)
    elif args.apply:
        print("DATABASE_URL is not set: --apply refused")
        return 1

    inserted = {table: 0 for table in TABLES}
    if args.apply:
        with pg.transaction():
            pg.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
            for table in TABLES:
                inserted[table] = copy_table(pg, table, rows[table], storage_root)
        pg.commit()

    print(f"{'table':36} {'sqlite':>7} {'postgres':>9} {'inserted':>9}")
    mismatch = False
    for table in TABLES:
        central = postgres_count(pg, table) if pg is not None else None
        if pg is not None:
            pg.rollback()
        if args.apply and central is not None and central < len(rows[table]):
            mismatch = True
        print(f"{table:36} {len(rows[table]):>7} {central if central is not None else '-':>9} {inserted[table]:>9}")

    if args.apply:
        problems = verify_central_masters(pg)
        if problems:
            print(f"Central Price Master SHA-256 mismatch: {', '.join(problems)}")
            return 1
        print("Central Price Master SHA-256 OK")
    else:
        print("DRY RUN: nothing written" + ("" if pg is not None else " (DATABASE_URL not set; PostgreSQL not contacted)"))
    source.close()
    if pg is not None:
        pg.close()
    return 1 if mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
