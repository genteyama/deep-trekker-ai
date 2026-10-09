import json
import sqlite3

import pytest

from agents.activity_catalog import timeline_event_label
from agents.activity_log import record_case_business_lifecycle
from agents.technical_case_persistence import run_from_record
from agents.work_lifecycle import (
    CaseLifecycleError,
    archive_record,
    close_technical_case,
    derive_technical_case,
    duplicate_technical_case,
    reopen_technical_case,
    restore_record,
    soft_delete_record,
)
from models import (
    CaseCloseReason,
    CaseLifecycleStatus,
    CaseLineageType,
    TechnicalCaseRecord,
    TechnicalCaseStatus,
)
from repositories.actor import set_current_actor
from repositories.sqlite import table_columns
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from repositories.technical_case_repository import TechnicalCaseConflictError
from ui.technical_case_persistence import persist_technical_case


def _record(case_id="CASE-B1", status=TechnicalCaseStatus.WAITING_MANUFACTURER.value):
    return TechnicalCaseRecord(
        case_id=case_id,
        customer_name="Customer",
        case_title="Case",
        status=status,
        archived_at=None,
        deleted_at=None,
    )


def test_old_record_without_business_lifecycle_defaults_to_active():
    record = TechnicalCaseRecord.model_validate({"case_id": "OLD", "status": "COMPLETED"})

    assert record.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert record.close_reason is None
    assert record.closed_at is None


def test_close_and_reopen_preserve_workflow_archive_and_close_metadata():
    set_current_actor("owner@example.com")
    original = _record()

    closed = close_technical_case(
        original,
        reason=CaseCloseReason.LOST,
        memo="Customer selected another supplier",
        closed_at="2026-10-09T10:00:00+00:00",
    )
    reopened = reopen_technical_case(closed)

    assert closed.case_lifecycle_status == CaseLifecycleStatus.CLOSED
    assert closed.status == TechnicalCaseStatus.WAITING_MANUFACTURER.value
    assert closed.archived_at is None
    assert closed.deleted_at is None
    assert closed.close_reason == CaseCloseReason.LOST
    assert closed.closed_by == "owner@example.com"
    assert reopened.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert reopened.status == closed.status
    assert reopened.close_reason == CaseCloseReason.LOST
    assert reopened.closed_at == closed.closed_at
    assert reopened.closed_by == closed.closed_by
    assert reopened.close_memo == closed.close_memo
    set_current_actor(None)


def test_normal_save_after_reopen_preserves_close_metadata(tmp_path):
    repo = SqliteTechnicalCaseRepository(tmp_path / "cases.sqlite3")
    original = _record(status=TechnicalCaseStatus.WAITING_MANUFACTURER.value)
    repo.save_case(original)
    set_current_actor("owner@example.com")
    closed = close_technical_case(
        repo.get_case(original.case_id),
        reason=CaseCloseReason.LOST,
        memo="Customer selected another supplier",
        closed_at="2026-10-09T10:00:00+00:00",
    )
    repo.save_case(closed)
    reopened = reopen_technical_case(repo.get_case(original.case_id))
    repo.save_case(reopened)
    set_current_actor(None)

    session = {}
    saved = persist_technical_case(session, run_from_record(reopened), repository=repo)
    loaded = repo.get_case(original.case_id)

    assert saved is not None
    assert loaded.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert loaded.status == TechnicalCaseStatus.WAITING_MANUFACTURER.value
    assert loaded.close_reason == CaseCloseReason.LOST
    assert loaded.closed_at == "2026-10-09T10:00:00+00:00"
    assert loaded.closed_by == "owner@example.com"
    assert loaded.close_memo == "Customer selected another supplier"


def test_close_and_reopen_validation_fail_closed():
    record = _record()

    with pytest.raises(CaseLifecycleError, match="CLOSE_REASON_REQUIRED"):
        close_technical_case(record, reason=None)
    with pytest.raises(CaseLifecycleError, match="OTHER_MEMO_REQUIRED"):
        close_technical_case(record, reason=CaseCloseReason.OTHER, memo=" ")
    with pytest.raises(CaseLifecycleError, match="CASE_NOT_CLOSED"):
        reopen_technical_case(record)

    closed = close_technical_case(record, reason=CaseCloseReason.WON)
    with pytest.raises(CaseLifecycleError, match="CASE_ALREADY_CLOSED"):
        close_technical_case(closed, reason=CaseCloseReason.WON)


def test_duplicate_and_derived_closed_case_reset_business_lifecycle():
    closed = close_technical_case(_record(), reason=CaseCloseReason.CANCELLED, memo="Stopped")

    copies = [
        duplicate_technical_case(closed),
        derive_technical_case(closed, relation_type=CaseLineageType.FOLLOW_UP.value),
    ]

    for copied in copies:
        assert copied.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
        assert copied.close_reason is None
        assert copied.closed_at is None
        assert copied.closed_by is None
        assert copied.close_memo is None


