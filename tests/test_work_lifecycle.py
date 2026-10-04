import sqlite3

from agents.technical_case_agent import run_technical_case_analysis
from agents.technical_case_persistence import build_record
from agents.work_lifecycle import (
    archive_quote,
    archive_record,
    derive_quote,
    derive_technical_case,
    duplicate_quote,
    duplicate_technical_case,
    restore_quote,
    restore_record,
    soft_delete_quote,
    soft_delete_record,
)
from llm.mock_provider import MockTechnicalCaseProvider
from models import CaseLineageType, QuoteDraftStatus, QuoteLineageType, TechnicalCaseStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft
from ui.home import _recent_work_items


def _case_repo(tmp_path) -> SqliteTechnicalCaseRepository:
    return SqliteTechnicalCaseRepository(tmp_path / "lifecycle.sqlite3")


def _quote_repo(tmp_path) -> SqliteQuoteRepository:
    return SqliteQuoteRepository(tmp_path / "lifecycle.sqlite3")


def _saved_case(repo):
    run = run_technical_case_analysis(
        "タンク肉厚測定",
        "IHI検査計測",
        "End User",
        "MAGで肉厚測定したい。",
        provider=MockTechnicalCaseProvider(),
    )
    record = build_record(run)
    repo.save_case(record)
    return repo.get_case(record.case_id)


def test_archive_hides_from_default_list(tmp_path):
    repo = _case_repo(tmp_path)
    record = _saved_case(repo)
    repo.save_case(archive_record(record))
    assert repo.list_recent_cases() == []
    archived = repo.list_recent_cases(view="archived")
    assert archived[0].case_id == record.case_id


def test_archive_restore(tmp_path):
    repo = _case_repo(tmp_path)
    record = _saved_case(repo)
    repo.save_case(archive_record(record))
    restored = restore_record(repo.get_case(record.case_id))
    repo.save_case(restored)
    assert repo.list_recent_cases()[0].case_id == record.case_id
    assert repo.get_case(record.case_id).archived_at is None


def test_soft_delete_and_trash_restore(tmp_path):
    repo = _case_repo(tmp_path)
    record = _saved_case(repo)
    repo.save_case(soft_delete_record(record))
    assert repo.list_recent_cases() == []
    assert repo.list_recent_cases(view="trash")[0].case_id == record.case_id
    repo.save_case(restore_record(repo.get_case(record.case_id)))
    assert repo.list_recent_cases()[0].case_id == record.case_id
    assert repo.get_case(record.case_id).deleted_at is None


def test_duplicate_case_gets_new_id_and_starts_draft(tmp_path):
    repo = _case_repo(tmp_path)
    original = _saved_case(repo)
    duplicate = duplicate_technical_case(original)
    repo.save_case(duplicate)
    assert duplicate.case_id != original.case_id
    assert duplicate.status == TechnicalCaseStatus.DRAFT.value
    assert duplicate.parent_case_id == original.case_id
    assert duplicate.relation_type == CaseLineageType.DUPLICATE.value
    assert duplicate.customer_name == original.customer_name
    assert duplicate.original_inquiry == original.original_inquiry
    assert duplicate.requirements == original.requirements
    assert duplicate.manufacturer_response_analysis is None
    assert duplicate.evidence_validation_result == []
    assert duplicate.approval_board is None
    assert duplicate.inquiry_success is False
    loaded_original = repo.get_case(original.case_id)
    assert loaded_original.status == original.status
    assert loaded_original.case_id == original.case_id


def test_duplicate_edit_does_not_affect_source(tmp_path):
    repo = _case_repo(tmp_path)
    original = _saved_case(repo)
    duplicate = duplicate_technical_case(original)
    duplicate.customer_name = "変更後顧客"
    duplicate.original_inquiry = "変更後問い合わせ"
    duplicate.requirements.append({"label": "mutated"})
    repo.save_case(duplicate)
    loaded = repo.get_case(original.case_id)
    assert loaded.customer_name == "IHI検査計測"
    assert loaded.original_inquiry == original.original_inquiry
    assert loaded.requirements == original.requirements


def test_derived_case_parent_link(tmp_path):
    repo = _case_repo(tmp_path)
    original = _saved_case(repo)
    derived = derive_technical_case(original, relation_type=CaseLineageType.FOLLOW_UP.value)
    repo.save_case(derived)
    loaded = repo.get_case(derived.case_id)
    assert loaded.parent_case_id == original.case_id
    assert loaded.relation_type == CaseLineageType.FOLLOW_UP.value
    children = repo.list_child_cases(original.case_id)
    assert children[0].case_id == derived.case_id


