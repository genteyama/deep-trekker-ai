from agents.quote_approval import apply_ihi_photon_human_final_fixture
from agents.quote_builder import apply_final_price, apply_presentation_mode
from agents.quote_dates import apply_date_widget_defaults, date_widget_keys
from models import CustomerPresentationMode, FinalPriceStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository, content_hash
from tests.test_quote_approval import _approve, _ready_photon
from tests.test_quote_builder import _photon_draft
from ui.quote_format import display_yen
from ui.quote_persistence import apply_ui_state
from ui.quote_steps import SESSION_QUOTE_STEP, persist_review_key
from ui.warning_summary import summarize_draft_warnings


def _repo(tmp_path) -> SqliteQuoteRepository:
    return SqliteQuoteRepository(tmp_path / "quotes.sqlite3")


def test_display_yen_uses_integer_and_unset():
    assert display_yen(5040786.54, None) == "¥5,040,787"
    assert display_yen(4313501, None) == "¥4,313,501"
    assert display_yen(None, None) is None
    assert display_yen(None, "未設定") == "未設定"


def test_warning_summary_uses_japanese_buckets_without_changing_raw():
    draft = _photon_draft()
    summary = summarize_draft_warnings(draft)

    assert summary["count"] >= 1
    kinds = {kind for kind, _count in summary["lines"]}
    assert "final_price" in kinds
    assert any("Final sales price is not set" in item for item in summary["raw"])


def test_draft_roundtrip_keeps_human_final_and_totals(tmp_path):
    repo = _repo(tmp_path)
    draft = _photon_draft()
    apply_ihi_photon_human_final_fixture(draft)
    ui_state = {
        "step": 4,
        "confirm_configuration": True,
        "confirm_presentation": True,
        "confirm_sales_price": False,
        "confirm_remarks": False,
        "selected_remarks": list(draft.remarks),
        "auto_valid_until": False,
    }

    first = repo.save_draft(draft, ui_state)
    skipped = repo.save_draft(draft, ui_state)
    loaded = repo.get_draft(draft.quote_draft_id, draft.quote_version)

    assert first.saved is True
    assert skipped.skipped is True
    assert skipped.updated_at == first.updated_at
    assert loaded is not None
    assert loaded.draft.model_dump(mode="json") == draft.model_dump(mode="json")
    assert loaded.draft.issue_date == "2026-09-26"
    assert loaded.draft.valid_until == "2026-10-31"
    assert loaded.draft.total_jpy == 7876000
    assert abs(loaded.draft.economics_result.gross_margin_rate - 0.29598) < 0.00001
    assert loaded.ui_state["step"] == 4
    assert loaded.ui_state["confirm_configuration"] is True
    assert loaded.ui_state["selected_remarks"]


def test_sqlite_reopen_and_cleared_session_can_restore(tmp_path):
    path = tmp_path / "reopen.sqlite3"
    draft = _photon_draft()
    apply_final_price(draft, draft.configuration_lines[0].line_id, FinalPriceStatus.MANUAL_OVERRIDE, amount_jpy=3540000)
    apply_presentation_mode(draft, draft.configuration_lines[0].line_id, CustomerPresentationMode.SEPARATE_LINE)
    first = SqliteQuoteRepository(path)
    first.save_draft(draft, {"step": 2, "confirm_configuration": True})
    first.close()

    session = {}
    second = SqliteQuoteRepository(path)
    loaded = second.get_draft(draft.quote_draft_id)
    apply_ui_state(session, loaded.draft, loaded.ui_state, init_dates=apply_date_widget_defaults)

    assert loaded.draft.configuration_lines[0].final_sales_price_jpy == 3540000
    assert loaded.draft.configuration_lines[0].customer_presentation_status == CustomerPresentationMode.SEPARATE_LINE
    assert session[SESSION_QUOTE_STEP] == 2
    assert session[persist_review_key("confirm_configuration")] is True
    keys = date_widget_keys(loaded.draft.quote_draft_id)
    assert keys["issue"] in session
    assert "quote_draft" not in session


def test_approved_snapshot_is_insert_only_and_not_overwritten_by_draft(tmp_path):
    repo = _repo(tmp_path)
    draft = _ready_photon()
    _, snapshot = _approve(draft)
    original_id = snapshot.approved_quote_snapshot_id
    original_total = snapshot.total_jpy
    original_margin = snapshot.gross_margin_rate

    assert repo.save_snapshot(snapshot) is True
    assert repo.save_snapshot(snapshot) is False
    repo.save_draft(draft, {"step": 5})
    loaded_snapshot = repo.get_snapshot(snapshot.approved_quote_snapshot_id)
    loaded_again = repo.get_snapshot_for_draft(draft.quote_draft_id, draft.quote_version)

    assert loaded_snapshot.approved_quote_snapshot_id == original_id
    assert loaded_snapshot.total_jpy == 7876000 == original_total
    assert abs(loaded_snapshot.gross_margin_rate - 0.29598) < 0.00001
    assert loaded_snapshot.gross_margin_rate == original_margin
    assert loaded_again.issue_date == "2026-09-26"
    assert loaded_snapshot.model_dump(mode="json") == snapshot.model_dump(mode="json")


def test_content_hash_changes_only_when_payload_or_ui_changes():
    draft = _photon_draft()
    payload = draft.model_dump(mode="json")
    first = content_hash(payload, {"step": 1})
    same = content_hash(payload, {"step": 1})
    changed = content_hash(payload, {"step": 2})

    assert first == same
    assert first != changed
