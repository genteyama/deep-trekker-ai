"""PORTAL-3A: approver, official quote number and revision lineage are tracked in the DB."""

import json

import pytest

from agents.quote_approval import (
    QuoteApprovalStore,
    all_confirmations,
    approve_quote,
    create_revision_draft,
    register_approval,
)
from agents.quote_builder import apply_official_quote_number, apply_tax_rate
from agents.quote_export import (
    QuoteExportError,
    build_export_bundle,
    export_internal_calc_excel,
    export_moneyforward_csv,
    export_moneyforward_tsv,
    export_spaceone_quote_excel,
    export_spaceone_quote_pdf,
)
from agents.formal_quote_document import build_formal_quote_document
from agents.work_lifecycle import duplicate_quote
from models import QuoteDraftStatus, QuoteLineageType
from repositories.actor import LOCAL_ACTOR, acting_person, set_current_actor
from repositories.quote_repository import QuoteRepositoryError
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from tests.test_app_pages import _open_quote_step, _start_app
from tests.test_quote_approval import _ready_photon
from ui.quote_list import quote_list_rows


@pytest.fixture(autouse=True)
def reset_actor():
    set_current_actor(None)
    yield
    set_current_actor(None)


def _approve_and_record(draft, number, *, actor="a@example.com", repo=None, store=None):
    """Same order as the UI: approve a copy, persist atomically, then mirror into the session store."""
    set_current_actor(actor)
    repo = repo or SqliteQuoteRepository()
    if repo.get_draft(draft.quote_draft_id, draft.quote_version) is None:
        repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    approval, snapshot = approve_quote(
        candidate,
        approved_by=acting_person(),
        confirmations=all_confirmations(),
        warnings_acknowledged=["Margin note"],
        official_quote_number=number,
    )
    repo.record_approval(candidate, snapshot)
    if store is not None:
        register_approval(store, candidate, approval, snapshot)
    return candidate, snapshot


def _status(repo, draft_id, version):
    return repo.get_draft(draft_id, version).draft.status


def _fresh_repo():
    # A new repository instance reads only what is in the DB (no session / memory state).
    return SqliteQuoteRepository()


# ---- Approver / approval record -----------------------------------------------------------------


def test_logged_in_user_is_the_approver_everywhere():
    draft = _ready_photon()
    approved, snapshot = _approve_and_record(draft, "Q-1001", actor="alice@example.com")

    repo = _fresh_repo()
    stored_draft = repo.get_draft(approved.quote_draft_id, approved.quote_version).draft
    stored_snapshot = repo.get_snapshot_for_draft(approved.quote_draft_id, approved.quote_version)
    column = repo._connection.execute(
        "SELECT approved_by FROM approved_quote_snapshots WHERE approved_quote_snapshot_id = ?",
        (snapshot.approved_quote_snapshot_id,),
    ).fetchone()["approved_by"]

    assert stored_snapshot.approved_by == "alice@example.com"
    assert stored_draft.approved_by == "alice@example.com"
    assert column == "alice@example.com"
    assert "弦" not in {stored_snapshot.approved_by, stored_draft.approved_by, column}
    assert stored_snapshot.approved_at is not None
    assert stored_draft.approved_at == stored_snapshot.approved_at


def test_approval_confirmations_survive_reload():
    draft = _ready_photon()
    approved, _ = _approve_and_record(draft, "Q-1002")

    stored = _fresh_repo().get_snapshot_for_draft(approved.quote_draft_id, approved.quote_version)

    assert stored.approval_confirmations == all_confirmations()
    assert stored.warnings_acknowledged == ["Margin note"]
    assert stored.reviewed_by == "a@example.com"


def test_approved_quote_stays_locked_after_reload():
    draft = _ready_photon()
    approved, _ = _approve_and_record(draft, "Q-1003")
    loaded = _fresh_repo().get_draft(approved.quote_draft_id, approved.quote_version).draft

    assert loaded.status == QuoteDraftStatus.APPROVED
    with pytest.raises(ValueError, match="Approved drafts cannot be edited"):
        apply_tax_rate(loaded, 0.08)


def test_local_mode_without_login_uses_explicit_local_marker():
    set_current_actor(None)
    assert acting_person() == LOCAL_ACTOR


def test_approval_activity_records_approver_and_number():
    from agents.activity_log import record_quote_approved

    draft = _ready_photon()
    approved, snapshot = _approve_and_record(draft, "Q-1004", actor="bob@example.com")
    record_quote_approved(SqliteActivityRepository(), approved, snapshot)

    events = [
        item
        for item in SqliteActivityRepository().list_events(entity_kind="quote", entity_id=approved.quote_draft_id)
        if item.event_type == "QUOTE_APPROVED"
    ]
    assert len(events) == 1
    assert events[0].payload["approved_by"] == "bob@example.com"
    assert events[0].payload["official_quote_number"] == "Q-1004"