def test_quote_duplicate_starts_draft_and_source_stays_approved(tmp_path):
    repo = _quote_repo(tmp_path)
    draft = _ready_photon()
    approval, snapshot = _approve(draft)
    repo.save_draft(draft, {})
    assert repo.save_snapshot(snapshot) is True
    original_id = snapshot.approved_quote_snapshot_id
    original_total = snapshot.total_jpy
    duplicate = duplicate_quote(draft)
    repo.save_draft(duplicate, {})
    assert duplicate.quote_draft_id != draft.quote_draft_id
    assert duplicate.status == QuoteDraftStatus.DRAFT
    assert duplicate.parent_quote_id == draft.quote_draft_id
    assert duplicate.relation_type == QuoteLineageType.DUPLICATE.value
    loaded_source = repo.get_draft(draft.quote_draft_id, draft.quote_version).draft
    assert loaded_source.status == QuoteDraftStatus.APPROVED
    stored_snapshot = repo.get_snapshot(original_id)
    assert stored_snapshot.total_jpy == original_total
    assert stored_snapshot.approved_quote_snapshot_id == original_id
    assert approval.status == QuoteDraftStatus.APPROVED


def test_derived_quote_parent_link(tmp_path):
    repo = _quote_repo(tmp_path)
    draft = _photon_draft()
    repo.save_draft(draft, {})
    derived = derive_quote(draft, relation_type=QuoteLineageType.ADDITIONAL.value)
    repo.save_draft(derived, {})
    loaded = repo.get_draft(derived.quote_draft_id).draft
    assert loaded.parent_quote_id == draft.quote_draft_id
    assert loaded.source_quote_id == draft.quote_draft_id
    assert loaded.relation_type == QuoteLineageType.ADDITIONAL.value
    children = repo.list_child_quotes(draft.quote_draft_id)
    assert children[0].quote_draft_id == derived.quote_draft_id


def test_quote_duplicate_edit_does_not_affect_source_or_snapshot(tmp_path):
    repo = _quote_repo(tmp_path)
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    repo.save_draft(draft, {})
    repo.save_snapshot(snapshot)
    duplicate = duplicate_quote(draft)
    duplicate.customer = "変更後顧客"
    if duplicate.configuration_lines:
        duplicate.configuration_lines[0].quantity = 99
    repo.save_draft(duplicate, {})
    source = repo.get_draft(draft.quote_draft_id, draft.quote_version).draft
    assert source.customer == draft.customer
    assert source.configuration_lines[0].quantity == draft.configuration_lines[0].quantity
    stored = repo.get_snapshot(snapshot.approved_quote_snapshot_id)
    assert stored.total_jpy == snapshot.total_jpy
    assert repo.save_snapshot(stored) is False


def test_quote_archive_and_soft_delete(tmp_path):
    repo = _quote_repo(tmp_path)
    draft = _photon_draft()
    repo.save_draft(draft, {})
    repo.save_draft(archive_quote(draft), {})
    assert repo.list_recent_drafts() == []
    assert repo.list_recent_drafts(view="archived")[0].quote_draft_id == draft.quote_draft_id
    loaded = repo.get_draft(draft.quote_draft_id).draft
    repo.save_draft(restore_quote(loaded), {})
    repo.save_draft(soft_delete_quote(repo.get_draft(draft.quote_draft_id).draft), {})
    assert repo.list_recent_drafts() == []
    assert repo.list_recent_drafts(view="trash")[0].quote_draft_id == draft.quote_draft_id


def test_top_excludes_archived_and_deleted_by_default(tmp_path, monkeypatch):
    case_repo = _case_repo(tmp_path)
    quote_repo = _quote_repo(tmp_path)
    active = _saved_case(case_repo)
    archived = _saved_case(case_repo)
    case_repo.save_case(archive_record(archived))
    deleted = _saved_case(case_repo)
    case_repo.save_case(soft_delete_record(deleted))
    draft = _photon_draft()
    quote_repo.save_draft(draft, {})
    archived_quote = _photon_draft()
    archived_quote.quote_draft_id = "archived-quote"
    quote_repo.save_draft(archive_quote(archived_quote), {})
    monkeypatch.setattr("ui.home.get_technical_case_repository", lambda: case_repo)
    monkeypatch.setattr("ui.home.get_quote_repository", lambda: quote_repo)
    items = _recent_work_items("in_progress")
    ids = {item["id"] for item in items}
    assert active.case_id in ids
    assert archived.case_id not in ids
    assert deleted.case_id not in ids
    assert "archived-quote" not in ids
    archived_items = _recent_work_items("archived")
    assert {item["id"] for item in archived_items} >= {archived.case_id, "archived-quote"}


def test_legacy_sqlite_migrates_lifecycle_columns(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE technical_cases (
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
        )
        """
    )
    connection.execute(
        """
        INSERT INTO technical_cases (
            case_id, customer_name, case_title, status, provider, model,
            payload_json, created_at, updated_at, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "CASE-LEGACY001",
            "旧顧客",
            "旧案件",
            "DRAFT",
            None,
            None,
            '{"case_id":"CASE-LEGACY001","customer_name":"旧顧客","case_title":"旧案件","status":"DRAFT"}',
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            1,
        ),
    )
    connection.commit()
    connection.close()
    repo = SqliteTechnicalCaseRepository(path)
    loaded = repo.get_case("CASE-LEGACY001")
    assert loaded is not None
    assert loaded.archived_at is None
    assert loaded.deleted_at is None
    items = repo.list_recent_cases()
    assert items[0].case_id == "CASE-LEGACY001"
