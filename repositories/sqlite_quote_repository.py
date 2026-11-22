from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3
from typing import Optional

from models import ApprovedQuoteSnapshot, QuoteDraft
from repositories.actor import current_actor
from repositories.postgres import is_postgres
from repositories.quote_repository import (
    SCHEMA_VERSION,
    ConcurrentUpdateError,
    DraftListItem,
    LoadedDraft,
    DuplicateOfficialQuoteNumberError,
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
        self._row_versions: dict[tuple[str, int], int] = {}
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        if is_postgres(self._connection):
            return
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
                schema_version INTEGER NOT NULL,
                approved_by TEXT
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
                "created_by": "TEXT",
                "updated_by": "TEXT",
                "row_version": "INTEGER NOT NULL DEFAULT 1",
            },
        )
        ensure_columns(
            self._connection,
            "approved_quote_snapshots",
            {"approved_by": "TEXT", "official_quote_number": "TEXT"},
        )
        # One official quote number belongs to exactly one approved snapshot. Legacy rows stay NULL.
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_approved_quote_snapshots_official_number
                ON approved_quote_snapshots(official_quote_number)
                WHERE official_quote_number IS NOT NULL
            """
        )
        self._connection.commit()

    def save_draft(
        self,
        draft: QuoteDraft,
        ui_state: Optional[dict] = None,
        *,
        force: bool = False,
        expected_row_version: Optional[int] = None,
    ) -> SaveResult:
        state = ui_state or {}
        payload = draft.model_dump(mode="json")
        digest = content_hash(payload, state)
        key = (draft.quote_draft_id, draft.quote_version)
        existing = self._connection.execute(
            """
            SELECT content_hash, created_at, updated_at, row_version
            FROM quote_drafts
            WHERE quote_draft_id = ? AND version = ?
            """,
            key,
        ).fetchone()
        if existing is not None and existing["content_hash"] == digest and not force:
            return SaveResult(
                saved=False,
                skipped=True,
                updated_at=existing["updated_at"],
                content_hash=digest,
                row_version=existing["row_version"],
            )
        try:
            row_version = self._write_draft_row(draft, payload, state, digest, existing, expected_row_version)
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            # Another session inserted the same draft version first.
            self._connection.rollback()
            raise ConcurrentUpdateError(f"{draft.quote_draft_id}:v{draft.quote_version}", None) from error
        except ConcurrentUpdateError:
            self._connection.rollback()
            raise
        except sqlite3.Error as error:
            raise QuoteRepositoryError(f"Failed to save quote draft: {error}") from error
        self._row_versions[key] = row_version
        return SaveResult(
            saved=True, skipped=False, updated_at=self._last_written_at, content_hash=digest, row_version=row_version
        )

    def _write_draft_row(self, draft: QuoteDraft, payload: dict, state: dict, digest: str, existing, expected_row_version):
        """INSERT or optimistic-lock UPDATE of one draft row. Does not commit."""
        key = (draft.quote_draft_id, draft.quote_version)
        now = now_iso()
        self._last_written_at = now
        actor = current_actor()
        columns = (
            draft.case_id,
            draft.status.value if draft.status else None,
            draft.customer,
            draft.title,
            draft.configuration_name,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(state, ensure_ascii=False),
            digest,
            now,
            draft.archived_at,
            draft.deleted_at,
            draft.parent_quote_id,
            draft.source_quote_id,
            draft.relation_type,
        )
        if existing is None:
            created = draft.created_at.isoformat() if draft.created_at else now
            self._connection.execute(
                """
                INSERT INTO quote_drafts (
                    case_id, status, customer_name, subject,
                    configuration_name, payload_json, ui_state_json, content_hash,
                    updated_at, archived_at, deleted_at, parent_quote_id, source_quote_id, relation_type,
                    quote_draft_id, version, created_at, schema_version,
                    created_by, updated_by, row_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (*columns, *key, created, SCHEMA_VERSION, actor, actor),
            )
            return 1
        expected = expected_row_version
        if expected is None:
            expected = self._row_versions.get(key, existing["row_version"])
        # Optimistic lock: only the version this session loaded may be replaced.
        cursor = self._connection.execute(
            """
            UPDATE quote_drafts SET
                case_id = ?, status = ?, customer_name = ?, subject = ?,
                configuration_name = ?, payload_json = ?, ui_state_json = ?, content_hash = ?,
                updated_at = ?, archived_at = ?, deleted_at = ?, parent_quote_id = ?,
                source_quote_id = ?, relation_type = ?,
                updated_by = ?, row_version = row_version + 1
            WHERE quote_draft_id = ? AND version = ? AND row_version = ?
            """,
            (*columns, actor, *key, expected),
        )
        if cursor.rowcount != 1:
            raise ConcurrentUpdateError(f"{draft.quote_draft_id}:v{draft.quote_version}", expected)
        return expected + 1

    def forget_row_version(self, quote_draft_id: str, version: int) -> None:
        """Drop the loaded version so the next get_draft becomes the editing base (reload)."""
        self._row_versions.pop((quote_draft_id, version), None)

    def get_draft(self, quote_draft_id: str, version: Optional[int] = None) -> Optional[LoadedDraft]:
        if version is None:
            row = self._connection.execute(
                """
                SELECT payload_json, ui_state_json, updated_at, content_hash, version, row_version
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
                SELECT payload_json, ui_state_json, updated_at, content_hash, version, row_version
                FROM quote_drafts
                WHERE quote_draft_id = ? AND version = ?
                """,
                (quote_draft_id, version),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        ui_state = json.loads(row["ui_state_json"] or "{}")
        # The first load in this session is the base version for optimistic locking.
        self._row_versions.setdefault((quote_draft_id, row["version"]), row["row_version"])
        return LoadedDraft(
            draft=QuoteDraft.model_validate(payload),
            ui_state=ui_state,
            updated_at=row["updated_at"],
            content_hash=row["content_hash"],
            row_version=row["row_version"],
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
        try:
            self._insert_snapshot(snapshot)
            self._connection.commit()
        except sqlite3.IntegrityError as error:
            self._connection.rollback()
            if self.official_quote_number_in_use(snapshot.official_quote_number):
                raise DuplicateOfficialQuoteNumberError(snapshot.official_quote_number) from error
            raise QuoteRepositoryError(f"Failed to save approved snapshot: {error}") from error
        except sqlite3.Error as error:
            raise QuoteRepositoryError(f"Failed to save approved snapshot: {error}") from error
        return True

    def _insert_snapshot(self, snapshot: ApprovedQuoteSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        self._connection.execute(
            """
            INSERT INTO approved_quote_snapshots (
                approved_quote_snapshot_id, quote_draft_id, quote_version,
                payload_json, created_at, schema_version, approved_by, official_quote_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.approved_quote_snapshot_id,
                snapshot.quote_draft_id,
                snapshot.quote_version,
                json.dumps(payload, ensure_ascii=False),
                snapshot.approved_at.isoformat() if snapshot.approved_at else now_iso(),
                SCHEMA_VERSION,
                # The approver recorded in the snapshot itself, so the column and payload always agree.
                snapshot.approved_by if snapshot.approved_by is not None else current_actor(),
                _clean_number(snapshot.official_quote_number),
            ),
        )

    def official_quote_number_in_use(self, official_quote_number: Optional[str]) -> bool:
        number = _clean_number(official_quote_number)
        if number is None:
            return False
        row = self._connection.execute(
            "SELECT 1 FROM approved_quote_snapshots WHERE official_quote_number = ? LIMIT 1",
            (number,),
        ).fetchone()
        return row is not None

    def record_approval(
        self,
        draft: QuoteDraft,
        snapshot: ApprovedQuoteSnapshot,
        ui_state: Optional[dict] = None,
        *,
        expected_row_version: Optional[int] = None,
    ) -> SaveResult:
        """Persist one approval atomically: snapshot, approved draft row, and the explicit revision parent.

        The parent (relation_type REVISION, parent_quote_id) becomes SUPERSEDED only here, when the
        revision is approved. Nothing is inferred from case IDs or configuration names.
        """
        number = _clean_number(snapshot.official_quote_number)
        if number is None or _clean_number(draft.official_quote_number) != number:
            raise QuoteRepositoryError("An approved quote requires its official quote number.")
        if draft.status.value != "APPROVED" or snapshot.quote_draft_id != draft.quote_draft_id:
            raise QuoteRepositoryError("Only the approved draft of this snapshot can be recorded.")
        state = ui_state or {}
        payload = draft.model_dump(mode="json")
        digest = content_hash(payload, state)
        key = (draft.quote_draft_id, draft.quote_version)
        try:
            with self._connection:
                if self.official_quote_number_in_use(number):
                    raise DuplicateOfficialQuoteNumberError(number)
                existing = self._connection.execute(
                    """
                    SELECT content_hash, created_at, updated_at, row_version
                    FROM quote_drafts WHERE quote_draft_id = ? AND version = ?
                    """,
                    key,
                ).fetchone()
                self._insert_snapshot(snapshot)
                row_version = self._write_draft_row(draft, payload, state, digest, existing, expected_row_version)
                superseded = self._supersede_revision_parent(snapshot)
        except DuplicateOfficialQuoteNumberError:
            raise
        except ConcurrentUpdateError:
            raise
        except sqlite3.IntegrityError as error:
            if self.official_quote_number_in_use(number):
                raise DuplicateOfficialQuoteNumberError(number) from error
            raise QuoteRepositoryError(f"Failed to record approval: {error}") from error
        except sqlite3.Error as error:
            raise QuoteRepositoryError(f"Failed to record approval: {error}") from error
        self._row_versions[key] = row_version
        for parent_key, parent_version in superseded:
            self._row_versions[parent_key] = parent_version
        return SaveResult(
            saved=True, skipped=False, updated_at=self._last_written_at, content_hash=digest, row_version=row_version
        )

    def _supersede_revision_parent(self, snapshot: ApprovedQuoteSnapshot) -> list[tuple[tuple[str, int], int]]:
        if snapshot.relation_type != "REVISION" or not snapshot.parent_quote_id:
            return []
        now = now_iso()
        actor = current_actor()
        changed = []
        rows = self._connection.execute(
            """
            SELECT quote_draft_id, version, payload_json, ui_state_json, row_version
            FROM quote_drafts WHERE quote_draft_id = ? AND status = 'APPROVED'
            """,
            (snapshot.parent_quote_id,),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["status"] = "SUPERSEDED"
            state = json.loads(row["ui_state_json"] or "{}")
            cursor = self._connection.execute(
                """
                UPDATE quote_drafts SET status = 'SUPERSEDED', payload_json = ?, content_hash = ?,
                    updated_at = ?, updated_by = ?, row_version = row_version + 1
                WHERE quote_draft_id = ? AND version = ? AND row_version = ?
                """,
                (
                    json.dumps(payload, ensure_ascii=False),
                    content_hash(payload, state),
                    now,
                    actor,
                    row["quote_draft_id"],
                    row["version"],
                    row["row_version"],
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError(f"{row['quote_draft_id']}:v{row['version']}", row["row_version"])
            changed.append(((row["quote_draft_id"], row["version"]), row["row_version"] + 1))
            snapshots = self._connection.execute(
                """
                SELECT approved_quote_snapshot_id, payload_json FROM approved_quote_snapshots
                WHERE quote_draft_id = ? AND quote_version = ?
                """,
                (row["quote_draft_id"], row["version"]),
            ).fetchall()
            for item in snapshots:
                stored = json.loads(item["payload_json"])
                if stored.get("status") != "APPROVED":
                    continue
                # Only the lifecycle status changes; the approved content stays as it was.
                stored["status"] = "SUPERSEDED"
                self._connection.execute(
                    "UPDATE approved_quote_snapshots SET payload_json = ? WHERE approved_quote_snapshot_id = ?",
                    (json.dumps(stored, ensure_ascii=False), item["approved_quote_snapshot_id"]),
                )
        return changed

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


def _clean_number(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None