# ---- Official quote number ----------------------------------------------------------------------


def test_approval_without_official_number_is_recorded():
    # PORTAL-3B.1.3: the official number is issued later (MoneyForward); approval does not need it.
    draft = _ready_photon()
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(candidate, approved_by="a@example.com", confirmations=all_confirmations())
    repo.record_approval(candidate, snapshot)

    assert _status(_fresh_repo(), draft.quote_draft_id, draft.quote_version) == QuoteDraftStatus.APPROVED
    stored = _fresh_repo().get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
    assert stored.official_quote_number is None and stored.approved_by == "a@example.com"


def test_draft_and_snapshot_numbers_must_agree_to_record_an_approval():
    draft = _ready_photon()
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="a@example.com", confirmations=all_confirmations(), official_quote_number="Q-9001"
    )
    candidate.official_quote_number = None

    with pytest.raises(QuoteRepositoryError):
        repo.record_approval(candidate, snapshot)

    assert _status(_fresh_repo(), draft.quote_draft_id, draft.quote_version) != QuoteDraftStatus.APPROVED
    assert _fresh_repo().get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version) is None


def test_official_number_is_fixed_on_draft_and_snapshot_after_reload():
    draft = _ready_photon()
    approved, snapshot = _approve_and_record(draft, "  Q-2001  ")

    repo = _fresh_repo()
    assert snapshot.official_quote_number == "Q-2001"
    assert repo.get_draft(approved.quote_draft_id, approved.quote_version).draft.official_quote_number == "Q-2001"
    assert repo.get_snapshot_for_draft(approved.quote_draft_id, approved.quote_version).official_quote_number == "Q-2001"


def test_all_outputs_use_the_snapshot_number(tmp_path):
    _, snapshot = _approve_and_record(_ready_photon(), "Q-3001")

    assert build_export_bundle(snapshot).official_quote_number == "Q-3001"
    assert build_formal_quote_document(snapshot).quote_number == "Q-3001"
    pdf_bundle, pdf_path = export_spaceone_quote_pdf(snapshot, output_dir=tmp_path)
    xlsx_bundle, xlsx_path = export_spaceone_quote_excel(snapshot, output_dir=tmp_path)
    internal_bundle, _ = export_internal_calc_excel(snapshot, output_dir=tmp_path)
    tsv_bundle, _ = export_moneyforward_tsv(snapshot, output_dir=tmp_path)
    csv_bundle, _ = export_moneyforward_csv(snapshot, output_dir=tmp_path)
    numbers = {
        pdf_bundle.official_quote_number,
        xlsx_bundle.official_quote_number,
        internal_bundle.official_quote_number,
        tsv_bundle.official_quote_number,
        csv_bundle.official_quote_number,
    }
    assert numbers == {"Q-3001"}
    assert pdf_path.name.startswith("Q-3001")
    assert xlsx_path.name.startswith("Q-3001")


def test_outputs_cannot_replace_the_fixed_number(tmp_path):
    _, snapshot = _approve_and_record(_ready_photon(), "Q-3002")

    with pytest.raises(QuoteExportError):
        export_spaceone_quote_pdf(snapshot, output_dir=tmp_path, official_quote_number="OTHER-1")
    with pytest.raises(QuoteExportError):
        export_moneyforward_tsv(snapshot, output_dir=tmp_path, official_quote_number="OTHER-1")
    with pytest.raises(QuoteExportError):
        build_formal_quote_document(snapshot, official_quote_number="OTHER-1")
    # Repeating the same number is harmless.
    assert build_export_bundle(snapshot, official_quote_number="Q-3002").official_quote_number == "Q-3002"


def test_same_number_is_allowed_for_unrelated_quotes_and_changes_nothing_else():
    quote_a, _ = _approve_and_record(_ready_photon(), "Q-4001")
    other = duplicate_quote(_ready_photon())
    other.status = QuoteDraftStatus.READY_FOR_APPROVAL

    approved_other, _ = _approve_and_record(other, "Q-4001")

    repo = _fresh_repo()
    assert _status(repo, approved_other.quote_draft_id, 1) == QuoteDraftStatus.APPROVED
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.APPROVED
    assert repo.get_snapshot_for_draft(quote_a.quote_draft_id, 1).official_quote_number == "Q-4001"
    assert repo.get_snapshot_for_draft(approved_other.quote_draft_id, 1).official_quote_number == "Q-4001"


