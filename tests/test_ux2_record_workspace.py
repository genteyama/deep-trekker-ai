from models import CaseLifecycleStatus, QuoteDraft, TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite_quote_repository import SqliteQuoteRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _open_case_step, _start_app
from tests.test_price_master_ui import _drop_stale_widgets


def _visible(at) -> str:
    return " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
    )


def _header(at) -> str:
    for item in at.markdown:
        if "<div class='record-header'>" in item.value:
            return item.value
    return ""


def _open_case(at, case_id: str):
    at.button(key="sidebar_nav_technical").click().run()
    at.session_state["technical_case_saved_id"] = case_id
    _drop_stale_widgets(at)
    at.run()
    return at


def test_new_case_record_header_has_identity_without_provider_or_database_write():
    repo = SqliteTechnicalCaseRepository()
    before = len(repo.list_recent_cases(limit=50))
    at = _start_app()
    at.button(key="sidebar_nav_technical").click().run()
    header = _header(at)
    visible = _visible(at)

    assert "record-header" in header
    assert "案件名なし" in header
    assert "顧客なし" in header
    assert "End User" in header
    assert "現在：1. 受付" in header
    assert "進捗：" in header
    assert "要確認：" in header
    assert "AI Provider" not in header
    assert "Model" not in header
    assert "案件ID" in visible
    assert _visible(at).count("dt-step-card is-compact") == 7
    assert not any(
        (button.key or "").startswith("technical_case_step_") and (button.key or "")[-1].isdigit()
        for button in at.button
    )
    assert all(at.button(key=f"sidebar_technical_step_{step}") for step in range(1, 8))
    assert at.button(key="new_technical_case")
    assert at.button(key="save_technical_case")
    assert at.button(key="technical_case_step_next")
    recent = next(item for item in at.expander if item.label == "最近の案件")
    assert recent.proto.expanded is False
    _drop_stale_widgets(at)
    at.button(key="technical_case_step_next").click().run()
    assert len(repo.list_recent_cases(limit=50)) == before


def test_saved_case_rail_shows_context_and_step_four_work_panel():
    case_id = "UX2F-CASE"
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name="株式会社ABC",
            case_title="港湾設備ROV確認",
            end_user_name="○○港湾",
            requested_products=["PIPE TREKKER"],
            created_at="2026-10-11T06:00:00+00:00",
            updated_at="2026-10-11T06:00:00+00:00",
            status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
        )
    )
    at = _open_case(_start_app(), case_id)
    header = _header(at)
    visible = _visible(at)

    assert "株式会社ABC" in header
    assert "港湾設備ROV確認" in header
    assert "○○港湾" in header
    assert "現在：" in header
    assert "進捗：" in header
    assert "要確認：" in header
    assert "AI Provider" not in header
    assert case_id in visible
    assert "PIPE TREKKER" in visible
    assert "2026/10/11" in visible
    assert "関連見積：0件" in visible

    _open_case_step(at, 4)
    assert "4. メーカー確認" in _visible(at)
    _drop_stale_widgets(at)
    at.button(key="technical_case_step_prev").click().run()
    assert at.session_state["technical_case_step"] == 3
    _drop_stale_widgets(at)
    at.button(key="technical_case_step_next").click().run()
    assert at.session_state["technical_case_step"] == 4


def test_related_quotes_appear_once_in_the_rail():
    case_id = "UX2F-RELATED"
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name="関連顧客",
            case_title="関連案件",
            status=TechnicalCaseStatus.DRAFT.value,
        )
    )
    SqliteQuoteRepository().save_draft(
        QuoteDraft(
            quote_draft_id="UX2F-QUOTE",
            case_id=case_id,
            title="港湾見積",
            configuration_name="標準構成",
            quote_version=3,
        )
    )
    at = _open_case(_start_app(), case_id)
    assert _visible(at).count("港湾見積") == 1
    assert "v3" in _visible(at)
    _open_case_step(at, 7)
    assert _visible(at).count("港湾見積") == 1
    assert at.button(key="complete_technical_case")
    assert at.button(key="archive_technical_case")
    assert at.button(key="trash_technical_case")


def test_closed_case_reopens_and_archive_restores():
    case_id = "UX2F-CLOSED"
    SqliteTechnicalCaseRepository().save_case(
        TechnicalCaseRecord(
            case_id=case_id,
            customer_name="終了顧客",
            case_title="終了案件",
            status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
            case_lifecycle_status=CaseLifecycleStatus.CLOSED,
            closed_at="2026-10-11T06:00:00+00:00",
        )
    )
    at = _open_case(_start_app(), case_id)
    assert "案件終了済み" in _header(at)
    assert not any(button.key == "save_technical_case" for button in at.button)
    assert not any(button.key == "analyze_inquiry" for button in at.button)
    at.button(key="reopen_technical_case").click().run()
    assert SqliteTechnicalCaseRepository().get_case(case_id).case_lifecycle_status == CaseLifecycleStatus.ACTIVE

    _open_case_step(at, 7)
    _drop_stale_widgets(at)
    at.button(key="archive_technical_case").click().run()
    _drop_stale_widgets(at)
    at.button(key="confirm_case_lifecycle").click().run()
    archived = SqliteTechnicalCaseRepository().get_case(case_id)
    assert archived.archived_at
    assert "アーカイブ" in _header(at)
    _drop_stale_widgets(at)
    at.button(key="restore_technical_case").click().run()
    restored = SqliteTechnicalCaseRepository().get_case(case_id)
    assert not restored.archived_at
    assert not restored.deleted_at
    _drop_stale_widgets(at)
    at.button(key="trash_technical_case").click().run()
    _drop_stale_widgets(at)
    at.button(key="confirm_case_lifecycle").click().run()
    trashed = SqliteTechnicalCaseRepository().get_case(case_id)
    assert trashed.deleted_at
    assert "ゴミ箱" in _header(at)
    _drop_stale_widgets(at)
    at.button(key="restore_technical_case").click().run()
    assert not SqliteTechnicalCaseRepository().get_case(case_id).deleted_at
