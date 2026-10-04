from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional

from models import ManufacturerResponseRevision, TechnicalCaseRecord, TechnicalCaseStatus
from repositories.quote_repository import SaveResult
from repositories.sqlite import connect_sqlite, default_sqlite_path, dumps_json, loads_json, now_iso, strip_secrets
from repositories.technical_case_repository import (
    SCHEMA_VERSION,
    TechnicalCaseListItem,
    TechnicalCaseRepositoryError,
)


_STATUS_ORDER = (
    TechnicalCaseStatus.DRAFT.value,
    TechnicalCaseStatus.ANALYZED.value,
    TechnicalCaseStatus.QUESTIONS_REVIEW.value,
    TechnicalCaseStatus.WAITING_MANUFACTURER.value,
    TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value,
    TechnicalCaseStatus.RESPONSE_REVIEW.value,
    TechnicalCaseStatus.COMPLETED.value,
)


def _forward_status(current: Optional[str], proposed: str) -> str:
    if current == TechnicalCaseStatus.COMPLETED.value:
        return current
    try:
        return _STATUS_ORDER[max(_STATUS_ORDER.index(current or TechnicalCaseStatus.DRAFT.value), _STATUS_ORDER.index(proposed))]
    except ValueError:
        return proposed


class SqliteTechnicalCaseRepository:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect_sqlite(self.path)
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS technical_cases (
                id INTEGER PRIMARY KEY,
                case_id TEXT NOT NULL UNIQUE,
                customer_name TEXT,
                case_title TEXT,
                status TEXT,
                provider TEXT,
                model TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS technical_case_response_revisions (
                id INTEGER PRIMARY KEY,
                case_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                provider TEXT,
                model TEXT,
                analyzed_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                UNIQUE(case_id, revision)
            );
            CREATE INDEX IF NOT EXISTS idx_technical_cases_updated
                ON technical_cases(updated_at DESC);
            """
        )
        self._connection.commit()

    def save_case(self, record: TechnicalCaseRecord) -> SaveResult:
        now = now_iso()
        existing = self._connection.execute(
            "SELECT created_at FROM technical_cases WHERE case_id = ?",
            (record.case_id,),
        ).fetchone()
        created = existing["created_at"] if existing is not None else (record.created_at or now)
        updated = now
        payload = strip_secrets(record.model_dump(mode="json"))
        payload["created_at"] = created
        payload["updated_at"] = updated
        payload["schema_version"] = SCHEMA_VERSION
        try:
            self._connection.execute(
                """
                INSERT INTO technical_cases (
                    case_id, customer_name, case_title, status, provider, model,
                    payload_json, created_at, updated_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    customer_name = excluded.customer_name,
                    case_title = excluded.case_title,
                    status = excluded.status,
                    provider = excluded.provider,
                    model = excluded.model,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.case_id,
                    record.customer_name,
                    record.case_title,
                    record.status,
                    record.provider,
                    record.model,
                    dumps_json(payload),
                    created,
                    updated,
                    SCHEMA_VERSION,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            raise TechnicalCaseRepositoryError(f"Failed to save technical case: {error}") from error
        return SaveResult(saved=True, skipped=False, updated_at=updated)

    def get_case(self, case_id: str) -> Optional[TechnicalCaseRecord]:
        row = self._connection.execute(
            "SELECT payload_json FROM technical_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            return None
        payload = loads_json(row["payload_json"])
        record = TechnicalCaseRecord.model_validate(payload)
        revisions = self._load_revisions(case_id)
        if revisions:
            record = record.model_copy(update={"response_revisions": revisions})
        return record

    def list_recent_cases(self, limit: int = 8) -> list[TechnicalCaseListItem]:
        rows = self._connection.execute(
            """
            SELECT case_id, customer_name, case_title, status, provider, updated_at
            FROM technical_cases
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            TechnicalCaseListItem(
                case_id=row["case_id"],
                customer_name=row["customer_name"],
                case_title=row["case_title"],
                status=row["status"],
                provider=row["provider"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def update_case(self, record: TechnicalCaseRecord) -> SaveResult:
        return self.save_case(record)

    def save_analysis_snapshot(self, record: TechnicalCaseRecord) -> SaveResult:
        return self.save_case(record)

    def save_manufacturer_response_result(
        self,
        case_id: str,
        revision: ManufacturerResponseRevision,
        record: Optional[TechnicalCaseRecord] = None,
    ) -> TechnicalCaseRecord:
        current = record or self.get_case(case_id)
        if current is None:
            raise TechnicalCaseRepositoryError(f"Technical case not found: {case_id}")
        next_revision = (max((item.revision for item in current.response_revisions), default=0) + 1)
        stored = revision.model_copy(update={"revision": next_revision})
        payload = strip_secrets(stored.model_dump(mode="json"))
        try:
            self._connection.execute(
                """
                INSERT INTO technical_case_response_revisions (
                    case_id, revision, provider, model, analyzed_at, payload_json, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    stored.revision,
                    stored.provider,
                    stored.model,
                    stored.analyzed_at,
                    dumps_json(payload),
                    SCHEMA_VERSION,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            raise TechnicalCaseRepositoryError(f"Failed to save manufacturer response revision: {error}") from error
        updated = current.model_copy(
            update={
                "manufacturer_response_input": stored.original_response,
                "manufacturer_response_analysis": stored.analysis,
                "validated_matches": list(stored.validated_matches),
                "evidence_validation_result": list(stored.evidence_validation_result),
                "provider": stored.provider or current.provider,
                "model": stored.model or current.model,
                "response_revisions": list(current.response_revisions) + [stored],
                "status": _forward_status(
                    current.status,
                    TechnicalCaseStatus.MANUFACTURER_RESPONSE_RECEIVED.value,
                ),
            }
        )
        self.save_case(updated)
        loaded = self.get_case(case_id)
        if loaded is None:
            raise TechnicalCaseRepositoryError(f"Technical case missing after save: {case_id}")
        return loaded

    def _load_revisions(self, case_id: str) -> list[ManufacturerResponseRevision]:
        rows = self._connection.execute(
            """
            SELECT payload_json
            FROM technical_case_response_revisions
            WHERE case_id = ?
            ORDER BY revision ASC
            """,
            (case_id,),
        ).fetchall()
        return [ManufacturerResponseRevision.model_validate(loads_json(row["payload_json"])) for row in rows]