def test_sqlite_migrates_old_table_and_old_row_to_active(tmp_path):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE technical_cases (
            id INTEGER PRIMARY KEY, case_id TEXT NOT NULL UNIQUE,
            customer_name TEXT, case_title TEXT, status TEXT, provider TEXT, model TEXT,
            payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        )
        """
    )
    payload = {"case_id": "OLD-ROW", "status": "DRAFT"}
    connection.execute(
        """
        INSERT INTO technical_cases (
            case_id, payload_json, created_at, updated_at, schema_version
        ) VALUES (?, ?, ?, ?, 1)
        """,
        ("OLD-ROW", json.dumps(payload), "2026-01-01", "2026-01-01"),
    )
    connection.commit()
    connection.close()

    repository = SqliteTechnicalCaseRepository(path)
    loaded = repository.get_case("OLD-ROW")

    assert {
        "case_lifecycle_status",
        "close_reason",
        "closed_at",
        "closed_by",
        "close_memo",
    }.issubset(table_columns(repository._connection, "technical_cases"))
    assert loaded.case_lifecycle_status == CaseLifecycleStatus.ACTIVE


def test_repository_roundtrip_filters_and_archive_trash_independence(tmp_path):
    repo = SqliteTechnicalCaseRepository(tmp_path / "cases.sqlite3")
    active = _record("ACTIVE")
    completed = _record("COMPLETE", TechnicalCaseStatus.COMPLETED.value)
    closed = close_technical_case(_record("CLOSED"), reason=CaseCloseReason.NO_RESPONSE)
    for record in (active, completed, closed):
        repo.save_case(record)

    assert {item.case_id for item in repo.list_recent_cases(view="in_progress")} == {"ACTIVE"}
    assert {item.case_id for item in repo.list_recent_cases(view="completed")} == {"COMPLETE"}
    closed_items = repo.list_recent_cases(view="closed")
    assert [item.case_id for item in closed_items] == ["CLOSED"]
    assert closed_items[0].close_reason == CaseCloseReason.NO_RESPONSE

    archived = archive_record(repo.get_case("CLOSED"))
    repo.save_case(archived)
    assert repo.list_recent_cases(view="closed") == []
    assert repo.list_recent_cases(view="archived")[0].case_lifecycle_status == CaseLifecycleStatus.CLOSED
    restored = restore_record(repo.get_case("CLOSED"))
    repo.save_case(restored)
    assert repo.list_recent_cases(view="closed")[0].case_id == "CLOSED"
    trashed = soft_delete_record(repo.get_case("CLOSED"))
    repo.save_case(trashed)
    assert repo.list_recent_cases(view="trash")[0].case_lifecycle_status == CaseLifecycleStatus.CLOSED
    repo.save_case(restore_record(repo.get_case("CLOSED")))
    assert repo.list_recent_cases(view="closed")[0].case_id == "CLOSED"


def test_close_uses_optimistic_lock_and_stale_writer_cannot_overwrite(tmp_path):
    path = tmp_path / "shared.sqlite3"
    first = SqliteTechnicalCaseRepository(path)
    second = SqliteTechnicalCaseRepository(path)
    first.save_case(_record())
    first_base = first.get_case("CASE-B1")
    stale = second.get_case("CASE-B1")
    first.save_case(close_technical_case(first_base, reason=CaseCloseReason.WON))

    with pytest.raises(TechnicalCaseConflictError):
        second.save_case(close_technical_case(stale, reason=CaseCloseReason.LOST))

    assert first.get_case("CASE-B1").close_reason == CaseCloseReason.WON


def test_close_reopen_activity_is_append_only_and_not_duplicated(tmp_path):
    activity = SqliteActivityRepository(tmp_path / "activity.sqlite3")
    original = _record()
    closed = close_technical_case(
        original,
        reason=CaseCloseReason.LOST,
        memo="Lost",
        closed_at="2026-10-09T10:00:00+00:00",
    )
    reopened = reopen_technical_case(closed)

    first_close = record_case_business_lifecycle(activity, closed, "close", previous=original)
    duplicate_close = record_case_business_lifecycle(activity, closed, "close", previous=original)
    first_reopen = record_case_business_lifecycle(activity, reopened, "reopen", previous=closed)
    duplicate_reopen = record_case_business_lifecycle(activity, reopened, "reopen", previous=closed)
    events = activity.list_events(entity_kind="case", entity_id=original.case_id)

    assert first_close.event_type == "CASE_CLOSED"
    assert duplicate_close is None
    assert first_reopen.event_type == "CASE_REOPENED"
    assert duplicate_reopen is None
    assert len(events) == 2
    assert first_close.payload["close_reason"] == "LOST"
    assert first_close.payload["previous_workflow_status"] == "WAITING_MANUFACTURER"
    assert first_reopen.payload["previous_closed_at"] == closed.closed_at
    assert timeline_event_label("CASE_CLOSED") == "案件終了"
    assert timeline_event_label("CASE_REOPENED") == "案件再開"


def test_postgres_schema_and_startup_migration_are_idempotent(monkeypatch, tmp_path):
    class FakePostgres:
        is_postgres = True

        def __init__(self):
            self.statements = []

        def execute(self, statement, params=None):
            self.statements.append(statement)

    fake = FakePostgres()
    monkeypatch.setattr(
        "repositories.sqlite_technical_case_repository.connect_sqlite",
        lambda _path: fake,
    )
    monkeypatch.setattr(
        "repositories.sqlite_technical_case_repository.is_postgres",
        lambda _connection: True,
    )

    SqliteTechnicalCaseRepository(tmp_path / "postgres-placeholder")
    SqliteTechnicalCaseRepository(tmp_path / "postgres-placeholder")
    schema = open("deploy/postgres_schema.sql", encoding="utf-8").read()

    assert len(fake.statements) == 10
    assert all("ADD COLUMN IF NOT EXISTS" in statement for statement in fake.statements)
    for column in (
        "case_lifecycle_status",
        "close_reason",
        "closed_at",
        "closed_by",
        "close_memo",
    ):
        assert column in schema
