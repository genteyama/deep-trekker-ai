from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

from models import ManufacturerPriceSource
from repositories.actor import current_actor
from repositories.postgres import is_postgres
from repositories.quote_repository import CONFLICT_MESSAGE
from repositories.sqlite import connect_sqlite, default_sqlite_path, now_iso

SOURCE_DT40 = "DT40"
SOURCE_PT30 = "PT30"
SOURCE_SPECTRA_GOLD = "SPECTRA_GOLD"

SOURCE_DEFAULTS = {
    SOURCE_DT40: {
        "display_name": "DT40",
        "parser_profile": "DT40",
        "lifecycle_status": "ACTIVE",
    },
    SOURCE_PT30: {
        "display_name": "PT30",
        "parser_profile": "PT30",
        "lifecycle_status": "ACTIVE",
    },
    SOURCE_SPECTRA_GOLD: {
        "display_name": "SPECTRA GOLD",
        "parser_profile": "SPECTRA_GOLD_FUTURE",
        "lifecycle_status": "FUTURE",
    },
}

RECORD_COLUMNS = (
    "source_key, display_name, source_url, enabled, parser_profile, lifecycle_status, "
    "last_checked_at, last_check_status, last_error, created_at, updated_at, updated_by, row_version"
)


class ManufacturerPriceSourceRepositoryError(RuntimeError):
    pass


class ManufacturerPriceSourceConflictError(ManufacturerPriceSourceRepositoryError):
    def __init__(self, source_key: str, expected_row_version: int):
        super().__init__(CONFLICT_MESSAGE)
        self.source_key = source_key
        self.expected_row_version = expected_row_version


class ManufacturerPriceSourceRepository:
    """Shared source settings. PostgreSQL is used when DATABASE_URL is configured."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect_sqlite(self.path)
        self._initialize()

    @property
    def is_central(self) -> bool:
        return is_postgres(self._connection)

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        if self.is_central:
            return
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS manufacturer_price_sources (
                id INTEGER PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                parser_profile TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL,
                last_checked_at TEXT,
                last_check_status TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT,
                row_version INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        self._connection.commit()

    def get(self, source_key: str) -> Optional[ManufacturerPriceSource]:
        row = self._connection.execute(
            f"SELECT {RECORD_COLUMNS} FROM manufacturer_price_sources WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        return _to_record(row) if row is not None else None

    def list_sources(self) -> list[ManufacturerPriceSource]:
        rows = self._connection.execute(
            f"SELECT {RECORD_COLUMNS} FROM manufacturer_price_sources ORDER BY source_key"
        ).fetchall()
        return [_to_record(row) for row in rows]

    def save(
        self,
        source: ManufacturerPriceSource,
        *,
        expected_row_version: int,
    ) -> ManufacturerPriceSource:
        if source.source_key not in SOURCE_DEFAULTS:
            raise ManufacturerPriceSourceRepositoryError(f"Unknown source: {source.source_key}")
        now = now_iso()
        actor = current_actor()
        existing = self.get(source.source_key)
        try:
            if existing is None:
                if expected_row_version != 0:
                    raise ManufacturerPriceSourceConflictError(source.source_key, expected_row_version)
                defaults = SOURCE_DEFAULTS[source.source_key]
                self._connection.execute(
                    """
                    INSERT INTO manufacturer_price_sources (
                        source_key, display_name, source_url, enabled, parser_profile,
                        lifecycle_status, last_checked_at, last_check_status, last_error,
                        created_at, updated_at, updated_by, row_version
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, 1)
                    """,
                    (
                        source.source_key,
                        defaults["display_name"],
                        source.source_url.strip(),
                        int(source.enabled),
                        defaults["parser_profile"],
                        defaults["lifecycle_status"],
                        now,
                        now,
                        actor,
                    ),
                )
            else:
                cursor = self._connection.execute(
                    """
                    UPDATE manufacturer_price_sources SET
                        source_url = ?, enabled = ?, updated_at = ?, updated_by = ?,
                        row_version = row_version + 1
                    WHERE source_key = ? AND row_version = ?
                    """,
                    (
                        source.source_url.strip(),
                        int(source.enabled),
                        now,
                        actor,
                        source.source_key,
                        expected_row_version,
                    ),
                )
                if cursor.rowcount != 1:
                    self._connection.rollback()
                    raise ManufacturerPriceSourceConflictError(source.source_key, expected_row_version)
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            raise ManufacturerPriceSourceConflictError(source.source_key, expected_row_version) from error
        except sqlite3.Error as error:
            self._connection.rollback()
            raise ManufacturerPriceSourceRepositoryError(f"Failed to save source: {error}") from error
        return self.get(source.source_key)

    def record_check(
        self,
        source_key: str,
        *,
        status: str,
        error: Optional[str],
        expected_row_version: int,
    ) -> ManufacturerPriceSource:
        now = now_iso()
        actor = current_actor()
        try:
            cursor = self._connection.execute(
                """
                UPDATE manufacturer_price_sources SET
                    last_checked_at = ?, last_check_status = ?, last_error = ?,
                    updated_at = ?, updated_by = ?, row_version = row_version + 1
                WHERE source_key = ? AND row_version = ?
                """,
                (now, status, error, now, actor, source_key, expected_row_version),
            )
            if cursor.rowcount != 1:
                self._connection.rollback()
                raise ManufacturerPriceSourceConflictError(source_key, expected_row_version)
            self._connection.commit()
        except sqlite3.Error as error:
            self._connection.rollback()
            raise ManufacturerPriceSourceRepositoryError(f"Failed to record source check: {error}") from error
        return self.get(source_key)


def default_source(source_key: str, *, source_url: str = "", enabled: bool = False) -> ManufacturerPriceSource:
    values = SOURCE_DEFAULTS[source_key]
    return ManufacturerPriceSource(
        source_key=source_key,
        display_name=values["display_name"],
        source_url=source_url,
        enabled=enabled,
        parser_profile=values["parser_profile"],
        lifecycle_status=values["lifecycle_status"],
        row_version=0,
    )


def _to_record(row) -> ManufacturerPriceSource:
    return ManufacturerPriceSource(
        source_key=row["source_key"],
        display_name=row["display_name"],
        source_url=row["source_url"] or "",
        enabled=bool(row["enabled"]),
        parser_profile=row["parser_profile"],
        lifecycle_status=row["lifecycle_status"],
        last_checked_at=row["last_checked_at"],
        last_check_status=row["last_check_status"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
        row_version=row["row_version"],
    )
