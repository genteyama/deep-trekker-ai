from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
import tempfile
from typing import Optional

from models import PriceMasterImport, PriceMasterType
from repositories.postgres import is_postgres
from repositories.sqlite import connect_sqlite, default_sqlite_path, dumps_json, loads_json, now_iso

SCHEMA_VERSION = 1
PRICE_MASTER_DIRECTORY = "price_masters"
CENTRAL_CACHE_DIRECTORY = "deep_trekker_price_masters"
# file_bytes (PostgreSQL only) is excluded so listing the registry never transfers workbooks.
RECORD_COLUMNS = (
    "id, import_id, master_type, source_type, original_filename, stored_path, sha256, size_bytes, "
    "imported_at, active, validation_status, validation_summary_json, activated_at, deactivated_at, schema_version"
)


class PriceMasterRepositoryError(RuntimeError):
    pass


class SqlitePriceMasterRepository:
    """Registry of imported price master files. Rows are never deleted; one row per import."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect_sqlite(self.path)
        self._initialize()

    @property
    def is_central(self) -> bool:
        return is_postgres(self._connection)

    @property
    def storage_root(self) -> Path:
        if self.is_central:
            # PostgreSQL file_bytes is the Source of Truth; this is only a local parse cache.
            return Path(tempfile.gettempdir()) / CENTRAL_CACHE_DIRECTORY
        # Managed files live next to the database: runtime/price_masters in production.
        return self.path.parent / PRICE_MASTER_DIRECTORY

    def get_file_bytes(self, import_id: str) -> Optional[bytes]:
        if not self.is_central:
            return None
        row = self._connection.execute(
            "SELECT file_bytes FROM price_master_imports WHERE import_id = ?", (import_id,)
        ).fetchone()
        if row is None or row["file_bytes"] is None:
            return None
        return bytes(row["file_bytes"])

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        if is_postgres(self._connection):
            return
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS price_master_imports (
                id INTEGER PRIMARY KEY,
                import_id TEXT NOT NULL UNIQUE,
                master_type TEXT NOT NULL,
                source_type TEXT NOT NULL,
                original_filename TEXT,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER,
                imported_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                validation_status TEXT NOT NULL,
                validation_summary_json TEXT,
                activated_at TEXT,
                deactivated_at TEXT,
                schema_version INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_price_master_imports_active
                ON price_master_imports(master_type, active);
            CREATE INDEX IF NOT EXISTS idx_price_master_imports_sha
                ON price_master_imports(master_type, sha256);
            """
        )
        self._connection.commit()

    def add(self, record: PriceMasterImport) -> PriceMasterImport:
        if self.is_central:
            return self._add_central(record)
        try:
            self._connection.execute(
                """
                INSERT INTO price_master_imports (
                    import_id, master_type, source_type, original_filename, stored_path, sha256,
                    size_bytes, imported_at, active, validation_status, validation_summary_json,
                    activated_at, deactivated_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, ?)
                """,
                (
                    record.import_id,
                    record.master_type.value,
                    record.source_type.value,
                    record.original_filename,
                    record.stored_path,
                    record.sha256,
                    record.size_bytes,
                    record.imported_at,
                    record.validation_status.value,
                    dumps_json(record.validation_summary),
                    SCHEMA_VERSION,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            raise PriceMasterRepositoryError(f"Failed to register price master: {error}") from error
        return self.get(record.import_id)

    def _add_central(self, record: PriceMasterImport) -> PriceMasterImport:
        from agents.price_master import resolve_stored_path

        data = resolve_stored_path(self, record).read_bytes()
        if hashlib.sha256(data).hexdigest() != record.sha256:
            raise PriceMasterRepositoryError(f"SHA-256 mismatch for {record.import_id}")
        try:
            self._connection.execute(
                """
                INSERT INTO price_master_imports (
                    import_id, master_type, source_type, original_filename, stored_path, sha256,
                    size_bytes, imported_at, active, validation_status, validation_summary_json,
                    activated_at, deactivated_at, schema_version, file_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    record.import_id,
                    record.master_type.value,
                    record.source_type.value,
                    record.original_filename,
                    record.stored_path,
                    record.sha256,
                    record.size_bytes,
                    record.imported_at,
                    record.validation_status.value,
                    dumps_json(record.validation_summary),
                    SCHEMA_VERSION,
                    data,
                ),
            )
        except sqlite3.Error as error:
            raise PriceMasterRepositoryError(f"Failed to register price master: {error}") from error
        return self.get(import_id=record.import_id)

    def activate(self, import_id: str) -> PriceMasterImport:
        record = self.get(import_id)
        if record is None:
            raise PriceMasterRepositoryError(f"Unknown price master import: {import_id}")
        now = now_iso()
        try:
            with self._connection:
                self._connection.execute(
                    """
                    UPDATE price_master_imports SET active = 0, deactivated_at = ?
                    WHERE master_type = ? AND active = 1 AND import_id != ?
                    """,
                    (now, record.master_type.value, import_id),
                )
                self._connection.execute(
                    "UPDATE price_master_imports SET active = 1, activated_at = ?, deactivated_at = NULL WHERE import_id = ?",
                    (now, import_id),
                )
        except sqlite3.Error as error:
            raise PriceMasterRepositoryError(f"Failed to activate price master: {error}") from error
        return self.get(import_id)

    def get(self, import_id: str) -> Optional[PriceMasterImport]:
        row = self._connection.execute(
            f"SELECT {RECORD_COLUMNS} FROM price_master_imports WHERE import_id = ?", (import_id,)
        ).fetchone()
        return _to_record(row) if row is not None else None

    def get_active(self, master_type: PriceMasterType) -> Optional[PriceMasterImport]:
        row = self._connection.execute(
            f"""
            SELECT {RECORD_COLUMNS} FROM price_master_imports WHERE master_type = ? AND active = 1
            ORDER BY activated_at DESC, id DESC LIMIT 1
            """,
            (PriceMasterType(master_type).value,),
        ).fetchone()
        return _to_record(row) if row is not None else None

    def find_by_sha(self, master_type: PriceMasterType, sha256: str) -> Optional[PriceMasterImport]:
        row = self._connection.execute(
            f"SELECT {RECORD_COLUMNS} FROM price_master_imports WHERE master_type = ? AND sha256 = ? ORDER BY id DESC LIMIT 1",
            (PriceMasterType(master_type).value, sha256),
        ).fetchone()
        return _to_record(row) if row is not None else None

    def list_imports(self, master_type: Optional[PriceMasterType] = None) -> list[PriceMasterImport]:
        if master_type is None:
            rows = self._connection.execute(f"SELECT {RECORD_COLUMNS} FROM price_master_imports ORDER BY id DESC").fetchall()
        else:
            rows = self._connection.execute(
                f"SELECT {RECORD_COLUMNS} FROM price_master_imports WHERE master_type = ? ORDER BY id DESC",
                (PriceMasterType(master_type).value,),
            ).fetchall()
        return [_to_record(row) for row in rows]


def _to_record(row) -> PriceMasterImport:
    return PriceMasterImport(
        import_id=row["import_id"],
        master_type=row["master_type"],
        source_type=row["source_type"],
        original_filename=row["original_filename"],
        stored_path=row["stored_path"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        imported_at=row["imported_at"],
        active=bool(row["active"]),
        validation_status=row["validation_status"],
        validation_summary=loads_json(row["validation_summary_json"], {}),
        activated_at=row["activated_at"],
        deactivated_at=row["deactivated_at"],
    )