def test_db_has_no_unique_rule_on_official_number():
    _, first = _approve_and_record(_ready_photon(), "Q-4002")
    repo = SqliteQuoteRepository()
    clone = first.model_copy(update={"approved_quote_snapshot_id": "aqs-other-v1", "quote_draft_id": "other"})

    assert repo.save_snapshot(clone) is True
    indexes = [row[1] for row in repo._connection.execute("PRAGMA index_list(approved_quote_snapshots)").fetchall()]
    assert "uq_approved_quote_snapshots_official_number" not in indexes
    migration = open("deploy/migrations/20261122_quote_integrity.sql", encoding="utf-8").read()
    schema = open("deploy/postgres_schema.sql", encoding="utf-8").read()
    assert "UNIQUE INDEX" not in migration.upper().replace("NO UNIQUENESS", "")
    assert "uq_approved_quote_snapshots_official_number" not in schema


# ---- Revision lineage ---------------------------------------------------------------------------


def _ready_revision(snapshot, *, root=None, store=None):
    from tests.test_quote_approval import _confirm_remarks
    from agents.quote_approval import apply_ihi_photon_human_final_fixture

    revision = create_revision_draft(snapshot, store=store, root_quote_id=root)
    apply_ihi_photon_human_final_fixture(revision)
    _confirm_remarks(revision)
    SqliteQuoteRepository().save_draft(revision)
    return revision


def test_revision_supersedes_only_its_parent_and_only_when_approved():
    store = QuoteApprovalStore()
    quote_a, snapshot_a1 = _approve_and_record(_ready_photon(), "A-001", store=store)
    revision = _ready_revision(snapshot_a1, store=store)

    repo = _fresh_repo()
    stored_revision = repo.get_draft(revision.quote_draft_id, 2).draft
    assert stored_revision.parent_quote_id == quote_a.quote_draft_id
    assert stored_revision.relation_type == QuoteLineageType.REVISION.value
    assert stored_revision.quote_version == 2
    # Revision in progress: v1 is still the valid approved version.
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.APPROVED
    assert repo.get_snapshot_for_draft(quote_a.quote_draft_id, 1).status == QuoteDraftStatus.APPROVED

    # An unrelated general quote (same empty case / configuration) does not touch quote A.
    quote_b = duplicate_quote(_ready_photon())
    quote_b.status = QuoteDraftStatus.READY_FOR_APPROVAL
    _approve_and_record(quote_b, "B-001", store=store)
    repo = _fresh_repo()
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.APPROVED
    assert store.snapshots[snapshot_a1.approved_quote_snapshot_id].status == QuoteDraftStatus.APPROVED

    _, snapshot_a2 = _approve_and_record(revision, "A-001-R1", store=store)

    repo = _fresh_repo()
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.SUPERSEDED
    assert _status(repo, revision.quote_draft_id, 2) == QuoteDraftStatus.APPROVED
    old_snapshot = repo.get_snapshot_for_draft(quote_a.quote_draft_id, 1)
    assert old_snapshot.status == QuoteDraftStatus.SUPERSEDED
    # The superseded record keeps its approved content and number.
    assert old_snapshot.official_quote_number == "A-001"
    assert old_snapshot.total_jpy == snapshot_a1.total_jpy
    assert snapshot_a2.parent_quote_id == quote_a.quote_draft_id
    assert _status(repo, quote_b.quote_draft_id, 1) == QuoteDraftStatus.APPROVED
    assert store.snapshots[snapshot_a1.approved_quote_snapshot_id].status == QuoteDraftStatus.SUPERSEDED


def test_duplicate_and_derived_quotes_never_supersede_their_source():
    quote_a, _ = _approve_and_record(_ready_photon(), "C-001")
    copy = duplicate_quote(quote_a)
    copy.status = QuoteDraftStatus.READY_FOR_APPROVAL
    assert copy.parent_quote_id == quote_a.quote_draft_id
    assert copy.relation_type == QuoteLineageType.DUPLICATE.value

    _approve_and_record(copy, "C-002")

    assert _status(_fresh_repo(), quote_a.quote_draft_id, 1) == QuoteDraftStatus.APPROVED


