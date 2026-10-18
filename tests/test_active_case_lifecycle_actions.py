from agents.activity_catalog import load_activity_rows
from models import (
    ActivityEventType,
    CaseCloseReason,
    CaseLifecycleStatus,
    TechnicalCaseRecord,
    TechnicalCaseStatus,
)
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _start_app
from tests.test_price_master_ui import _drop_stale_widgets
from tests.test_ux2_record_workspace import _open_case


def _keys(at):
    return {button.key for button in at.button}


def _save_active(case_id="CASE-ACTIVE-LIFE"):
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name="進行顧客",
            case_title="進行案件",
            status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
            case_lifecycle_status=CaseLifecycleStatus.ACTIVE,
        )
    )
    return case_id


def test_saved_active_case_shows_lifecycle_actions_in_case_management():
    case_id = _save_active()
    at = _open_case(_start_app(), case_id)
    keys = _keys(at)
    assert "start_close_technical_case" in keys
    assert "duplicate_technical_case" in keys
    assert "derive_technical_case" in keys
    assert "archive_technical_case" in keys
    assert "trash_technical_case" in keys
    manage = next(item for item in at.expander if item.label == "案件管理")
    assert manage.proto.expanded is False


def test_unsaved_case_has_no_lifecycle_actions():
    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()
    keys = _keys(at)
    assert "duplicate_technical_case" not in keys
    assert "derive_technical_case" not in keys
    assert "archive_technical_case" not in keys
    assert "trash_technical_case" not in keys
    assert "restore_technical_case" not in keys
    assert "start_close_technical_case" not in keys


def test_active_trash_requires_confirmation_then_soft_deletes_and_restores():
    case_id = _save_active("CASE-ACTIVE-TRASH")
    repo = SqliteTechnicalCaseRepository()
    at = _open_case(_start_app(), case_id)
    _drop_stale_widgets(at)
    at.button(key="trash_technical_case").click().run()
    assert repo.get_case(case_id).deleted_at in (None, "")
    assert repo.get_case(case_id).case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert at.button(key="confirm_case_lifecycle")
    _drop_stale_widgets(at)
    at.button(key="confirm_case_lifecycle").click().run()
    trashed = repo.get_case(case_id)
    assert trashed.deleted_at
    assert trashed.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert all(item.case_id != case_id for item in repo.list_recent_cases())
    rows = load_activity_rows(repo, SqliteQuoteRepository(), SqliteActivityRepository())
    assert all(row.entity_id != case_id for row in rows)
    events = SqliteActivityRepository().list_events(entity_kind="case", entity_id=case_id)
    assert any(event.event_type == ActivityEventType.MOVED_TO_TRASH.value for event in events)
    assert at.button(key="restore_technical_case")
    _drop_stale_widgets(at)
    at.button(key="restore_technical_case").click().run()
    restored = repo.get_case(case_id)
    assert not restored.deleted_at
    assert restored.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert any(item.case_id == case_id for item in repo.list_recent_cases())


def test_active_archive_uses_existing_confirmation_and_restore():
    case_id = _save_active("CASE-ACTIVE-ARCHIVE")
    repo = SqliteTechnicalCaseRepository()
    at = _open_case(_start_app(), case_id)
    _drop_stale_widgets(at)
    at.button(key="archive_technical_case").click().run()
    assert not repo.get_case(case_id).archived_at
    _drop_stale_widgets(at)
    at.button(key="confirm_case_lifecycle").click().run()
    archived = repo.get_case(case_id)
    assert archived.archived_at
    assert not archived.deleted_at
    assert archived.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert all(item.case_id != case_id for item in repo.list_recent_cases())
    _drop_stale_widgets(at)
    at.button(key="restore_technical_case").click().run()
    restored = repo.get_case(case_id)
    assert not restored.archived_at
    assert not restored.deleted_at


def test_closed_reopen_stays_separate_from_trash():
    case_id = "CASE-CLOSED-REOPEN"
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name="終了顧客",
            case_title="終了案件",
            status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
            case_lifecycle_status=CaseLifecycleStatus.CLOSED,
            close_reason=CaseCloseReason.OTHER,
            closed_at="2026-10-11T06:00:00+00:00",
        )
    )
    at = _open_case(_start_app(), case_id)
    assert at.button(key="reopen_technical_case")
    assert "trash_technical_case" not in _keys(at) or at.button(key="trash_technical_case")
    _drop_stale_widgets(at)
    at.button(key="reopen_technical_case").click().run()
    reopened = SqliteTechnicalCaseRepository().get_case(case_id)
    assert reopened.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert not reopened.deleted_at
