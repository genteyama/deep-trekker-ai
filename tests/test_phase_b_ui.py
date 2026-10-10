from agents.activity_log import append_activity_event
from models import CaseCloseReason, CaseLifecycleStatus, TechnicalCaseRecord, TechnicalCaseStatus
from repositories.sqlite_activity_repository import SqliteActivityRepository
from repositories.sqlite_technical_case_repository import SqliteTechnicalCaseRepository
from tests.test_app_pages import _start_app
from ui.components.portal import format_portal_datetime
from ui.home import _user_progress
from ui.technical_case import _display_timestamp
from ui.technical_case_steps import build_technical_workflow
from ui.work_status import summarize_technical_case


def _texts(at):
    return " ".join(
        [item.value for item in at.text]
        + [item.value for item in at.markdown]
        + [item.value for item in at.caption]
        + [item.value for item in at.error]
        + [item.value for item in at.warning]
    )


def _save_case(case_id="CASE-UI"):
    record = TechnicalCaseRecord(
        case_id=case_id,
        customer_name="Quick Customer",
        case_title="Quick Case",
        status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
        original_inquiry="Question",
    )
    SqliteTechnicalCaseRepository().save_case(record)
    return record


def test_home_quick_view_is_deterministic_and_opens_case_without_ai():
    _save_case()
    append_activity_event(
        SqliteActivityRepository(),
        event_type="MANUFACTURER_RESPONSE_RECEIVED",
        entity_kind="case",
        entity_id="CASE-UI",
    )
    at = _start_app()

    at.button(key="home_quick_technical_CASE-UI").click().run()
    texts = _texts(at)

    loaded = SqliteTechnicalCaseRepository().get_case("CASE-UI")
    workflow = build_technical_workflow(summarize_technical_case(record=loaded))
    assert "案件ステータス" in texts
    assert "業務状態：進行中" in texts
    assert "現在Phase：メーカー回答待ち" in texts
    assert "現在の状況：メーカー回答待ち" in texts
    assert "次にやること：メーカー回答を待つ" in texts
    assert "最新更新内容：メーカー回答受領" in texts
    assert f"進捗：{workflow.completed} / 7" in texts
    assert f"要確認：{workflow.review_required}件" in texts
    assert format_portal_datetime(loaded.updated_at) in texts
    assert loaded.updated_at not in texts
    assert "+00:00" not in texts
    assert "T00:" not in texts

    at.button(key="quick_open_technical_CASE-UI").click().run()
    assert at.title[0].value == "営業・技術受付AI"
    assert at.session_state["technical_case_saved_id"] == "CASE-UI"


def test_close_form_validates_other_then_closes_and_reopens():
    _save_case()
    at = _start_app()
    at.button(key="home_resume_technical_CASE-UI").click().run()

    at.button(key="start_close_technical_case").click().run()
    at.selectbox(key="technical_case_close_reason").select(CaseCloseReason.OTHER).run()
    at.button(key="confirm_close_technical_case").click().run()
    assert "「その他」を選んだ場合はメモを入力してください。" in _texts(at)

    at.selectbox(key="technical_case_close_reason").select(CaseCloseReason.LOST).run()
    at.text_area(key="technical_case_close_memo").set_value("Lost to competitor").run()
    at.button(key="confirm_close_technical_case").click().run()

    texts = _texts(at)
    assert "案件終了済み" in texts
    assert "終了理由：失注" in texts
    assert "Lost to competitor" in texts
    assert not any(item.key == "analyze_inquiry" for item in at.button)
    assert not any(item.key == "save_technical_case" for item in at.button)
    closed = SqliteTechnicalCaseRepository().get_case("CASE-UI")
    assert closed.case_lifecycle_status == CaseLifecycleStatus.CLOSED
    assert closed.status == TechnicalCaseStatus.WAITING_MANUFACTURER.value
    events = SqliteActivityRepository().list_events(entity_kind="case", entity_id="CASE-UI")
    assert [item.event_type for item in events].count("CASE_CLOSED") == 1

    at.button(key="reopen_technical_case").click().run()
    reopened = SqliteTechnicalCaseRepository().get_case("CASE-UI")
    assert reopened.case_lifecycle_status == CaseLifecycleStatus.ACTIVE
    assert reopened.status == TechnicalCaseStatus.WAITING_MANUFACTURER.value
    assert reopened.close_reason == CaseCloseReason.LOST
    assert any(item.key == "save_technical_case" for item in at.button)
    events = SqliteActivityRepository().list_events(entity_kind="case", entity_id="CASE-UI")
    assert [item.event_type for item in events].count("CASE_REOPENED") == 1


def test_closed_filter_separates_completed_and_closed_cases():
    repository = SqliteTechnicalCaseRepository()
    repository.save_case(
        TechnicalCaseRecord(
            case_id="COMPLETE-UI",
            case_title="Workflow Complete",
            status=TechnicalCaseStatus.COMPLETED.value,
        )
    )
    closed = TechnicalCaseRecord(
        case_id="CLOSED-UI",
        case_title="Business Closed",
        status=TechnicalCaseStatus.WAITING_MANUFACTURER.value,
        case_lifecycle_status=CaseLifecycleStatus.CLOSED,
        close_reason=CaseCloseReason.CANCELLED,
        closed_at="2026-10-09T10:00:00+00:00",
    )
    repository.save_case(closed)
    at = _start_app()

    at.radio(key="home_work_filter").set_value("closed").run()
    texts = _texts(at)

    assert "Business Closed" in texts
    assert "Workflow Complete" not in texts
    assert "業務状態：終了" not in texts  # Quick View remains collapsed.
    assert any(item.key == "home_quick_technical_CLOSED-UI" for item in at.button)