def test_revision_of_a_revision_keeps_the_root_id_and_supersedes_v2_only():
    quote_a, snapshot_1 = _approve_and_record(_ready_photon(), "D-001")
    revision_2 = _ready_revision(snapshot_1)
    _, snapshot_2 = _approve_and_record(revision_2, "D-002")
    revision_3 = _ready_revision(snapshot_2, root=revision_2.source_quote_id)

    assert revision_3.quote_draft_id == f"{quote_a.quote_draft_id}-v3"
    assert revision_3.parent_quote_id == revision_2.quote_draft_id
    _approve_and_record(revision_3, "D-003")

    repo = _fresh_repo()
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.SUPERSEDED
    assert _status(repo, revision_2.quote_draft_id, 2) == QuoteDraftStatus.SUPERSEDED
    assert _status(repo, revision_3.quote_draft_id, 3) == QuoteDraftStatus.APPROVED


def test_quote_list_shows_number_version_and_status():
    store = QuoteApprovalStore()
    quote_a, snapshot = _approve_and_record(_ready_photon(), "E-001", store=store)
    revision = _ready_revision(snapshot, store=store)
    _approve_and_record(revision, "E-002", store=store)
    repo = _fresh_repo()

    rows = {(row["見積ID"], row["Version"]): row for row in quote_list_rows(repo.list_recent_drafts(limit=50), load_draft=repo.get_draft)}

    old = rows[(quote_a.quote_draft_id, 1)]
    new = rows[(revision.quote_draft_id, 2)]
    assert (old["正式見積番号"], old["_raw_status"]) == ("E-001", "SUPERSEDED")
    assert (new["正式見積番号"], new["_raw_status"]) == ("E-002", "APPROVED")
    assert "e-002" in new["_search"]


def test_snapshot_payload_and_column_agree_in_db():
    _, snapshot = _approve_and_record(_ready_photon(), "F-001", actor="carol@example.com")
    row = _fresh_repo()._connection.execute(
        "SELECT approved_by, official_quote_number, payload_json FROM approved_quote_snapshots WHERE approved_quote_snapshot_id = ?",
        (snapshot.approved_quote_snapshot_id,),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert (row["approved_by"], payload["approved_by"]) == ("carol@example.com", "carol@example.com")
    assert (row["official_quote_number"], payload["official_quote_number"]) == ("F-001", "F-001")


# ---- UI -----------------------------------------------------------------------------------------


def _ui_ready_at_step_four():
    draft = _ready_photon()
    SqliteQuoteRepository().save_draft(draft)
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    at.session_state["quote_draft"] = draft
    at.session_state["quote_workspace_step"] = 1
    at.run()
    _open_quote_step(at, 4)
    for key in ("confirm_configuration", "confirm_presentation", "confirm_sales_price", "confirm_remarks"):
        at.checkbox(key=key).set_value(True).run()
    at.button(key="check_quote_approval").click().run()
    return at, draft


def _number_inputs(at):
    return [item.key for item in at.text_input if "official_quote_number" in (item.key or "")]


def test_ui_approves_without_official_number_as_logged_in_user():
    at, draft = _ui_ready_at_step_four()
    at.session_state["auth_email"] = "dana@example.com"
    at.run()
    assert not at.exception
    # PORTAL-3B.1.3: no number input; approval is offered without a number.
    assert _number_inputs(at) == []
    assert any(item.value.startswith("正式見積番号：未発番") for item in at.caption)

    at.button(key="approve_quote_snapshot").click().run()

    assert not at.exception
    snapshot = SqliteQuoteRepository().get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)
    assert snapshot.official_quote_number is None
    assert snapshot.approved_by == "dana@example.com"
    assert at.session_state["quote_draft"].status == QuoteDraftStatus.APPROVED
    # Export step: no number or free "generated by" input; the number is shown as not issued.
    assert at.session_state["quote_workspace_step"] == 5
    assert not any(item.key in {"input_official_quote_number", "input_export_generated_by"} for item in at.text_input)
    assert _number_inputs(at) == []
    assert any(item.value == "正式見積番号：未発番" for item in at.markdown)


def test_ui_revision_keeps_the_parent_number_without_an_input():
    draft = _ready_photon()
    approved, snapshot = _approve_and_record(draft, "UI-R-01")
    at = _start_app()
    at.button(key="sidebar_nav_quote").click().run()
    at.session_state["quote_draft"] = approved
    at.session_state["approved_quote_snapshot"] = snapshot
    at.session_state["quote_workspace_step"] = 1
    at.run()
    _open_quote_step(at, 4)
    assert any(item.value == "正式見積番号：UI-R-01" for item in at.caption)
    at.button(key="create_quote_revision").click().run()
    revision = at.session_state["quote_draft"]
    assert revision.quote_version == 2
    assert revision.official_quote_number == "UI-R-01"

    _open_quote_step(at, 4)
    assert not at.exception
    assert _number_inputs(at) == []
    assert any(item.value == "正式見積番号：UI-R-01（前の版から引き継ぎ）" for item in at.caption)
    stored = SqliteQuoteRepository().get_draft(revision.quote_draft_id, 2).draft
    assert stored.official_quote_number == "UI-R-01"
    assert stored.status != QuoteDraftStatus.APPROVED


