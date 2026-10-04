from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3
from typing import Optional

from models import ApprovedQuoteSnapshot, QuoteDraft
from repositories.quote_repository import (
    SCHEMA_VERSION,
    DraftListItem,
    LoadedDraft,
    QuoteRepositoryError,
    SaveResult,
)
from repositories.sqlite import connect_sqlite, default_sqlite_path, ensure_columns, lifecycle_where, now_iso

DEFAULT_DB_NAME = "deep_trekker.sqlite3"


def content_hash(payload: dict, ui_state: dict) -> str:
    encoded = json.dumps({"payload": payload, "ui_state": ui_state}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SqliteQuoteRepository:
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
            CREATE TABLE IF NOT EXISTS quote_drafts (
                id INTEGER PRIMARY KEY,
                quote_draft_id TEXT NOT NULL,
                case_id TEXT,
                version INTEGER NOT NULL,
                status TEXT,
                customer_name TEXT,
                subject TEXT,
                configuration_name TEXT,
                payload_json TEXT NOT NULL,
                ui_state_json TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                archived_at TEXT,
                deleted_at TEXT,
                parent_quote_id TEXT,
                source_quote_id TEXT,
                relation_type TEXT,
                UNIQUE(quote_draft_id, version)
            );
            CREATE TABLE IF NOT EXISTS approved_quote_snapshots (
                id INTEGER PRIMARY KEY,
                approved_quote_snapshot_id TEXT NOT NULL UNIQUE,
                quote_draft_id TEXT NOT NULL,
                quote_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quote_drafts_updated
                ON quote_drafts(updated_at DESC);
            """
        )
        ensure_columns(
            self._connection,
            "quote_drafts",
            {
                "archived_at": "TEXT",
                "deleted_at": "TEXT",
                "parent_quote_id": "TEXT",
                "source_quote_id": "TEXT",
                "relation_type": "TEXT",
            },
        )
        self._connection.commit()

    def save_draft(self, draft: QuoteDraft, ui_state: Optional[dict] = None, *, force: bool = False) -> SaveResult:
        state = ui_state or {}
        payload = draft.model_dump(mode="json")
        digest = content_hash(payload, state)
        existing = self._connection.execute(
            """
            SELECT content_hash, created_at, updated_at
            FROM quote_drafts
            WHERE quote_draft_id = ? AND version = ?
            """,
            (draft.quote_draft_id, draft.quote_version),
        ).fetchone()
        if existing is not None and existing["content_hash"] == digest and not force:
            return SaveResult(saved=False, skipped=True, updated_at=existing["updated_at"], content_hash=digest)
        now = now_iso()
        created = existing["created_at"] if existing is not None else (draft.created_at.isoformat() if draft.created_at else now)
        try:
            self._connection.execute(
                """
                INSERT INTO quote_drafts (
                    quote_draft_id, case_id, version, status, customer_name, subject,
                    configuration_name, payload_json, ui_state_json, content_hash,
                    created_at, updated_at, schema_version,
                    archived_at, deleted_at, parent_quote_id, source_quote_id, relation_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(quote_draft_id, version) DO UPDATE SET
                    case_id = excluded.case_id,
                    status = excluded.status,
                    customer_name = excluded.customer_name,
                    subject = excluded.subject,
                    configuration_name = excluded.configuration_name,
                    payload_json = excluded.payload_json,
                    ui_state_json = excluded.ui_state_json,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at,
                    archived_at = excluded.archived_at,
                    deleted_at = excluded.deleted_at,
                    parent_quote_id = excluded.parent_quote_id,
                    source_quote_id = excluded.source_quote_id,
                    relation_type = excluded.relation_type
                """,
                (
                    draft.quote_draft_id,
                    draft.case_id,
                    draft.quote_version,
                    draft.status.value if draft.status else None,
                    draft.customer,
                    draft.title,
                    draft.configuration_name,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(state, ensure_ascii=False),
                    digest,
                    created,
                    now,
                    SCHEMA_VERSION,
                    draft.archived_at,
                    draft.deleted_at,
                    draft.parent_quote_id,
                    draft.source_quote_id,
                    draft.relation_type,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            raise QuoteRepositoryError(f"Failed to save quote draft: {error}") from error
        return SaveResult(saved=True, skipped=False, updated_at=now, content_hash=digest)

    def get_draft(self, quote_draft_id: str, version: Optional[int] = None) -> Optional[LoadedDraft]:
        if version is None:
            row = self._connection.execute(
                """
                SELECT payload_json, ui_state_json, updated_at, content_hash
                FROM quote_drafts
                WHERE quote_draft_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (quote_draft_id,),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT payload_json, ui_state_json, updated_at, content_hash
                FROM quote_drafts
                WHERE quote_draft_id = ? AND version = ?
                """,
                (quote_draft_id, version),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        ui_state = json.loads(row["ui_state_json"] or "{}")
        return LoadedDraft(
            draft=QuoteDraft.model_validate(payload),
            ui_state=ui_state,
            updated_at=row["updated_at"],
            content_hash=row["content_hash"],
        )

    def list_recent_drafts(self, limit: int = 8, *, view: str = "active") -> list[DraftListItem]:
        clause = lifecycle_where(view, completed_statuses=("APPROVED",))
        rows = self._connection.execute(
            f"""
            SELECT quote_draft_id, version, status, customer_name, subject,
                   configuration_name, updated_at, archived_at, deleted_at,
                   parent_quote_id, source_quote_id, relation_type
            FROM quote_drafts
            WHERE {clause}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            DraftListItem(
                quote_draft_id=row["quote_draft_id"],
                version=row["version"],
                status=row["status"],
                customer_name=row["customer_name"],
                subject=row["subject"],
                configuration_name=row["configuration_name"],
                updated_at=row["updated_at"],
                archived_at=row["archived_at"],
                deleted_at=row["deleted_at"],
                parent_quote_id=row["parent_quote_id"],
                source_quote_id=row["source_quote_id"],
                relation_type=row["relation_type"],
            )
            for row in rows
        ]

    def list_child_quotes(self, parent_quote_id: str) -> list[DraftListItem]:
        rows = self._connection.execute(
            """
            SELECT quote_draft_id, version, status, customer_name, subject,
                   configuration_name, updated_at, archived_at, deleted_at,
                   parent_quote_id, source_quote_id, relation_type
            FROM quote_drafts
            WHERE parent_quote_id = ? AND (deleted_at IS NULL OR deleted_at = '')
            ORDER BY updated_at DESC
            """,
            (parent_quote_id,),
        ).fetchall()
        return [
            DraftListItem(
                quote_draft_id=row["quote_draft_id"],
                version=row["version"],
                status=row["status"],
                customer_name=row["customer_name"],
                subject=row["subject"],
                configuration_name=row["configuration_name"],
                updated_at=row["updated_at"],
                archived_at=row["archived_at"],
                deleted_at=row["deleted_at"],
                parent_quote_id=row["parent_quote_id"],
                source_quote_id=row["source_quote_id"],
                relation_type=row["relation_type"],
            )
            for row in rows
        ]

    def save_snapshot(self, snapshot: ApprovedQuoteSnapshot) -> bool:
        existing = self._connection.execute(
            "SELECT approved_quote_snapshot_id FROM approved_quote_snapshots WHERE approved_quote_snapshot_id = ?",
            (snapshot.approved_quote_snapshot_id,),
        ).fetchone()
        if existing is not None:
            return False
        payload = snapshot.model_dump(mode="json")
        try:
            self._connection.execute(
                """
                INSERT INTO approved_quote_snapshots (
                    approved_quote_snapshot_id, quote_draft_id, quote_version,
                    payload_json, created_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.approved_quote_snapshot_id,
                    snapshot.quote_draft_id,
                    snapshot.quote_version,
                    json.dumps(payload, ensure_ascii=False),
                    snapshot.approved_at.isoformat() if snapshot.approved_at else now_iso(),
                    SCHEMA_VERSION,
                ),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            raise QuoteRepositoryError(f"Failed to save approved snapshot: {error}") from error
        return True

    def get_snapshot(self, approved_quote_snapshot_id: str) -> Optional[ApprovedQuoteSnapshot]:
        row = self._connection.execute(
            "SELECT payload_json FROM approved_quote_snapshots WHERE approved_quote_snapshot_id = ?",
            (approved_quote_snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        return ApprovedQuoteSnapshot.model_validate(json.loads(row["payload_json"]))

    def get_snapshot_for_draft(self, quote_draft_id: str, version: int) -> Optional[ApprovedQuoteSnapshot]:
        row = self._connection.execute(
            """
            SELECT payload_json FROM approved_quote_snapshots
            WHERE quote_draft_id = ? AND quote_version = ?
            """,
            (quote_draft_id, version),
        ).fetchone()
        if row is None:
            return None
        return ApprovedQuoteSnapshot.model_validate(json.loads(row["payload_json"]))