def test_conflicting_draft_update_rolls_back_the_whole_approval():
    from repositories.quote_repository import ConcurrentUpdateError

    draft = _ready_photon()
    repo = SqliteQuoteRepository()
    repo.save_draft(draft)
    candidate = draft.model_copy(deep=True)
    _, snapshot = approve_quote(
        candidate, approved_by="a@example.com", confirmations=all_confirmations(), official_quote_number="G-001"
    )

    with pytest.raises(ConcurrentUpdateError):
        repo.record_approval(candidate, snapshot, expected_row_version=99)

    fresh = _fresh_repo()
    assert fresh.get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version) is None
    assert fresh.get_draft(draft.quote_draft_id, draft.quote_version).draft.status != QuoteDraftStatus.APPROVED



# ---- Number rule: may repeat across revisions, fixed per approved version -------------------------


def test_revision_inherits_and_can_keep_the_same_number():
    store = QuoteApprovalStore()
    quote_a, snapshot_1 = _approve_and_record(_ready_photon(), "Q-001", store=store)
    revision = _ready_revision(snapshot_1, store=store)
    assert revision.official_quote_number == "Q-001"

    _, snapshot_2 = _approve_and_record(revision, revision.official_quote_number, store=store)

    repo = _fresh_repo()
    v1 = repo.get_snapshot_for_draft(quote_a.quote_draft_id, 1)
    v2 = repo.get_snapshot_for_draft(revision.quote_draft_id, 2)
    assert (v1.official_quote_number, v2.official_quote_number) == ("Q-001", "Q-001")
    assert (v1.status, v2.status) == (QuoteDraftStatus.SUPERSEDED, QuoteDraftStatus.APPROVED)
    assert (v1.quote_version, v2.quote_version) == (1, 2)
    assert v2.parent_quote_id == quote_a.quote_draft_id
    stored_revision = repo.get_draft(revision.quote_draft_id, 2).draft
    assert stored_revision.parent_quote_id == quote_a.quote_draft_id
    assert stored_revision.source_quote_id == quote_a.quote_draft_id
    assert stored_revision.relation_type == QuoteLineageType.REVISION.value


def test_revision_can_change_to_a_suffixed_number_before_approval(tmp_path):
    quote_a, snapshot_1 = _approve_and_record(_ready_photon(), "Q-001")
    revision = _ready_revision(snapshot_1)
    apply_official_quote_number(revision, " Q-001-02 ")
    SqliteQuoteRepository().save_draft(revision, force=True)

    _, snapshot_2 = _approve_and_record(revision, revision.official_quote_number)

    repo = _fresh_repo()
    v1 = repo.get_snapshot_for_draft(quote_a.quote_draft_id, 1)
    v2 = repo.get_snapshot_for_draft(revision.quote_draft_id, 2)
    assert (v1.official_quote_number, v2.official_quote_number) == ("Q-001", "Q-001-02")
    assert _status(repo, quote_a.quote_draft_id, 1) == QuoteDraftStatus.SUPERSEDED
    # Each approved version keeps its own stored number. (Formal PDF/Excel files are issued only from the
    # current APPROVED version — an existing rule; the superseded record still resolves its number.)
    assert build_formal_quote_document(v1).quote_number == "Q-001"
    assert build_formal_quote_document(v2).quote_number == "Q-001-02"
    assert export_spaceone_quote_pdf(v2, output_dir=tmp_path)[0].official_quote_number == "Q-001-02"
    assert export_spaceone_quote_excel(v2, output_dir=tmp_path)[0].official_quote_number == "Q-001-02"
    assert export_moneyforward_tsv(v1, output_dir=tmp_path)[0].official_quote_number == "Q-001"
    assert export_moneyforward_csv(v2, output_dir=tmp_path)[0].official_quote_number == "Q-001-02"


def test_number_cannot_change_after_approval():
    approved, snapshot = _approve_and_record(_ready_photon(), "Q-005")
    loaded = _fresh_repo().get_draft(approved.quote_draft_id, 1).draft

    with pytest.raises(ValueError, match="Approved drafts cannot be edited"):
        apply_official_quote_number(loaded, "Q-005-02")
    with pytest.raises(QuoteExportError):
        build_export_bundle(snapshot, official_quote_number="Q-005-02")
    with pytest.raises(Exception):
        snapshot.official_quote_number = "Q-005-02"  # frozen model
